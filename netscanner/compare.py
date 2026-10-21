"""Vergleich zweier Scans (z.B. vor und nach dem Umzug) inkl. Soll/Ist-Pruefung gegen den Patch-Plan."""

from .reports import plan_key


def _key(d):
    return d.get("mac") or d["id"]


def _loc(d):
    if not d.get("port_id"):
        return ""
    return "%s %s" % (d.get("switch_name", ""), d.get("port_name", ""))


def compare(a, b, plan):
    da = {_key(d): d for d in a.get("devices", [])}
    db = {_key(d): d for d in b.get("devices", [])}
    rows = []
    for k, d in da.items():
        n = db.get(k)
        pl = plan.get(plan_key(d.get("switch_name", ""), d.get("port_name", ""))) if d.get("port_id") else None
        expected = ""
        if pl and (pl.get("target_switch") or pl.get("target_port")):
            expected = "%s %s" % (pl.get("target_switch", ""), pl.get("target_port", ""))
        row = {"key": k, "hostname": d.get("hostname") or (n or {}).get("hostname", ""), "mac": d.get("mac", ""),
               "ip_old": d.get("ip", ""), "ip_new": (n or {}).get("ip", ""), "vlan_old": d.get("vlan"),
               "vlan_new": (n or {}).get("vlan"), "loc_old": _loc(d), "loc_new": _loc(n) if n else "",
               "expected": expected.strip(), "virtual": d.get("virtual", False)}
        if n is None:
            row["status"] = "fehlt"
        elif expected:
            row["status"] = "korrekt" if row["loc_new"].lower().split() == expected.lower().split() else "abweichend"
        elif row["loc_old"] != row["loc_new"]:
            row["status"] = "verschoben"
        elif row["ip_old"] != row["ip_new"] or row["vlan_old"] != row["vlan_new"]:
            row["status"] = "geaendert"
        else:
            row["status"] = "unveraendert"
        rows.append(row)
    for k, n in db.items():
        if k not in da:
            rows.append({"key": k, "hostname": n.get("hostname", ""), "mac": n.get("mac", ""), "ip_old": "",
                         "ip_new": n.get("ip", ""), "vlan_old": None, "vlan_new": n.get("vlan"), "loc_old": "",
                         "loc_new": _loc(n), "expected": "", "status": "neu", "virtual": n.get("virtual", False)})
    order = {"fehlt": 0, "abweichend": 1, "verschoben": 2, "geaendert": 3, "neu": 4, "korrekt": 5, "unveraendert": 6}
    rows.sort(key=lambda r: (order.get(r["status"], 9), r["loc_old"], r["ip_old"]))
    summary = {}
    for r in rows:
        summary[r["status"]] = summary.get(r["status"], 0) + 1
    return {"a": {"id": a["id"], "name": a.get("name")}, "b": {"id": b["id"], "name": b.get("name")},
            "summary": summary, "rows": rows}
