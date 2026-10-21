"""Liest Switches / Router per SNMP aus: Interfaces, VLANs, MAC-Tabellen, ARP, LLDP/CDP, LAGs."""

import ipaddress
import re

from .snmp import SnmpClient, to_text, to_mac

# ---------------------------------------------------------------- OIDs
SYS = {
    "descr": "1.3.6.1.2.1.1.1.0", "object_id": "1.3.6.1.2.1.1.2.0", "uptime": "1.3.6.1.2.1.1.3.0",
    "contact": "1.3.6.1.2.1.1.4.0", "name": "1.3.6.1.2.1.1.5.0", "location": "1.3.6.1.2.1.1.6.0",
    "services": "1.3.6.1.2.1.1.7.0",
}
IF_DESCR = "1.3.6.1.2.1.2.2.1.2"
IF_TYPE = "1.3.6.1.2.1.2.2.1.3"
IF_SPEED = "1.3.6.1.2.1.2.2.1.5"
IF_PHYS = "1.3.6.1.2.1.2.2.1.6"
IF_ADMIN = "1.3.6.1.2.1.2.2.1.7"
IF_OPER = "1.3.6.1.2.1.2.2.1.8"
IF_NAME = "1.3.6.1.2.1.31.1.1.1.1"
IF_HIGHSPEED = "1.3.6.1.2.1.31.1.1.1.15"
IF_ALIAS = "1.3.6.1.2.1.31.1.1.1.18"
IF_STACK = "1.3.6.1.2.1.31.1.2.1.3"

BASE_PORT_IFINDEX = "1.3.6.1.2.1.17.1.4.1.2"
DOT1D_FDB_PORT = "1.3.6.1.2.1.17.4.3.1.2"
DOT1D_FDB_STATUS = "1.3.6.1.2.1.17.4.3.1.3"
DOT1Q_FDB_PORT = "1.3.6.1.2.1.17.7.1.2.2.1.2"
DOT1Q_FDB_STATUS = "1.3.6.1.2.1.17.7.1.2.2.1.3"
DOT1Q_VLAN_FDBID = "1.3.6.1.2.1.17.7.1.4.2.1.3"
DOT1Q_CUR_EGRESS = "1.3.6.1.2.1.17.7.1.4.2.1.4"
DOT1Q_CUR_UNTAGGED = "1.3.6.1.2.1.17.7.1.4.2.1.5"
DOT1Q_VLAN_NAME = "1.3.6.1.2.1.17.7.1.4.3.1.1"
DOT1Q_STATIC_EGRESS = "1.3.6.1.2.1.17.7.1.4.3.1.2"
DOT1Q_STATIC_UNTAGGED = "1.3.6.1.2.1.17.7.1.4.3.1.4"
DOT1Q_PVID = "1.3.6.1.2.1.17.7.1.4.5.1.1"

CISCO_VTP_VLAN_STATE = "1.3.6.1.4.1.9.9.46.1.3.1.1.2"
CISCO_VTP_VLAN_NAME = "1.3.6.1.4.1.9.9.46.1.3.1.1.4"
CISCO_VM_VLAN = "1.3.6.1.4.1.9.9.68.1.2.2.1.2"
CISCO_TRUNK_NATIVE = "1.3.6.1.4.1.9.9.46.1.6.1.1.5"
CISCO_TRUNK_STATUS = "1.3.6.1.4.1.9.9.46.1.6.1.1.14"
CISCO_TRUNK_VLANS = ["1.3.6.1.4.1.9.9.46.1.6.1.1.4", "1.3.6.1.4.1.9.9.46.1.6.1.1.17",
                     "1.3.6.1.4.1.9.9.46.1.6.1.1.18", "1.3.6.1.4.1.9.9.46.1.6.1.1.19"]
CISCO_PAGP_GROUP = "1.3.6.1.4.1.9.9.98.1.1.1.1.8"

LAG_ATTACHED = "1.2.840.10006.300.43.1.2.1.1.13"

IP_ADDR_IFINDEX = "1.3.6.1.2.1.4.20.1.2"
IP_ADDR_MASK = "1.3.6.1.2.1.4.20.1.3"
ARP_TABLE = "1.3.6.1.2.1.4.22.1.2"
ARP_TABLE_NEW = "1.3.6.1.2.1.4.35.1.4"

