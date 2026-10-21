"""Sicherung der Switch-Konfigurationen per SSH (Netmiko) mit max. 5 Versionen je Switch."""

import difflib
import hashlib
import json
import os
import re
import threading
import time
from datetime import datetime

from .paths import data_dir, IS_WINDOWS

MAX_VERSIONS = 5

# Netmiko-Geraetetyp -> Befehl, der die komplette laufende Konfiguration ausgibt
CONFIG_COMMANDS = {
    "cisco_ios": "show running-config",
    "cisco_xe": "show running-config",
    "cisco_nxos": "show running-config",
    "cisco_asa": "show running-config",
    "cisco_xr": "show running-config",
    "cisco_s300": "show running-config",
    "aruba_aoscx": "show running-config",
    "aruba_procurve": "show running-config",
    "hp_procurve": "show running-config",
    "hp_comware": "display current-configuration",
    "huawei": "display current-configuration",
    "huawei_vrpv8": "display current-configuration",
    "juniper_junos": "show configuration | display set",
    "arista_eos": "show running-config",
    "dell_os10": "show running-configuration",
    "dell_force10": "show running-config",
    "dell_powerconnect": "show running-config",
    "extreme_exos": "show configuration",
    "extreme_vsp": "show running-config",
    "ruckus_fastiron": "show running-config",
    "brocade_fastiron": "show running-config",
    "alcatel_aos": "show configuration snapshot",
    "allied_telesis_awplus": "show running-config",
    "ubiquiti_edgeswitch": "show running-config",
    "zyxel_os": "show running-config",
    "netgear_prosafe": "show running-config",
    "dlink_ds": "show config current_config",
    "tplink_jetstream": "show running-config",
    "hirschmann_hios": "show running-config",
    "fortinet": "show",
    "paloalto_panos": "show config running",
    "mikrotik_routeros": "/export",
    "vyos": "show configuration commands",
    "linux": "cat /etc/network/interfaces",
}

DEVICE_TYPE_LABELS = {
    "auto": "Automatisch (aus SNMP-Daten)",
    "cisco_ios": "Cisco IOS / IOS-XE", "cisco_nxos": "Cisco NX-OS", "cisco_asa": "Cisco ASA",
    "cisco_xr": "Cisco IOS-XR", "cisco_s300": "Cisco Small Business (SG)",
    "aruba_aoscx": "HPE Aruba AOS-CX", "hp_procurve": "HPE Aruba AOS-Switch / ProCurve",
    "hp_comware": "HPE Comware / H3C", "huawei": "Huawei VRP", "juniper_junos": "Juniper Junos",
    "arista_eos": "Arista EOS", "dell_os10": "Dell OS10", "dell_force10": "Dell OS9 / Force10",
    "dell_powerconnect": "Dell PowerConnect / N-Series", "extreme_exos": "Extreme EXOS",
    "extreme_vsp": "Extreme VOSS / VSP", "ruckus_fastiron": "Ruckus / Brocade FastIron",
    "alcatel_aos": "Alcatel-Lucent OmniSwitch", "allied_telesis_awplus": "Allied Telesis AlliedWare+",
    "ubiquiti_edgeswitch": "Ubiquiti EdgeSwitch", "zyxel_os": "Zyxel", "netgear_prosafe": "Netgear ProSafe",
    "dlink_ds": "D-Link", "tplink_jetstream": "TP-Link JetStream", "hirschmann_hios": "Hirschmann HiOS",
    "fortinet": "Fortinet FortiGate", "paloalto_panos": "Palo Alto PAN-OS", "mikrotik_routeros": "MikroTik RouterOS",
    "vyos": "VyOS",
}


