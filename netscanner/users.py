"""Benutzerverwaltung (Rollen Administrator / Benutzer / Audit) und Audit-Protokoll."""

import json
import os
import re
import threading
import time
from datetime import datetime

from werkzeug.security import check_password_hash, generate_password_hash

from .paths import data_path, IS_WINDOWS

ROLES = {
    "admin": "Administrator",
    "user": "Benutzer",
    "audit": "Audit",
}

# Rechte je Rolle. Der Server prueft jede Anfrage dagegen, die Oberflaeche blendet nur aus.
PERMISSIONS = {
    "view": ("admin", "user", "audit"),           # Dashboard, Ergebnisse, Reports
    "scan": ("admin", "user"),                    # Scan starten/abbrechen
    "plan_edit": ("admin", "user"),               # Umzugsplanung bearbeiten
    "backup_run": ("admin", "user"),              # Switch-Konfiguration sichern
    "backup_view": ("admin", "user", "audit"),    # gesicherte Konfigurationen ansehen/herunterladen
    "backup_delete": ("admin",),
    "backup_location": ("admin",),                # beliebigen Speicherort auf dem Server waehlen
    "settings": ("admin",),                       # Einstellungen / Zugangsdaten aendern
    "scan_manage": ("admin",),                    # Scans loeschen, umbenennen, importieren
    "users": ("admin",),
    "audit_log": ("admin", "audit"),
    "update": ("admin",),
}

MIN_PASSWORD = 8
_USER_RE = re.compile(r"^[A-Za-z0-9._@-]{2,64}$")
_lock = threading.Lock()


class UserError(ValueError):
    pass


def can(role, perm):
    return role in PERMISSIONS.get(perm, ())


def perms_for(role):
    return sorted(p for p, roles in PERMISSIONS.items() if role in roles)


# ---------------------------------------------------------------- Speicher

def _path():
    return data_path("users.json")


def _restrict(p):
    if not IS_WINDOWS:
        try:
            os.chmod(p, 0o600)
        except OSError:
            pass


def _load():
    p = _path()
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    data = {"users": {}}
    # Migration aus Version 1.0: einzelnes Passwort in auth.json -> Administrator "admin"
    old = data_path("auth.json")
    if os.path.exists(old):
        with open(old, encoding="utf-8") as f:
            auth = json.load(f)
        if auth.get("password_hash"):
            data["users"]["admin"] = {"role": "admin", "password_hash": auth["password_hash"],
                                      "created": _now(), "full_name": "Administrator", "disabled": False}
            _save(data)
    return data


def _save(data):
    p = _path()
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, p)
    _restrict(p)


def _now():
    return datetime.now().isoformat(timespec="seconds")


def _public(name, u):
    return {"username": name, "role": u.get("role"), "role_label": ROLES.get(u.get("role"), u.get("role")),
            "full_name": u.get("full_name", ""), "disabled": bool(u.get("disabled")),
            "created": u.get("created"), "last_login": u.get("last_login")}


# ---------------------------------------------------------------- API

def has_users():
    with _lock:
        return any(not u.get("disabled") and u.get("role") == "admin" for u in _load()["users"].values())


def list_users():
    with _lock:
        return [_public(n, u) for n, u in sorted(_load()["users"].items())]


def get_user(name):
    with _lock:
        u = _load()["users"].get(name)
        return _public(name, u) if u else None


def _check_password(pw):
    if not pw or len(pw) < MIN_PASSWORD:
        raise UserError("Das Passwort muss mindestens %d Zeichen lang sein." % MIN_PASSWORD)


def create_user(name, password, role, full_name=""):
    name = (name or "").strip()
    if not _USER_RE.match(name):
        raise UserError("Ungueltiger Benutzername (2-64 Zeichen: Buchstaben, Ziffern, . _ @ -).")
    if role not in ROLES:
        raise UserError("Unbekannte Rolle.")
    _check_password(password)
    with _lock:
        data = _load()
        if name.lower() in (n.lower() for n in data["users"]):
            raise UserError("Benutzer existiert bereits.")
        data["users"][name] = {"role": role, "password_hash": generate_password_hash(password),
                               "full_name": (full_name or "")[:100], "created": _now(), "disabled": False}
        _save(data)


