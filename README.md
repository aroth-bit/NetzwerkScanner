# NetzwerkScanner

Netzwerk-Inventarisierung für Rechenzentrums-Umzüge: findet alle Switches, VLANs und Geräte, ordnet **jedes Gerät seinem Switch-Port** zu und erzeugt eine **Patchliste** (Excel / PDF / CSV), mit der jedes Kabel wieder an den richtigen Port gesteckt werden kann.

Läuft auf **Kali Linux** (und anderen Debian/Ubuntu-Systemen) sowie auf **Windows Server 2016+ / Windows 10/11**.

---

## Was der Scanner macht

| Quelle | Was ermittelt wird |
|---|---|
| **SNMP auf Switches** (v1/v2c/v3) | alle Ports mit Name, Beschreibung, Link-Status, Speed, Access/Trunk, VLANs, LACP/Port-Channels, MAC-Adresstabellen (Q-BRIDGE und Cisco *community@vlan*), Modell, Seriennummer, Standort |
| **SNMP auf Routern/L3-Switches/Firewalls** | ARP-Tabellen (IP ↔ MAC in **allen VLANs**), Subnetze und Gateways je VLAN |
| **LLDP / CDP** | Switch-zu-Switch-Verbindungen, weitere Switches werden **automatisch gefunden**; Telefone, APs, Firewalls, Server mit LLDP |
| **Ping / TCP / nmap** | aktive Hosts in allen Netzen (auch Hosts mit Firewall per TCP-Fallback) |
| **DNS / NetBIOS** | Hostnamen |
| **IEEE-OUI-Liste** | Hersteller der Netzwerkkarte, Erkennung virtueller Maschinen |

Die Zuordnung **Gerät → Port** erfolgt über die MAC-Tabellen: Ports zu anderen gescannten Switches (per LLDP/CDP oder gelernten Switch-MACs) werden als Uplinks erkannt und herausgefiltert, so dass jedes Gerät am **Access-Port des nächstgelegenen Switches** landet. Ohne LLDP werden Switch-Verbindungen aus den MAC-Tabellen abgeleitet (gestrichelt, „vermutet“).

**Für den Umzug wichtig – auch diese Ports stehen in der Patchliste:**
- Ports mit Link, aber **ohne erkanntes Gerät** (stille Geräte, z. B. Replikationsnetze, iLO/iDRAC ohne Traffic)
- Ports, die **down sind, aber eine Beschreibung haben** (ausgeschaltete Server)
- **alle Mitglieder eines LAG/Port-Channels** (beide Kabel eines Server-Bonds)
- Uplinks zwischen Switches
- Geräte, die per Ping gefunden, aber **keinem Port zugeordnet** werden konnten, werden separat als „manuell prüfen“ ausgewiesen.

## Dashboard

- **Übersicht** – Kennzahlen, Warnungen, Port-Belegung je Switch
- **Topologie** – interaktiver Netzplan (Switches, Verbindungen mit Portnummern, Endgeräte farbig nach VLAN, Suche)
- **Switches & Ports** – Frontansicht jedes Switches (Ports wie am Gerät angeordnet, farbig nach Status); Klick zeigt Gerät(e), IP, Hostname, MAC, VLAN
- **Geräte** – durchsuchbare/sortierbare Liste aller Geräte mit IP, Hostname, MAC, Hersteller, VLAN, Switch und Port
- **VLANs & Netze** – VLANs mit Subnetzen, Gateways und Geräten
- **Umzugsplanung** – je Quell-Port Ziel-Switch, Ziel-Port, Kabel-Label, Bemerkung und „Erledigt“ erfassen (wird in alle Reports übernommen)
- **Vergleich** – Scan vorher/nachher vergleichen: fehlende Geräte, falscher Port (Soll/Ist gegen die Umzugsplanung), neue Geräte
- **Konfigurationen** – Switch-Konfigurationen per SSH sichern (einzeln, Auswahl oder alle), Speicherort wählen, Versionen ansehen, vergleichen, herunterladen
- **Scan & Einstellungen** – Netze, Switches, SNMP- und SSH-Zugangsdaten, Optionen, Fortschritt und Protokoll, Scan-Historie, JSON-Import
- **Benutzer** – Benutzer anlegen, Rollen vergeben, sperren (nur Administratoren)
- **Protokoll** – wer hat wann was gemacht (Anmeldungen, Scans, Sicherungen, Änderungen) – für Administratoren und Audit
- **System & Update** – installierte Version, Update von GitHub per Knopfdruck

