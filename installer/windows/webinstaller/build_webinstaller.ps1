<#
.SYNOPSIS
  Baut NetzwerkScanner-Installer.exe (Online-Installer) mit dem csc.exe des .NET Frameworks.
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File installer\windows\webinstaller\build_webinstaller.ps1
#>
param(
    [string]$OutDir = "",
    [switch]$AsInvoker   # nur fuer Tests: ohne Administrator-Anforderung
)
$ErrorActionPreference = "Stop"
$here = $PSScriptRoot
$root = (Resolve-Path (Join-Path $here "..\..\..")).Path
if (-not $OutDir) { $OutDir = Join-Path $root "dist" }
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$csc = Join-Path $env:WINDIR "Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if (-not (Test-Path $csc)) { $csc = Join-Path $env:WINDIR "Microsoft.NET\Framework\v4.0.30319\csc.exe" }
if (-not (Test-Path $csc)) { throw ".NET Framework 4 (csc.exe) nicht gefunden." }

$manifest = Join-Path $here "app.manifest"
if ($AsInvoker) {
    $manifest = Join-Path $env:TEMP "netscanner-asinvoker.manifest"
    (Get-Content (Join-Path $here "app.manifest") -Raw) -replace 'requireAdministrator', 'asInvoker' |
        Set-Content -Path $manifest -Encoding UTF8
}
$out = Join-Path $OutDir "NetzwerkScanner-Installer.exe"
$script = Join-Path $here "..\install-from-github.ps1"
$icon = Join-Path $here "..\netscanner.ico"

& $csc /nologo /target:exe /platform:anycpu /optimize+ "/out:$out" "/win32icon:$icon" "/win32manifest:$manifest" `
    "/resource:$script,install-from-github.ps1" (Join-Path $here "NetzwerkScannerInstaller.cs")
if ($LASTEXITCODE -ne 0) { throw "csc fehlgeschlagen" }
Write-Host "    $out ($([math]::Round((Get-Item $out).Length / 1KB)) KB)"
