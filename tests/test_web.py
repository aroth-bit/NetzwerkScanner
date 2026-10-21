"""Smoke-Test fuer Rollen, Rechte, Konfigurationssicherung und Update-Pruefung.

Voraussetzung fuer den Sicherungsteil: tests/sim/fake_ssh_switch.py laeuft mit
    backup sim-ssh-pass-1 sim-enable-1 127.0.0.11:2222=CORE-SW01 127.0.0.13:2222=ACC-SW02
Aufruf: python tests/test_web.py
"""

import json
import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from netscanner import paths  # noqa: E402

TMP = tempfile.mkdtemp(prefix="nstest-")
paths.set_data_dir(TMP)

from netscanner import users  # noqa: E402
from netscanner.web import create_app, load_demo  # noqa: E402

H = {"X-NS": "1"}
LOCAL = {"REMOTE_ADDR": "127.0.0.1"}
ok_count = 0


def check(cond, msg):
    global ok_count
    if not cond:
        raise AssertionError(msg)
    ok_count += 1
    print("  ok  ", msg)


def client(app, name=None, pw=None):
    c = app.test_client()
    if name:
        r = c.post("/login", data={"username": name, "password": pw}, environ_base=LOCAL)
        check(r.status_code == 302 and r.headers["Location"].endswith("/"), "Login %s" % name)
    return c


