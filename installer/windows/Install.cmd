@echo off
rem NetzwerkScanner installieren (startet Install.ps1 mit Administratorrechten)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install.ps1" %*
