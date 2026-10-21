"""MAC-Hersteller-Zuordnung (IEEE OUI)."""

import os
import threading

from .paths import resource_dir, data_dir

_table = None
_lock = threading.Lock()

_NMAP_FILES = ["/usr/share/nmap/nmap-mac-prefixes", r"C:\Program Files (x86)\Nmap\nmap-mac-prefixes",
               r"C:\Program Files\Nmap\nmap-mac-prefixes"]


def _load():
    table = {}
    for path in _NMAP_FILES:
        if os.path.exists(path):
            with open(path, encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if line.startswith("#") or len(line) < 8:
                        continue
                    p = line.rstrip("\n").split(" ", 1)
                    if len(p) == 2 and len(p[0]) == 6:
                        table[p[0].upper()] = p[1].strip()
            break
    # mitgelieferte IEEE-Liste und optional aktualisierte Liste im Datenverzeichnis haben Vorrang
    for path in (os.path.join(resource_dir(), "data", "oui.txt"), os.path.join(data_dir(), "oui.txt")):
        if os.path.exists(path):
            with open(path, encoding="utf-8", errors="ignore") as f:
                for line in f:
                    p = line.rstrip("\n").split("\t", 1)
                    if len(p) == 2:
                        table[p[0].upper()] = p[1]
    return table


def vendor(mac: str) -> str:
    global _table
    if not mac:
        return ""
    if _table is None:
        with _lock:
            if _table is None:
                _table = _load()
    h = mac.replace(":", "").replace("-", "").upper()
    if len(h) < 6:
        return ""
    v = _table.get(h[:6], "")
    if not v and int(h[1], 16) & 0x2:
        return "(lokal verwaltete / zufaellige MAC)"
    return v
