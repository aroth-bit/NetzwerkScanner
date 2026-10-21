<#
.SYNOPSIS
  Installiert den NetzwerkScanner auf Windows Server / Windows 10/11.

.DESCRIPTION
  - kopiert das Programm nach "C:\Program Files\NetzwerkScanner"
  - legt das Datenverzeichnis C:\ProgramData\NetzwerkScanner an (nur Administratoren/SYSTEM)
  - richtet einen Hintergrunddienst (geplante Aufgabe beim Systemstart, Konto SYSTEM) ein
  - oeffnet die Windows-Firewall fuer den Dashboard-Port (Domaene/Privat)
  - legt Startmenue-Eintraege und einen Eintrag unter "Programme und Features" an

.EXAMPLE
  .\Install.ps1
  .\Install.ps1 -Port 8443 -NoFirewall
  .\Install.ps1 -Silent -NoService
  .\Install.ps1 -Update -Silent     (wird vom Update-Button im Dashboard verwendet)
#>
[CmdletBinding()]
param(
    [string]$InstallDir = (Join-Path $env:ProgramFiles "NetzwerkScanner"),
    [int]$Port = 8080,
    [switch]$NoService,
    [switch]$NoFirewall,
    [switch]$Silent,
    [switch]$FromInno,
    [switch]$Update
)

$ErrorActionPreference = "Stop"
$AppName = "NetzwerkScanner"
$TaskName = "NetzwerkScanner"
$DataDir = Join-Path $env:ProgramData $AppName

function Write-Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }

# ------------------------------------------------------------ Adminrechte
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
           ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "Administratorrechte erforderlich - starte neu mit erhoehten Rechten ..." -ForegroundColor Yellow
    $args2 = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$PSCommandPath`"", "-InstallDir", "`"$InstallDir`"", "-Port", $Port)
    if ($NoService) { $args2 += "-NoService" }
    if ($NoFirewall) { $args2 += "-NoFirewall" }
    if ($Silent) { $args2 += "-Silent" }
    if ($Update) { $args2 += "-Update" }
    Start-Process powershell.exe -Verb RunAs -ArgumentList $args2
    exit 0
}

$exe = Join-Path $InstallDir "NetzwerkScanner.exe"
if ($Update) {
    # Update: bisherige Einstellungen beibehalten (Dienst nur, wenn er schon eingerichtet war)
    $Silent = $true
    $hadTask = [bool](Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue)
    if (-not $hadTask) { $NoService = $true }
    $NoFirewall = -not [bool](Get-NetFirewallRule -DisplayName "NetzwerkScanner Dashboard" -ErrorAction SilentlyContinue)
    New-Item -ItemType Directory -Force -Path (Join-Path $DataDir "update") | Out-Null
    try { Start-Transcript -Path (Join-Path $DataDir "update\install-transcript.log") -Force | Out-Null } catch { }
}

# ------------------------------------------------------------ laufende Instanz stoppen
Write-Step "Vorhandene Installation pruefen"
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
}
Get-Process -Name "NetzwerkScanner" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 1

# ------------------------------------------------------------ Dateien kopieren
if (-not $FromInno) {
    $src = Join-Path $PSScriptRoot "NetzwerkScanner"
    if (-not (Test-Path (Join-Path $src "NetzwerkScanner.exe"))) {
        throw "Programmdateien nicht gefunden: $src\NetzwerkScanner.exe"
    }
    Write-Step "Kopiere Programm nach $InstallDir"
    New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
    & robocopy.exe $src $InstallDir /MIR /NFL /NDL /NJH /NJS /NP /XF "Install.ps1" "Uninstall.ps1" | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "Kopieren fehlgeschlagen (robocopy $LASTEXITCODE)" }
    Copy-Item (Join-Path $PSScriptRoot "Uninstall.ps1") $InstallDir -Force
    Copy-Item $PSCommandPath (Join-Path $InstallDir "Install.ps1") -Force -ErrorAction SilentlyContinue
}
$Version = (& $exe --version 2>$null | Select-Object -Last 1)
if (-not $Version) { $Version = "?" }

# ------------------------------------------------------------ Datenverzeichnis
Write-Step "Datenverzeichnis $DataDir (Zugriff nur Administratoren/SYSTEM)"
New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
& icacls.exe $DataDir /inheritance:r /grant:r "*S-1-5-32-544:(OI)(CI)F" "*S-1-5-18:(OI)(CI)F" | Out-Null