LLDP_LOC_PORT_ID = "1.0.8802.1.1.2.1.3.7.1.3"
LLDP_LOC_PORT_DESC = "1.0.8802.1.1.2.1.3.7.1.4"
LLDP_REM = "1.0.8802.1.1.2.1.4.1.1"
LLDP_REM_MAN_ADDR = "1.0.8802.1.1.2.1.4.2.1.3"

CDP_CACHE = "1.3.6.1.4.1.9.9.23.1.2.1.1"

ENT_DESCR = "1.3.6.1.2.1.47.1.1.1.1.2"
ENT_CLASS = "1.3.6.1.2.1.47.1.1.1.1.5"
ENT_SW_REV = "1.3.6.1.2.1.47.1.1.1.1.10"
ENT_SERIAL = "1.3.6.1.2.1.47.1.1.1.1.11"
ENT_MODEL = "1.3.6.1.2.1.47.1.1.1.1.13"

PHYSICAL_IFTYPES = {6, 62, 69, 117}
LAG_IFTYPE = 161

ENTERPRISES = {
    9: "Cisco", 11: "HPE", 25506: "HPE Comware/H3C", 47196: "HPE Aruba", 14823: "Aruba", 2636: "Juniper",
    1916: "Extreme", 1991: "Brocade/Foundry", 1588: "Brocade", 674: "Dell", 6027: "Dell EMC",
    4526: "Netgear", 30065: "Arista", 12356: "Fortinet", 25461: "Palo Alto", 2011: "Huawei",
    8072: "Net-SNMP (Linux)", 311: "Microsoft", 6876: "VMware", 207: "Allied Telesis", 171: "D-Link",
    11863: "TP-Link", 41112: "Ubiquiti", 14988: "MikroTik", 2356: "LANCOM", 3375: "F5", 6486: "Alcatel-Lucent",
    4329: "Siemens", 5624: "Enterasys", 3076: "Cisco (Altiga)", 22610: "A10", 26928: "Aerohive",
    1663: "Mellanox", 33049: "Mellanox", 12325: "pfSense/FreeBSD", 8741: "SonicWall", 2620: "Check Point",
    10002: "Ubiquiti", 21839: "Hirschmann", 248: "Hirschmann", 4413: "Broadcom", 37072: "Zyxel", 890: "Zyxel",
}

LLDP_CAPS = [(0x80, "other"), (0x40, "repeater"), (0x20, "bridge"), (0x10, "wlan-ap"),
             (0x08, "router"), (0x04, "telephone"), (0x02, "docsis"), (0x01, "station")]
CDP_CAPS = [(0x01, "router"), (0x02, "bridge"), (0x04, "bridge"), (0x08, "bridge"), (0x10, "station"),
            (0x40, "repeater"), (0x80, "telephone")]

VLAN_IF_RE = re.compile(r"(?:^|[^a-z])(?:vlan|vlanif|vlan-interface|irb|ve|bvi|vl)[\s._/-]*(\d{1,4})\b", re.I)


def vlan_from_ifname(name: str):
    m = VLAN_IF_RE.search(name or "")
    if m:
        v = int(m.group(1))
        if 1 <= v <= 4094:
            return v
    return None


def portlist_to_ports(bitmap: bytes):
    """Q-BRIDGE PortList (Bitmap) -> Menge von Bridge-Portnummern."""
    ports = set()
    for i, byte in enumerate(bitmap or b""):
        if not byte:
            continue
        for j in range(8):
            if byte & (0x80 >> j):
                ports.add(i * 8 + j + 1)
    return ports


def bitmap_to_vlans(bitmap: bytes, offset: int = 0):
    vlans = set()
    for i, byte in enumerate(bitmap or b""):
        if not byte:
            continue
        for j in range(8):
            if byte & (0x80 >> j):
                v = offset + i * 8 + j
                if 1 <= v <= 4094:
                    vlans.add(v)
    return vlans