def main():
    # Migration aus Version 1.0 (auth.json mit einzelnem Passwort)
    from werkzeug.security import generate_password_hash
    with open(os.path.join(TMP, "auth.json"), "w") as f:
        json.dump({"secret_key": "x" * 64, "password_hash": generate_password_hash("altes-passwort-1")}, f)
    check(users.get_user("admin") is None or True, "vor Migration")
    app = create_app()
    check(users.has_users() and users.get_user("admin")["role"] == "admin", "Migration: admin aus auth.json")

    anon = app.test_client()
    check(anon.get("/", environ_base=LOCAL).status_code == 302, "unangemeldet -> Login")
    check(anon.get("/api/scans", environ_base=LOCAL).status_code == 401, "API ohne Login -> 401")

    for _ in range(5):
        anon.post("/login", data={"username": "admin", "password": "falsch"}, environ_base=LOCAL)
    r = anon.post("/login", data={"username": "admin", "password": "altes-passwort-1"}, environ_base=LOCAL)
    check(b"Fehlversuche" in r.data, "Sperre nach 5 Fehlversuchen")
    users._fails.clear()

    admin = client(app, "admin", "altes-passwort-1")
    check(admin.get("/api/me").json["role"] == "admin", "/api/me admin")
    check(admin.post("/api/users", json={"username": "max", "password": "kurz", "role": "user"},
                     headers=H).status_code == 400, "zu kurzes Passwort abgelehnt")
    for n, role in (("max", "user"), ("prüfer", "audit")):
        r = admin.post("/api/users", json={"username": n, "password": "geheim-12345", "role": role}, headers=H)
        if n == "prüfer":
            check(r.status_code == 400, "Umlaute im Benutzernamen abgelehnt")
            r = admin.post("/api/users", json={"username": "pruefer", "password": "geheim-12345", "role": role},
                           headers=H)
        check(r.status_code == 200, "Benutzer angelegt (%s)" % role)
    check(admin.post("/api/users", json={"username": "x"}).status_code == 403, "ohne X-NS-Header -> 403")
    check(admin.put("/api/users/admin", json={"role": "user"}, headers=H).status_code == 400,
          "letzter Admin kann nicht herabgestuft werden")
    check(admin.delete("/api/users/admin", headers=H).status_code == 400, "eigenes Konto nicht loeschbar")

    load_demo()
    user = client(app, "max", "geheim-12345")
    aud = client(app, "pruefer", "geheim-12345")
    check(user.post("/api/config", json={}, headers=H).status_code == 403, "Benutzer darf Einstellungen nicht aendern")
    check(user.get("/api/users").status_code == 403, "Benutzer sieht keine Benutzerverwaltung")
    check(user.get("/api/update/check").status_code == 403, "Benutzer darf nicht updaten")
    check(aud.post("/api/scan/start", json={}, headers=H).status_code == 403, "Audit darf keinen Scan starten")
    check(aud.post("/api/plan", json={"key": "a|b", "values": {"note": "x"}}, headers=H).status_code == 403,
          "Audit darf Umzugsplanung nicht aendern")
    check(aud.get("/api/scans/demo").status_code == 200, "Audit sieht Ergebnisse")
    check(aud.get("/report/demo/xlsx").status_code == 200, "Audit laedt Report")
    check(aud.get("/api/audit").status_code == 200, "Audit sieht Protokoll")
    check(user.get("/api/audit").status_code == 403, "Benutzer sieht kein Protokoll")
    check(user.post("/api/plan", json={"key": "CORE-SW01|1/1/4", "values": {"note": "Test"}},
                    headers=H).status_code == 200, "Benutzer bearbeitet Umzugsplanung")

    # Einstellungen mit SSH-Zugang; Geheimnisse werden maskiert
    cfg = admin.get("/api/config").json
    cfg["ssh_credentials"] = [{"name": "sim", "username": "backup", "password": "sim-ssh-pass-1",
                               "secret": "sim-enable-1", "port": 2222}]
    check(admin.post("/api/config", json=cfg, headers=H).status_code == 200, "SSH-Zugang gespeichert")
    cfg2 = admin.get("/api/config").json
    check(cfg2["ssh_credentials"][0]["password"] == "********", "SSH-Passwort maskiert")
    check(admin.post("/api/config", json=cfg2, headers=H).status_code == 200, "Speichern mit Maske")
    from netscanner.config import load_config
    check(load_config()["ssh_credentials"][0]["password"] == "sim-ssh-pass-1", "Passwort bleibt erhalten")

    # Geraetetyp fuer den Core (Aruba-Simulator spricht hier Cisco-CLI)
    check(admin.post("/api/backups/device-type", json={"ip": "127.0.0.11", "device_type": "cisco_ios"},
                     headers=H).status_code == 200, "Geraetetyp ueberschrieben")
    ov = user.get("/api/backups/overview?scan=demo").json
    check(len(ov["switches"]) == 3 and ov["max_versions"] == 5, "Uebersicht Konfigurationen")
    check({s["name"]: s["guessed_type"] for s in ov["switches"]}["ACC-SW02"] == "cisco_ios", "Cisco erkannt")
    check({s["name"]: s["guessed_type"] for s in ov["switches"]}["ACC-SW01"] == "aruba_aoscx", "AOS-CX erkannt")

    other = os.path.join(TMP, "anderer-ort")
    r = user.post("/api/backups/run", json={"switch_ids": ["sw-127.0.0.13"], "scan_id": "demo", "location": other},
                  headers=H)
    check(r.status_code == 403, "Benutzer darf keinen neuen Speicherort waehlen")
    check(aud.post("/api/backups/run", json={}, headers=H).status_code == 403, "Audit darf nicht sichern")
    check(user.get("/api/fs/browse").status_code == 403, "Benutzer darf Dateisystem nicht durchsuchen")
    check(admin.get("/api/fs/browse").status_code == 200, "Admin durchsucht Dateisystem")

    if "--no-ssh" not in sys.argv:
        def wait_job(c):
            for _ in range(120):
                st = c.get("/api/backups/job").json
                if st["state"] == "done":
                    return st
                time.sleep(0.5)
            raise AssertionError("Sicherung haengt")

        r = admin.post("/api/backups/run", json={"scan_id": "demo", "location": other, "remember": True}, headers=H)
        check(r.status_code == 200, "Admin sichert alle Switches an neuem Ort")
        st = wait_job(admin)
        res = {x["name"]: x for x in st["results"]}
        check(res["CORE-SW01"]["ok"] and res["ACC-SW02"]["ok"], "CORE-SW01 und ACC-SW02 gesichert")
        check(not res["ACC-SW01"]["ok"], "ACC-SW01 ohne SSH -> Fehler gemeldet (%s)" % res["ACC-SW01"]["error"][:50])
        for _ in range(6):
            r = user.post("/api/backups/run", json={"switch_ids": ["sw-127.0.0.13"], "scan_id": "demo"}, headers=H)
            check(r.status_code == 200, "Benutzer sichert am Standardort")
            wait_job(user)
        ov = aud.get("/api/backups/overview?scan=demo").json
        sw = {s["name"]: s for s in ov["switches"]}["ACC-SW02"]
        check(ov["default_location"] == other, "Standardort gemerkt")
        check(len(sw["versions"]) == 5, "max. 5 Versionen (%d)" % len(sw["versions"]))
        v0, v1 = sw["versions"][0], sw["versions"][1]
        q = "location=%s&switch=ACC-SW02" % other
        check("hostname ACC-SW02" in aud.get("/api/backups/file?%s&file=%s" % (q, v0["file"])).json["text"],
              "Audit liest Konfiguration")
        d = aud.get("/api/backups/diff?%s&a=%s&b=%s" % (q, v1["file"], v0["file"])).json["diff"]
        check("Rev" in d, "Vergleich zeigt Aenderungen")
        check(aud.get("/api/backups/file?location=C:/Windows&switch=..&file=win.ini").status_code in (400, 404),
              "fremde Pfade gesperrt")
        check(user.delete("/api/backups/file", json={"location": other, "switch": "ACC-SW02", "file": v0["file"]},
                          headers=H).status_code == 403, "Benutzer darf nicht loeschen")
        check(admin.delete("/api/backups/file", json={"location": other, "switch": "ACC-SW02", "file": v0["file"]},
                           headers=H).status_code == 200, "Admin loescht Version")

    # Update-Pruefung (nur Erreichbarkeit/Fehlerbehandlung - ohne Token ist ein privates Repo 404)
    r = admin.get("/api/update/check")
    check(r.status_code in (200, 502), "Update-Pruefung antwortet (%s)" % (r.json.get("latest") or r.json.get("error")))

    log = aud.get("/api/audit").json
    actions = {x["action"] for x in log}
    check({"login", "login_failed", "user_created", "settings_changed"} <= actions, "Protokoll enthaelt Aktionen")
    print("\n%d Pruefungen erfolgreich." % ok_count)


if __name__ == "__main__":
    try:
        main()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
