"""Erzeugt netscanner/data/demo_scan.json aus den laufenden snmpsim-Switches (siehe tests/sim).

Aufruf: python tests/make_demo.py <simdata-verzeichnis mit names.json>
"""

import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from netscanner.collector import Collector  # noqa: E402
from netscanner.config import DEFAULT_CONFIG, _merge  # noqa: E402
from netscanner.correlate import Correlator  # noqa: E402

CRED = {"name": "Demo v2c", "version": "2c", "community": "public"}


def main(simdir):
    with open(os.path.join(simdir, "names.json")) as f:
        dns = json.load(f)
    switches = [Collector(h, CRED, 2, 1).collect() for h in ("127.0.0.11", "127.0.0.12", "127.0.0.13")]
    # Hosts, die per Ping gefunden wurden (inkl. zwei Geraete ohne Switch-Port-Zuordnung)
    alive = {ip: {"method": "Ping", "ttl": 128 if "cl-" in n else 64} for ip, n in dns.items()}
    alive["10.10.20.77"] = {"method": "Ping", "ttl": 255}
    alive["10.10.10.99"] = {"method": "TCP"}
    names = {ip: {"dns": n} for ip, n in dns.items()}
    names["10.10.20.77"] = {"dns": "", "netbios": "LABOR-PC7", "netbios_domain": "FIRMA",
                            "netbios_mac": "00:11:32:aa:bb:cc"}
    cfg = _merge(DEFAULT_CONFIG, {"vlans": [{"id": 30, "name": "Management", "subnet": "10.10.30.0/24"}]})
    model = Correlator(switches, alive, names, {}, {"10.10.20.250": [80, 443, 9100]}, cfg).build()
    now = datetime.now().isoformat(timespec="seconds")
    scan = {"id": "demo", "name": "DEMO - simuliertes Rechenzentrum", "started": now, "finished": now, "duration": 42,
            "warnings": ["Demo-Daten: 3 simulierte Switches (Aruba-Core, Aruba-Access mit LLDP, Cisco ohne LLDP)"],
            "settings": {"subnets": ["10.10.10.0/24", "10.10.20.0/24"], "snmp_devices": ["CORE-SW01"]},
            **model}
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = os.path.join(root, "netscanner", "data", "demo_scan.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(scan, f, ensure_ascii=False, separators=(",", ":"))
    print("geschrieben:", os.path.abspath(out), model["stats"])


if __name__ == "__main__":
    main(sys.argv[1])
