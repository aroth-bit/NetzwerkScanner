<#
.SYNOPSIS
  Installiert (oder aktualisiert) den NetzwerkScanner direkt aus den GitHub-Releases.

.DESCRIPTION
  Laedt das Windows-Paket des neuesten Releases, prueft die SHA-256-Pruefsumme und startet Install.ps1.
  In einer PowerShell, die ALS ADMINISTRATOR gestartet wurde:

    Oeffentliches Repository:
      & ([scriptblock]::Create((irm https://raw.githubusercontent.com/aroth-bit/NetzwerkScanner/main/installer/windows/install-from-github.ps1)))

    Privates Repository (Token mit Leserecht auf "Contents"):
      $t = "ghp_..."
      & ([scriptblock]::Create((irm -Headers @{Authorization="Bearer $t"} https://raw.githubusercontent.com/aroth-bit/NetzwerkScanner/main/installer/windows/install-from-github.ps1))) -Token $t

  Weitere Parameter werden an Install.ps1 weitergegeben: -Port 9000 -NoService -NoFirewall -Silent
#>
param(
    [string]$Repo = "aroth-bit/NetzwerkScanner",
    [string]$Token = $env:GITHUB_TOKEN,
    [string]$Tag = "latest",
    [int]$Port = 8765,
    [switch]$NoService,
    [switch]$NoFirewall,
    [switch]$Silent
)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
           ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) { throw "Bitte PowerShell 'Als Administrator ausfuehren' und den Befehl erneut starten." }

$headers = @{ "Accept" = "application/vnd.github+json"; "User-Agent" = "NetzwerkScanner-Installer" }
if ($Token) { $headers["Authorization"] = "Bearer $Token" }
$api = if ($Tag -eq "latest") { "https://api.github.com/repos/$Repo/releases/latest" } else { "https://api.github.com/repos/$Repo/releases/tags/$Tag" }
Write-Host "==> Suche Release in $Repo ..." -ForegroundColor Cyan
try { $rel = Invoke-RestMethod -Uri $api -Headers $headers }
catch { throw "Release nicht gefunden ($($_.Exception.Message)). Privates Repository? Dann -Token angeben." }
$asset = $rel.assets | Where-Object { $_.name -like "*-Windows.zip" } | Select-Object -First 1
if (-not $asset) { throw "Im Release $($rel.tag_name) fehlt das Windows-Paket (*-Windows.zip)." }
Write-Host "    Version $($rel.tag_name): $($asset.name) ($([math]::Round($asset.size / 1MB, 1)) MB)"

$work = Join-Path $env:TEMP ("NetzwerkScanner-" + $rel.tag_name)
if (Test-Path $work) { Remove-Item -Recurse -Force $work }
New-Item -ItemType Directory -Path $work | Out-Null
$zip = Join-Path $work $asset.name

Write-Host "==> Lade herunter ..." -ForegroundColor Cyan
if ($Token) {
    # privates Repo: ueber die API laden; die Weiterleitung zum Speicher-Server ohne Token aufrufen
    $req = [System.Net.HttpWebRequest]::Create($asset.url)
    $req.Accept = "application/octet-stream"; $req.UserAgent = "NetzwerkScanner-Installer"
    $req.Headers.Add("Authorization", "Bearer $Token"); $req.AllowAutoRedirect = $false
    $resp = $req.GetResponse()
    $loc = $resp.Headers["Location"]; $resp.Close()
    if (-not $loc) { throw "Keine Download-Adresse erhalten." }
    Invoke-WebRequest -Uri $loc -OutFile $zip -UseBasicParsing
} else {
    Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $zip -UseBasicParsing
}

$hash = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
if ($asset.digest -and $asset.digest -like "sha256:*") {
    if ($asset.digest.Substring(7) -ne $hash) { throw "Pruefsumme stimmt nicht - Download verworfen." }
    Write-Host "    SHA-256 geprueft: $hash"
} else { Write-Host "    SHA-256: $hash (keine Referenz im Release)" }

Expand-Archive -LiteralPath $zip -DestinationPath $work -Force
$installer = Join-Path $work "Install.ps1"
$params = @{ Port = $Port }
if ($NoService) { $params.NoService = $true }
if ($NoFirewall) { $params.NoFirewall = $true }
if ($Silent) { $params.Silent = $true }
& $installer @params

# Repository und Token fuer den Update-Button hinterlegen
$env:GITHUB_TOKEN = $Token
& (Join-Path $env:ProgramFiles "NetzwerkScanner\NetzwerkScanner.exe") --data (Join-Path $env:ProgramData "NetzwerkScanner") --configure-update $Repo
Remove-Item Env:\GITHUB_TOKEN -ErrorAction SilentlyContinue
