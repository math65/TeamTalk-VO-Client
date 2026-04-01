# =============================================================================
# build_windows.ps1 – TeamTalk VO Client für Windows bauen
# =============================================================================
# Voraussetzungen:
#   - Windows 10 oder neuer (64-Bit)
#   - Python 3.9–3.12 (https://python.org) – "Add Python to PATH" aktivieren
#   - PortAudio-DLL (wird von pyaudio mitgeliefert)
#
# Aufruf (PowerShell, aus dem Projektverzeichnis):
#   .\scripts\build_windows.ps1            # nur App bauen
#   .\scripts\build_windows.ps1 -Release   # bauen + ZIP erstellen
# =============================================================================

param(
    [switch]$Release
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# Ins Projektverzeichnis wechseln (Skript liegt in scripts/)
$ProjectDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $ProjectDir

# ---------------------------------------------------------------------------
# 1. Python prüfen
# ---------------------------------------------------------------------------
$PythonExe = $null
foreach ($candidate in @("python3.12", "python3.11", "python3.10", "python3.9", "python3", "python")) {
    $found = Get-Command $candidate -ErrorAction SilentlyContinue
    if ($found) {
        $ver = & $candidate -c "import sys; print('%d.%d' % sys.version_info[:2])"
        $parts = $ver.Split(".")
        if ([int]$parts[0] -eq 3 -and [int]$parts[1] -ge 9 -and [int]$parts[1] -le 12) {
            $PythonExe = $candidate
            Write-Host "==> Python: $(& $candidate --version) ($candidate)"
            break
        }
    }
}

if (-not $PythonExe) {
    Write-Error "Python 3.9–3.12 nicht gefunden. Bitte von https://python.org installieren."
    exit 1
}

# ---------------------------------------------------------------------------
# 2. Virtuelle Umgebung anlegen / aktualisieren
# ---------------------------------------------------------------------------
if (-not (Test-Path ".venv")) {
    Write-Host "==> Erstelle virtuelle Umgebung (.venv)..."
    & $PythonExe -m venv .venv
}

Write-Host "==> Installiere Abhaengigkeiten (requirements_windows.txt)..."
.venv\Scripts\pip install --upgrade pip --quiet
.venv\Scripts\pip install -r requirements_windows.txt --quiet
Write-Host "    Fertig."

# ---------------------------------------------------------------------------
# 3. Version ermitteln
# ---------------------------------------------------------------------------
$VersionLine = Select-String -Path "src\app.py" -Pattern 'APP_VERSION = "([^"]+)"'
if (-not $VersionLine) {
    Write-Error "APP_VERSION nicht in src\app.py gefunden."
    exit 1
}
$Version = $VersionLine.Matches[0].Groups[1].Value
Write-Host "==> Version: $Version"

# ---------------------------------------------------------------------------
# 4. App bauen (PyInstaller)
# ---------------------------------------------------------------------------
Write-Host "==> Starte PyInstaller-Build..."
.venv\Scripts\pyinstaller -y "TeamTalk VO Client_win.spec"
Write-Host "==> Build abgeschlossen: dist\TeamTalk VO Client\"

# ---------------------------------------------------------------------------
# 5. Optional: ZIP-Archiv erstellen
# ---------------------------------------------------------------------------
if ($Release) {
    $ZipName = "TeamTalk VO Client $Version Windows.zip"
    $ZipPath = "dist\$ZipName"
    Write-Host "==> Erstelle ZIP: $ZipName"
    Compress-Archive -Path "dist\TeamTalk VO Client" -DestinationPath $ZipPath -Force
    $SizeMB = [math]::Round((Get-Item $ZipPath).Length / 1MB, 1)
    Write-Host "    Groesse: ${SizeMB} MB"
}

# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "============================================================"
Write-Host " Fertig!"
if ($Release) {
    Write-Host " dist\$ZipName"
}
Write-Host "============================================================"
