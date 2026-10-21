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
- **Scan & Einstellungen** – Netze, Switches, SNMP-Zugangsdaten, Optionen, Fortschritt und Protokoll, Scan-Historie, JSON-Import

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

## Installation Windows Server

### Variante A: Setup-Assistent
`NetzwerkScanner-Setup-1.0.0.exe` als Administrator ausführen. Optionen: Hintergrunddienst (Port 8080) und Firewall-Regel. Am Ende wird das Dashboard-Passwort abgefragt.

### Variante B: ZIP-Paket
1. `NetzwerkScanner-1.0.0-Windows.zip` entpacken
2. `Install.cmd` doppelklicken (fordert Administratorrechte an)
3. Passwort für das Dashboard eingeben
4. Browser öffnet `http://localhost:8080/`

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
Benötigt Python 3.10+. Erzeugt `dist\NetzwerkScanner-1.0.0-Windows.zip` und – wenn [Inno Setup 6](https://jrsoftware.org/isinfo.php) installiert ist – `dist\NetzwerkScanner-Setup-1.0.0.exe`.

## Installation Kali Linux

```bash
sudo ./installer/linux/install_kali.sh
```
Installiert Python-Umgebung, nmap, den Befehl `netscanner` und den systemd-Dienst `netscanner` (Port 8080). Optionen: `--port 9000`, `--no-service`. Entfernen mit `sudo /opt/netscanner/uninstall.sh` (`--purge` löscht auch die Daten).

Ohne Internet (offline): auf einem Rechner mit Internet `pip download -r requirements.txt -d wheels` (gleiche Python-Version) ausführen und den Ordner `wheels/` neben `installer/` legen – das Skript installiert dann offline.

Ohne Installation testen:
```bash
python3 -m venv venv && venv/bin/pip install -r requirements.txt
venv/bin/python -m netscanner --port 8080 --demo
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
netscanner [--host 0.0.0.0] [--port 8080] [--data VERZ] [--no-browser]
netscanner --set-password            Dashboard-Passwort setzen
netscanner --scan --report out.xlsx  Scan ohne Web-UI (gespeicherte Einstellungen), Report schreiben
netscanner --demo                    Beispiel-Scan importieren
```
Unter Windows: `"C:\Program Files\NetzwerkScanner\NetzwerkScanner.exe" --data C:\ProgramData\NetzwerkScanner …`

## Sicherheit

- Das Dashboard ist passwortgeschützt. Solange kein Passwort gesetzt ist, ist es nur lokal am Server erreichbar (`/setup`).
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
| Port 8080 belegt | Installation mit `-Port` / `--port` wiederholen |

## Projektstruktur

```
netscanner/            Python-Paket (Scanner, Web-Dashboard, Reports)
  collector.py         SNMP-Auslesen der Switches (IF-MIB, BRIDGE/Q-BRIDGE, LLDP, CDP, ARP, LAG, Entity)
  discovery.py         Ping, TCP, nmap, ARP, DNS, NetBIOS
  correlate.py         Zuordnung Gerät → Port, Uplinks, Topologie, VLANs
  engine.py            Scan-Ablauf
  reports.py           Excel / PDF / CSV
  web.py               Dashboard + REST-API
installer/windows/     PyInstaller-Spec, Inno-Setup-Skript, Install.ps1, build_windows.ps1
installer/linux/       install_kali.sh, uninstall.sh
tests/                 SNMP-Simulator-Daten (snmpsim) und Demo-Generator
```
