"""Update ueber GitHub-Releases: pruefen, herunterladen (mit SHA-256-Pruefung) und installieren."""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import threading
import urllib.error
import urllib.request
import zipfile
from datetime import datetime

from . import __version__
from .paths import IS_WINDOWS, data_dir, resource_dir

DEFAULT_REPO = "aroth-bit/NetzwerkScanner"
API = "https://api.github.com"
_NO_WINDOW = 0x08000000 if IS_WINDOWS else 0


class UpdateError(Exception):
    pass


def parse_version(v):
    nums = re.findall(r"\d+", v or "")
    return tuple(int(x) for x in nums[:3]) + (0,) * (3 - len(nums[:3]))


def install_mode():
    """'windows' (installierte EXE), 'linux' (install_kali.sh) oder 'source' (kein Auto-Update)."""
    if IS_WINDOWS and getattr(sys, "frozen", False):
        if os.path.exists(os.path.join(os.path.dirname(sys.executable), "Install.ps1")):
            return "windows"
    if not IS_WINDOWS and os.path.abspath(resource_dir()).startswith("/opt/netscanner/") \
            and os.path.exists("/opt/netscanner/uninstall.sh"):
        return "linux"
    return "source"


def _headers(token, accept="application/vnd.github+json"):
    h = {"Accept": accept, "User-Agent": "NetzwerkScanner/%s" % __version__, "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        h["Authorization"] = "Bearer %s" % token
    return h


def _get_json(url, token):
    req = urllib.request.Request(url, headers=_headers(token))
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise UpdateError("Repository oder Release nicht gefunden (privates Repository? Dann GitHub-Token "
                              "eintragen).")
        if e.code in (401, 403):
            raise UpdateError("Zugriff verweigert (%d) - GitHub-Token pruefen." % e.code)
        raise UpdateError("GitHub-Fehler %d" % e.code)
    except urllib.error.URLError as e:
        raise UpdateError("GitHub nicht erreichbar: %s (Proxy? Umgebungsvariable HTTPS_PROXY setzen)" % e.reason)


def _asset_pattern(mode):
    return r"-Windows\.zip$" if mode == "windows" else r"-Linux\.tar\.gz$"


def check(repo=None, token=None):
    repo = repo or DEFAULT_REPO
    if not re.match(r"^[\w.-]+/[\w.-]+$", repo):
        raise UpdateError("Repository bitte als 'besitzer/name' angeben.")
    rel = _get_json("%s/repos/%s/releases/latest" % (API, repo), token)
    tag = rel.get("tag_name", "")
    mode = install_mode()
    assets = [{"name": a["name"], "size": a["size"], "url": a["url"], "digest": a.get("digest") or ""}
              for a in rel.get("assets", [])]
    pat = _asset_pattern(mode)
    asset = next((a for a in assets if re.search(pat, a["name"])), None)
    return {
        "current": __version__, "latest": tag.lstrip("v"), "tag": tag, "name": rel.get("name") or tag,
        "notes": rel.get("body") or "", "published": rel.get("published_at"), "url": rel.get("html_url"),
        "update_available": parse_version(tag) > parse_version(__version__),
        "mode": mode, "asset": asset, "can_install": mode != "source" and asset is not None,
        "repo": repo,
    }


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _download(asset, token, dest):
    """Asset ueber die API laden. Die Weiterleitung zum Speicher-Server erfolgt ohne Token."""
    req = urllib.request.Request(asset["url"], headers=_headers(token, "application/octet-stream"))
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        resp = opener.open(req, timeout=60)
    except urllib.error.HTTPError as e:
        if e.code in (301, 302, 303, 307, 308) and e.headers.get("Location"):
            resp = urllib.request.urlopen(urllib.request.Request(
                e.headers["Location"], headers={"User-Agent": "NetzwerkScanner/%s" % __version__}), timeout=60)
        else:
            raise UpdateError("Download fehlgeschlagen (%d)" % e.code)
    h = hashlib.sha256()
    with resp, open(dest, "wb") as f:
        while True:
            chunk = resp.read(1024 * 256)
            if not chunk:
                break
            h.update(chunk)
            f.write(chunk)
    digest = (asset.get("digest") or "").lower()
    if digest.startswith("sha256:") and digest.split(":", 1)[1] != h.hexdigest():
        os.remove(dest)
        raise UpdateError("Pruefsumme stimmt nicht - Download verworfen.")
    if os.path.getsize(dest) != asset.get("size", os.path.getsize(dest)):
        raise UpdateError("Download unvollstaendig.")
    return h.hexdigest()


def _safe_extract(archive, dest):
    dest = os.path.abspath(dest)
    if archive.endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            for n in z.namelist():
                target = os.path.abspath(os.path.join(dest, n))
                if not (target == dest or target.startswith(dest + os.sep)):
                    raise UpdateError("Unsicherer Pfad im Archiv: %s" % n)
            z.extractall(dest)
    else:
        with tarfile.open(archive) as t:
            try:
                t.extractall(dest, filter="data")
            except TypeError:  # Python < 3.12
                for m in t.getmembers():
                    target = os.path.abspath(os.path.join(dest, m.name))
                    if not target.startswith(dest + os.sep) or m.issym() or m.islnk():
                        raise UpdateError("Unsicherer Pfad im Archiv: %s" % m.name)
                t.extractall(dest)


_state = {"state": "idle", "message": "", "log": []}
_state_lock = threading.Lock()


def state():
    with _state_lock:
        return dict(_state, log=list(_state["log"]))


def _set(st=None, msg=None):
    with _state_lock:
        if st:
            _state["state"] = st
        if msg:
            _state["message"] = msg
            _state["log"].append("%s  %s" % (datetime.now().strftime("%H:%M:%S"), msg))


def start_install(repo, token, port, audit=None):
    with _state_lock:
        if _state["state"] in ("downloading", "installing"):
            raise UpdateError("Update laeuft bereits.")
        _state.update(state="downloading", message="", log=[])
    info = check(repo, token)
    if not info["can_install"]:
        _set("error", "Automatisches Update ist fuer diese Installationsart nicht moeglich (%s)." % info["mode"])
        raise UpdateError(_state["message"])
    threading.Thread(target=_install, args=(info, token, port, audit), daemon=True).start()
    return info


def _install(info, token, port, audit):
    try:
        base = os.path.join(data_dir(), "update")
        work = os.path.join(base, info["tag"] or "latest")
        if os.path.exists(work):
            shutil.rmtree(work, ignore_errors=True)
        os.makedirs(work, exist_ok=True)
        archive = os.path.join(base, info["asset"]["name"])
        _set("downloading", "Lade %s (%.1f MB) ..." % (info["asset"]["name"], info["asset"]["size"] / 1048576.0))
        sha = _download(info["asset"], token, archive)
        _set(None, "Download ok, SHA-256 %s%s" % (sha[:16], " (geprueft)" if info["asset"].get("digest") else ""))
        _safe_extract(archive, work)
        os.remove(archive)
        _set("installing", "Installiere Version %s - der Dienst startet gleich neu ..." % info["latest"])
        if audit:
            audit("update_install", "%s -> %s" % (__version__, info["latest"]))
        if info["mode"] == "windows":
            _apply_windows(work, port, base)
        else:
            _apply_linux(work, base)
    except Exception as e:
        _set("error", "Update fehlgeschlagen: %s" % e)


def _apply_windows(work, port, base):
    script = os.path.join(work, "Install.ps1")
    if not os.path.exists(script):
        raise UpdateError("Install.ps1 fehlt im Update-Paket.")
    install_dir = os.path.dirname(sys.executable)
    log = os.path.join(base, "install.log")
    runner = os.path.join(base, "run-update.cmd")
    with open(runner, "w", encoding="ascii", errors="replace") as f:
        f.write('@echo off\r\npowershell.exe -NoProfile -ExecutionPolicy Bypass -File "%s" -Update -Silent '
                '-Port %d -InstallDir "%s" > "%s" 2>&1\r\n' % (script, int(port), install_dir, log))
    # eigene geplante Aufgabe als SYSTEM: laeuft unabhaengig von diesem Prozess weiter,
    # auch wenn der Dienst waehrend der Installation beendet wird
    r = subprocess.run(["schtasks", "/Create", "/TN", "NetzwerkScanner-Update", "/SC", "ONCE", "/ST", "00:00",
                        "/RU", "SYSTEM", "/RL", "HIGHEST", "/F", "/TR", '"%s"' % runner],
                       capture_output=True, creationflags=_NO_WINDOW)
    if r.returncode != 0:
        raise UpdateError("Update-Aufgabe konnte nicht angelegt werden (Administratorrechte noetig): %s"
                          % r.stderr.decode("cp850", "ignore").strip())
    r = subprocess.run(["schtasks", "/Run", "/TN", "NetzwerkScanner-Update"], capture_output=True,
                       creationflags=_NO_WINDOW)
    if r.returncode != 0:
        raise UpdateError("Update-Aufgabe konnte nicht gestartet werden.")


def _apply_linux(work, base):
    script = None
    for root, _dirs, files in os.walk(work):
        if "install_kali.sh" in files and root.endswith(os.path.join("installer", "linux")):
            script = os.path.join(root, "install_kali.sh")
            break
    if not script:
        raise UpdateError("install_kali.sh fehlt im Update-Paket.")
    os.chmod(script, 0o755)
    log = os.path.join(base, "install.log")
    cmd = "/bin/bash '%s' --update > '%s' 2>&1" % (script, log)
    unit = "netscanner-update-%s" % datetime.now().strftime("%Y%m%d%H%M%S")
    if shutil.which("systemd-run"):
        # eigene systemd-Unit, damit der Neustart des Dienstes die Installation nicht abbricht
        r = subprocess.run(["systemd-run", "--unit", unit, "--collect", "--no-block", "/bin/sh", "-c", cmd],
                           capture_output=True)
        if r.returncode != 0:
            raise UpdateError("systemd-run fehlgeschlagen: %s" % r.stderr.decode("utf-8", "ignore"))
    else:
        subprocess.Popen(["/bin/sh", "-c", cmd], start_new_session=True)
