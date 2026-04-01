#!/usr/bin/env bash
# =============================================================================
# build_linux.sh – TeamTalk VO Client für Linux bauen
# =============================================================================
# Voraussetzungen:
#   - Ubuntu 22.04 / Debian 12 oder neuer (64-Bit)
#   - Python 3.9–3.12 und pip
#   - System-Pakete (einmalig):
#       sudo apt install python3-dev portaudio19-dev libgtk-3-dev \
#                        libgstreamer1.0-dev gstreamer1.0-plugins-base \
#                        xdotool grim  # xdotool für X11, grim für Wayland
#
# Aufruf (aus dem Projektverzeichnis):
#   ./scripts/build_linux.sh            # nur App bauen
#   ./scripts/build_linux.sh --package  # bauen + tar.gz erstellen
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$SCRIPT_DIR"

PACKAGE=false
for arg in "$@"; do
  [[ "$arg" == "--package" ]] && PACKAGE=true
done

# ---------------------------------------------------------------------------
# 1. System-Abhängigkeiten prüfen
# ---------------------------------------------------------------------------
check_apt() {
  dpkg -s "$1" &>/dev/null 2>&1
}

MISSING=()
for pkg in python3-dev portaudio19-dev libgtk-3-dev; do
  if ! check_apt "$pkg"; then
    MISSING+=("$pkg")
  fi
done

if [[ ${#MISSING[@]} -gt 0 ]]; then
  echo "WARNUNG: Folgende System-Pakete fehlen: ${MISSING[*]}"
  echo "  Installieren: sudo apt install ${MISSING[*]}"
  echo "  Weiter auf eigene Gefahr..."
fi

# ---------------------------------------------------------------------------
# 2. Python prüfen
# ---------------------------------------------------------------------------
PYTHON=""
for candidate in python3.12 python3.11 python3.10 python3.9 python3; do
  if command -v "$candidate" &>/dev/null; then
    PYVER=$("$candidate" -c "import sys; print('%d.%d' % sys.version_info[:2])")
    PYMAJ=$(echo "$PYVER" | cut -d. -f1)
    PYMIN=$(echo "$PYVER" | cut -d. -f2)
    if [[ "$PYMAJ" -eq 3 && "$PYMIN" -ge 9 && "$PYMIN" -le 12 ]]; then
      PYTHON="$candidate"
      break
    fi
  fi
done

if [[ -z "$PYTHON" ]]; then
  echo "FEHLER: Python 3.9–3.12 nicht gefunden." >&2
  exit 1
fi
echo "==> Python: $($PYTHON --version) ($PYTHON)"

# ---------------------------------------------------------------------------
# 3. Virtuelle Umgebung anlegen / aktualisieren
# ---------------------------------------------------------------------------
if [[ ! -d ".venv" ]]; then
  echo "==> Erstelle virtuelle Umgebung (.venv)..."
  "$PYTHON" -m venv .venv
fi

echo "==> Installiere Abhängigkeiten (requirements_linux.txt)..."
.venv/bin/pip install --upgrade pip --quiet
.venv/bin/pip install -r requirements_linux.txt --quiet
echo "    Fertig."

# ---------------------------------------------------------------------------
# 4. Version ermitteln
# ---------------------------------------------------------------------------
VERSION=$(grep 'APP_VERSION = ' src/app.py | cut -d'"' -f2)
if [[ -z "$VERSION" ]]; then
  echo "FEHLER: APP_VERSION nicht in src/app.py gefunden." >&2
  exit 1
fi
echo "==> Version: $VERSION"

# ---------------------------------------------------------------------------
# 5. TeamTalk-SDK prüfen (Linux)
# ---------------------------------------------------------------------------
SDK_PATH="third_party/teamtalk/tt5sdk_v5.19a_linux_x64"
if [[ ! -d "$SDK_PATH" ]]; then
  echo "WARNUNG: Linux-SDK nicht gefunden: $SDK_PATH"
  echo "  Download: https://bearware.dk/teamtalksdk"
  echo "  Entpacken nach: third_party/teamtalk/tt5sdk_v5.19a_linux_x64/"
fi

# ---------------------------------------------------------------------------
# 6. App bauen (PyInstaller)
# ---------------------------------------------------------------------------
echo "==> Starte PyInstaller-Build..."
.venv/bin/pyinstaller -y "TeamTalk VO Client_linux.spec"
echo "==> Build abgeschlossen: dist/TeamTalk VO Client/"

# ---------------------------------------------------------------------------
# 7. Optional: tar.gz-Archiv erstellen
# ---------------------------------------------------------------------------
if $PACKAGE; then
  PKG_NAME="TeamTalk_VO_Client_${VERSION}_linux_x64"
  PKG_PATH="dist/${PKG_NAME}.tar.gz"
  echo "==> Erstelle Archiv: ${PKG_NAME}.tar.gz"
  tar -czf "$PKG_PATH" -C dist "TeamTalk VO Client"
  echo "    Größe: $(du -sh "$PKG_PATH" | cut -f1)"
fi

# ---------------------------------------------------------------------------
echo ""
echo "============================================================"
echo " Fertig!"
if $PACKAGE; then
  echo " dist/${PKG_NAME}.tar.gz"
fi
echo "============================================================"