def guess_device_type(sw):
    """Netmiko-Typ aus den SNMP-Daten eines Switches ableiten."""
    v = (sw.get("vendor") or "").lower()
    d = (sw.get("descr") or sw.get("sys_descr") or "").lower()
    m = (sw.get("model") or "").lower()
    if "cisco" in v:
        if "nx-os" in d or "nexus" in d:
            return "cisco_nxos"
        if "adaptive security" in d or "asa" in m:
            return "cisco_asa"
        if "ios xr" in d or "ios-xr" in d:
            return "cisco_xr"
        if re.search(r"\bsg\d{3}|\bcbs\d{3}", m + " " + d):
            return "cisco_s300"
        return "cisco_ios"
    if "aruba" in v or "hpe" in v or v == "hp":
        if "comware" in v or "comware" in d or "h3c" in d:
            return "hp_comware"
        if "aos-cx" in d or "arubaos-cx" in d or re.search(r"\b(fl|gl|ll|pl|tl|xl|de|dl)\.\d", d) \
                or re.search(r"\b(6[1-4]\d\d|8[1-4]\d\d|10000)\b", m + " " + d):
            return "aruba_aoscx"
        return "hp_procurve"
    if "comware" in v or "h3c" in v:
        return "hp_comware"
    if "huawei" in v:
        return "huawei"
    if "juniper" in v:
        return "juniper_junos"
    if "arista" in v:
        return "arista_eos"
    if "dell" in v:
        if "os10" in d or "os 10" in d:
            return "dell_os10"
        if "force10" in d or "ftos" in d or "os9" in d:
            return "dell_force10"
        return "dell_powerconnect"
    if "extreme" in v:
        return "extreme_vsp" if ("voss" in d or "vsp" in d) else "extreme_exos"
    if "brocade" in v or "foundry" in v or "ruckus" in d:
        return "ruckus_fastiron"
    if "alcatel" in v:
        return "alcatel_aos"
    if "allied" in v:
        return "allied_telesis_awplus"
    if "fortinet" in v:
        return "fortinet"
    if "palo alto" in v:
        return "paloalto_panos"
    if "mikrotik" in v:
        return "mikrotik_routeros"
    if "ubiquiti" in v:
        return "ubiquiti_edgeswitch"
    if "zyxel" in v:
        return "zyxel_os"
    if "netgear" in v:
        return "netgear_prosafe"
    if "tp-link" in v:
        return "tplink_jetstream"
    if "d-link" in v:
        return "dlink_ds"
    if "hirschmann" in v:
        return "hirschmann_hios"
    return "autodetect"


def safe_name(name):
    n = re.sub(r"[^A-Za-z0-9._-]+", "_", name or "").strip("._")
    return n[:80] or "switch"


def default_location():
    return os.path.join(data_dir(), "config-backups")


# ---------------------------------------------------------------- Abruf per SSH

def fetch_config(host, cred, device_type, timeout=20):
    """-> (config_text, effektiver device_type). Wirft Exception bei Fehlern."""
    from netmiko import ConnectHandler, SSHDetect

    params = {
        "host": host, "username": cred.get("username", ""), "password": cred.get("password", ""),
        "secret": cred.get("secret") or cred.get("password", ""), "port": int(cred.get("port") or 22),
        "conn_timeout": timeout, "auth_timeout": timeout, "banner_timeout": timeout,
        "fast_cli": False, "allow_agent": False, "use_keys": False,
    }
    if device_type in (None, "", "auto", "autodetect"):
        det = SSHDetect(device_type="autodetect", **params)
        device_type = det.autodetect() or "cisco_ios"
        try:
            det.connection.disconnect()
        except Exception:
            pass
    cmd = CONFIG_COMMANDS.get(device_type, "show running-config")
    params["device_type"] = device_type
    with ConnectHandler(**params) as conn:
        if device_type.startswith("cisco") or device_type in ("dell_force10", "dell_powerconnect",
                                                               "ruckus_fastiron", "allied_telesis_awplus"):
            try:
                if not conn.check_enable_mode():
                    conn.enable()
            except Exception:
                pass  # ohne Enable-Modus versuchen (z.B. privilege 15 direkt)
        out = conn.send_command(cmd, read_timeout=180, strip_prompt=True, strip_command=True)
    text = (out or "").replace("\r\n", "\n").strip("\n") + "\n"
    if len(text.strip()) < 20 or re.search(r"^\s*(% ?Invalid|Invalid input|Unrecognized command|% Unknown)",
                                           text, re.I | re.M):
        raise RuntimeError("Unerwartete Ausgabe von '%s': %s" % (cmd, text.strip()[:200]))
    return text, device_type


# ---------------------------------------------------------------- Ablage