def compress_vlans(vlans) -> str:
    vs = sorted(set(vlans))
    if not vs:
        return ""
    if len(vs) >= 4000:
        return "alle"
    parts, start, prev = [], vs[0], vs[0]
    for v in vs[1:] + [None]:
        if v is not None and v == prev + 1:
            prev = v
            continue
        parts.append(str(start) if start == prev else "%d-%d" % (start, prev))
        if v is not None:
            start = prev = v
    return ",".join(parts)


def _caps(raw, table):
    if not isinstance(raw, bytes) or not raw:
        return []
    val = int.from_bytes(raw, "big") if table is CDP_CAPS else raw[0]
    out = []
    for bit, name in table:
        if val & bit and name not in out:
            out.append(name)
    return out


def _ip_from_idx(idx):
    if len(idx) >= 4 and all(0 <= x <= 255 for x in idx[-4:]):
        return ".".join(str(x) for x in idx[-4:])
    return ""


def _id_text(subtype, raw):
    """LLDP Chassis-/Port-ID je nach Subtype lesbar machen."""
    if isinstance(raw, bytes):
        if subtype in (4, 3) and len(raw) == 6 and subtype is not None:
            # chassis subtype 4 = macAddress, port subtype 3 = macAddress
            return to_mac(raw)
        if subtype == 5 and len(raw) == 5 and raw[0] == 1:
            return ".".join(str(b) for b in raw[1:])
        txt = to_text(raw)
        if txt and all(32 <= ord(c) < 127 for c in txt):
            return txt
        if len(raw) == 6:
            return to_mac(raw)
        return raw.hex()
    return to_text(raw)


