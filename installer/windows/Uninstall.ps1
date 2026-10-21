<#
.SYNOPSIS
  Entfernt den NetzwerkScanner. Scans und Einstellungen in C:\ProgramData\NetzwerkScanner bleiben
  erhalten, ausser es wird -RemoveData angegeben.
#>
[CmdletBinding()]
param(
    [switch]$RemoveData,
    [switch]$FromInno
)
$ErrorActionPreference = "Continue"
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
           ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    $a = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$PSCommandPath`"")
    if ($RemoveData) { $a += "-RemoveData" }
    Start-Process powershell.exe -Verb RunAs -ArgumentList $a
    exit 0
}
$InstallDir = $PSScriptRoot
$DataDir = Join-Path $env:ProgramData "NetzwerkScanner"

Write-Host "Stoppe NetzwerkScanner ..."
if (Get-ScheduledTask -TaskName "NetzwerkScanner" -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask -TaskName "NetzwerkScanner" -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName "NetzwerkScanner" -Confirm:$false
}
Get-Process -Name "NetzwerkScanner" -ErrorAction SilentlyContinue | Stop-Process -Force
Get-NetFirewallRule -DisplayName "NetzwerkScanner Dashboard" -ErrorAction SilentlyContinue | Remove-NetFirewallRule
Remove-Item -Recurse -Force (Join-Path $env:ProgramData "Microsoft\Windows\Start Menu\Programs\NetzwerkScanner") -ErrorAction SilentlyContinue

if (-not $FromInno) {
    Remove-Item -Path "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\NetzwerkScanner" -Recurse -Force -ErrorAction SilentlyContinue
    if (-not $RemoveData -and (Test-Path $DataDir)) {
        $ans = Read-Host "Gespeicherte Scans und Einstellungen in $DataDir ebenfalls loeschen? (j/N)"
        if ($ans -match "^[jJyY]") { $RemoveData = $true }
    }
    # Programmverzeichnis nach Ende dieses Skripts loeschen (Skript liegt selbst darin)
    Start-Process cmd.exe -WindowStyle Hidden -ArgumentList "/c timeout /t 3 /nobreak >nul & rmdir /s /q `"$InstallDir`""
}
if ($RemoveData) { Remove-Item -Recurse -Force $DataDir -ErrorAction SilentlyContinue }
Write-Host "NetzwerkScanner wurde entfernt." -ForegroundColor Green
if ($RemoveData) { Write-Host "Daten geloescht." } else { Write-Host "Daten bleiben erhalten: $DataDir" }