# ------------------------------------------------------------ Firewall
if (-not $NoFirewall) {
    Write-Step "Firewall-Regel fuer TCP $Port (Domaene/Privat)"
    Get-NetFirewallRule -DisplayName "NetzwerkScanner Dashboard" -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    New-NetFirewallRule -DisplayName "NetzwerkScanner Dashboard" -Direction Inbound -Protocol TCP -LocalPort $Port `
        -Action Allow -Profile Domain, Private -Program $exe | Out-Null
}

# ------------------------------------------------------------ Hintergrunddienst
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}
if (-not $NoService) {
    Write-Step "Hintergrunddienst (geplante Aufgabe '$TaskName', startet mit Windows)"
    $action = New-ScheduledTaskAction -Execute $exe -Argument "--no-browser --port $Port --data `"$DataDir`"" -WorkingDirectory $InstallDir
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
    $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 5 `
        -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings `
        -Description "NetzwerkScanner Dashboard (http://localhost:$Port)" | Out-Null
}

# ------------------------------------------------------------ Startmenue
Write-Step "Startmenue-Eintraege"
$menu = Join-Path $env:ProgramData "Microsoft\Windows\Start Menu\Programs\NetzwerkScanner"
New-Item -ItemType Directory -Force -Path $menu | Out-Null
Set-Content -Path (Join-Path $menu "NetzwerkScanner Dashboard.url") -Encoding ASCII -Value @(
    "[InternetShortcut]", "URL=http://localhost:$Port/", "IconFile=$exe", "IconIndex=0")
$sh = New-Object -ComObject WScript.Shell
$lnk = $sh.CreateShortcut((Join-Path $menu "NetzwerkScanner (Konsole).lnk"))
$lnk.TargetPath = $exe; $lnk.Arguments = "--port $Port --data `"$DataDir`""; $lnk.WorkingDirectory = $InstallDir
$lnk.Description = "Startet den Scanner im Konsolenfenster (nur wenn der Hintergrunddienst nicht laeuft)"; $lnk.Save()
$lnk = $sh.CreateShortcut((Join-Path $menu "Dashboard-Passwort setzen.lnk"))
$lnk.TargetPath = $exe; $lnk.Arguments = "--set-password --data `"$DataDir`""; $lnk.WorkingDirectory = $InstallDir; $lnk.Save()
if (-not $FromInno) {
    $lnk = $sh.CreateShortcut((Join-Path $menu "NetzwerkScanner deinstallieren.lnk"))
    $lnk.TargetPath = "powershell.exe"
    $lnk.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$InstallDir\Uninstall.ps1`""; $lnk.Save()

    # -------------------------------------------------------- Programme und Features
    $reg = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\NetzwerkScanner"
    New-Item -Path $reg -Force | Out-Null
    $vals = @{ DisplayName = "NetzwerkScanner"; DisplayVersion = $Version; Publisher = "NetzwerkScanner";
               InstallLocation = $InstallDir; DisplayIcon = $exe; NoModify = 1; NoRepair = 1;
               UninstallString = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$InstallDir\Uninstall.ps1`"" }
    foreach ($k in $vals.Keys) { Set-ItemProperty -Path $reg -Name $k -Value $vals[$k] }
}

# ------------------------------------------------------------ Passwort
$usersFile = Join-Path $DataDir "users.json"
$authFile = Join-Path $DataDir "auth.json"
$hasPw = ((Test-Path $usersFile) -and ((Get-Content $usersFile -Raw) -match "password_hash")) -or
         ((Test-Path $authFile) -and ((Get-Content $authFile -Raw) -match "password_hash"))
if (-not $hasPw -and -not $Silent) {
    Write-Step "Ersten Administrator fuer das Dashboard anlegen"
    & $exe --set-password --data $DataDir
}

# ------------------------------------------------------------ Start
if ($Update) {
    Unregister-ScheduledTask -TaskName "NetzwerkScanner-Update" -Confirm:$false -ErrorAction SilentlyContinue
}
if (-not $NoService) {
    Write-Step "Starte Hintergrunddienst"
    Start-ScheduledTask -TaskName $TaskName
    Start-Sleep -Seconds 4
}

Write-Host ""
Write-Host "NetzwerkScanner $Version wurde installiert." -ForegroundColor Green
Write-Host "  Programm : $InstallDir"
Write-Host "  Daten    : $DataDir"
Write-Host "  Dashboard: http://localhost:$Port/  (aus dem Netz: http://$($env:COMPUTERNAME):$Port/)"
if (-not $hasPw -and $Silent) {
    Write-Host "  Noch kein Administrator: http://localhost:$Port/setup direkt auf dem Server aufrufen." -ForegroundColor Yellow
}
if (-not $NoService -and -not $Silent) { Start-Process "http://localhost:$Port/" }
if ($Update) { try { Stop-Transcript | Out-Null } catch { } }
if (-not $Silent -and -not $FromInno) { Read-Host "Enter zum Beenden" | Out-Null }
