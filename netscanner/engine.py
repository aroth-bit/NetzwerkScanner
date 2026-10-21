"""Steuert einen kompletten Scan-Durchlauf in einem Hintergrund-Thread."""

import copy
import ipaddress
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from . import discovery, storage
from .collector import Collector
from .correlate import Correlator
from .snmp import probe

PHASES = [
    ("snmp", "Switches/Router per SNMP auslesen", 0, 25),
    ("hosts", "Hosts suchen (Ping/TCP/nmap)", 25, 65),
    ("snmp_probe", "Weitere SNMP-Geraete pruefen", 65, 70),
    ("names", "Hostnamen aufloesen (DNS/NetBIOS)", 70, 90),
    ("ports", "Port-Scan", 90, 97),
    ("correlate", "Daten zusammenfuehren", 97, 100),
]


class Cancelled(Exception):
    pass


class ScanJob(threading.Thread):
    def __init__(self, config, name=""):
        super().__init__(daemon=True)
        self.cfg = copy.deepcopy(config)
        self.opts = self.cfg.get("options", {})
        self.name_ = name
        self.id = datetime.now().strftime("%Y%m%d-%H%M%S")
        self._cancel = threading.Event()
        self._lock = threading.Lock()
        self.status = {"id": self.id, "state": "running", "phase": "", "phase_label": "", "percent": 0,
                       "message": "", "log": [], "started": datetime.now().isoformat(timespec="seconds"),
                       "counts": {}}
        self.warnings = []

    # ---------------------------------------------------------------- Status
    def log(self, msg):
        line = "%s  %s" % (datetime.now().strftime("%H:%M:%S"), msg)
        with self._lock:
            self.status["log"].append(line)
            if len(self.status["log"]) > 3000:
                del self.status["log"][:500]

    def warn(self, msg):
        self.warnings.append(msg)
        self.log("WARNUNG: " + msg)

    def _phase(self, key):
        for k, label, a, _b in PHASES:
            if k == key:
                with self._lock:
                    self.status.update(phase=k, phase_label=label, percent=a, message=label)
                self.log("=== " + label + " ===")

    def _progress(self, key, done, total, msg=""):
        for k, _l, a, b in PHASES:
            if k == key:
                pct = a + (b - a) * (done / float(total)) if total else b
                with self._lock:
                    self.status["percent"] = round(pct, 1)
                    if msg:
                        self.status["message"] = msg

    def snapshot(self, log_from=0):
        with self._lock:
            s = dict(self.status)
            s["log"] = self.status["log"][log_from:]
            s["log_total"] = len(self.status["log"])
            return s

    def cancel(self):
        self._cancel.set()

    def _check(self):
        if self._cancel.is_set():
            raise Cancelled()

    # ---------------------------------------------------------------- Ablauf
    def run(self):
        t0 = time.time()
        try:
            switches = self._snmp_phase()
            targets = self._targets(switches)
            alive, local_arp = self._host_phase(targets)
            switches += self._snmp_probe_phase(alive, switches)
            names = self._names_phase(alive, switches, local_arp)
            open_ports = self._port_phase(alive)
            self._phase("correlate")
            model = Correlator(switches, alive, names, local_arp, open_ports, self.cfg).build()
            scan = {
                "id": self.id, "name": self.name_ or "Scan %s" % datetime.now().strftime("%d.%m.%Y %H:%M"),
                "started": self.status["started"], "finished": datetime.now().isoformat(timespec="seconds"),
                "duration": round(time.time() - t0), "warnings": self.warnings,
                "settings": self._settings_summary(targets),
                **model,
            }
            storage.save_scan(scan)
            st = model["stats"]
            self.log("Fertig: %d Switches, %d Geraete (%d mit Port-Zuordnung), %d VLANs in %ds" % (
                st["switches"], st["devices"], st["devices_with_port"], st["vlans"], scan["duration"]))
            with self._lock:
                self.status.update(state="done", percent=100, message="Scan abgeschlossen")
        except Cancelled:
            self.log("Scan abgebrochen.")
            with self._lock:
                self.status.update(state="cancelled", message="Abgebrochen")
        except Exception as e:  # pragma: no cover
            self.log("FEHLER: %s" % e)
            self.log(traceback.format_exc())
            with self._lock:
                self.status.update(state="error", message=str(e))

    def _settings_summary(self, targets):
        return {"subnets": self.cfg.get("subnets", []), "snmp_devices": self.cfg.get("snmp_devices", []),
                "target_count": len(targets), "options": self.opts,
                "credentials": [c.get("name") or c.get("version") for c in self.cfg.get("credentials", [])]}

    # ---------------------------------------------------------------- 1. SNMP
    def _snmp_phase(self):
        self._phase("snmp")
        creds = self.cfg.get("credentials", [])
        timeout = float(self.opts.get("snmp_timeout", 2))
        retries = int(self.opts.get("snmp_retries", 1))
        queue = []
        for entry in self.cfg.get("snmp_devices", []):
            entry = str(entry).strip()
            if not entry or entry.startswith("#"):
                continue
            if "/" in entry or "-" in entry:
                try:
                    queue += discovery.expand_targets([entry], limit=4096)
                except ValueError as e:
                    self.warn(str(e))
            else:
                queue.append(entry)
        if not queue:
            self.log("Keine SNMP-Geraete konfiguriert - Port-Zuordnung ist ohne Switch-Daten nicht moeglich.")
            self.warn("Keine Switches konfiguriert: Geraete koennen keinem Switch-Port zugeordnet werden.")
            return []
        if not creds:
            self.warn("Keine SNMP-Zugangsdaten konfiguriert.")
            return []
        visited, results, known_names = set(), [], set()
        crawl = bool(self.opts.get("lldp_cdp_crawl", True))
        total_est = len(queue)

        def work(host):
            cred, _info = probe(host, creds, timeout, retries)
            if not cred:
                return host, None, "keine SNMP-Antwort (Zugangsdaten/ACL pruefen)"
            try:
                return host, Collector(host, cred, timeout, retries, log=self.log).collect(), None
            except Exception as e:
                return host, None, str(e)

        with ThreadPoolExecutor(max_workers=8) as ex:
            while queue:
                self._check()
                batch = []
                for h in queue:
                    hh = h.split(":")[0]
                    if hh not in visited:
                        visited.add(hh)
                        batch.append(h)
                queue = []
                futs = [ex.submit(work, h) for h in batch]
                for f in as_completed(futs):
                    self._check()
                    host, dev, err = f.result()
                    if err:
                        self.warn("SNMP %s: %s" % (host, err))
                        continue
                    key = ((dev.get("sys_name") or "").lower(), dev.get("mac"))
                    if key[0] and key in known_names:
                        self.log("  %s ist ein bereits erfasster Switch (%s) - uebersprungen" % (host, key[0]))
                        continue
                    known_names.add(key)
                    results.append(dev)
                    for a in dev.get("ip_addresses", []):
                        visited.add(a["ip"])
                    if crawl:
                        for n in dev.get("neighbors", []):
                            caps = n.get("caps") or []
                            ip = n.get("mgmt_ip")
                            if not ip or ip in visited:
                                continue
                            if ("bridge" in caps or "router" in caps) and "telephone" not in caps \
                                    and "wlan-ap" not in caps:
                                self.log("  Nachbar gefunden: %s (%s) via %s" % (n.get("name") or "?", ip,
                                                                                 dev.get("sys_name")))
                                queue.append(ip)
                    self._progress("snmp", len(results), max(total_est, len(results) + len(queue)),
                                   "%d Switches/Router ausgelesen" % len(results))
                total_est += len(queue)
        self.log("%d SNMP-Geraete erfasst." % len(results))
        with self._lock:
            self.status["counts"]["switches"] = len(results)
        return results

    # ---------------------------------------------------------------- Zielnetze
    def _targets(self, switches):
        subnets = list(self.cfg.get("subnets", []))
        for v in self.cfg.get("vlans", []):
            if v.get("subnet") and v.get("scan", True):
                subnets.append(v["subnet"])
        if self.opts.get("auto_subnets", True):
            min_prefix = int(self.opts.get("auto_subnet_min_prefix", 20))
            seen = set()
            for s in switches:
                for a in s.get("ip_addresses", []):
                    net = ipaddress.ip_network(a["network"])
                    if net.prefixlen < min_prefix:
                        if a["network"] not in seen:
                            self.log("Subnetz %s (%s) zu gross fuer Auto-Scan - bitte manuell eintragen" % (
                                a["network"], s.get("sys_name")))
                    elif net.prefixlen <= 30 and a["network"] not in seen:
                        subnets.append(a["network"])
                    seen.add(a["network"])
        try:
            targets = discovery.expand_targets(subnets, self.cfg.get("exclude", []),
                                               int(self.opts.get("max_hosts", 70000)))
        except ValueError as e:
            self.warn(str(e))
            targets = []
        self.log("%d Zieladressen in %d Bereichen." % (len(targets), len(set(subnets))))
        return targets

    # ---------------------------------------------------------------- 2. Hosts
    def _host_phase(self, targets):
        self._phase("hosts")
        alive = {}
        if not targets or not self.opts.get("ping_sweep", True):
            return alive, discovery.local_arp()
        workers = max(4, int(self.opts.get("workers", 128)))
        use_nmap = self.opts.get("use_nmap", True) and discovery.nmap_path()
        if use_nmap:
            self.log("nmap gefunden: %s" % discovery.nmap_path())
            chunk = 1024
            for i in range(0, len(targets), chunk):
                self._check()
                part = targets[i:i + chunk]
                res = discovery.nmap_sweep(part) or {}
                for ip, info in res.items():
                    alive[ip] = {"method": "nmap", "mac": info.get("mac", ""), "vendor": info.get("vendor", "")}
                self._progress("hosts", i + len(part), len(targets), "%d / %d Adressen, %d aktiv" % (
                    i + len(part), len(targets), len(alive)))
        else:
            tmo = int(self.opts.get("ping_timeout_ms", 800))
            done = 0
            with ThreadPoolExecutor(max_workers=workers) as ex:
                futs = {ex.submit(discovery.ping, ip, tmo): ip for ip in targets}
                for f in as_completed(futs):
                    done += 1
                    if self._cancel.is_set():
                        ex.shutdown(wait=False, cancel_futures=True)
                        raise Cancelled()
                    ttl = f.result()
                    if ttl:
                        alive[futs[f]] = {"method": "Ping", "ttl": ttl}
                    if done % 64 == 0 or done == len(targets):
                        self._progress("hosts", done * (0.7 if self.opts.get("tcp_fallback") else 1),
                                       len(targets), "Ping: %d / %d, %d aktiv" % (done, len(targets), len(alive)))
            self.log("Ping: %d von %d Adressen antworten." % (len(alive), len(targets)))
            if self.opts.get("tcp_fallback", True):
                rest = [ip for ip in targets if ip not in alive]
                ports = self.opts.get("tcp_fallback_ports") or [445, 3389, 22, 443, 80]
                done = 0
                with ThreadPoolExecutor(max_workers=workers) as ex:
                    futs = {ex.submit(discovery.tcp_alive, ip, ports, 0.5): ip for ip in rest}
                    for f in as_completed(futs):
                        done += 1
                        if self._cancel.is_set():
                            ex.shutdown(wait=False, cancel_futures=True)
                            raise Cancelled()
                        if f.result():
                            alive[futs[f]] = {"method": "TCP"}
                        if done % 64 == 0 or done == len(rest):
                            self._progress("hosts", len(targets) * 0.7 + done * 0.3, len(targets),
                                           "TCP-Pruefung: %d / %d" % (done, len(rest)))
                self.log("TCP-Fallback: insgesamt %d aktive Hosts." % len(alive))
        local = discovery.local_arp()
        self.log("Lokale ARP-Tabelle: %d Eintraege." % len(local))
        with self._lock:
            self.status["counts"]["alive"] = len(alive)
        return alive, local

    # ---------------------------------------------------------------- 3. SNMP-Probe
    def _snmp_probe_phase(self, alive, switches):
        if not self.opts.get("snmp_probe_hosts"):
            return []
        self._phase("snmp_probe")
        known = {s["ip"] for s in switches} | {a["ip"] for s in switches for a in s.get("ip_addresses", [])}
        cands = [ip for ip in alive if ip not in known]
        creds = self.cfg.get("credentials", [])
        found = []

        def work(ip):
            cred, info = probe(ip, creds, 1.0, 0)
            if not cred:
                return None
            services = info.get("1.3.6.1.2.1.1.7.0")
            if isinstance(services, int) and services & 0x02:
                try:
                    return Collector(ip, cred, float(self.opts.get("snmp_timeout", 2)),
                                     int(self.opts.get("snmp_retries", 1)), log=self.log).collect()
                except Exception as e:
                    self.warn("SNMP %s: %s" % (ip, e))
            return None

        done = 0
        names = {(s.get("sys_name") or "").lower() for s in switches}
        with ThreadPoolExecutor(max_workers=32) as ex:
            for f in as_completed([ex.submit(work, ip) for ip in cands]):
                done += 1
                self._check()
                d = f.result()
                if d and (d.get("sys_name") or "").lower() not in names:
                    names.add((d.get("sys_name") or "").lower())
                    found.append(d)
                    self.log("  Zusaetzlicher Switch: %s (%s)" % (d.get("sys_name"), d["ip"]))
                self._progress("snmp_probe", done, len(cands))
        return found

    # ---------------------------------------------------------------- 4. Namen
    def _names_phase(self, alive, switches, local_arp):
        self._phase("names")
        ips = set(alive)
        for s in switches:
            for a in s.get("arp", []):
                ips.add(a["ip"])
            for n in s.get("neighbors", []):
                if n.get("mgmt_ip"):
                    ips.add(n["mgmt_ip"])
        ips |= set(local_arp)
        dns = self.opts.get("dns_lookup", True)
        nb = self.opts.get("netbios_lookup", True)
        names = {}

        def work(ip):
            r = {}
            if dns:
                r["dns"] = discovery.reverse_dns(ip)
            if nb:
                st = discovery.netbios_status(ip, 0.8)
                if st:
                    r["netbios"] = st["name"]
                    r["netbios_domain"] = st["domain"]
                    r["netbios_mac"] = st["mac"]
            return ip, r

        ips = sorted(ips)
        done = 0
        with ThreadPoolExecutor(max_workers=min(64, max(4, int(self.opts.get("workers", 128))))) as ex:
            for f in as_completed([ex.submit(work, ip) for ip in ips]):
                done += 1
                self._check()
                ip, r = f.result()
                if any(r.values()):
                    names[ip] = r
                if done % 32 == 0 or done == len(ips):
                    self._progress("names", done, len(ips), "Namen: %d / %d" % (done, len(ips)))
        self.log("%d von %d Adressen mit Namen." % (sum(1 for r in names.values() if r.get("dns") or
                                                       r.get("netbios")), len(ips)))
        return names

    # ---------------------------------------------------------------- 5. Ports
    def _port_phase(self, alive):
        if not self.opts.get("port_scan"):
            return {}
        self._phase("ports")
        ports = self.opts.get("port_scan_ports") or []
        res = {}
        done = 0
        with ThreadPoolExecutor(max_workers=64) as ex:
            futs = {ex.submit(discovery.tcp_probe, ip, ports, 0.5): ip for ip in alive}
            for f in as_completed(futs):
                done += 1
                self._check()
                if f.result():
                    res[futs[f]] = f.result()
                self._progress("ports", done, len(futs))
        return res


# ---------------------------------------------------------------- Singleton

_current = None
_cur_lock = threading.Lock()


def start_scan(config, name=""):
    global _current
    with _cur_lock:
        if _current and _current.is_alive():
            raise RuntimeError("Es laeuft bereits ein Scan.")
        _current = ScanJob(config, name)
        _current.start()
        return _current


def current():
    return _current
