param([switch]$NoUpload)

# TeamTalk VO Client - Windows Build Script
# Aufruf: .\scripts\build_windows.ps1
# Kein Upload: .\scripts\build_windows.ps1 -NoUpload

$ErrorActionPreference = "Stop"

$GITEA_TOKEN = "e91faa5c35310a376937604fffba15a8d7c66345"
$GITEA_API   = "https://git.garogaming.xyz/api/v1/repos/flarion/TeamTalk-VO-Client"

# Projektverzeichnis (eine Ebene ueber diesem Skript)
$ROOT = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $ROOT
Write-Host "Arbeitsverzeichnis: $ROOT"

# -----------------------------------------------------------------------
# 1. Python suchen
# -----------------------------------------------------------------------
Write-Host ""
Write-Host "==> Suche Python 3.9-3.12..."
$py = $null
foreach ($name in "python3.12","python3.11","python3.10","python3.9","python3","python") {
    if (Get-Command $name -ErrorAction SilentlyContinue) {
        $raw = & $name --version 2>&1
        if ($raw -match "Python 3\.(\d+)") {
            $minor = [int]$Matches[1]
            if ($minor -ge 9 -and $minor -le 12) {
                $py = $name
                Write-Host "    Gefunden: $raw"
                break
            }
        }
    }
}
if (-not $py) {
    Write-Host "FEHLER: Python 3.9-3.12 nicht gefunden."
    Write-Host "Download: https://python.org"
    exit 1
}

# -----------------------------------------------------------------------
# 2. Virtuelle Umgebung
# -----------------------------------------------------------------------
Write-Host ""
Write-Host "==> Virtuelle Umgebung..."
if (-not (Test-Path ".venv")) {
    Write-Host "    Erstelle .venv"
    & $py -m venv .venv
} else {
    Write-Host "    .venv vorhanden"
}

$pip   = Join-Path $ROOT ".venv\Scripts\pip.exe"
$pyins = Join-Path $ROOT ".venv\Scripts\pyinstaller.exe"

Write-Host "    Installiere requirements_windows.txt..."
& $pip install --upgrade pip --quiet
& $pip install -r requirements_windows.txt --quiet
Write-Host "    Fertig."

# -----------------------------------------------------------------------
# 3. Version auslesen
# -----------------------------------------------------------------------
Write-Host ""
Write-Host "==> Lese Version aus src\app.py..."
$match = Select-String -Path "src\app.py" -Pattern 'APP_VERSION\s*=\s*"([^"]+)"'
if (-not $match) {
    Write-Host "FEHLER: APP_VERSION nicht gefunden."
    exit 1
}
$VERSION = $match.Matches[0].Groups[1].Value
Write-Host "    Version: $VERSION"

# -----------------------------------------------------------------------
# 4. PyInstaller
# -----------------------------------------------------------------------
Write-Host ""
Write-Host "==> Starte PyInstaller..."
& $pyins -y "TeamTalk VO Client_win.spec"
Write-Host "==> Build fertig: dist\TeamTalk VO Client"

# -----------------------------------------------------------------------
# 5. ZIP erstellen
# -----------------------------------------------------------------------
$zipName = "TeamTalk VO Client $VERSION Windows.zip"
$zipPath = Join-Path $ROOT "dist\$zipName"
Write-Host ""
Write-Host "==> Erstelle ZIP: $zipName"
if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
Compress-Archive -Path "dist\TeamTalk VO Client" -DestinationPath $zipPath
$sizeMB = [math]::Round((Get-Item $zipPath).Length / 1MB, 1)
Write-Host "    $sizeMB MB"

# -----------------------------------------------------------------------
# 6. Gitea-Release + Upload
# -----------------------------------------------------------------------
if (-not $NoUpload) {
    Write-Host ""
    Write-Host "==> Gitea-Release..."

    $authHdr = "Authorization: token $GITEA_TOKEN"

    # Release suchen oder anlegen
    $releaseId = $null
    try {
        $resp = curl.exe -sf -H $authHdr "$GITEA_API/releases/tags/v$VERSION" 2>$null
        if ($resp) {
            $obj = $resp | ConvertFrom-Json
            if ($obj.id) {
                $releaseId = $obj.id
                Write-Host "    Release v$VERSION existiert bereits (ID $releaseId)."
            }
        }
    } catch {}

    if (-not $releaseId) {
        Write-Host "    Lege Release v$VERSION an..."
        $body = '{"tag_name":"v' + $VERSION + '","name":"v' + $VERSION + '","is_draft":false}'
        $resp = curl.exe -s -X POST -H $authHdr -H "Content-Type: application/json" `
            -d $body "$GITEA_API/releases"
        $obj  = $resp | ConvertFrom-Json
        $releaseId = $obj.id
        Write-Host "    Release-ID: $releaseId"
    }

    # ZIP hochladen
    Write-Host "    Lade ZIP hoch..."
    $nameEnc = [Uri]::EscapeDataString($zipName)
    $resp = curl.exe -s -X POST -H $authHdr -H "Content-Type: application/octet-stream" `
        --data-binary "@$zipPath" `
        "$GITEA_API/releases/$releaseId/assets?name=$nameEnc"
    $obj = $resp | ConvertFrom-Json
    Write-Host "    Asset: $($obj.name)"
}

# -----------------------------------------------------------------------
Write-Host ""
Write-Host "============================================================"
Write-Host " Fertig!  dist\$zipName"
if (-not $NoUpload) {
    Write-Host " https://git.garogaming.xyz/flarion/TeamTalk-VO-Client/releases/tag/v$VERSION"
}
Write-Host "============================================================"