class Collector:
    def __init__(self, host, cred, timeout=2.0, retries=1, log=None):
        self.host = host
        self.cred = cred
        self.c = SnmpClient(host, cred, timeout, retries)
        self.log = log or (lambda msg: None)
        self.errors = []

    def _safe(self, fn, *args, default=None, **kw):
        try:
            return fn(*args, **kw)
        except Exception as e:  # einzelne Tabellen duerfen fehlen
            self.errors.append("%s: %s" % (args[0] if args else fn.__name__, e))
            return {} if default is None else default

    def collect(self):
        try:
            return self._collect()
        finally:
            self.c.close()

    def _collect(self):
        c = self.c
        sysinfo = c.get(list(SYS.values()))
        inv = {v: k for k, v in SYS.items()}
        sysd = {inv[k]: v for k, v in sysinfo.items() if k in inv}
        oid = sysd.get("object_id") or ""
        ent = 0
        m = re.match(r"1\.3\.6\.1\.4\.1\.(\d+)", oid)
        if m:
            ent = int(m.group(1))
        services = sysd.get("services") if isinstance(sysd.get("services"), int) else 0
        dev = {
            "host": self.host,
            "ip": self.host.split(":")[0],
            "sys_name": to_text(sysd.get("name")),
            "sys_descr": to_text(sysd.get("descr")),
            "sys_object_id": oid,
            "location": to_text(sysd.get("location")),
            "contact": to_text(sysd.get("contact")),
            "uptime": sysd.get("uptime") if isinstance(sysd.get("uptime"), int) else None,
            "vendor": ENTERPRISES.get(ent, "Enterprise %d" % ent if ent else ""),
            "is_bridge": bool(services & 0x02),
            "is_router": bool(services & 0x04),
            "credential": self.cred.get("name", ""),
        }
        is_cisco = ent == 9
        self.log("  %s: %s (%s)" % (self.host, dev["sys_name"] or "?", dev["vendor"] or "unbekannt"))

        # ---------------------------------------------------- Interfaces
        ifs = {}
        for idx, v in self._safe(c.walk_first, IF_DESCR).items():
            ifs.setdefault(idx, {})["descr"] = to_text(v)
        for col, key in ((IF_NAME, "name"), (IF_ALIAS, "alias")):
            for idx, v in self._safe(c.walk_first, col).items():
                ifs.setdefault(idx, {})[key] = to_text(v)
        for col, key in ((IF_TYPE, "type"), (IF_ADMIN, "admin"), (IF_OPER, "oper"),
                         (IF_HIGHSPEED, "speed"), (IF_SPEED, "_speed_bps")):
            for idx, v in self._safe(c.walk_first, col).items():
                if isinstance(v, int):
                    ifs.setdefault(idx, {})[key] = v
        for idx, v in self._safe(c.walk_first, IF_PHYS).items():
            ifs.setdefault(idx, {})["mac"] = to_mac(v)
        for idx, i in ifs.items():
            i["ifindex"] = idx
            i.setdefault("name", "")
            if not i["name"]:
                i["name"] = i.get("descr") or "if%d" % idx
            sp = i.get("speed")
            if not sp and i.get("_speed_bps"):
                i["speed"] = i["_speed_bps"] // 1000000
            i.pop("_speed_bps", None)
            t = i.get("type", 0)
            i["physical"] = t in PHYSICAL_IFTYPES
            i["is_lag"] = t == LAG_IFTYPE or bool(re.match(r"(port-?channel|po\d|bond|ae\d|trk|bagg|lag|eth-trunk)",
                                                              i["name"], re.I))
            i["vlan_if"] = vlan_from_ifname(i["name"]) if t in (53, 135, 136) or "vlan" in i["name"].lower() \
                or t not in PHYSICAL_IFTYPES else None
        dev["interfaces"] = ifs

        # ---------------------------------------------------- Bridge-Port -> ifIndex
        bp2if = {k: v for k, v in self._safe(c.walk_first, BASE_PORT_IFINDEX).items() if isinstance(v, int)}

        # ---------------------------------------------------- VLANs
        vlans = {}
        for idx, v in self._safe(c.walk_first, DOT1Q_VLAN_NAME).items():
            vlans[idx] = to_text(v)
        if is_cisco or not vlans:
            states = {idx[-1]: v for idx, v in self._safe(c.walk, CISCO_VTP_VLAN_STATE, default=[])}
            for idx, v in self._safe(c.walk, CISCO_VTP_VLAN_NAME, default=[]):
                vid = idx[-1]
                if states.get(vid, 1) == 1:
                    vlans[vid] = to_text(v)
        dev["vlans"] = {int(k): v for k, v in vlans.items()
                        if 1 <= int(k) <= 4094 and not (is_cisco and 1002 <= int(k) <= 1005)}

        # Portzuordnung der VLANs (Q-BRIDGE)
        pvid = {k: v for k, v in self._safe(c.walk_first, DOT1Q_PVID).items() if isinstance(v, int)}
        egress = {idx[-1]: v for idx, v in self._safe(c.walk, DOT1Q_STATIC_EGRESS, default=[])}
        untagged = {idx[-1]: v for idx, v in self._safe(c.walk, DOT1Q_STATIC_UNTAGGED, default=[])}
        if not egress:
            egress = {idx[-1]: v for idx, v in self._safe(c.walk, DOT1Q_CUR_EGRESS, default=[])}
            untagged = {idx[-1]: v for idx, v in self._safe(c.walk, DOT1Q_CUR_UNTAGGED, default=[])}
        port_tagged = {}
        port_untagged = {}
        for vid, bm in egress.items():
            if not isinstance(bm, bytes):
                continue
            un = portlist_to_ports(untagged.get(vid, b"")) if isinstance(untagged.get(vid), bytes) else set()
            for bp in portlist_to_ports(bm):
                (port_untagged if bp in un else port_tagged).setdefault(bp, set()).add(vid)
        for bp, ifidx in bp2if.items():
            i = ifs.get(ifidx)
            if i is None:
                continue
            if bp in pvid:
                i["pvid"] = pvid[bp]
            tagged = port_tagged.get(bp, set())
            if tagged:
                i["mode"] = "trunk"
                i["tagged_vlans"] = sorted(tagged)
            elif bp in pvid or bp in port_untagged:
                i["mode"] = "access"
            if bp in port_untagged and "pvid" not in i:
                i["pvid"] = sorted(port_untagged[bp])[0]

        if is_cisco:
            for idx, v in self._safe(c.walk_first, CISCO_VM_VLAN).items():
                if idx in ifs and isinstance(v, int):
                    ifs[idx]["pvid"] = v
                    ifs[idx].setdefault("mode", "access")
            native = self._safe(c.walk_first, CISCO_TRUNK_NATIVE)
            tvl = [self._safe(c.walk_first, o) for o in CISCO_TRUNK_VLANS]
            for idx, st in self._safe(c.walk_first, CISCO_TRUNK_STATUS).items():
                if idx in ifs and st == 1:
                    i = ifs[idx]
                    i["mode"] = "trunk"
                    if isinstance(native.get(idx), int):
                        i["pvid"] = native[idx]
                    vl = set()
                    for n, table in enumerate(tvl):
                        if isinstance(table.get(idx), bytes):
                            vl |= bitmap_to_vlans(table[idx], n * 1024)
                    if vl:
                        i["tagged_vlans"] = sorted(vl)

        # ---------------------------------------------------- LAG-Mitglieder
        lag = {}
        for idx, agg in self._safe(c.walk_first, LAG_ATTACHED).items():
            if isinstance(agg, int) and agg and agg != idx:
                lag[idx] = agg
        if is_cisco:
            for idx, grp in self._safe(c.walk_first, CISCO_PAGP_GROUP).items():
                if isinstance(grp, int) and grp and grp != idx and idx not in lag:
                    lag[idx] = grp
        if not lag:
            for idx, _st in self._safe(c.walk, IF_STACK, default=[]):
                if len(idx) == 2:
                    hi, lo = idx
                    if hi in ifs and lo in ifs and ifs[hi].get("is_lag") and ifs[lo].get("physical"):
                        lag[lo] = hi
        for member, agg in lag.items():
            if member in ifs:
                ifs[member]["lag"] = agg
                if agg in ifs:
                    ifs[agg].setdefault("lag_members", []).append(member)
                    # VLAN-Infos des LAG an die Mitglieder vererben
                    for k in ("pvid", "mode", "tagged_vlans"):
                        if k in ifs[agg] and k not in ifs[member]:
                            ifs[member][k] = ifs[agg][k]

        # ---------------------------------------------------- MAC-Tabelle (FDB)
        fdb = self._collect_fdb(bp2if, dev["vlans"], is_cisco)
        own_macs = {i.get("mac") for i in ifs.values() if i.get("mac")}
        dev["fdb"] = [e for e in fdb if e["mac"] not in own_macs]
        dev["mac"] = self._chassis_mac(ifs)

        # ---------------------------------------------------- IP-Adressen / ARP
        ip_if = {_ip_from_idx(idx): v for idx, v in self._safe(c.walk, IP_ADDR_IFINDEX, default=[])}
        ip_mask = {_ip_from_idx(idx): v for idx, v in self._safe(c.walk, IP_ADDR_MASK, default=[])}
        addrs = []
        for ip, ifidx in ip_if.items():
            if not ip or ip.startswith("127."):
                continue
            mask = ip_mask.get(ip) or "255.255.255.255"
            try:
                net = ipaddress.ip_network("%s/%s" % (ip, mask), strict=False)
            except ValueError:
                continue
            ifname = ifs.get(ifidx, {}).get("name", "")
            addrs.append({"ip": ip, "mask": mask, "network": str(net), "ifindex": ifidx, "ifname": ifname,
                          "vlan": vlan_from_ifname(ifname)})
        dev["ip_addresses"] = addrs

        arp = []
        for idx, v in self._safe(c.walk, ARP_TABLE, default=[]):
            mac = to_mac(v)
            ip = _ip_from_idx(idx)
            if mac and ip and len(idx) == 5 and mac != "ff:ff:ff:ff:ff:ff":
                arp.append({"ip": ip, "mac": mac, "ifindex": idx[0]})
        if not arp:
            for idx, v in self._safe(c.walk, ARP_TABLE_NEW, default=[]):
                # Index: ifIndex, addrType(1=ipv4), len(4), a.b.c.d
                if len(idx) == 7 and idx[1] == 1 and idx[2] == 4:
                    mac = to_mac(v)
                    if mac:
                        arp.append({"ip": _ip_from_idx(idx), "mac": mac, "ifindex": idx[0]})
        for a in arp:
            ifname = ifs.get(a["ifindex"], {}).get("name", "")
            a["ifname"] = ifname
            a["vlan"] = vlan_from_ifname(ifname)
            if a["vlan"] is None:
                # VLAN ueber das Subnetz der L3-Schnittstelle bestimmen
                for ad in addrs:
                    if ad["ifindex"] == a["ifindex"] and ad["vlan"]:
                        a["vlan"] = ad["vlan"]
                        break
        dev["arp"] = arp

        # ---------------------------------------------------- Nachbarn
        dev["neighbors"] = self._collect_lldp(ifs, bp2if) + self._collect_cdp(ifs)

        # ---------------------------------------------------- Hardware
        dev.update(self._collect_entity())

        dev["errors"] = self.errors[:50]
        self.log("  %s: %d Interfaces, %d VLANs, %d MAC-Eintraege, %d ARP, %d Nachbarn" % (
            dev["sys_name"] or self.host, len(ifs), len(dev["vlans"]), len(dev["fdb"]), len(arp),
            len(dev["neighbors"])))
        return dev

    @staticmethod
    def _chassis_mac(ifs):
        macs = [i.get("mac") for i in sorted(ifs.values(), key=lambda x: x["ifindex"]) if i.get("mac")]
        return macs[0] if macs else ""

    def _collect_fdb(self, bp2if, vlans, is_cisco):
        c = self.c
        out = []
        # Q-BRIDGE: Index = fdbId + 6 Byte MAC
        fdb2vlan = {}
        for idx, v in self._safe(c.walk, DOT1Q_VLAN_FDBID, default=[]):
            if isinstance(v, int) and idx:
                fdb2vlan[v] = idx[-1]
        status = {idx: v for idx, v in self._safe(c.walk, DOT1Q_FDB_STATUS, default=[])}
        for idx, port in self._safe(c.walk, DOT1Q_FDB_PORT, default=[]):
            if len(idx) != 7 or not isinstance(port, int) or port == 0:
                continue
            if status.get(idx) in (4, 5):  # self / mgmt
                continue
            mac = ":".join("%02x" % b for b in idx[1:])
            vid = fdb2vlan.get(idx[0], idx[0])
            out.append({"mac": mac, "vlan": vid if 1 <= vid <= 4094 else None,
                        "bridge_port": port, "ifindex": bp2if.get(port, port)})
        if out:
            return out

        # BRIDGE-MIB (ohne VLAN)
        def dot1d(vlan=None, bpmap=None):
            res = []
            st = {idx: v for idx, v in self._safe(c.walk, DOT1D_FDB_STATUS, vlan=vlan, default=[])}
            for idx, port in self._safe(c.walk, DOT1D_FDB_PORT, vlan=vlan, default=[]):
                if len(idx) != 6 or not isinstance(port, int) or port == 0 or st.get(idx) in (4, 5):
                    continue
                res.append({"mac": ":".join("%02x" % b for b in idx), "vlan": vlan, "bridge_port": port,
                            "ifindex": (bpmap or bp2if).get(port, port)})
            return res

        out = dot1d()
        if is_cisco and vlans:
            # Cisco IOS: MAC-Tabelle nur je VLAN-Kontext (community@vlan bzw. SNMPv3-Kontext vlan-X)
            per_vlan = []
            for vid in sorted(vlans):
                if 1002 <= vid <= 1005:
                    continue
                bpm = {k: v for k, v in self._safe(c.walk_first, BASE_PORT_IFINDEX, vlan=vid).items()
                       if isinstance(v, int)}
                per_vlan += dot1d(vid, {**bp2if, **bpm})
            if per_vlan:
                out = per_vlan
        return out

    def _collect_lldp(self, ifs, bp2if):
        c = self.c
        rem = {}
        cols = {4: "chassis_subtype", 5: "chassis_raw", 6: "port_subtype", 7: "port_raw", 8: "port_desc",
                9: "name", 10: "descr", 12: "caps_raw"}
        for idx, v in self._safe(c.walk, LLDP_REM, default=[]):
            if len(idx) < 4 or idx[0] not in cols:
                continue
            key = idx[1:4]  # timeMark, localPortNum, remIndex
            rem.setdefault(key, {})[cols[idx[0]]] = v
        if not rem:
            return []
        mgmt = {}
        for idx, _v in self._safe(c.walk, LLDP_REM_MAN_ADDR, default=[]):
            # timeMark, localPort, remIndex, subtype, len, addr...
            if len(idx) >= 9 and idx[3] == 1 and idx[4] == 4:
                mgmt.setdefault(tuple(idx[:3]), ".".join(str(x) for x in idx[5:9]))
        loc_id = {k: to_text(v) for k, v in self._safe(c.walk_first, LLDP_LOC_PORT_ID).items()}
        loc_desc = {k: to_text(v) for k, v in self._safe(c.walk_first, LLDP_LOC_PORT_DESC).items()}
        by_name = {}
        for idx, i in ifs.items():
            for k in ("name", "descr"):
                if i.get(k):
                    by_name.setdefault(i[k].lower(), idx)

        def local_if(lport):
            for txt in (loc_id.get(lport), loc_desc.get(lport)):
                if txt and txt.lower() in by_name:
                    return by_name[txt.lower()]
            if lport in bp2if and lport not in ifs:
                return bp2if[lport]
            if lport in ifs:
                return lport
            return bp2if.get(lport)

        out = []
        for key, r in rem.items():
            ifidx = local_if(key[1])
            n = {
                "source": "LLDP",
                "ifindex": ifidx,
                "local_port": ifs.get(ifidx, {}).get("name") or loc_id.get(key[1]) or str(key[1]),
                "name": to_text(r.get("name")),
                "chassis_id": _id_text(r.get("chassis_subtype"), r.get("chassis_raw")),
                "port_id": _id_text(r.get("port_subtype"), r.get("port_raw")),
                "port_desc": to_text(r.get("port_desc")),
                "descr": to_text(r.get("descr"))[:200],
                "caps": _caps(r.get("caps_raw"), LLDP_CAPS),
                "mgmt_ip": mgmt.get(key, ""),
            }
            if not n["mgmt_ip"] and r.get("chassis_subtype") == 5:
                n["mgmt_ip"] = n["chassis_id"]
            out.append(n)
        return out

    def _collect_cdp(self, ifs):
        c = self.c
        rows = {}
        cols = {3: "addr_type", 4: "addr", 6: "name", 7: "port", 8: "platform", 9: "caps"}
        for idx, v in self._safe(c.walk, CDP_CACHE, default=[]):
            if len(idx) != 3 or idx[0] not in cols:
                continue
            rows.setdefault((idx[1], idx[2]), {})[cols[idx[0]]] = v
        out = []
        for (ifidx, _d), r in rows.items():
            addr = r.get("addr")
            ip = ".".join(str(b) for b in addr) if isinstance(addr, bytes) and len(addr) == 4 else ""
            name = to_text(r.get("name"))
            out.append({
                "source": "CDP", "ifindex": ifidx, "local_port": ifs.get(ifidx, {}).get("name", str(ifidx)),
                "name": re.sub(r"\(.*\)$", "", name),  # Seriennummer in Klammern entfernen
                "chassis_id": name, "port_id": to_text(r.get("port")), "port_desc": "",
                "descr": to_text(r.get("platform")), "caps": _caps(r.get("caps"), CDP_CAPS), "mgmt_ip": ip,
            })
        return out

    def _collect_entity(self):
        c = self.c
        cls = self._safe(c.walk_first, ENT_CLASS)
        chassis = sorted(k for k, v in cls.items() if v == 3)
        if not chassis:
            return {"model": "", "serial": "", "sw_version": ""}
        model = self._safe(c.walk_first, ENT_MODEL)
        serial = self._safe(c.walk_first, ENT_SERIAL)
        swrev = self._safe(c.walk_first, ENT_SW_REV)
        descr = self._safe(c.walk_first, ENT_DESCR)
        models = [to_text(model.get(k)) or to_text(descr.get(k)) for k in chassis]
        serials = [to_text(serial.get(k)) for k in chassis if to_text(serial.get(k))]
        sw = next((to_text(swrev.get(k)) for k in chassis if to_text(swrev.get(k))), "")
        uniq_models = list(dict.fromkeys(m for m in models if m))
        return {"model": ", ".join(uniq_models), "serial": ", ".join(serials), "sw_version": sw,
                "stack_members": len(chassis)}