## Benutzer und Rollen

| Rolle | Rechte |
|---|---|
| **Administrator** | alles: Einstellungen und Zugangsdaten, Benutzerverwaltung, Updates, Scans/Sicherungen löschen, beliebige Speicherorte |
| **Benutzer** | alles ansehen, Scans starten, Umzugsplanung bearbeiten, Konfigurationen sichern (an den vom Admin freigegebenen Speicherorten), Reports |
| **Audit** | nur lesen: Ergebnisse, Reports, gesicherte Konfigurationen, Protokoll – keine Änderungen |

Die Rechte werden auf dem Server geprüft (nicht nur in der Oberfläche). Nach 5 falschen Passwörtern wird die Anmeldung für 2 Minuten gesperrt. Alle Aktionen landen im Protokoll (`audit.log` im Datenverzeichnis). Beim Update von Version 1.0 wird das bisherige Passwort automatisch zum Benutzer **admin**.

## Konfigurationssicherung

1. *Scan & Einstellungen* → **SSH-Zugangsdaten** eintragen (Benutzer mit Leserechten; bei Cisco ggf. Enable-Passwort). Mehrere Zugänge werden der Reihe nach probiert.
2. *Konfigurationen* → Switch(es) auswählen → **Konfiguration speichern** → Speicherort wählen (Administratoren können über **Durchsuchen** jeden Ordner des Servers oder eine Netzwerkfreigabe wählen und als Standard merken).
3. Je Switch entsteht ein Unterordner mit `<Switch>_<Datum-Uhrzeit>.cfg`. Es bleiben **höchstens 5 Versionen** – die sechste Sicherung ersetzt automatisch die älteste.
4. **Versionen** zeigt alle Stände; **Vergleich mit Vorversion** zeigt die Änderungen zeilengenau.

Der Gerätetyp wird aus den SNMP-Daten erkannt (Cisco IOS/NX-OS, Aruba AOS-CX/AOS-Switch, Comware, Huawei, Juniper, Arista, Dell, Extreme, Fortinet, Palo Alto, MikroTik u. a.) und kann je Switch überschrieben werden.

## Reports (Download über „Report herunterladen“)

- **Excel (.xlsx)**: Übersicht, Patchliste aller zu steckenden Ports (farbig, Filter, Abhak-Spalte), je Switch ein Blatt mit allen Ports, Geräte, Geräte ohne Zuordnung, VLANs, Netze, Switch-Verbindungen
- **PDF** (A4 quer, zum Ausdrucken im RZ): je Switch eine Frontansicht + Port-Tabelle mit Abhak-Kästchen
- **CSV**: Patchliste, alle Ports, Geräteliste
- **JSON**: Rohdaten (z. B. auf Kali scannen und auf dem Windows-Server importieren)

---

## Voraussetzungen im Netzwerk

1. **SNMP-Lesezugriff** auf alle Switches und den Core/Router (v2c-Community oder v3-Benutzer). Die IP des Scan-Rechners muss in den SNMP-ACLs erlaubt sein.
2. **LLDP oder CDP** auf den Switches aktiv (empfohlen, damit Switches automatisch gefunden und Uplinks sicher erkannt werden).
3. Cisco IOS mit SNMPv3: der Benutzer braucht Zugriff auf die VLAN-Kontexte (`snmp-server group … context vlan- match prefix`), sonst fehlen die MAC-Tabellen.
4. Ping/TCP vom Scan-Rechner in die Server-Netze (für Hostnamen und „erreichbar“). Die Port-Zuordnung selbst funktioniert auch ohne Ping, nur per SNMP.

