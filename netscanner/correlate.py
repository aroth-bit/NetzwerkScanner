"""Fuehrt SNMP-Daten und Host-Scan zusammen: Geraet -> Switch-Port, VLANs, Topologie."""

import ipaddress
import re
from collections import defaultdict

from . import oui
from .collector import compress_vlans
from .discovery import os_from_ttl

VIRTUAL_VENDORS = ("vmware", "microsoft", "qemu", "xensource", "xen", "virtualbox", "parallels",
                   "proxmox", "nutanix", "red hat")
VIRTUAL_PREFIXES = ("00:50:56", "00:0c:29", "00:05:69", "00:1c:14", "00:15:5d", "52:54:00", "00:16:3e",
                    "08:00:27", "bc:24:11", "0a:00:27")


def natural_key(s):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s or "")]


def _ip_key(ip):
    try:
        return int(ipaddress.ip_address(ip))
    except ValueError:
        return 0


def _short(name):
    n = (name or "").strip().lower()
    return n.split(".")[0] if n and not re.match(r"^\d+\.\d+\.\d+\.\d+$", n) else n


class Correlator:
    def __init__(self, switches, alive, names, local_arp, open_ports, config):
        self.raw_switches = [s for s in switches if s]
        self.alive = alive or {}
        self.names = names or {}
        self.local_arp = local_arp or {}
        self.open_ports = open_ports or {}
        self.cfg = config
        self.threshold = int(config.get("options", {}).get("uplink_mac_threshold", 30))

    # ------------------------------------------------------------------ main
    def build(self):
        self._index_switches()
        self._build_networks()
        self._build_ip_mac()
        self._build_ports()
        self._mark_uplinks()
        self._assign_macs()
        self._build_devices()
        self._attach_neighbors()
        links = self._build_links()
        vlans = self._build_vlans()
        switches = self._export_switches()
        devices = sorted(self.devices.values(), key=lambda d: (_ip_key(d.get("ip") or ""), d.get("mac") or ""))
        stats = self._stats(switches, devices, vlans)
        return {"switches": switches, "devices": devices, "vlans": vlans, "links": links,
                "networks": sorted(self.networks.values(), key=lambda n: _ip_key(n["network"].split("/")[0])),
                "stats": stats}

    # ------------------------------------------------------------------ Switches
    def _index_switches(self):
        self.sw = {}
        self.sw_by_ip = {}
        self.sw_by_name = {}
        self.sw_by_mac = {}
        for s in self.raw_switches:
            sid = "sw-" + s["host"].replace(":", "_")
            s["id"] = sid
            self.sw[sid] = s
            ips = {s["ip"]} | {a["ip"] for a in s.get("ip_addresses", [])}
            for ip in ips:
                self.sw_by_ip[ip] = sid
            for n in (s.get("sys_name"), _short(s.get("sys_name"))):
                if n:
                    self.sw_by_name[n.lower()] = sid
            macs = {i.get("mac") for i in s.get("interfaces", {}).values() if i.get("mac")}
            if s.get("mac"):
                macs.add(s["mac"])
            for m in macs:
                if m and m != "00:00:00:00:00:00":
                    self.sw_by_mac[m] = sid
            s["_macs"] = macs
        # Management-MACs ueber ARP-Eintraege anderer Router ergaenzen
        for s in self.raw_switches:
            for a in s.get("arp", []):
                sid = self.sw_by_ip.get(a["ip"])
                if sid and a["mac"] not in self.sw_by_mac:
                    self.sw_by_mac[a["mac"]] = sid
                    self.sw[sid]["_macs"].add(a["mac"])

    def _neighbor_switch(self, n):
        """LLDP/CDP-Nachbar einem gescannten Switch zuordnen."""
        if n.get("mgmt_ip") and n["mgmt_ip"] in self.sw_by_ip:
            return self.sw_by_ip[n["mgmt_ip"]]
        for k in (n.get("name"), _short(n.get("name"))):
            if k and k.lower() in self.sw_by_name:
                return self.sw_by_name[k.lower()]
        cid = (n.get("chassis_id") or "").lower()
        if cid in self.sw_by_mac:
            return self.sw_by_mac[cid]
        return None

    # ------------------------------------------------------------------ Netze
    def _build_networks(self):
        self.networks = {}

        def add(net, vlan=None, name="", source=""):
            try:
                n = ipaddress.ip_network(net, strict=False)
            except ValueError:
                return
            if n.version != 4 or n.prefixlen >= 31 or n.prefixlen < 8:
                return
            key = str(n)
            e = self.networks.setdefault(key, {"network": key, "vlan": None, "name": "", "sources": [],
                                                "gateways": []})
            if vlan and not e["vlan"]:
                e["vlan"] = vlan
            if name and not e["name"]:
                e["name"] = name
            if source and source not in e["sources"]:
                e["sources"].append(source)
            return e

        for v in self.cfg.get("vlans", []):
            if v.get("subnet"):
                for sn in re.split(r"[\s,;]+", v["subnet"]):
                    if sn:
                        add(sn, int(v["id"]) if str(v.get("id", "")).isdigit() else None, v.get("name", ""),
                            "Konfiguration")
        for s in self.raw_switches:
            for a in s.get("ip_addresses", []):
                e = add(a["network"], a.get("vlan"), "", s.get("sys_name") or s["ip"])
                if e is not None:
                    e["gateways"].append({"ip": a["ip"], "device": s.get("sys_name") or s["ip"],
                                          "interface": a.get("ifname", "")})
        for sn in self.cfg.get("subnets", []):
            for part in re.split(r"[\s,;]+", sn):
                if "/" in part:
                    add(part, None, "", "Scan-Bereich")
        self._net_objs = sorted(((ipaddress.ip_network(k), v) for k, v in self.networks.items()),
                                key=lambda x: -x[0].prefixlen)

    def _network_for(self, ip):
        try:
            a = ipaddress.ip_address(ip)
        except ValueError:
            return None
        for net, e in self._net_objs:
            if a in net:
                return e
        return None

    # ------------------------------------------------------------------ IP <-> MAC
    def _build_ip_mac(self):
        self.ip2mac = {}
        self.ip_vlan = {}
        self.mac2ips = defaultdict(list)
        self.arp_seen = set()
        for s in self.raw_switches:
            for a in s.get("arp", []):
                self.ip2mac.setdefault(a["ip"], a["mac"])
                self.arp_seen.add(a["ip"])
                if a.get("vlan"):
                    self.ip_vlan.setdefault(a["ip"], a["vlan"])
        for ip, mac in self.local_arp.items():
            self.ip2mac.setdefault(ip, mac)
        for ip, info in self.alive.items():
            if info.get("mac"):
                self.ip2mac[ip] = info["mac"]
        for ip, nm in self.names.items():
            if nm.get("netbios_mac") and ip not in self.ip2mac:
                self.ip2mac[ip] = nm["netbios_mac"]
        for ip, mac in self.ip2mac.items():
            if ip not in self.mac2ips[mac]:
                self.mac2ips[mac].append(ip)
        for mac in self.mac2ips:
            self.mac2ips[mac].sort(key=_ip_key)

    # ------------------------------------------------------------------ Ports
    def _build_ports(self):
        self.ports = {}
        for sid, s in self.sw.items():
            ifs = s.get("interfaces", {})
            for idx, i in ifs.items():
                if not (i.get("physical") or i.get("is_lag")):
                    continue
                if i.get("is_lag") and not i.get("lag_members") and i.get("oper") != 1:
                    continue  # leere, inaktive Port-Channel-Interfaces ausblenden
                pid = "%s|%s" % (sid, idx)
                tv = i.get("tagged_vlans") or []
                self.ports[pid] = {
                    "id": pid, "switch_id": sid, "ifindex": idx, "name": i.get("name", ""),
                    "descr": i.get("descr", ""), "alias": i.get("alias", ""),
                    "oper": {1: "up", 2: "down", 3: "testing", 5: "dormant", 6: "notPresent",
                             7: "lowerLayerDown"}.get(i.get("oper"), "unbekannt"),
                    "admin": {1: "up", 2: "down", 3: "testing"}.get(i.get("admin"), ""),
                    "speed": i.get("speed") or 0, "mode": i.get("mode") or "", "pvid": i.get("pvid"),
                    "vlans": compress_vlans(tv) if tv else (str(i["pvid"]) if i.get("pvid") else ""),
                    "is_lag": bool(i.get("is_lag")),
                    "lag": ifs.get(i["lag"], {}).get("name", "") if i.get("lag") else "",
                    "lag_ifindex": i.get("lag"),
                    "lag_members": [ifs.get(m, {}).get("name", str(m)) for m in i.get("lag_members", [])],
                    "macs": set(), "fdb_vlans": {}, "neighbors": [], "device_ids": [], "uplink_to": None,
                    "role": "",
                }
        # FDB zuordnen (LAG-Eintraege bleiben am Port-Channel)
        for sid, s in self.sw.items():
            for e in s.get("fdb", []):
                pid = "%s|%s" % (sid, e["ifindex"])
                p = self.ports.get(pid)
                if p is None:
                    continue
                p["macs"].add(e["mac"])
                if e.get("vlan"):
                    p["fdb_vlans"][e["mac"]] = e["vlan"]
        for sid, s in self.sw.items():
            for n in s.get("neighbors", []):
                p = self.ports.get("%s|%s" % (sid, n.get("ifindex")))
                if p is None:
                    continue
                nn = dict(n)
                nn["switch_id"] = self._neighbor_switch(n)
                if nn["switch_id"] == sid:
                    nn["switch_id"] = None
                p["neighbors"].append(nn)

    def _mark_uplinks(self):
        """Ports zu anderen gescannten Switches erkennen (LLDP/CDP oder gelernte Switch-MACs)."""
        self.uplink_ports = set()
        self.sw_seen = {}  # port_id -> Menge der dahinter liegenden Switches
        for pid, p in self.ports.items():
            for n in p["neighbors"]:
                if n.get("switch_id"):
                    p["uplink_to"] = n["switch_id"]
                    self.uplink_ports.add(pid)
            seen = {self.sw_by_mac[m] for m in p["macs"] if m in self.sw_by_mac} - {p["switch_id"]}
            self.sw_seen[pid] = seen
            if seen:
                self.uplink_ports.add(pid)
        # Mitglieder eines Uplink-LAG sind ebenfalls Uplinks
        for pid, p in list(self.ports.items()):
            if p["lag_ifindex"]:
                agg = "%s|%s" % (p["switch_id"], p["lag_ifindex"])
                if agg in self.uplink_ports:
                    self.uplink_ports.add(pid)
                    self.ports[agg]["uplink_to"] = self.ports[agg]["uplink_to"] or p["uplink_to"]
                    p["uplink_to"] = p["uplink_to"] or self.ports[agg]["uplink_to"]

    # ------------------------------------------------------------------ MAC -> Port
    def _assign_macs(self):
        cand = defaultdict(list)
        for pid, p in self.ports.items():
            for m in p["macs"]:
                cand[m].append(pid)
        self.mac_port = {}
        self.mac_quality = {}
        for mac, pids in cand.items():
            if mac in self.sw_by_mac:
                continue
            access = [x for x in pids if x not in self.uplink_ports]
            if access:
                best = min(access, key=lambda x: (len(self.ports[x]["macs"]), natural_key(x)))
                if len(access) == 1:
                    q = "sicher" if len(self.ports[best]["macs"]) <= self.threshold else "mehrere MACs"
                else:
                    q = "mehrdeutig"
            else:
                best = min(pids, key=lambda x: (len(self.ports[x]["macs"]), natural_key(x)))
                q = "nur ueber Uplink"
            self.mac_port[mac] = best
            self.mac_quality[mac] = q

    # ------------------------------------------------------------------ Geraete
    def _new_device(self, key):
        return self.devices.setdefault(key, {
            "id": key, "mac": "", "vendor": "", "ip": "", "ips": [], "hostname": "", "dns_name": "",
            "netbios_name": "", "netbios_domain": "", "lldp_name": "", "lldp_descr": "", "vlan": None,
            "subnet": "", "switch_id": None, "switch_name": "", "port_id": None, "port_name": "",
            "port_alias": "", "assignment": "keine", "alive": False, "ttl": None, "os_guess": "",
            "open_ports": [], "sources": [], "type": "unbekannt", "virtual": False, "notes": [],
        })

    def _build_devices(self):
        self.devices = {}
        switch_ips = set(self.sw_by_ip)
        # 1) alle MACs aus den Switch-Tabellen
        for mac, pid in self.mac_port.items():
            d = self._new_device(mac)
            d["mac"] = mac
            d["sources"].append("MAC-Tabelle")
        # 2) IPs aus Ping/nmap/ARP
        all_ips = set(self.alive) | self.arp_seen | set(self.names)
        for ip in all_ips:
            if ip in switch_ips:
                continue
            mac = self.ip2mac.get(ip, "")
            if mac in self.sw_by_mac:
                continue
            key = mac or "ip:" + ip
            d = self._new_device(key)
            if mac:
                d["mac"] = mac
            if ip not in d["ips"]:
                d["ips"].append(ip)
            if ip in self.alive:
                d["alive"] = True
                a = self.alive[ip]
                if a.get("ttl"):
                    d["ttl"] = a["ttl"]
                    d["os_guess"] = os_from_ttl(a["ttl"])
                src = a.get("method", "Ping")
                if src not in d["sources"]:
                    d["sources"].append(src)
                if a.get("vendor") and not d["vendor"]:
                    d["vendor"] = a["vendor"]
            if ip in self.arp_seen and "ARP" not in d["sources"]:
                d["sources"].append("ARP")
        # 3) Details
        for key, d in self.devices.items():
            mac = d["mac"]
            for ip in self.mac2ips.get(mac, []) if mac else []:
                if ip not in d["ips"] and ip not in switch_ips:
                    d["ips"].append(ip)
            d["ips"].sort(key=_ip_key)
            alive_ips = [ip for ip in d["ips"] if ip in self.alive]
            d["ip"] = (alive_ips or d["ips"] or [""])[0]
            if len(d["ips"]) > 16:
                d["notes"].append("%d IPs an einer MAC (Router/Proxy-ARP/Firewall?)" % len(d["ips"]))
            if mac and not d["vendor"]:
                d["vendor"] = oui.vendor(mac)
            for ip in [d["ip"]] + d["ips"]:
                nm = self.names.get(ip)
                if not nm:
                    continue
                d["dns_name"] = d["dns_name"] or nm.get("dns", "")
                d["netbios_name"] = d["netbios_name"] or nm.get("netbios", "")
                d["netbios_domain"] = d["netbios_domain"] or nm.get("netbios_domain", "")
            for ip in d["ips"]:
                if ip in self.open_ports:
                    d["open_ports"] = sorted(set(d["open_ports"]) | set(self.open_ports[ip]))
            pid = self.mac_port.get(mac) if mac else None
            if pid:
                self._attach(d, pid, self.mac_quality.get(mac, ""))
            # VLAN
            if d["vlan"] is None and d["ip"] in self.ip_vlan:
                d["vlan"] = self.ip_vlan[d["ip"]]
            net = self._network_for(d["ip"]) if d["ip"] else None
            if net:
                d["subnet"] = net["network"]
                if d["vlan"] is None and net.get("vlan"):
                    d["vlan"] = net["vlan"]
            v = (d["vendor"] or "").lower()
            d["virtual"] = bool(mac) and (mac.startswith(VIRTUAL_PREFIXES) or any(x in v for x in ("vmware",
                                                                                                    "qemu", "xensource")))
            self._finish_name(d)
            self._guess_type(d)

    def _attach(self, d, pid, quality):
        p = self.ports[pid]
        s = self.sw[p["switch_id"]]
        d["switch_id"] = p["switch_id"]
        d["switch_name"] = s.get("sys_name") or s["ip"]
        d["port_id"] = pid
        d["port_name"] = p["name"]
        d["port_alias"] = p["alias"]
        d["assignment"] = quality or "sicher"
        if d["mac"] and d["mac"] in p["fdb_vlans"]:
            d["vlan"] = p["fdb_vlans"][d["mac"]]
        elif p.get("pvid") and p.get("mode") != "trunk":
            d["vlan"] = p["pvid"]
        if d["id"] not in p["device_ids"]:
            p["device_ids"].append(d["id"])

    @staticmethod
    def _finish_name(d):
        d["hostname"] = d["dns_name"] or d["netbios_name"] or d["lldp_name"] or ""

    @staticmethod
    def _guess_type(d):
        v = (d.get("vendor") or "").lower()
        caps = d.get("_caps", [])
        ports = set(d.get("open_ports") or [])
        if "telephone" in caps or any(x in v for x in ("polycom", "yealink", "snom", "avaya", "mitel",
                                                         "grandstream", "unify")):
            t = "Telefon"
        elif "wlan-ap" in caps or any(x in v for x in ("ubiquiti", "ruckus", "aruba")) and "ap" in \
                (d.get("lldp_descr") or "").lower():
            t = "Access Point"
        elif "router" in caps:
            t = "Router/Firewall"
        elif "bridge" in caps:
            t = "Switch (nicht gescannt)"
        elif d["virtual"]:
            t = "Virtuelle Maschine"
        elif 9100 in ports or any(x in v for x in ("lexmark", "kyocera", "brother", "ricoh", "xerox",
                                                    "konica", "canon", "epson", "sharp")):
            t = "Drucker"
        elif any(x in v for x in ("american power", "apc", "schneider", "eaton", "rittal")):
            t = "USV/Infrastruktur"
        elif any(x in v for x in ("fortinet", "palo alto", "sophos", "watchguard", "check point", "sonicwall")):
            t = "Router/Firewall"
        elif any(x in v for x in ("netapp", "emc", "pure storage", "synology", "qnap", "nimble", "hitachi")):
            t = "Storage"
        elif d.get("notes") and any("Proxy-ARP" in n for n in d["notes"]):
            t = "Router/Firewall"
        elif 3389 in ports or 445 in ports or d.get("os_guess") == "Windows":
            t = "Windows-System"
        elif 22 in ports or d.get("os_guess", "").startswith("Linux"):
            t = "Linux/Unix-System"
        elif any(x in v for x in ("dell", "hewlett", "hpe", "supermicro", "lenovo", "fujitsu", "cisco systems",
                                  "intel", "broadcom", "mellanox", "emulex", "qlogic")):
            t = "Server/PC"
        else:
            t = "Unbekannt"
        d["type"] = t

    def _attach_neighbors(self):
        """LLDP/CDP-Nachbarn, die keine gescannten Switches sind, als Geraete am Port fuehren."""
        for pid, p in self.ports.items():
            for n in p["neighbors"]:
                if n.get("switch_id"):
                    continue
                d = None
                cid = (n.get("chassis_id") or "").lower()
                if re.match(r"^([0-9a-f]{2}:){5}[0-9a-f]{2}$", cid) and cid in self.devices:
                    d = self.devices[cid]
                if d is None and n.get("mgmt_ip"):
                    for dev in self.devices.values():
                        if n["mgmt_ip"] in dev["ips"]:
                            d = dev
                            break
                if d is None:
                    # Nachbar ueber MAC am selben Port finden (z.B. Server mit LLDP)
                    for did in p["device_ids"]:
                        dev = self.devices.get(did)
                        if dev and dev["mac"] and dev["mac"] == cid:
                            d = dev
                            break
                if d is None:
                    key = cid if re.match(r"^([0-9a-f]{2}:){5}[0-9a-f]{2}$", cid) else "lldp:%s:%s" % (
                        n.get("name") or cid, pid)
                    d = self._new_device(key)
                    if key == cid:
                        d["mac"] = cid
                        d["vendor"] = oui.vendor(cid)
                    if n.get("mgmt_ip"):
                        d["ips"] = [n["mgmt_ip"]]
                        d["ip"] = n["mgmt_ip"]
                        net = self._network_for(d["ip"])
                        if net:
                            d["subnet"] = net["network"]
                            d["vlan"] = d["vlan"] or net.get("vlan")
                src = n.get("source", "LLDP")
                if src not in d["sources"]:
                    d["sources"].append(src)
                d["lldp_name"] = d["lldp_name"] or n.get("name", "")
                d["lldp_descr"] = d["lldp_descr"] or n.get("descr", "")
                d["neighbor_port"] = n.get("port_id") or n.get("port_desc") or ""
                d["_caps"] = n.get("caps", [])
                # LLDP-Nachbar ist direkt am Port -> Zuordnung sicher
                if d["port_id"] != pid:
                    if d["port_id"] and d["id"] in self.ports[d["port_id"]]["device_ids"]:
                        self.ports[d["port_id"]]["device_ids"].remove(d["id"])
                    self._attach(d, pid, "sicher (%s)" % src)
                elif not d["assignment"].startswith("sicher"):
                    d["assignment"] = "sicher (%s)" % src
                self._finish_name(d)
                self._guess_type(d)
        for d in self.devices.values():
            d.pop("_caps", None)

    # ------------------------------------------------------------------ Topologie
    def _build_links(self):
        links = {}

        def add(a_sw, a_port, b_sw, b_port, source):
            key = tuple(sorted([(a_sw, a_port), (b_sw, b_port)]))
            pair = tuple(sorted([a_sw, b_sw]))
            # pro Switch-Paar und Port nur ein Link
            if key in links:
                return
            for k, l in links.items():
                if tuple(sorted([l["a"], l["b"]])) == pair and (
                        (l["a"] == a_sw and l["a_port"] == a_port) or (l["b"] == a_sw and l["b_port"] == a_port)):
                    if not l["b_port"] and b_port:
                        l["b_port"] = b_port
                    return
            links[key] = {"a": a_sw, "a_port": a_port, "b": b_sw, "b_port": b_port, "source": source}

        for pid, p in self.ports.items():
            for n in p["neighbors"]:
                if n.get("switch_id"):
                    remote = self._remote_port_name(n["switch_id"], n)
                    add(p["switch_id"], p["name"], n["switch_id"], remote, n.get("source", "LLDP"))
        # Ohne LLDP: Links aus gelernten Switch-MACs ableiten (Baum-Kriterium)
        lldp_pairs = {tuple(sorted([l["a"], l["b"]])) for l in links.values()}
        toward = defaultdict(dict)  # toward[A][B] = port_id auf A Richtung B
        for pid, seen in self.sw_seen.items():
            a = self.ports[pid]["switch_id"]
            if self.ports[pid]["is_lag"] is False and self.ports[pid]["lag_ifindex"]:
                continue  # LAG-Mitglieder: Port-Channel zaehlt
            for b in seen:
                cur = toward[a].get(b)
                if cur is None or len(self.sw_seen[pid]) < len(self.sw_seen[cur]):
                    toward[a][b] = pid
        for a in toward:
            for b, pa in toward[a].items():
                pair = tuple(sorted([a, b]))
                if pair in lldp_pairs:
                    continue
                pb = toward.get(b, {}).get(a)
                if pb is None:
                    continue
                if self.sw_seen[pa] & self.sw_seen[pb]:
                    continue  # anderer Switch dazwischen
                self.ports[pa]["uplink_to"] = self.ports[pa]["uplink_to"] or b
                self.ports[pb]["uplink_to"] = self.ports[pb]["uplink_to"] or a
                add(a, self.ports[pa]["name"], b, self.ports[pb]["name"], "MAC-Tabelle (vermutet)")
        return list(links.values())

    def _remote_port_name(self, sid, n):
        s = self.sw[sid]
        cands = [n.get("port_id"), n.get("port_desc")]
        for i in s.get("interfaces", {}).values():
            for c in cands:
                if c and c.lower() in ((i.get("name") or "").lower(), (i.get("descr") or "").lower()):
                    return i["name"]
        return n.get("port_id") or n.get("port_desc") or ""

    # ------------------------------------------------------------------ VLANs
    def _build_vlans(self):
        vl = {}

        def get(vid):
            return vl.setdefault(vid, {"id": vid, "name": "", "subnets": [], "switches": [], "device_count": 0,
                                       "port_count": 0, "gateways": []})

        for s in self.sw.values():
            for vid, name in s.get("vlans", {}).items():
                v = get(int(vid))
                v["name"] = v["name"] or name
                v["switches"].append(s.get("sys_name") or s["ip"])
        for v in self.cfg.get("vlans", []):
            try:
                e = get(int(v["id"]))
            except (KeyError, ValueError, TypeError):
                continue
            if v.get("name"):
                e["name"] = v["name"]
        for n in self.networks.values():
            if n.get("vlan"):
                e = get(n["vlan"])
                if n["network"] not in e["subnets"]:
                    e["subnets"].append(n["network"])
                e["gateways"] += ["%s (%s)" % (g["ip"], g["device"]) for g in n["gateways"]]
        for d in self.devices.values():
            if d.get("vlan"):
                get(d["vlan"])["device_count"] += 1
        for p in self.ports.values():
            if p.get("mode") != "trunk" and p.get("pvid") and p["oper"] == "up":
                get(p["pvid"])["port_count"] += 1
        return [vl[k] for k in sorted(vl)]

    # ------------------------------------------------------------------ Export
    def _port_status(self, p):
        if p["uplink_to"] or (p["id"] in self.uplink_ports):
            return "uplink"
        if p["device_ids"]:
            return "belegt"
        if p["neighbors"]:
            return "nachbar"
        if p["admin"] == "down":
            return "deaktiviert"
        if p["oper"] == "up":
            return "aktiv-ohne-geraet"
        if p["alias"]:
            return "down-beschriftet"
        return "frei"

    def _export_switches(self):
        out = []
        for sid, s in self.sw.items():
            ports = [p for p in self.ports.values() if p["switch_id"] == sid]
            ports.sort(key=lambda p: (p["is_lag"], natural_key(p["name"])))
            plist = []
            counts = defaultdict(int)
            for p in ports:
                st = self._port_status(p)
                # Mitglieder eines belegten LAG: Geraete des Port-Channels anzeigen
                dev_ids = list(p["device_ids"])
                if not dev_ids and p["lag_ifindex"]:
                    agg = self.ports.get("%s|%s" % (sid, p["lag_ifindex"]))
                    if agg:
                        dev_ids = list(agg["device_ids"])
                        if dev_ids and st in ("frei", "aktiv-ohne-geraet", "down-beschriftet"):
                            st = "belegt"
                counts[st] += 1
                upl = self.sw.get(p["uplink_to"]) if p["uplink_to"] else None
                dev_ids.sort(key=lambda x: (self.devices[x]["virtual"], _ip_key(self.devices[x]["ip"]))
                             if x in self.devices else (True, 0))
                plist.append({
                    "id": p["id"], "name": p["name"], "descr": p["descr"], "alias": p["alias"], "oper": p["oper"],
                    "admin": p["admin"], "speed": p["speed"], "mode": p["mode"], "pvid": p["pvid"],
                    "vlans": p["vlans"], "is_lag": p["is_lag"], "lag": p["lag"], "lag_members": p["lag_members"],
                    "mac_count": len(p["macs"]), "status": st, "device_ids": dev_ids,
                    "uplink_to": p["uplink_to"],
                    "uplink_name": (upl.get("sys_name") or upl["ip"]) if upl else "",
                    "neighbors": [{k: n.get(k) for k in ("source", "name", "port_id", "port_desc", "mgmt_ip",
                                                         "caps", "descr", "switch_id", "chassis_id")}
                                  for n in p["neighbors"]],
                })
            out.append({
                "id": sid, "ip": s["ip"], "host": s["host"], "name": s.get("sys_name") or s["ip"],
                "descr": s.get("sys_descr", ""), "vendor": s.get("vendor", ""), "model": s.get("model", ""),
                "serial": s.get("serial", ""), "sw_version": s.get("sw_version", ""),
                "location": s.get("location", ""), "contact": s.get("contact", ""), "mac": s.get("mac", ""),
                "stack_members": s.get("stack_members", 1), "is_router": s.get("is_router", False),
                "vlans": {str(k): v for k, v in sorted(s.get("vlans", {}).items())},
                "ip_addresses": s.get("ip_addresses", []), "ports": plist, "port_counts": dict(counts),
                "fdb_count": len(s.get("fdb", [])), "arp_count": len(s.get("arp", [])),
                "errors": s.get("errors", []), "credential": s.get("credential", ""),
            })
        out.sort(key=lambda s: natural_key(s["name"]))
        return out

    def _stats(self, switches, devices, vlans):
        ports = [p for s in switches for p in s["ports"] if not p["is_lag"]]
        return {
            "switches": len(switches),
            "devices": len(devices),
            "devices_alive": sum(1 for d in devices if d["alive"]),
            "devices_with_port": sum(1 for d in devices if d["port_id"]),
            "devices_without_port": sum(1 for d in devices if not d["port_id"]),
            "devices_with_hostname": sum(1 for d in devices if d["hostname"]),
            "virtual": sum(1 for d in devices if d["virtual"]),
            "vlans": len(vlans),
            "networks": len(self.networks),
            "ports_total": len(ports),
            "ports_up": sum(1 for p in ports if p["oper"] == "up"),
            "ports_patch": sum(1 for p in ports if p["status"] in ("belegt", "uplink", "nachbar",
                                                                   "aktiv-ohne-geraet", "down-beschriftet")),
            "ports_up_no_device": sum(1 for p in ports if p["status"] == "aktiv-ohne-geraet"),
            "ports_uplink": sum(1 for p in ports if p["status"] == "uplink"),
        }
