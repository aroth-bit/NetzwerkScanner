"""Startpunkt:  python -m netscanner  [Optionen]"""

import argparse
import getpass
import os
import sys
import threading
import time
import webbrowser

from . import __version__


def main(argv=None):
    ap = argparse.ArgumentParser(prog="netscanner", description="NetzwerkScanner %s - Dashboard & Scanner" %
                                 __version__)
    ap.add_argument("--host", default=os.environ.get("NETSCANNER_HOST", "0.0.0.0"),
                    help="Bind-Adresse des Web-Servers (Standard 0.0.0.0)")
    ap.add_argument("--port", type=int, default=int(os.environ.get("NETSCANNER_PORT", "8080")),
                    help="Port des Web-Servers (Standard 8080)")
    ap.add_argument("--data", help="Datenverzeichnis (Konfiguration, Scans)")
    ap.add_argument("--no-browser", action="store_true", help="Browser nicht automatisch oeffnen")
    ap.add_argument("--set-password", action="store_true",
                    help="Passwort eines Benutzers setzen (legt ihn als Administrator an, falls neu) und beenden")
    ap.add_argument("--user", help="Benutzername fuer --set-password (Standard: admin bzw. Abfrage)")
    ap.add_argument("--list-users", action="store_true", help="Benutzer auflisten und beenden")
    ap.add_argument("--configure-update", metavar="BESITZER/REPO",
                    help="GitHub-Repository fuer Updates festlegen (Token aus Umgebungsvariable GITHUB_TOKEN)")
    ap.add_argument("--scan", action="store_true", help="Scan mit gespeicherter Konfiguration ohne Web-UI starten")
    ap.add_argument("--report", help="nach --scan einen Report schreiben (.xlsx, .pdf oder .csv)")
    ap.add_argument("--demo", action="store_true", help="Beispiel-Scan importieren")
    ap.add_argument("--version", action="version", version=__version__)
    args = ap.parse_args(argv)

    from . import paths
    if args.data:
        paths.set_data_dir(args.data)
    print("NetzwerkScanner %s  -  Daten: %s" % (__version__, paths.data_dir()))

    if args.list_users:
        from . import users
        for u in users.list_users():
            print("%-24s %-14s %s" % (u["username"], u["role_label"], "gesperrt" if u["disabled"] else ""))
        return 0

    if args.configure_update:
        from .config import load_config, save_config
        cfg = load_config()
        cfg["update"] = {"repo": args.configure_update, "token": os.environ.get("GITHUB_TOKEN", "")}
        save_config(cfg)
        print("Update-Quelle: %s%s" % (args.configure_update, " (mit Token)" if cfg["update"]["token"] else ""))
        return 0

    if args.set_password:
        from . import users
        name = args.user
        if not name:
            name = (input("Benutzername [admin]: ") if sys.stdin and sys.stdin.isatty() else "").strip() or "admin"
        exists = users.get_user(name) is not None
        print("%s '%s'" % ("Neues Passwort fuer" if exists else "Lege Administrator an:", name))
        pw = getpass.getpass("Passwort (min. 8 Zeichen): ")
        if pw != getpass.getpass("Wiederholen: "):
            print("Abgebrochen: Passwoerter nicht identisch.")
            return 1
        try:
            users.set_password(name, pw, "admin")
        except users.UserError as e:
            print("Abgebrochen: %s" % e)
            return 1
        users.audit(name, "password_set_cli", "ueber Kommandozeile")
        print("Gespeichert.")
        return 0

    if args.demo:
        from .web import load_demo
        print("Demo-Scan importiert: %s" % load_demo())

    if args.scan:
        return headless_scan(args.report)

    from waitress import serve
    from .web import create_app
    app = create_app(port=args.port)
    url = "http://%s:%d/" % ("localhost" if args.host in ("0.0.0.0", "::") else args.host, args.port)
    print("Dashboard: %s   (Beenden mit Strg+C)" % url)
    if not args.no_browser and not os.environ.get("NETSCANNER_SERVICE"):
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    serve(app, host=args.host, port=args.port, threads=12, channel_timeout=300)
    return 0


def headless_scan(report_path=None):
    from . import engine, reports, storage
    from .config import load_config
    job = engine.start_scan(load_config())
    pos = 0
    while job.is_alive():
        time.sleep(1)
        snap = job.snapshot(pos)
        for line in snap["log"]:
            print(line)
        pos = snap["log_total"]
    snap = job.snapshot(pos)
    for line in snap["log"]:
        print(line)
    if snap["state"] != "done":
        return 2
    if report_path:
        scan = storage.load_scan(job.id)
        plan = storage.load_plan()
        ext = report_path.lower().rsplit(".", 1)[-1]
        data = {"xlsx": reports.build_excel, "pdf": reports.build_pdf}.get(ext, lambda s, p: reports.build_csv(s, p))(
            scan, plan)
        with open(report_path, "wb") as f:
            f.write(data)
        print("Report geschrieben: %s" % report_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
