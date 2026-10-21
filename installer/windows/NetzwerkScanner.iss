; Inno-Setup-Skript fuer NetzwerkScanner-Setup.exe
; Kompilieren: build_windows.ps1 (ruft ISCC.exe auf) oder in Inno Setup 6 oeffnen und F9.
; Erwartet den PyInstaller-Build unter ..\..\dist\NetzwerkScanner

#ifndef AppPort
  #define AppPort "8765"
#endif
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6E8B2C1A-4F3D-4B7A-9C55-2D1E0A9B7F31}
AppName=NetzwerkScanner
AppVersion={#AppVersion}
AppPublisher=NetzwerkScanner
DefaultDirName={autopf}\NetzwerkScanner
DefaultGroupName=NetzwerkScanner
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\..\dist
OutputBaseFilename=NetzwerkScanner-Setup-{#AppVersion}
SetupIconFile=netscanner.ico
UninstallDisplayIcon={app}\NetzwerkScanner.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Languages]
Name: "german"; MessagesFile: "compiler:Languages\German.isl"

[Tasks]
Name: "service"; Description: "Als Hintergrunddienst beim Windows-Start ausfuehren (Dashboard auf Port {#AppPort}, bei Belegung naechster freier Port)"
Name: "firewall"; Description: "Windows-Firewall fuer das Dashboard oeffnen (Domaene/Privat, TCP-Port des Dashboards)"

[Files]
Source: "..\..\dist\NetzwerkScanner\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "Install.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "Uninstall.ps1"; DestDir: "{app}"; Flags: ignoreversion

[Run]
Filename: "powershell.exe"; \
  Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\Install.ps1"" -FromInno -InstallDir ""{app}"" -Port {#AppPort} {code:ExtraArgs}"; \
  StatusMsg: "Richte Dienst, Firewall und Passwort ein ..."; Flags: waituntilterminated

[UninstallRun]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\Uninstall.ps1"" -FromInno"; \
  Flags: runhidden waituntilterminated; RunOnceId: "NetzwerkScannerUninstall"

[Code]
function ExtraArgs(Param: String): String;
begin
  Result := '';
  if not WizardIsTaskSelected('service') then Result := Result + ' -NoService';
  if not WizardIsTaskSelected('firewall') then Result := Result + ' -NoFirewall';
  if WizardSilent() then Result := Result + ' -Silent';
end;