_FILE_RE = re.compile(r"^(?P<name>.+)_(?P<ts>\d{8}-\d{6})\.cfg$")


def _switch_dir(location, sw_name):
    return os.path.join(location, safe_name(sw_name))


def list_versions(location, sw_name):
    d = _switch_dir(location, sw_name)
    if not os.path.isdir(d):
        return []
    out = []
    for fn in os.listdir(d):
        m = _FILE_RE.match(fn)
        if not m:
            continue
        p = os.path.join(d, fn)
        meta = {}
        try:
            with open(p[:-4] + ".json", encoding="utf-8") as f:
                meta = json.load(f)
        except (OSError, ValueError):
            pass
        out.append({"file": fn, "path": p, "ts": m.group("ts"), "size": os.path.getsize(p),
                    "time": meta.get("time") or datetime.strptime(m.group("ts"), "%Y%m%d-%H%M%S").isoformat(),
                    "user": meta.get("user", ""), "device_type": meta.get("device_type", ""),
                    "sha256": meta.get("sha256", ""), "changed": meta.get("changed"), "ip": meta.get("ip", ""),
                    "location": location})
    out.sort(key=lambda x: x["ts"], reverse=True)
    return out


def store(location, sw_name, ip, text, device_type, user):
    """Speichert eine neue Version und loescht ueberzaehlige alte (max. MAX_VERSIONS)."""
    d = _switch_dir(location, sw_name)
    os.makedirs(d, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = os.path.join(d, "%s_%s" % (safe_name(sw_name), ts))
    while os.path.exists(base + ".cfg"):  # zwei Sicherungen in derselben Sekunde
        time.sleep(1)
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        base = os.path.join(d, "%s_%s" % (safe_name(sw_name), ts))
    prev = list_versions(location, sw_name)
    sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    changed = (prev[0]["sha256"] != sha) if prev and prev[0].get("sha256") else None  # None = erste Version
    with open(base + ".cfg", "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    meta = {"switch": sw_name, "ip": ip, "time": datetime.now().isoformat(timespec="seconds"), "user": user,
            "device_type": device_type, "sha256": sha, "size": len(text.encode("utf-8")), "changed": changed}
    with open(base + ".json", "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=1, ensure_ascii=False)
    removed = []
    for old in list_versions(location, sw_name)[MAX_VERSIONS:]:
        for ext in (".cfg", ".json"):
            try:
                os.remove(old["path"][:-4] + ext)
            except OSError:
                pass
        removed.append(old["file"])
    return {"file": os.path.basename(base + ".cfg"), "changed": changed, "removed": removed}


def resolve_file(location, sw_name, filename):
    """Pfad einer Version - nur Dateien aus dem Switch-Ordner (Schutz vor Pfadmanipulation)."""
    if not _FILE_RE.match(filename or "") or os.path.basename(filename) != filename:
        raise ValueError("ungueltiger Dateiname")
    p = os.path.join(_switch_dir(location, sw_name), filename)
    if not os.path.isfile(p):
        raise FileNotFoundError(filename)
    return p


def read_version(location, sw_name, filename):
    with open(resolve_file(location, sw_name, filename), encoding="utf-8", errors="replace") as f:
        return f.read()


def delete_version(location, sw_name, filename):
    p = resolve_file(location, sw_name, filename)
    for ext in (".cfg", ".json"):
        try:
            os.remove(p[:-4] + ext)
        except OSError:
            pass


def diff(location, sw_name, file_a, file_b):
    a = read_version(location, sw_name, file_a).splitlines()
    b = read_version(location, sw_name, file_b).splitlines()
    return "\n".join(difflib.unified_diff(a, b, fromfile=file_a, tofile=file_b, lineterm="", n=3))


def check_location(path):
    """Pruefen, ob ein Speicherort beschreibbar ist (legt ihn bei Bedarf an)."""
    if not path or not os.path.isabs(path):
        raise ValueError("Bitte einen absoluten Pfad angeben (z.B. D:\\Backups oder \\\\server\\freigabe).")
    os.makedirs(path, exist_ok=True)
    probe = os.path.join(path, ".netscanner-write-test")
    with open(probe, "w") as f:
        f.write("ok")
    os.remove(probe)
    return os.path.abspath(path)


def browse(path):
    """Ordnerliste fuer die Auswahl des Speicherorts."""
    if not path:
        if IS_WINDOWS:
            import string
            drives = ["%s:\\" % c for c in string.ascii_uppercase if os.path.exists("%s:\\" % c)]
            return {"path": "", "parent": None, "dirs": drives}
        path = "/"
    path = os.path.abspath(path)
    dirs = []
    try:
        for e in sorted(os.scandir(path), key=lambda e: e.name.lower()):
            if e.is_dir(follow_symlinks=False) and not e.name.startswith((".", "$")):
                dirs.append(e.path)
    except OSError as e:
        raise ValueError("Ordner nicht lesbar: %s" % e)
    parent = os.path.dirname(path.rstrip("\\/")) if path.rstrip("\\/") != path[:3].rstrip("\\/") else None
    if IS_WINDOWS and re.match(r"^[A-Za-z]:\\?$", path):
        parent = ""
    if parent == path:
        parent = None
    return {"path": path, "parent": parent, "dirs": dirs[:500]}


# ---------------------------------------------------------------- Hintergrund-Job

class BackupJob(threading.Thread):
    def __init__(self, targets, location, credentials, user, audit=None):
        """targets: [{name, ip, device_type}]"""
        super().__init__(daemon=True)
        self.targets = targets
        self.location = location
        self.creds = credentials
        self.user = user
        self.audit = audit or (lambda *a: None)
        self.status = {"state": "running", "done": 0, "total": len(targets), "results": [], "log": [],
                       "location": location, "started": datetime.now().isoformat(timespec="seconds")}
        self._lock = threading.Lock()

    def log(self, msg):
        with self._lock:
            self.status["log"].append("%s  %s" % (datetime.now().strftime("%H:%M:%S"), msg))

    def snapshot(self):
        with self._lock:
            return json.loads(json.dumps(self.status))

    def run(self):
        for t in self.targets:
            res = {"name": t["name"], "ip": t["ip"], "ok": False}
            self.log("%s (%s): verbinde per SSH ..." % (t["name"], t["ip"]))
            err = "keine SSH-Zugangsdaten hinterlegt"
            for cred in self.creds:
                try:
                    text, dtype = fetch_config(t["ip"], cred, t.get("device_type") or "auto")
                    info = store(self.location, t["name"], t["ip"], text, dtype, self.user)
                    res.update(ok=True, file=info["file"], changed=info["changed"], device_type=dtype,
                               credential=cred.get("name", ""), removed=info["removed"])
                    self.log("%s: gesichert als %s (%s%s)%s" % (
                        t["name"], info["file"], dtype,
                        "" if info["changed"] is None else (", geaendert" if info["changed"] else ", unveraendert"),
                        (" - aelteste Version(en) ersetzt: " + ", ".join(info["removed"])) if info["removed"] else ""))
                    self.audit("config_backup", "%s (%s) -> %s" % (t["name"], t["ip"], info["file"]))
                    break
                except Exception as e:  # naechste Zugangsdaten probieren
                    err = "%s: %s" % (cred.get("name", "SSH"), e)
                    if "Authentication" not in str(e) and "auth" not in str(e).lower():
                        break  # kein Anmeldefehler -> andere Zugangsdaten helfen nicht
            if not res["ok"]:
                res["error"] = err
                self.log("%s: FEHLER %s" % (t["name"], err))
                self.audit("config_backup_failed", "%s (%s): %s" % (t["name"], t["ip"], err))
            with self._lock:
                self.status["results"].append(res)
                self.status["done"] += 1
        with self._lock:
            self.status["state"] = "done"
        self.log("Fertig: %d von %d gesichert." % (sum(1 for r in self.status["results"] if r["ok"]),
                                                     len(self.targets)))


_job = None
_job_lock = threading.Lock()


def start_job(targets, location, credentials, user, audit=None):
    global _job
    with _job_lock:
        if _job and _job.is_alive():
            raise RuntimeError("Es laeuft bereits eine Sicherung.")
        _job = BackupJob(targets, location, credentials, user, audit)
        _job.start()
        return _job


def current_job():
    return _job

