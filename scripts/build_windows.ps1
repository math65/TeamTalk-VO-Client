param([switch]$NoUpload)

# TeamTalk VO Client - Windows Build Script
# Aufruf: .\scripts\build_windows.ps1
# Kein Upload: .\scripts\build_windows.ps1 -NoUpload

$ErrorActionPreference = "Stop"

$GITEA_TOKEN = "e91faa5c35310a376937604fffba15a8d7c66345"
$GITEA_API   = "https://git.garogaming.xyz/api/v1/repos/flarion/TeamTalk-VO-Client"

# Projektverzeichnis = eine Ebene ueber dem scripts/-Ordner
# Resolve-Path loest ".." auf und liefert den absoluten Pfad
$ROOT = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Write-Host "Projektverzeichnis: $ROOT"
Set-Location $ROOT

# -----------------------------------------------------------------------
# 1. Python suchen
# -----------------------------------------------------------------------
Write-Host ""
Write-Host "==> Suche Python 3.9-3.12..."
$py = $null
foreach ($name in @("python3.12","python3.11","python3.10","python3.9","python3","python")) {
    $cmd = Get-Command $name -ErrorAction SilentlyContinue
    if ($cmd) {
        $raw = & $cmd.Source --version 2>&1
        if ($raw -match "Python 3\.(\d+)") {
            $minor = [int]$Matches[1]
            if ($minor -ge 9 -and $minor -le 12) {
                $py = $cmd.Source
                Write-Host "    $raw  ($py)"
                break
            }
        }
    }
}
if (-not $py) {
    Write-Host "FEHLER: Python 3.9-3.12 nicht gefunden. Download: https://python.org"
    exit 1
}

# -----------------------------------------------------------------------
# 2. Virtuelle Umgebung
# -----------------------------------------------------------------------
Write-Host ""
Write-Host "==> Virtuelle Umgebung..."
$venvDir  = Join-Path $ROOT ".venv"
$pipExe   = Join-Path $venvDir "Scripts\pip.exe"
$pyinsExe = Join-Path $venvDir "Scripts\pyinstaller.exe"

if (-not (Test-Path $venvDir)) {
    Write-Host "    Erstelle .venv..."
    & $py -m venv $venvDir
} else {
    Write-Host "    .venv bereits vorhanden."
}

Write-Host "    Installiere Abhaengigkeiten..."
& $pipExe install --upgrade pip --quiet
& $pipExe install -r (Join-Path $ROOT "requirements_windows.txt") --quiet
Write-Host "    Fertig."

# -----------------------------------------------------------------------
# 3. Version auslesen
# -----------------------------------------------------------------------
Write-Host ""
Write-Host "==> Lese Version..."
$appPy = Join-Path $ROOT "src\app.py"
$match = Select-String -Path $appPy -Pattern 'APP_VERSION\s*=\s*"([^"]+)"'
if (-not $match) {
    Write-Host "FEHLER: APP_VERSION nicht in src\app.py gefunden."
    exit 1
}
$VERSION = $match.Matches[0].Groups[1].Value
Write-Host "    Version: $VERSION"

# -----------------------------------------------------------------------
# 4. PyInstaller
# -----------------------------------------------------------------------
Write-Host ""
Write-Host "==> PyInstaller-Build..."
$specFile = Join-Path $ROOT "TeamTalk VO Client_win.spec"
& $pyinsExe -y $specFile
Write-Host "    Build fertig."

# -----------------------------------------------------------------------
# 5. ZIP erstellen
# -----------------------------------------------------------------------
$appDir  = Join-Path $ROOT "dist\TeamTalk VO Client"
$zipName = "TeamTalk VO Client $VERSION Windows.zip"
$zipPath = Join-Path $ROOT "dist\$zipName"

Write-Host ""
Write-Host "==> Erstelle ZIP..."
if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
Compress-Archive -Path $appDir -DestinationPath $zipPath
$sizeMB = [math]::Round((Get-Item $zipPath).Length / 1MB, 1)
Write-Host "    $zipName ($sizeMB MB)"

# -----------------------------------------------------------------------
# 6. Gitea-Release + Upload
# -----------------------------------------------------------------------
if (-not $NoUpload) {
    Write-Host ""
    Write-Host "==> Gitea-Release..."

    $hdrAuth = "Authorization: token $GITEA_TOKEN"
    $hdrJson = "Content-Type: application/json"

    # Release suchen
    $releaseId = $null
    $resp = curl.exe -sf -H $hdrAuth "$GITEA_API/releases/tags/v$VERSION"
    if ($resp) {
        $obj = $resp | ConvertFrom-Json -ErrorAction SilentlyContinue
        if ($obj -and $obj.id) {
            $releaseId = $obj.id
            Write-Host "    Release v$VERSION existiert (ID $releaseId)."
        }
    }

    # Release anlegen falls noetig
    if (-not $releaseId) {
        Write-Host "    Lege Release v$VERSION an..."
        $body = "{`"tag_name`":`"v$VERSION`",`"name`":`"v$VERSION`",`"is_draft`":false}"
        $resp = curl.exe -s -X POST -H $hdrAuth -H $hdrJson -d $body "$GITEA_API/releases"
        $obj  = $resp | ConvertFrom-Json
        $releaseId = $obj.id
        Write-Host "    Release-ID: $releaseId"
    }

    # ZIP hochladen
    Write-Host "    Lade ZIP hoch..."
    $nameEnc = [Uri]::EscapeDataString($zipName)
    $uploadUrl = "$GITEA_API/releases/$releaseId/assets?name=$nameEnc"
    $hdrBin = "Content-Type: application/octet-stream"
    $resp = curl.exe -s -X POST -H $hdrAuth -H $hdrBin --data-binary "@$zipPath" $uploadUrl
    $obj  = $resp | ConvertFrom-Json
    Write-Host "    Asset: $($obj.name)"
}

# -----------------------------------------------------------------------
Write-Host ""
Write-Host "============================================================"
Write-Host " Fertig!  $zipName"
if (-not $NoUpload) {
    Write-Host " https://git.garogaming.xyz/flarion/TeamTalk-VO-Client/releases/tag/v$VERSION"
}
Write-Host "============================================================"
