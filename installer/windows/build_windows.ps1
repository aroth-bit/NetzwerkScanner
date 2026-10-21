<#
.SYNOPSIS
  Baut das Windows-Installationspaket.

  Ergebnis in .\dist :
    NetzwerkScanner\                       PyInstaller-Programm (ohne Python lauffaehig)
    NetzwerkScanner-<ver>-Windows.zip      Paket mit Install.cmd / Install.ps1
    NetzwerkScanner-Setup-<ver>.exe        Setup-Assistent (nur wenn Inno Setup 6 installiert ist)

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File installer\windows\build_windows.ps1
  powershell -ExecutionPolicy Bypass -File installer\windows\build_windows.ps1 -Python "C:\Python312\python.exe"
#>
param(
    [string]$Python = "",
    [string]$Venv = ""
)
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Version = ([regex]::Match((Get-Content (Join-Path $Root "netscanner\__init__.py") -Raw), '__version__ = "([^"]+)"')).Groups[1].Value
if (-not $Version) { throw "Version nicht gefunden" }
Write-Host "==> NetzwerkScanner $Version"
$Dist = Join-Path $Root "dist"
Set-Location $Root

# ------------------------------------------------------------ Python / venv
if (-not $Venv) { $Venv = Join-Path $Root "build\venv" }
$py = Join-Path $Venv "Scripts\python.exe"
if (-not (Test-Path $py)) {
    if (-not $Python) {
        if (Get-Command py.exe -ErrorAction SilentlyContinue) { $Python = "py.exe"; $pyArgs = @("-3") }
        else { $Python = "python.exe"; $pyArgs = @() }
    } else { $pyArgs = @() }
    Write-Host "==> Erzeuge venv $Venv"
    & $Python @pyArgs -m venv $Venv
}
Write-Host "==> Installiere Abhaengigkeiten"
& $py -m pip install --upgrade pip | Out-Null
& $py -m pip install -r (Join-Path $Root "requirements.txt") pyinstaller
if ($LASTEXITCODE -ne 0) { throw "pip install fehlgeschlagen" }

# ------------------------------------------------------------ PyInstaller
Write-Host "==> PyInstaller"
& $py -m PyInstaller --noconfirm --clean --distpath $Dist --workpath (Join-Path $Root "build\pyi") `
    (Join-Path $PSScriptRoot "NetzwerkScanner.spec")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller fehlgeschlagen" }
& (Join-Path $Dist "NetzwerkScanner\NetzwerkScanner.exe") --version
if ($LASTEXITCODE -ne 0) { throw "Selbsttest der EXE fehlgeschlagen" }

# ------------------------------------------------------------ ZIP-Paket
$pkgName = "NetzwerkScanner-$Version-Windows"
$pkg = Join-Path $Dist $pkgName
Write-Host "==> Paket $pkg"
if (Test-Path $pkg) { Remove-Item -Recurse -Force $pkg }
New-Item -ItemType Directory -Path $pkg | Out-Null
Copy-Item -Recurse (Join-Path $Dist "NetzwerkScanner") (Join-Path $pkg "NetzwerkScanner")
foreach ($f in "Install.ps1", "Install.cmd", "Uninstall.ps1") { Copy-Item (Join-Path $PSScriptRoot $f) $pkg }
Copy-Item (Join-Path $Root "README.md") (Join-Path $pkg "LIESMICH.md")
$zip = Join-Path $Dist "$pkgName.zip"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path (Join-Path $pkg "*") -DestinationPath $zip -CompressionLevel Optimal
Write-Host "    $zip"

# ------------------------------------------------------------ Setup.exe (Inno Setup)
$iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
          "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($iscc) {
    Write-Host "==> Inno Setup: $iscc"
    & $iscc "/DAppVersion=$Version" (Join-Path $PSScriptRoot "NetzwerkScanner.iss")
    if ($LASTEXITCODE -ne 0) { throw "ISCC fehlgeschlagen" }
} else {
    # Fallback ohne Zusatzsoftware: selbstentpackendes Setup mit dem Windows-Bordmittel IExpress
    Write-Host "==> Inno Setup 6 nicht gefunden - baue Setup.exe mit IExpress" -ForegroundColor Yellow
    $stage = Join-Path $Root "build\iexpress"
    if (Test-Path $stage) { Remove-Item -Recurse -Force $stage }
    New-Item -ItemType Directory -Path $stage | Out-Null
    Copy-Item $zip (Join-Path $stage "payload.zip")
    Copy-Item (Join-Path $PSScriptRoot "iexpress_setup.cmd") (Join-Path $stage "setup.cmd")
    $target = Join-Path $Dist "NetzwerkScanner-Setup-$Version.exe"
    $sed = @"
[Version]
Class=IEXPRESS
SEDVersion=3
[Options]
PackagePurpose=InstallApp
ShowInstallProgramWindow=1
HideExtractAnimation=0
UseLongFileName=1
InsideCompressed=0
CAB_FixedSize=0
CAB_ResvCodeSigning=0
RebootMode=N
InstallPrompt=
DisplayLicense=
FinishMessage=
TargetName=$target
FriendlyName=NetzwerkScanner $Version Setup
AppLaunched=cmd.exe /c setup.cmd
PostInstallCmd=<None>
AdminQuietInstCmd=cmd.exe /c setup.cmd -Silent
UserQuietInstCmd=cmd.exe /c setup.cmd -Silent
SourceFiles=SourceFiles
[Strings]
FILE0="setup.cmd"
FILE1="payload.zip"
[SourceFiles]
SourceFiles0=$stage\
[SourceFiles0]
%FILE0%=
%FILE1%=
"@
    $sedFile = Join-Path $stage "setup.sed"
    Set-Content -Path $sedFile -Value $sed -Encoding ASCII
    if (Test-Path $target) { Remove-Item $target }
    Start-Process -FilePath "$env:SystemRoot\System32\iexpress.exe" -ArgumentList "/N", "/Q", $sedFile -Wait -NoNewWindow
    if (Test-Path $target) { Write-Host "    $target" }
    else { Write-Host "IExpress fehlgeschlagen - bitte ZIP-Paket verwenden oder Inno Setup installieren." -ForegroundColor Red }
}
Write-Host "Fertig." -ForegroundColor Green
