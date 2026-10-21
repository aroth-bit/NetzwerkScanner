"""Scan-Konfiguration (config.json im Datenverzeichnis)."""

import copy
import json
import os
import secrets
import threading

from .paths import data_path, IS_WINDOWS

DEFAULT_CONFIG = {
    # Netze, die per Ping/TCP gescannt werden (CIDR, Bereich a.b.c.d-e oder einzelne IP)
    "subnets": [],
    "exclude": [],
    # Switches / Router / Firewalls, die per SNMP abgefragt werden (Startpunkte)
    "snmp_devices": [],
    # SNMP-Zugangsdaten, werden der Reihe nach probiert
    "credentials": [
        {"name": "Standard v2c", "version": "2c", "community": "public"},
    ],
    # Manuelle VLAN-Definitionen (ergaenzen die per SNMP gefundenen)
    "vlans": [],  # {"id": 10, "name": "Server", "subnet": "10.0.10.0/24"}
    # SSH-Zugangsdaten fuer die Konfigurationssicherung, werden der Reihe nach probiert
    "ssh_credentials": [],  # {"name", "username", "password", "secret" (Enable), "port"}
    # Netmiko-Geraetetyp je Switch-IP, falls die automatische Erkennung nicht passt
    "device_types": {},
    "backup": {"default_location": "", "locations": []},
    "update": {"repo": "aroth-bit/NetzwerkScanner", "token": ""},
    "options": {
        "lldp_cdp_crawl": True,          # weitere Switches ueber LLDP/CDP-Nachbarn finden
        "auto_subnets": True,            # Subnetze von L3-Interfaces der Router/Switches uebernehmen
        "auto_subnet_min_prefix": 20,    # groessere Netze (z.B. /16) nicht automatisch scannen
        "ping_sweep": True,
        "tcp_fallback": True,            # Hosts ohne Ping-Antwort per TCP-Connect pruefen
        "tcp_fallback_ports": [22, 80, 135, 139, 443, 445, 3389, 5985, 8080],
        "use_nmap": True,                # nmap verwenden, wenn installiert (schneller)
        "snmp_probe_hosts": False,       # alle gefundenen Hosts auf SNMP pruefen (findet weitere Switches)
        "port_scan": False,              # offene Standardports je Host ermitteln
        "port_scan_ports": [21, 22, 23, 25, 53, 80, 110, 135, 139, 143, 161, 389, 443, 445, 636,
                            1433, 1521, 2049, 3306, 3389, 5432, 5900, 5985, 8080, 8443, 9100],
        "dns_lookup": True,
        "netbios_lookup": True,
        "ping_timeout_ms": 800,
        "workers": 128,
        "snmp_timeout": 2.0,
        "snmp_retries": 1,
        "uplink_mac_threshold": 30,      # Ports mit mehr MACs gelten ohne LLDP als Uplink-verdaechtig
        "max_hosts": 70000,
    },
}

_lock = threading.Lock()


def _merge(default, loaded):
    out = copy.deepcopy(default)
    for k, v in (loaded or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def _path():
    return data_path("config.json")


def load_config() -> dict:
    with _lock:
        p = _path()
        if not os.path.exists(p):
            return copy.deepcopy(DEFAULT_CONFIG)
        with open(p, "r", encoding="utf-8") as f:
            return _merge(DEFAULT_CONFIG, json.load(f))


def save_config(cfg: dict) -> dict:
    cfg = _merge(DEFAULT_CONFIG, cfg)
    with _lock:
        p = _path()
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
        os.replace(tmp, p)
        _restrict(p)
    return cfg


def _restrict(p):
    # Zugangsdaten liegen hier im Klartext -> Datei nur fuer Besitzer lesbar
    if not IS_WINDOWS:
        try:
            os.chmod(p, 0o600)
        except OSError:
            pass


# ---------------------------------------------------------------- Web-Login

def _auth_path():
    return data_path("auth.json")


def load_auth() -> dict:
    p = _auth_path()
    data = {}
    if os.path.exists(p):
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
    if not data.get("secret_key"):
        data["secret_key"] = secrets.token_hex(32)
        save_auth(data)
    return data


def save_auth(data: dict) -> None:
    p = _auth_path()
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    _restrict(p)

