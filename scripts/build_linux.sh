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
#   ./scripts/build_linux.sh              # App bauen + tar.gz + Gitea-Upload
#   ./scripts/build_linux.sh --no-upload  # ohne Gitea-Upload
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$SCRIPT_DIR"

# Gitea-Zugangsdaten
GITEA_TOKEN="e91faa5c35310a376937604fffba15a8d7c66345"
GITEA_BASE="https://git.garogaming.xyz/api/v1/repos/flarion/TeamTalk-VO-Client"

UPLOAD=true
for arg in "$@"; do
  [[ "$arg" == "--no-upload" ]] && UPLOAD=false
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
# 7. tar.gz-Archiv erstellen
# ---------------------------------------------------------------------------
PKG_NAME="TeamTalk_VO_Client_${VERSION}_linux_x64"
PKG_PATH="dist/${PKG_NAME}.tar.gz"
echo "==> Erstelle Archiv: ${PKG_NAME}.tar.gz"
tar -czf "$PKG_PATH" -C dist "TeamTalk VO Client"
echo "    Größe: $(du -sh "$PKG_PATH" | cut -f1)"

# ---------------------------------------------------------------------------
# 8. Gitea-Release hochladen
# ---------------------------------------------------------------------------
if $UPLOAD; then
  EXISTING=$(curl -sf -H "Authorization: token $GITEA_TOKEN" \
    "$GITEA_BASE/releases/tags/v${VERSION}" \
    | python3 -c "import sys,json; print(json.load(sys.stdin).get('id',''))" 2>/dev/null || true)

  if [[ -n "$EXISTING" ]]; then
    echo "==> Release v${VERSION} (ID $EXISTING) existiert bereits."
    RELEASE_ID="$EXISTING"
  else
    echo "==> Lege Gitea-Release v${VERSION} an..."
    RELEASE_ID=$(curl -s -X POST "$GITEA_BASE/releases" \
      -H "Authorization: token $GITEA_TOKEN" -H "Content-Type: application/json" \
      -d "{\"tag_name\":\"v${VERSION}\",\"name\":\"v${VERSION}\",\"is_draft\":false}" \
      | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
    echo "    Release-ID: $RELEASE_ID"
  fi

  echo "==> Lade tar.gz hoch..."
  PKG_NAME_ENC=$(python3 -c "import urllib.parse; print(urllib.parse.quote('${PKG_NAME}.tar.gz'))")
  curl -s -X POST "$GITEA_BASE/releases/${RELEASE_ID}/assets?name=${PKG_NAME_ENC}" \
    -H "Authorization: token $GITEA_TOKEN" \
    -H "Content-Type: application/octet-stream" \
    --data-binary "@${PKG_PATH}" \
    | python3 -c "import sys,json; r=json.load(sys.stdin); print('    Asset:', r.get('name', r.get('message','?')))"
fi

# ---------------------------------------------------------------------------
echo ""
echo "============================================================"
echo " Fertig! dist/${PKG_NAME}.tar.gz"
if $UPLOAD; then
  echo " Release: https://git.garogaming.xyz/flarion/TeamTalk-VO-Client/releases/tag/v${VERSION}"
fi
echo "============================================================"
