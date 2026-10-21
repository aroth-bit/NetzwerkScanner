@echo off
rem Startskript im IExpress-Setup: Paket entpacken und Install.ps1 ausfuehren
set "T=%TEMP%\NetzwerkScanner-Setup"
if exist "%T%" rmdir /s /q "%T%"
echo Entpacke NetzwerkScanner ...
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -LiteralPath '%~dp0payload.zip' -DestinationPath '%T%' -Force"
if errorlevel 1 (
  echo Entpacken fehlgeschlagen.
  pause
  exit /b 1
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%T%\Install.ps1" %*
