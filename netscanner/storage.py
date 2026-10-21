"""Ablage von Scan-Ergebnissen und Patch-Plan als JSON-Dateien."""

import json
import os
import re
import threading

from .paths import data_path, data_dir

_lock = threading.Lock()
_ID_RE = re.compile(r"^[0-9A-Za-z_-]{1,64}$")


def _scan_dir():
    d = os.path.join(data_dir(), "scans")
    os.makedirs(d, exist_ok=True)
    return d


def _check(scan_id):
    if not _ID_RE.match(scan_id or ""):
        raise ValueError("ungueltige Scan-ID")
    return scan_id


def _write(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)


def save_scan(scan):
    sid = _check(scan["id"])
    meta = {k: scan.get(k) for k in ("id", "name", "started", "finished", "duration", "stats", "warnings")}
    with _lock:
        _write(os.path.join(_scan_dir(), sid + ".json"), scan)
        _write(os.path.join(_scan_dir(), sid + ".meta.json"), meta)


def list_scans():
    out = []
    for fn in os.listdir(_scan_dir()):
        if fn.endswith(".meta.json"):
            try:
                with open(os.path.join(_scan_dir(), fn), encoding="utf-8") as f:
                    out.append(json.load(f))
            except (OSError, ValueError):
                continue
    out.sort(key=lambda m: m.get("started") or "", reverse=True)
    return out


def load_scan(scan_id):
    p = os.path.join(_scan_dir(), _check(scan_id) + ".json")
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def latest_scan_id():
    s = list_scans()
    return s[0]["id"] if s else None


def delete_scan(scan_id):
    for suffix in (".json", ".meta.json"):
        p = os.path.join(_scan_dir(), _check(scan_id) + suffix)
        if os.path.exists(p):
            os.remove(p)


def rename_scan(scan_id, name):
    scan = load_scan(scan_id)
    if scan is None:
        return False
    scan["name"] = name[:120]
    save_scan(scan)
    return True


# ---------------------------------------------------------------- Patch-Plan
# Schluessel: "<Switch-Name>|<Port-Name>" -> {target_switch, target_port, label, note, done}

PLAN_FIELDS = ("target_switch", "target_port", "label", "note", "done")


def load_plan():
    p = data_path("plan.json")
    if not os.path.exists(p):
        return {}
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def update_plan(key, values):
    with _lock:
        plan = load_plan()
        entry = plan.get(key, {})
        for k in PLAN_FIELDS:
            if k in values:
                entry[k] = bool(values[k]) if k == "done" else str(values[k])[:200]
        if any(entry.get(k) for k in PLAN_FIELDS):
            plan[key] = entry
        else:
            plan.pop(key, None)
        _write(data_path("plan.json"), plan)
        return entry


def replace_plan(plan):
    with _lock:
        _write(data_path("plan.json"), plan)