> **Tipp:** Scan kurz vor dem Umzug laufen lassen, wenn alle Systeme in Betrieb sind. MAC-Einträge verfallen auf Switches meist nach 5 Minuten Inaktivität – der Ping-Sweep sorgt dafür, dass die Tabellen frisch gefüllt sind. Bei Bedarf zwei Scans im Abstand von einigen Minuten machen.

---

## Dashboard-Port

Das Dashboard läuft standardmäßig auf **Port 8765** (`http://<server>:8765/`). Ist der Port bereits belegt, nehmen die Installer automatisch den nächsten freien Port und zeigen ihn am Ende an. Eigener Port: Windows `-Port 9000`, Kali `--port 9000`.

## Installation direkt von GitHub

### Online-Installer (am einfachsten)

**[NetzwerkScanner-Installer.exe herunterladen](https://github.com/aroth-bit/NetzwerkScanner/releases/latest/download/NetzwerkScanner-Installer.exe)** (ca. 20 KB) und auf dem Windows Server per Doppelklick starten. Der Installer fordert Administratorrechte an, lädt die jeweils neueste Version von GitHub, prüft die SHA-256-Prüfsumme und installiert sie (Dienst, Firewall-Regel, Startmenü, erster Administrator). Bei einer vorhandenen Installation wird aktualisiert.

Optionen (Eingabeaufforderung): `NetzwerkScanner-Installer.exe -Port 9000`, `-NoService`, `-NoFirewall`, `-Tag v1.1.1` (bestimmte Version) oder `-DownloadOnly -OutDir D:\Pakete` (nur das ZIP-Paket herunterladen, z. B. für Server ohne Internet).

Da die Datei nicht digital signiert ist, zeigt Windows SmartScreen beim ersten Start ggf. eine Warnung („Weitere Informationen“ → „Trotzdem ausführen“).

### Per Befehl

Die Installationspakete werden bei jeder neuen Version automatisch von GitHub Actions gebaut und unter [Releases](https://github.com/aroth-bit/NetzwerkScanner/releases) veröffentlicht. Die folgenden Befehle laden immer die neueste Version, prüfen die SHA-256-Prüfsumme und installieren.

**Windows Server** (PowerShell *als Administrator*):
```powershell
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/aroth-bit/NetzwerkScanner/main/installer/windows/install-from-github.ps1)))
```

**Kali Linux:**
```bash
curl -fsSL https://raw.githubusercontent.com/aroth-bit/NetzwerkScanner/main/installer/linux/install-from-github.sh | sudo bash
```

**Privates Repository:** zusätzlich ein GitHub-Token mit Leserecht auf *Contents* angeben (Fine-grained Token, nur dieses Repository):
```powershell
$t = "github_pat_..."
& ([scriptblock]::Create((irm -Headers @{Authorization="Bearer $t"} https://raw.githubusercontent.com/aroth-bit/NetzwerkScanner/main/installer/windows/install-from-github.ps1))) -Token $t
```
```bash
export GITHUB_TOKEN=github_pat_...
curl -fsSL -H "Authorization: Bearer $GITHUB_TOKEN" https://raw.githubusercontent.com/aroth-bit/NetzwerkScanner/main/installer/linux/install-from-github.sh | sudo GITHUB_TOKEN="$GITHUB_TOKEN" bash
```
Das Token wird für den Update-Button gespeichert (nur für Administratoren lesbar).

## Update

*System & Update* → **Nach Updates suchen** → **Update installieren**. Der Scanner lädt das passende Paket aus dem neuesten GitHub-Release, prüft die Prüfsumme und installiert es; der Dienst startet danach neu. Einstellungen, Benutzer, Scans und Sicherungen bleiben erhalten.

- Windows: die Installation läuft als eigene geplante Aufgabe (SYSTEM), Protokoll unter `C:\ProgramData\NetzwerkScanner\update\install.log`
- Kali: die Installation läuft als eigene systemd-Unit, Protokoll unter `/var/lib/netscanner/update/install.log`
- Hinter einem Proxy: Umgebungsvariable `HTTPS_PROXY` für den Dienst setzen

Neue Version veröffentlichen: `__version__` in `netscanner/__init__.py` erhöhen, committen, dann `git tag v1.2.0 && git push origin v1.2.0` – GitHub Actions baut Setup, ZIP und Linux-Paket und erstellt das Release.

## Installation Windows Server (manuell)

### Variante A: Setup-Assistent
`NetzwerkScanner-Setup-<version>.exe` als Administrator ausführen. Optionen: Hintergrunddienst (Port 8765) und Firewall-Regel. Am Ende wird der erste Administrator angelegt.

### Variante B: ZIP-Paket
1. `NetzwerkScanner-<version>-Windows.zip` entpacken
2. `Install.cmd` doppelklicken (fordert Administratorrechte an)
3. ersten Administrator (Benutzername + Passwort) anlegen
4. Browser öffnet `http://localhost:8765/`

Optionen: `Install.cmd -Port 9000`, `-NoService` (nur manuell starten), `-NoFirewall`, `-Silent`.

Ergebnis:
- Programm: `C:\Program Files\NetzwerkScanner`
- Daten (Scans, Einstellungen, Patchplan): `C:\ProgramData\NetzwerkScanner` (nur Administratoren/SYSTEM)
- Dienst: geplante Aufgabe **NetzwerkScanner** (startet mit Windows als SYSTEM)
- Startmenü: Dashboard, Konsole, Passwort setzen, Deinstallieren
- Deinstallation über „Programme und Features“ bzw. das Startmenü (Daten bleiben auf Wunsch erhalten)

**Optional:** [nmap für Windows](https://nmap.org/download) installieren – der Host-Scan wird dann deutlich schneller.

### Setup selbst bauen
```powershell
powershell -ExecutionPolicy Bypass -File installer\windows\build_windows.ps1
```
Benötigt Python 3.10+. Erzeugt `dist\NetzwerkScanner-<version>-Windows.zip` und – wenn [Inno Setup 6](https://jrsoftware.org/isinfo.php) installiert ist – `dist\NetzwerkScanner-Setup-<version>.exe`.

## Installation Kali Linux

```bash
sudo ./installer/linux/install_kali.sh
```
Installiert Python-Umgebung, nmap, den Befehl `netscanner` und den systemd-Dienst `netscanner` (Port 8765). Optionen: `--port 9000`, `--no-service`. Entfernen mit `sudo /opt/netscanner/uninstall.sh` (`--purge` löscht auch die Daten).

Ohne Internet (offline): auf einem Rechner mit Internet `pip download -r requirements.txt -d wheels` (gleiche Python-Version) ausführen und den Ordner `wheels/` neben `installer/` legen – das Skript installiert dann offline.

Ohne Installation testen:
```bash
python3 -m venv venv && venv/bin/pip install -r requirements.txt
venv/bin/python -m netscanner --demo
```

---

## Erste Schritte

1. Dashboard öffnen, mit dem Passwort anmelden
2. **Scan & Einstellungen**:
   - *Switches, Router & Firewalls*: zuerst den Core-Switch / das Gateway eintragen (weitere Switches werden über LLDP/CDP gefunden). Bereiche wie `10.0.100.0/24` (Management-Netz) sind möglich.
   - *SNMP-Zugangsdaten*: Community bzw. v3-Benutzer eintragen, mit **Testen** prüfen
   - *Zusätzliche Netze*: Netze, die nicht über einen Router erreichbar sind (die Subnetze der L3-Switches werden automatisch gescannt)
3. **Speichern & Scan starten** – Fortschritt und Protokoll werden live angezeigt
4. Ergebnis prüfen: **Übersicht** → Warnungen („ohne Port-Zuordnung“, „Link ohne Gerät“)
5. **Umzugsplanung** ausfüllen (Ziel-Switch/Port, Kabel-Labels) → **Report herunterladen**
6. Nach dem Umzug erneut scannen → **Vergleich** zeigt fehlende Geräte und falsch gesteckte Ports

## Kommandozeile

```
netscanner [--host 0.0.0.0] [--port 8765] [--data VERZ] [--no-browser]
netscanner --set-password [--user NAME]   Passwort setzen (legt den Benutzer als Administrator an, falls neu)
netscanner --list-users                   Benutzer auflisten
netscanner --configure-update OWNER/REPO  Update-Quelle festlegen (Token aus GITHUB_TOKEN)
netscanner --scan --report out.xlsx  Scan ohne Web-UI (gespeicherte Einstellungen), Report schreiben
netscanner --demo                    Beispiel-Scan importieren
```
Unter Windows: `"C:\Program Files\NetzwerkScanner\NetzwerkScanner.exe" --data C:\ProgramData\NetzwerkScanner …`

## Sicherheit

- Anmeldung mit Benutzername und Passwort, Rollen Administrator/Benutzer/Audit. Solange kein Administrator existiert, ist das Dashboard nur lokal am Server erreichbar (`/setup`).
- SSH-Zugangsdaten und GitHub-Token liegen wie die SNMP-Daten nur im geschützten Datenverzeichnis und werden im Browser maskiert.
- Gesicherte Konfigurationen enthalten u. a. Passwort-Hashes und Communities – Speicherort entsprechend schützen.
- SNMP-Zugangsdaten liegen in `config.json` im Datenverzeichnis, das nur für Administratoren/root lesbar ist; im Browser werden sie maskiert angezeigt.
- Der Scanner liest nur (SNMP GET/WALK, Ping, TCP-Connect, DNS, NetBIOS) – es werden keine Konfigurationen verändert.
- Nur in Netzen einsetzen, für die eine Freigabe vorliegt.

## Fehlersuche

| Problem | Ursache / Lösung |
|---|---|
| „keine SNMP-Antwort“ | Community/v3-Daten, SNMP-ACL auf dem Switch, Firewall (UDP 161) prüfen; mit **Testen** einzeln probieren |
| Geräte ohne Port-Zuordnung | Gerät hängt an einem nicht gescannten Switch (Switch eintragen) oder MAC-Eintrag abgelaufen (erneut scannen) |
| Cisco: MAC-Tabellen leer | SNMPv2c: Community muss für `community@vlan` gelten; SNMPv3: VLAN-Kontexte freigeben |
| Keine Hostnamen | Reverse-DNS-Zonen fehlen → NetBIOS hilft bei Windows; LLDP-Namen werden ebenfalls genutzt |
| Scan großer Netze dauert lange | nmap installieren, „TCP-Prüfung“ deaktivieren, Netze eingrenzen |
| Port belegt | Die Installer weichen automatisch auf den nächsten freien Port aus (Meldung beachten). Manuell: Installation mit `-Port 9000` bzw. `--port 9000` wiederholen |

## Projektstruktur

```
netscanner/            Python-Paket (Scanner, Web-Dashboard, Reports)
  collector.py         SNMP-Auslesen der Switches (IF-MIB, BRIDGE/Q-BRIDGE, LLDP, CDP, ARP, LAG, Entity)
  discovery.py         Ping, TCP, nmap, ARP, DNS, NetBIOS
  correlate.py         Zuordnung Gerät → Port, Uplinks, Topologie, VLANs
  configbackup.py      Konfigurationssicherung per SSH (Netmiko), 5 Versionen je Switch
  users.py             Benutzer, Rollen, Protokoll
  updater.py           Update aus GitHub-Releases
  engine.py            Scan-Ablauf
  reports.py           Excel / PDF / CSV
  web.py               Dashboard + REST-API
installer/windows/     PyInstaller-Spec, Inno-Setup-Skript, Install.ps1, install-from-github.ps1, build_windows.ps1
installer/linux/       install_kali.sh, install-from-github.sh, uninstall.sh, build_linux_package.py
.github/workflows/     release.yml – baut und veröffentlicht Releases bei Versions-Tags
tests/                 SNMP- und SSH-Simulator, Demo-Generator, test_web.py (Rollen/Rechte/Sicherung)
```
