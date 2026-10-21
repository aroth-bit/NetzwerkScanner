"""Web-Dashboard und REST-API."""

import json
import os
import re
from datetime import timedelta
from functools import wraps

from flask import (Flask, Response, abort, jsonify, redirect, render_template, request, send_from_directory,
                   session, url_for)
from werkzeug.security import check_password_hash

from . import __version__, config as cfgmod, discovery, engine, reports, storage
from .compare import compare
from .paths import resource_dir, data_dir
from .snmp import probe

LOCAL = ("127.0.0.1", "::1", "::ffff:127.0.0.1")
SECRET_FIELDS = ("community", "auth_key", "priv_key")
MASK = "********"


def load_demo():
    """Mitgelieferten Beispiel-Scan (simulierte Switches) ins Datenverzeichnis uebernehmen."""
    with open(os.path.join(resource_dir(), "data", "demo_scan.json"), encoding="utf-8") as f:
        scan = json.load(f)
    storage.save_scan(scan)
    return scan["id"]


def create_app():
    res = resource_dir()
    app = Flask(__name__, template_folder=os.path.join(res, "templates"),
                static_folder=os.path.join(res, "static"))
    auth = cfgmod.load_auth()
    app.secret_key = auth["secret_key"]
    app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Strict",
                      PERMANENT_SESSION_LIFETIME=timedelta(hours=12), MAX_CONTENT_LENGTH=200 * 1024 * 1024)

    # ------------------------------------------------------------ Login
    def has_password():
        return bool(cfgmod.load_auth().get("password_hash"))

    @app.before_request
    def guard():
        ep = request.endpoint or ""
        if ep in ("static", "login", "setup"):
            return None
        if not has_password():
            if request.remote_addr not in LOCAL:
                return Response("Ersteinrichtung nur lokal am Server moeglich (http://localhost:<port>/setup).",
                                403)
            return redirect(url_for("setup"))
        if not session.get("auth"):
            if request.path.startswith("/api/") or request.path.startswith("/report/"):
                return jsonify({"error": "nicht angemeldet"}), 401
            return redirect(url_for("login", next=request.path))
        return None

    @app.route("/setup", methods=["GET", "POST"])
    def setup():
        if has_password():
            return redirect(url_for("login"))
        if request.remote_addr not in LOCAL:
            return Response("Ersteinrichtung nur lokal am Server moeglich.", 403)
        error = ""
        if request.method == "POST":
            pw, pw2 = request.form.get("password", ""), request.form.get("password2", "")
            if len(pw) < 8:
                error = "Das Passwort muss mindestens 8 Zeichen lang sein."
            elif pw != pw2:
                error = "Die Passwoerter stimmen nicht ueberein."
            else:
                cfgmod.set_password(pw)
                session.permanent = True
                session["auth"] = True
                return redirect(url_for("index"))
        return render_template("login.html", setup=True, error=error, version=__version__)

    @app.route("/login", methods=["GET", "POST"])
    def login():
        error = ""
        if request.method == "POST":
            h = cfgmod.load_auth().get("password_hash", "")
            if h and check_password_hash(h, request.form.get("password", "")):
                session.permanent = True
                session["auth"] = True
                nxt = request.args.get("next") or "/"
                return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else "/")
            error = "Falsches Passwort."
        return render_template("login.html", setup=False, error=error, version=__version__)

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    # ------------------------------------------------------------ UI
    @app.route("/")
    def index():
        return render_template("index.html", version=__version__)

    # ------------------------------------------------------------ Konfiguration
    def masked(cfg):
        cfg = json.loads(json.dumps(cfg))
        for c in cfg.get("credentials", []):
            for f in SECRET_FIELDS:
                if c.get(f):
                    c[f] = MASK
        return cfg

    @app.get("/api/config")
    def get_config():
        return jsonify(masked(cfgmod.load_config()))

    @app.post("/api/config")
    def post_config():
        new = request.get_json(force=True) or {}
        old = cfgmod.load_config()
        old_list = old.get("credentials", [])
        old_creds = {c.get("name"): c for c in old_list if c.get("name")}
        for i, c in enumerate(new.get("credentials", [])):
            prev = old_creds.get(c.get("name")) or (old_list[i] if i < len(old_list) else {})
            for f in SECRET_FIELDS:
                if c.get(f) == MASK:
                    c[f] = prev.get(f, "")
        for key in ("subnets", "exclude", "snmp_devices"):
            if isinstance(new.get(key), str):
                new[key] = [x.strip() for x in re.split(r"[\r\n]+", new[key]) if x.strip()]
        try:
            for key in ("subnets", "exclude"):
                discovery.parse_targets(new.get(key, []))
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        return jsonify(masked(cfgmod.save_config(new)))

    @app.get("/api/local-networks")
    def local_networks():
        return jsonify({"networks": discovery.local_addresses(), "nmap": bool(discovery.nmap_path()),
                        "data_dir": data_dir()})

    @app.post("/api/test-snmp")
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
    def scan_start():
        body = request.get_json(silent=True) or {}
        try:
            job = engine.start_scan(cfgmod.load_config(), body.get("name", ""))
        except RuntimeError as e:
            return jsonify({"error": str(e)}), 409
        return jsonify({"id": job.id})

    @app.post("/api/scan/cancel")
    def scan_cancel():
        job = engine.current()
        if job:
            job.cancel()
        return jsonify({"ok": True})

    @app.get("/api/scan/status")
    def scan_status():
        job = engine.current()
        if not job:
            return jsonify({"state": "idle"})
        return jsonify(job.snapshot(int(request.args.get("from", 0))))

    # ------------------------------------------------------------ Ergebnisse
    @app.get("/api/scans")
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
    def scan_get(scan_id):
        return jsonify(_load(scan_id))

    @app.delete("/api/scans/<scan_id>")
    def scan_delete(scan_id):
        storage.delete_scan(scan_id)
        return jsonify({"ok": True})

    @app.post("/api/scans/<scan_id>/rename")
    def scan_rename(scan_id):
        storage.rename_scan(scan_id, (request.get_json(force=True) or {}).get("name", ""))
        return jsonify({"ok": True})

    @app.post("/api/scans/import")
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
        return jsonify({"id": scan["id"]})

    @app.post("/api/demo")
    def demo():
        return jsonify({"id": load_demo()})

    @app.get("/api/compare")
    def api_compare():
        return jsonify(compare(_load(request.args["a"]), _load(request.args["b"]), storage.load_plan()))

    # ------------------------------------------------------------ Patch-Plan
    @app.get("/api/plan")
    def plan_get():
        return jsonify(storage.load_plan())

    @app.post("/api/plan")
    def plan_post():
        body = request.get_json(force=True) or {}
        if not body.get("key"):
            return jsonify({"error": "key fehlt"}), 400
        return jsonify(storage.update_plan(body["key"], body.get("values", {})))

    # ------------------------------------------------------------ Reports
    @app.get("/report/<scan_id>/<fmt>")
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
        return Response(data, mimetype=mime,
                        headers={"Content-Disposition": 'attachment; filename="%s.%s"' % (base, ext)})

    @app.get("/favicon.ico")
    def favicon():
        return send_from_directory(app.static_folder, "favicon.svg", mimetype="image/svg+xml")

    return app
