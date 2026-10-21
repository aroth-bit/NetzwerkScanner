"""Web-Dashboard und REST-API."""

import json
import os
import re
from datetime import timedelta
from functools import wraps

from flask import (Flask, Response, abort, g, jsonify, redirect, render_template, request, send_from_directory,
                   session, url_for)

from . import __version__, DEFAULT_PORT, config as cfgmod, configbackup, discovery, engine, reports, storage, updater, users
from .compare import compare
from .paths import resource_dir, data_dir
from .snmp import probe

LOCAL = ("127.0.0.1", "::1", "::ffff:127.0.0.1")
MASK = "********"
# geheime Felder je Konfigurationsbereich: werden im Browser nur maskiert angezeigt
SECRET_LISTS = {"credentials": ("community", "auth_key", "priv_key"), "ssh_credentials": ("password", "secret")}


def load_demo():
    """Mitgelieferten Beispiel-Scan (simulierte Switches) ins Datenverzeichnis uebernehmen."""
    with open(os.path.join(resource_dir(), "data", "demo_scan.json"), encoding="utf-8") as f:
        scan = json.load(f)
    storage.save_scan(scan)
    return scan["id"]


def masked(cfg):
    cfg = json.loads(json.dumps(cfg))
    for key, fields in SECRET_LISTS.items():
        for c in cfg.get(key, []):
            for f in fields:
                if c.get(f):
                    c[f] = MASK
    if cfg.get("update", {}).get("token"):
        cfg["update"]["token"] = MASK
    return cfg


def unmask(new, old):
    """Maskierte Werte aus dem Browser durch die gespeicherten ersetzen."""
    for key, fields in SECRET_LISTS.items():
        old_list = old.get(key, [])
        by_name = {c.get("name"): c for c in old_list if c.get("name")}
        for i, c in enumerate(new.get(key, [])):
            prev = by_name.get(c.get("name")) or (old_list[i] if i < len(old_list) else {})
            for f in fields:
                if c.get(f) == MASK:
                    c[f] = prev.get(f, "")
    if new.get("update", {}).get("token") == MASK:
        new["update"]["token"] = old.get("update", {}).get("token", "")
    return new


