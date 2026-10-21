#!/usr/bin/env bash
# NetzwerkScanner entfernen. Daten in /var/lib/netscanner bleiben erhalten (ausser --purge).
set -euo pipefail
if [[ $EUID -ne 0 ]]; then echo "Bitte mit sudo ausfuehren." >&2; exit 1; fi
if command -v systemctl >/dev/null && [[ -f /etc/systemd/system/netscanner.service ]]; then
  systemctl disable --now netscanner.service || true
  rm -f /etc/systemd/system/netscanner.service
  systemctl daemon-reload
fi
rm -f /usr/local/bin/netscanner
rm -rf /opt/netscanner
if [[ "${1:-}" == "--purge" ]]; then
  rm -rf /var/lib/netscanner
  echo "NetzwerkScanner und alle Daten entfernt."
else
  echo "NetzwerkScanner entfernt. Daten bleiben unter /var/lib/netscanner (loeschen mit --purge)."
fi