def _active_admins(data, without=None):
    return [n for n, u in data["users"].items()
            if u.get("role") == "admin" and not u.get("disabled") and n != without]


def update_user(name, role=None, full_name=None, disabled=None, password=None):
    with _lock:
        data = _load()
        u = data["users"].get(name)
        if not u:
            raise UserError("Benutzer nicht gefunden.")
        demote = (role is not None and role != "admin") or disabled
        if u.get("role") == "admin" and demote and not _active_admins(data, without=name):
            raise UserError("Der letzte aktive Administrator kann nicht herabgestuft oder gesperrt werden.")
        if role is not None:
            if role not in ROLES:
                raise UserError("Unbekannte Rolle.")
            u["role"] = role
        if full_name is not None:
            u["full_name"] = full_name[:100]
        if disabled is not None:
            u["disabled"] = bool(disabled)
        if password:
            _check_password(password)
            u["password_hash"] = generate_password_hash(password)
            u["pw_changed"] = _now()
        _save(data)


def delete_user(name):
    with _lock:
        data = _load()
        if name not in data["users"]:
            raise UserError("Benutzer nicht gefunden.")
        if data["users"][name].get("role") == "admin" and not _active_admins(data, without=name):
            raise UserError("Der letzte aktive Administrator kann nicht geloescht werden.")
        del data["users"][name]
        _save(data)


def set_password(name, password, role_if_new="admin"):
    """Passwort setzen; legt den Benutzer an, wenn er nicht existiert (CLI / Ersteinrichtung)."""
    _check_password(password)
    with _lock:
        data = _load()
        u = data["users"].get(name)
        if u is None:
            if not _USER_RE.match(name or ""):
                raise UserError("Ungueltiger Benutzername.")
            data["users"][name] = {"role": role_if_new, "full_name": "", "created": _now(), "disabled": False}
            u = data["users"][name]
        u["password_hash"] = generate_password_hash(password)
        u["disabled"] = False
        _save(data)


# Anmeldung mit einfacher Sperre gegen Passwort-Raten (5 Fehlversuche -> 2 Minuten je Name und IP)
_fails = {}


def authenticate(name, password, ip=""):
    key = ((name or "").lower(), ip)
    now = time.time()
    cnt, until = _fails.get(key, (0, 0))
    if until > now:
        return None, "Zu viele Fehlversuche - bitte %d Sekunden warten." % int(until - now)
    with _lock:
        data = _load()
        real = next((n for n in data["users"] if n.lower() == (name or "").lower()), None)
        u = data["users"].get(real) if real else None
        ok = bool(u and u.get("password_hash") and check_password_hash(u["password_hash"], password or ""))
        if ok and u.get("disabled"):
            return None, "Benutzer ist gesperrt."
        if ok:
            u["last_login"] = _now()
            _save(data)
            _fails.pop(key, None)
            return _public(real, u), None
    cnt += 1
    _fails[key] = (cnt, now + 120 if cnt >= 5 else 0)
    return None, "Benutzername oder Passwort falsch."


# ---------------------------------------------------------------- Audit-Protokoll

def audit(user, action, detail="", ip=""):
    line = json.dumps({"time": _now(), "user": user or "-", "ip": ip or "", "action": action,
                       "detail": str(detail)[:1000]}, ensure_ascii=False)
    p = data_path("audit.log")
    with _lock:
        with open(p, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        # Rotation bei 10 MB
        try:
            if os.path.getsize(p) > 10 * 1024 * 1024:
                os.replace(p, p + ".1")
        except OSError:
            pass


def read_audit(limit=2000, query=""):
    p = data_path("audit.log")
    if not os.path.exists(p):
        return []
    with open(p, encoding="utf-8") as f:
        lines = f.readlines()
    out = []
    q = (query or "").lower()
    for line in reversed(lines):
        if q and q not in line.lower():
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
        if len(out) >= limit:
            break
    return out