def create_app(port=DEFAULT_PORT):
    res = resource_dir()
    app = Flask(__name__, template_folder=os.path.join(res, "templates"),
                static_folder=os.path.join(res, "static"))
    app.secret_key = cfgmod.load_auth()["secret_key"]
    app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Strict",
                      PERMANENT_SESSION_LIFETIME=timedelta(hours=12), MAX_CONTENT_LENGTH=200 * 1024 * 1024,
                      PORT=port)

    def audit(action, detail=""):
        users.audit(g.get("user", {}).get("username") if g.get("user") else None, action, detail,
                    request.remote_addr if request else "")

    def need(perm):
        def deco(fn):
            @wraps(fn)
            def inner(*a, **kw):
                if not users.can(g.user["role"], perm):
                    return jsonify({"error": "Keine Berechtigung (%s)" % perm}), 403
                return fn(*a, **kw)
            return inner
        return deco

    # ------------------------------------------------------------ Anmeldung
    @app.before_request
    def guard():
        ep = request.endpoint or ""
        if ep in ("static", "login", "setup", "favicon"):
            return None
        if not users.has_users():
            if request.remote_addr not in LOCAL:
                return Response("Ersteinrichtung nur lokal am Server moeglich (http://localhost:<port>/setup).",
                                403)
            return redirect(url_for("setup"))
        u = users.get_user(session.get("user", "")) if session.get("user") else None
        if not u or u["disabled"]:
            session.clear()
            if request.path.startswith(("/api/", "/report/")):
                return jsonify({"error": "nicht angemeldet"}), 401
            return redirect(url_for("login", next=request.path))
        g.user = u
        # einfacher CSRF-Schutz zusaetzlich zu SameSite=Strict: aendernde API-Aufrufe nur aus der App
        if request.method in ("POST", "PUT", "DELETE") and request.path.startswith("/api/") \
                and request.headers.get("X-NS") != "1":
            return jsonify({"error": "ungueltige Anfrage"}), 403
        return None

    @app.route("/setup", methods=["GET", "POST"])
    def setup():
        if users.has_users():
            return redirect(url_for("login"))
        if request.remote_addr not in LOCAL:
            return Response("Ersteinrichtung nur lokal am Server moeglich.", 403)
        error = ""
        if request.method == "POST":
            name = request.form.get("username", "").strip() or "admin"
            pw, pw2 = request.form.get("password", ""), request.form.get("password2", "")
            if pw != pw2:
                error = "Die Passwoerter stimmen nicht ueberein."
            else:
                try:
                    users.set_password(name, pw, "admin")
                    users.audit(name, "setup", "erster Administrator angelegt", request.remote_addr)
                    session.permanent = True
                    session["user"] = name
                    return redirect(url_for("index"))
                except users.UserError as e:
                    error = str(e)
        return render_template("login.html", setup=True, error=error, version=__version__)

    @app.route("/login", methods=["GET", "POST"])
    def login():
        error = ""
        if request.method == "POST":
            name = request.form.get("username", "").strip()
            u, err = users.authenticate(name, request.form.get("password", ""), request.remote_addr)
            if u:
                session.clear()
                session.permanent = True
                session["user"] = u["username"]
                users.audit(u["username"], "login", "", request.remote_addr)
                nxt = request.args.get("next") or "/"
                return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else "/")
            users.audit(name or "-", "login_failed", err, request.remote_addr)
            error = err
        return render_template("login.html", setup=False, error=error, version=__version__)

    @app.route("/logout")
    def logout():
        if session.get("user"):
            users.audit(session["user"], "logout", "", request.remote_addr)
        session.clear()
        return redirect(url_for("login"))

    @app.route("/")
    def index():
        return render_template("index.html", version=__version__)

    @app.get("/favicon.ico")
    def favicon():
        return send_from_directory(app.static_folder, "favicon.svg", mimetype="image/svg+xml")

    # ------------------------------------------------------------ eigenes Konto
    @app.get("/api/me")
    def me():
        return jsonify({**g.user, "permissions": users.perms_for(g.user["role"]), "version": __version__,
                        "install_mode": updater.install_mode(), "roles": users.ROLES})

    @app.post("/api/me/password")
    def me_password():
        body = request.get_json(force=True) or {}
        u, _err = users.authenticate(g.user["username"], body.get("old", ""), request.remote_addr)
        if not u:
            return jsonify({"error": "Aktuelles Passwort ist falsch."}), 400
        try:
            users.update_user(g.user["username"], password=body.get("new", ""))
        except users.UserError as e:
            return jsonify({"error": str(e)}), 400
        audit("password_changed", "eigenes Passwort")
        return jsonify({"ok": True})

    # ------------------------------------------------------------ Benutzerverwaltung
    @app.get("/api/users")
    @need("users")
    def users_list():
        return jsonify(users.list_users())

    @app.post("/api/users")
    @need("users")
    def users_create():
        b = request.get_json(force=True) or {}
        try:
            users.create_user(b.get("username", ""), b.get("password", ""), b.get("role", "user"),
                              b.get("full_name", ""))
        except users.UserError as e:
            return jsonify({"error": str(e)}), 400
        audit("user_created", "%s (%s)" % (b.get("username"), b.get("role")))
        return jsonify({"ok": True})

    @app.put("/api/users/<name>")
    @need("users")
    def users_update(name):
        b = request.get_json(force=True) or {}
        try:
            users.update_user(name, role=b.get("role"), full_name=b.get("full_name"), disabled=b.get("disabled"),
                              password=b.get("password") or None)
        except users.UserError as e:
            return jsonify({"error": str(e)}), 400
        changes = ", ".join("%s=%s" % (k, v) for k, v in b.items() if k != "password" and v is not None)
        audit("user_changed", "%s: %s%s" % (name, changes, " +Passwort" if b.get("password") else ""))
        return jsonify({"ok": True})

    @app.delete("/api/users/<name>")
    @need("users")
    def users_delete(name):
        if name == g.user["username"]:
            return jsonify({"error": "Das eigene Konto kann nicht geloescht werden."}), 400
        try:
            users.delete_user(name)
        except users.UserError as e:
            return jsonify({"error": str(e)}), 400
        audit("user_deleted", name)
        return jsonify({"ok": True})

    @app.get("/api/audit")
    @need("audit_log")
    def audit_log():
        return jsonify(users.read_audit(int(request.args.get("limit", 2000)), request.args.get("q", "")))

    # ------------------------------------------------------------ Konfiguration
    @app.get("/api/config")
    @need("view")
    def get_config():
        return jsonify(masked(cfgmod.load_config()))

    @app.post("/api/config")
    @need("settings")
    def post_config():
        new = request.get_json(force=True) or {}
        old = cfgmod.load_config()
        new = unmask(new, old)
        for key in ("subnets", "exclude", "snmp_devices"):
            if isinstance(new.get(key), str):
                new[key] = [x.strip() for x in re.split(r"[\r\n]+", new[key]) if x.strip()]
        try:
            for key in ("subnets", "exclude"):
                discovery.parse_targets(new.get(key, []))
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        saved = cfgmod.save_config(new)
        changed = [k for k in new if json.dumps(old.get(k), sort_keys=True) != json.dumps(new.get(k), sort_keys=True)]
        audit("settings_changed", ", ".join(changed) or "keine Aenderung")
        return jsonify(masked(saved))

    @app.get("/api/local-networks")
    @need("view")
    def local_networks():
        return jsonify({"networks": discovery.local_addresses(), "nmap": bool(discovery.nmap_path()),
                        "data_dir": data_dir()})

    @app.post("/api/test-snmp")
    @need("settings")
    def test_snmp():
        body = request.get_json(force=True) or {}
        host = (body.get("host") or "").strip()
        if not host:
            return jsonify({"error": "Host fehlt"}), 400
        creds = cfgmod.load_config().get("credentials", [])
        cred, info = probe(host, creds, 2.0, 1)
        if not cred:
            return jsonify({"ok": False, "message": "Keine Antwort mit den hinterlegten Zugangsdaten."})
        from .snmp import to_text
        return jsonify({"ok": True, "credential": cred.get("name"),
                        "sys_name": to_text(info.get("1.3.6.1.2.1.1.5.0")),
                        "sys_descr": to_text(info.get("1.3.6.1.2.1.1.1.0"))[:200]})

    # ------------------------------------------------------------ Scan
    @app.post("/api/scan/start")
    @need("scan")
    def scan_start():
        body = request.get_json(silent=True) or {}
        try:
            job = engine.start_scan(cfgmod.load_config(), body.get("name", ""))
        except RuntimeError as e:
            return jsonify({"error": str(e)}), 409
        audit("scan_started", body.get("name", "") or job.id)
        return jsonify({"id": job.id})

    @app.post("/api/scan/cancel")
    @need("scan")
    def scan_cancel():
        job = engine.current()
        if job:
            job.cancel()
            audit("scan_cancelled", job.id)
        return jsonify({"ok": True})

    @app.get("/api/scan/status")
    @need("view")
    def scan_status():
        job = engine.current()
        if not job:
            return jsonify({"state": "idle"})
        return jsonify(job.snapshot(int(request.args.get("from", 0))))

    # ------------------------------------------------------------ Ergebnisse
    @app.get("/api/scans")
    @need("view")
    def scans():
        return jsonify(storage.list_scans())

    def _load(scan_id):
        if scan_id == "latest":
            scan_id = storage.latest_scan_id()
            if not scan_id:
                abort(404)
        try:
            s = storage.load_scan(scan_id)
        except ValueError:
            abort(400)
        if s is None:
            abort(404)
        return s

    @app.get("/api/scans/<scan_id>")
    @need("view")
    def scan_get(scan_id):
        return jsonify(_load(scan_id))

    @app.delete("/api/scans/<scan_id>")
    @need("scan_manage")
    def scan_delete(scan_id):
        storage.delete_scan(scan_id)
        audit("scan_deleted", scan_id)
        return jsonify({"ok": True})

    @app.post("/api/scans/<scan_id>/rename")
    @need("scan_manage")
    def scan_rename(scan_id):
        name = (request.get_json(force=True) or {}).get("name", "")
        storage.rename_scan(scan_id, name)
        audit("scan_renamed", "%s -> %s" % (scan_id, name))
        return jsonify({"ok": True})

    @app.post("/api/scans/import")
    @need("scan_manage")
    def scan_import():
        f = request.files.get("file")
        if not f:
            return jsonify({"error": "Keine Datei"}), 400
        try:
            scan = json.load(f.stream)
            assert isinstance(scan, dict) and "switches" in scan and "devices" in scan and "id" in scan
        except Exception:
            return jsonify({"error": "Keine gueltige Scan-Datei (JSON-Export)"}), 400
        scan["id"] = re.sub(r"[^0-9A-Za-z_-]", "", str(scan["id"]))[:40] or "import"
        if storage.load_scan(scan["id"]):
            scan["id"] += "-imp"
        storage.save_scan(scan)
        audit("scan_imported", scan["id"])
        return jsonify({"id": scan["id"]})

    @app.post("/api/demo")
    @need("scan_manage")
    def demo():
        return jsonify({"id": load_demo()})

    @app.get("/api/compare")
    @need("view")
    def api_compare():
        return jsonify(compare(_load(request.args["a"]), _load(request.args["b"]), storage.load_plan()))

    # ------------------------------------------------------------ Patch-Plan
    @app.get("/api/plan")
    @need("view")
    def plan_get():
        return jsonify(storage.load_plan())

    @app.post("/api/plan")
    @need("plan_edit")
    def plan_post():
        body = request.get_json(force=True) or {}
        if not body.get("key"):
            return jsonify({"error": "key fehlt"}), 400
        entry = storage.update_plan(body["key"], body.get("values", {}))
        audit("plan_changed", "%s: %s" % (body["key"], json.dumps(body.get("values", {}), ensure_ascii=False)))
        return jsonify(entry)

    # ------------------------------------------------------------ Konfigurationssicherung
    def backup_locations():
        b = cfgmod.load_config().get("backup", {})
        default = b.get("default_location") or configbackup.default_location()
        locs = [default] + [x for x in b.get("locations", []) if x and x != default]
        return default, locs

    def _loc_arg(loc):
        _default, locs = backup_locations()
        if loc not in locs:
            abort(400, "Unbekannter Speicherort")
        return loc

    @app.get("/api/backups/overview")
    @need("view")
    def backups_overview():
        scan_id = request.args.get("scan") or storage.latest_scan_id()
        scan = storage.load_scan(scan_id) if scan_id else None
        cfg = cfgmod.load_config()
        overrides = cfg.get("device_types", {})
        default, locs = backup_locations()
        out = []
        for s in (scan or {}).get("switches", []):
            versions = []
            for loc in locs:
                versions += configbackup.list_versions(loc, s["name"])
            versions.sort(key=lambda v: v["ts"], reverse=True)
            for v in versions:
                v.pop("path", None)
            out.append({"id": s["id"], "name": s["name"], "ip": s["ip"], "vendor": s.get("vendor", ""),
                        "model": s.get("model", ""), "guessed_type": configbackup.guess_device_type(s),
                        "device_type": overrides.get(s["ip"], "auto"), "versions": versions})
        return jsonify({"switches": out, "default_location": default, "locations": locs,
                        "max_versions": configbackup.MAX_VERSIONS, "scan_id": scan_id,
                        "device_types": configbackup.DEVICE_TYPE_LABELS,
                        "ssh_configured": bool(cfg.get("ssh_credentials"))})

    @app.post("/api/backups/run")
    @need("backup_run")
    def backups_run():
        b = request.get_json(force=True) or {}
        cfg = cfgmod.load_config()
        creds = cfg.get("ssh_credentials", [])
        if not creds:
            return jsonify({"error": "Keine SSH-Zugangsdaten hinterlegt (Scan & Einstellungen)."}), 400
        default, locs = backup_locations()
        loc = (b.get("location") or default).strip()
        if loc not in locs:
            if not users.can(g.user["role"], "backup_location"):
                return jsonify({"error": "Neue Speicherorte darf nur ein Administrator festlegen."}), 403
        try:
            loc = configbackup.check_location(loc)
        except (OSError, ValueError) as e:
            return jsonify({"error": "Speicherort nicht beschreibbar: %s" % e}), 400
        if users.can(g.user["role"], "backup_location"):
            bc = cfg.setdefault("backup", {})
            if loc not in locs:
                bc.setdefault("locations", []).append(loc)
            if b.get("remember"):
                bc["default_location"] = loc
            cfgmod.save_config(cfg)
        scan = storage.load_scan(b.get("scan_id") or storage.latest_scan_id() or "")
        if not scan:
            return jsonify({"error": "Kein Scan vorhanden - zuerst scannen."}), 400
        ids = set(b.get("switch_ids") or [])
        overrides = cfg.get("device_types", {})
        targets = []
        for s in scan["switches"]:
            if ids and s["id"] not in ids:
                continue
            dt = overrides.get(s["ip"], "auto")
            targets.append({"name": s["name"], "ip": s["ip"],
                            "device_type": configbackup.guess_device_type(s) if dt == "auto" else dt})
        if not targets:
            return jsonify({"error": "Keine Switches ausgewaehlt."}), 400
        user = g.user["username"]
        ip = request.remote_addr
        try:
            configbackup.start_job(targets, loc, creds, user,
                                   audit=lambda a, d: users.audit(user, a, d, ip))
        except RuntimeError as e:
            return jsonify({"error": str(e)}), 409
        audit("config_backup_started", "%d Switch(es) -> %s" % (len(targets), loc))
        return jsonify({"ok": True, "location": loc})

    @app.get("/api/backups/job")
    @need("view")
    def backups_job():
        j = configbackup.current_job()
        return jsonify(j.snapshot() if j else {"state": "idle"})

    @app.get("/api/backups/file")
    @need("backup_view")
    def backups_file():
        loc = _loc_arg(request.args.get("location", ""))
        sw, fn = request.args.get("switch", ""), request.args.get("file", "")
        try:
            text = configbackup.read_version(loc, sw, fn)
        except (ValueError, FileNotFoundError):
            abort(404)
        if request.args.get("download"):
            audit("config_downloaded", "%s/%s" % (sw, fn))
            return Response(text, mimetype="text/plain; charset=utf-8",
                            headers={"Content-Disposition": 'attachment; filename="%s"' % fn})
        return jsonify({"text": text})

    @app.get("/api/backups/diff")
    @need("backup_view")
    def backups_diff():
        loc = _loc_arg(request.args.get("location", ""))
        try:
            d = configbackup.diff(loc, request.args.get("switch", ""), request.args["a"], request.args["b"])
        except (ValueError, FileNotFoundError, KeyError):
            abort(404)
        return jsonify({"diff": d})

    @app.delete("/api/backups/file")
    @need("backup_delete")
    def backups_delete():
        b = request.get_json(force=True) or {}
        loc = _loc_arg(b.get("location", ""))
        try:
            configbackup.delete_version(loc, b.get("switch", ""), b.get("file", ""))
        except (ValueError, FileNotFoundError):
            abort(404)
        audit("config_deleted", "%s/%s" % (b.get("switch"), b.get("file")))
        return jsonify({"ok": True})

    @app.post("/api/backups/device-type")
    @need("settings")
    def backups_device_type():
        b = request.get_json(force=True) or {}
        cfg = cfgmod.load_config()
        dt = cfg.setdefault("device_types", {})
        if b.get("device_type") in (None, "", "auto"):
            dt.pop(b.get("ip", ""), None)
        elif b["device_type"] in configbackup.DEVICE_TYPE_LABELS or b["device_type"] in configbackup.CONFIG_COMMANDS:
            dt[b["ip"]] = b["device_type"]
        else:
            return jsonify({"error": "Unbekannter Geraetetyp"}), 400
        cfgmod.save_config(cfg)
        audit("device_type_changed", "%s -> %s" % (b.get("ip"), b.get("device_type")))
        return jsonify({"ok": True})

    @app.get("/api/fs/browse")
    @need("backup_location")
    def fs_browse():
        try:
            return jsonify(configbackup.browse(request.args.get("path", "")))
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    @app.post("/api/fs/mkdir")
    @need("backup_location")
    def fs_mkdir():
        b = request.get_json(force=True) or {}
        name = re.sub(r'[<>:"/\\|?*]', "", b.get("name", "")).strip()
        if not name or not b.get("parent"):
            return jsonify({"error": "Name fehlt"}), 400
        p = os.path.join(b["parent"], name)
        try:
            os.makedirs(p, exist_ok=True)
        except OSError as e:
            return jsonify({"error": str(e)}), 400
        audit("folder_created", p)
        return jsonify({"path": p})

    # ------------------------------------------------------------ Update
    def _upd_cfg():
        u = cfgmod.load_config().get("update", {})
        return u.get("repo") or updater.DEFAULT_REPO, u.get("token") or None

    @app.get("/api/update/check")
    @need("update")
    def update_check():
        repo, token = _upd_cfg()
        try:
            return jsonify(updater.check(repo, token))
        except updater.UpdateError as e:
            return jsonify({"error": str(e), "current": __version__, "mode": updater.install_mode()}), 502

    @app.post("/api/update/install")
    @need("update")
    def update_install():
        repo, token = _upd_cfg()
        try:
            info = updater.start_install(repo, token, app.config["PORT"],
                                         audit=lambda a, d, u=g.user["username"], ip=request.remote_addr:
                                         users.audit(u, a, d, ip))
        except updater.UpdateError as e:
            return jsonify({"error": str(e)}), 400
        audit("update_started", "%s -> %s" % (__version__, info["latest"]))
        return jsonify({"ok": True, "latest": info["latest"]})

    @app.get("/api/update/state")
    @need("view")
    def update_state():
        return jsonify({**updater.state(), "version": __version__})

    # ------------------------------------------------------------ Reports
    @app.get("/report/<scan_id>/<fmt>")
    @need("view")
    def report(scan_id, fmt):
        scan = _load(scan_id)
        plan = storage.load_plan()
        base = "Netzwerk-Report_%s" % re.sub(r"[^0-9A-Za-z_-]", "_", scan["id"])
        if fmt == "xlsx":
            data, mime, ext = reports.build_excel(scan, plan), \
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"
        elif fmt == "pdf":
            data, mime, ext = reports.build_pdf(scan, plan), "application/pdf", "pdf"
        elif fmt == "csv":
            data, mime, ext = reports.build_csv(scan, plan, True), "text/csv; charset=utf-8", "csv"
            base += "_Patchliste"
        elif fmt == "csv-all":
            data, mime, ext = reports.build_csv(scan, plan, False), "text/csv; charset=utf-8", "csv"
            base += "_alle-Ports"
        elif fmt == "csv-devices":
            data, mime, ext = reports.build_devices_csv(scan), "text/csv; charset=utf-8", "csv"
            base += "_Geraete"
        elif fmt == "json":
            data, mime, ext = json.dumps(scan, ensure_ascii=False, indent=1).encode("utf-8"), \
                "application/json", "json"
            base = "Scan_%s" % scan["id"]
        else:
            abort(404)
        audit("report_downloaded", "%s (%s)" % (scan["id"], fmt))
        return Response(data, mimetype=mime,
                        headers={"Content-Disposition": 'attachment; filename="%s.%s"' % (base, ext)})

    return app
