#!/usr/bin/env bash
# NetzwerkScanner direkt aus den GitHub-Releases installieren (Kali / Debian / Ubuntu)
#
#   Oeffentliches Repository:
#     curl -fsSL https://raw.githubusercontent.com/aroth-bit/NetzwerkScanner/main/installer/linux/install-from-github.sh | sudo bash
#
#   Privates Repository (Token mit Leserecht auf "Contents"):
#     export GITHUB_TOKEN=ghp_...
#     curl -fsSL -H "Authorization: Bearer $GITHUB_TOKEN" \
#       https://raw.githubusercontent.com/aroth-bit/NetzwerkScanner/main/installer/linux/install-from-github.sh \
#       | sudo GITHUB_TOKEN="$GITHUB_TOKEN" bash
#
#   Optionen fuer install_kali.sh anhaengen:  ... | sudo bash -s -- --port 9000
set -euo pipefail

REPO="${NETSCANNER_REPO:-aroth-bit/NetzwerkScanner}"
TOKEN="${GITHUB_TOKEN:-}"
TAG="${NETSCANNER_TAG:-latest}"

if [[ $EUID -ne 0 ]]; then echo "Bitte mit sudo ausfuehren." >&2; exit 1; fi
for c in curl tar python3 sha256sum; do
  command -v $c >/dev/null || { apt-get update -qq && apt-get install -y -qq curl tar python3 coreutils >/dev/null; break; }
done

AUTH=()
[[ -n "$TOKEN" ]] && AUTH=(-H "Authorization: Bearer $TOKEN")
if [[ "$TAG" == "latest" ]]; then API="https://api.github.com/repos/$REPO/releases/latest"
else API="https://api.github.com/repos/$REPO/releases/tags/$TAG"; fi

echo "==> Suche Release in $REPO ..."
JSON=$(curl -fsSL "${AUTH[@]}" -H "Accept: application/vnd.github+json" "$API") || {
  echo "Release nicht gefunden. Privates Repository? Dann GITHUB_TOKEN setzen." >&2; exit 1; }
read -r NAME URL DIGEST TAGNAME < <(python3 -c '
import json, sys
r = json.load(sys.stdin)
a = next((a for a in r.get("assets", []) if a["name"].endswith("-Linux.tar.gz")), None)
if not a:
    sys.exit("Linux-Paket fehlt im Release")
print(a["name"], a["url"], (a.get("digest") or "-").replace("sha256:", ""), r["tag_name"])' <<<"$JSON")
echo "    Version $TAGNAME: $NAME"

WORK=$(mktemp -d /tmp/netscanner-XXXXXX)
trap 'rm -rf "$WORK"' EXIT
# curl gibt den Token bei der Weiterleitung zum Speicher-Server nicht weiter (anderer Host)
curl -fsSL "${AUTH[@]}" -H "Accept: application/octet-stream" -o "$WORK/$NAME" "$URL"
SUM=$(sha256sum "$WORK/$NAME" | cut -d' ' -f1)
if [[ "$DIGEST" != "-" ]]; then
  [[ "$SUM" == "$DIGEST" ]] || { echo "Pruefsumme stimmt nicht - Abbruch." >&2; exit 1; }
  echo "    SHA-256 geprueft: $SUM"
fi
tar -xzf "$WORK/$NAME" -C "$WORK"
DIR=$(find "$WORK" -maxdepth 1 -type d -name "NetzwerkScanner-*" | head -n1)

# Rueckfragen (Administrator anlegen) auch bei "curl | bash" ueber das Terminal ermoeglichen
if [[ -r /dev/tty ]]; then
  bash "$DIR/installer/linux/install_kali.sh" "$@" </dev/tty
else
  bash "$DIR/installer/linux/install_kali.sh" "$@"
fi

# Repository/Token fuer den Update-Button hinterlegen
GITHUB_TOKEN="$TOKEN" /usr/local/bin/netscanner --configure-update "$REPO"
