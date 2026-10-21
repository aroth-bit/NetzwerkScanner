#!/usr/bin/env bash
# NetzwerkScanner - Installation auf Kali Linux / Debian / Ubuntu
#
#   sudo ./installer/linux/install_kali.sh            # Installation + systemd-Dienst auf Port 8080
#   sudo ./installer/linux/install_kali.sh --port 9000
#   sudo ./installer/linux/install_kali.sh --no-service
#   sudo ./installer/linux/install_kali.sh --update     # Update: Port/Dienst bleiben, keine Rueckfragen
#
# Installiert nach /opt/netscanner, Daten unter /var/lib/netscanner, Befehl: netscanner
set -euo pipefail

PORT=8080
SERVICE=1
UPDATE=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --port) PORT="$2"; shift 2 ;;
    --no-service) SERVICE=0; shift ;;
    --update) UPDATE=1; shift ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *) echo "Unbekannte Option: $1"; exit 1 ;;
  esac
done

if [[ $EUID -ne 0 ]]; then
  echo "Bitte mit sudo ausfuehren." >&2
  exit 1
fi

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
APP=/opt/netscanner
DATA=/var/lib/netscanner

if [[ $UPDATE -eq 1 ]]; then
  # vorhandene Einstellungen uebernehmen
  if [[ -f /etc/systemd/system/netscanner.service ]]; then
    P=$(grep -oP -- '--port \K[0-9]+' /etc/systemd/system/netscanner.service || true)
    PORT=${P:-$PORT}
  else
    SERVICE=0
  fi
  echo "==> Update auf Version $(grep -oP '__version__ = "\K[^"]+' "$SRC/netscanner/__init__.py") (Port $PORT)"
fi

echo "==> Systempakete (python3, venv, nmap, ping)"
if [[ $UPDATE -eq 0 ]] && command -v apt-get >/dev/null; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq || true
  apt-get install -y -qq python3 python3-venv python3-pip nmap iputils-ping iproute2 >/dev/null
fi

echo "==> Kopiere Programm nach $APP"
mkdir -p "$APP"
rm -rf "$APP/netscanner"
cp -r "$SRC/netscanner" "$SRC/requirements.txt" "$SRC/run_netscanner.py" "$APP/"
cp "$SRC/installer/linux/uninstall.sh" "$APP/" 2>/dev/null || true
find "$APP/netscanner" -name "__pycache__" -type d -prune -exec rm -rf {} +

echo "==> Python-Umgebung"
if [[ ! -x "$APP/venv/bin/python" ]]; then
  python3 -m venv "$APP/venv"
fi
if [[ -d "$SRC/wheels" ]]; then
  # Offline-Installation mit mitgebrachten Wheels (siehe README)
  "$APP/venv/bin/pip" install -q --no-index --find-links "$SRC/wheels" -r "$APP/requirements.txt"
else
  "$APP/venv/bin/pip" install -q --upgrade pip
  "$APP/venv/bin/pip" install -q -r "$APP/requirements.txt"
fi

echo "==> Datenverzeichnis $DATA"
mkdir -p "$DATA"
chmod 700 "$DATA"

cat > /usr/local/bin/netscanner <<EOF
#!/bin/sh
# Wrapper: NetzwerkScanner mit zentralem Datenverzeichnis
cd "$APP" && exec "$APP/venv/bin/python" -m netscanner --data "$DATA" "\$@"
EOF
chmod 755 /usr/local/bin/netscanner

if ! grep -qs password_hash "$DATA/users.json" "$DATA/auth.json"; then
  if [[ -t 0 && $UPDATE -eq 0 ]]; then
    echo "==> Ersten Administrator fuer das Dashboard anlegen"
    /usr/local/bin/netscanner --set-password
  else
    echo "Hinweis: Administrator spaeter mit 'sudo netscanner --set-password' anlegen."
  fi
fi

if [[ $SERVICE -eq 1 ]] && command -v systemctl >/dev/null; then
  echo "==> systemd-Dienst netscanner.service (Port $PORT)"
  cat > /etc/systemd/system/netscanner.service <<EOF
[Unit]
Description=NetzwerkScanner Dashboard
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$APP
Environment=NETSCANNER_SERVICE=1
ExecStart=$APP/venv/bin/python -m netscanner --no-browser --port $PORT --data $DATA
Restart=on-failure
RestartSec=5
# root wird fuer nmap-ARP-Scans und Raw-Sockets benoetigt
User=root

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  systemctl enable netscanner.service
  systemctl restart netscanner.service
  sleep 2
  systemctl --no-pager --lines=3 status netscanner.service || true
fi

IP=$(hostname -I 2>/dev/null | awk '{print $1}')
echo
echo "NetzwerkScanner installiert."
echo "  Dashboard : http://localhost:$PORT/   bzw. http://${IP:-<IP>}:$PORT/"
echo "  Befehl    : netscanner --help   (z.B. 'sudo netscanner --scan --report /tmp/report.xlsx')"
echo "  Dienst    : systemctl status|restart|stop netscanner"
echo "  Entfernen : sudo $APP/uninstall.sh"
