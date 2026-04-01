#!/usr/bin/env bash
# =============================================================================
# build_macos.sh – TeamTalk VO Client für macOS bauen
# =============================================================================
# Voraussetzungen:
#   - macOS 11 Big Sur oder neuer
#   - Python 3.9–3.12 (system oder pyenv)
#   - Xcode Command Line Tools: xcode-select --install
#   - PortAudio (für pyaudio): brew install portaudio
#
# Aufruf (aus dem Projektverzeichnis):
#   ./scripts/build_macos.sh            # App + DMG bauen + Gitea-Release hochladen
#   ./scripts/build_macos.sh --no-upload  # nur App + DMG, kein Upload
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$SCRIPT_DIR"

# Gitea-Zugangsdaten (privates Repo)
GITEA_TOKEN="e91faa5c35310a376937604fffba15a8d7c66345"
GITEA_BASE="https://git.garogaming.xyz/api/v1/repos/flarion/TeamTalk-VO-Client"

UPLOAD=true
for arg in "$@"; do
  [[ "$arg" == "--no-upload" ]] && UPLOAD=false
done

# ---------------------------------------------------------------------------
# 1. Python prüfen
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
  echo "  Installieren: brew install python@3.12  oder  pyenv install 3.12" >&2
  exit 1
fi
echo "==> Python: $($PYTHON --version) ($PYTHON)"

# ---------------------------------------------------------------------------
# 2. Virtuelle Umgebung anlegen / aktualisieren
# ---------------------------------------------------------------------------
if [[ ! -d ".venv" ]]; then
  echo "==> Erstelle virtuelle Umgebung (.venv)..."
  "$PYTHON" -m venv .venv
fi

echo "==> Installiere Abhängigkeiten (requirements_macos.txt)..."
.venv/bin/pip install --upgrade pip --quiet
.venv/bin/pip install -r requirements_macos.txt --quiet
echo "    Fertig."

# ---------------------------------------------------------------------------
# 3. Version ermitteln
# ---------------------------------------------------------------------------
VERSION=$(grep 'APP_VERSION = ' src/app.py | cut -d'"' -f2)
if [[ -z "$VERSION" ]]; then
  echo "FEHLER: APP_VERSION nicht in src/app.py gefunden." >&2
  exit 1
fi
echo "==> Version: $VERSION"

# ---------------------------------------------------------------------------
# 4. BlackHole-PKG prüfen
# ---------------------------------------------------------------------------
BH_PKG="third_party/blackhole/BlackHole2ch.pkg"
if [[ ! -f "$BH_PKG" ]]; then
  echo "WARNUNG: $BH_PKG fehlt – wird nicht in den Bundle eingebunden."
  echo "  Download: https://github.com/ExistentialAudio/BlackHole/releases"
fi

# ---------------------------------------------------------------------------
# 5. App bauen (PyInstaller)
# ---------------------------------------------------------------------------
echo "==> Starte PyInstaller-Build..."
.venv/bin/pyinstaller -y "TeamTalk VO Client.spec"
echo "==> Build abgeschlossen: dist/TeamTalk VO Client.app"

# ---------------------------------------------------------------------------
# 6. DMG erstellen
# ---------------------------------------------------------------------------
DMG_NAME="TeamTalk VO Client ${VERSION}.dmg"
DMG_PATH="dist/${DMG_NAME}"

echo "==> Erstelle DMG: ${DMG_NAME}"
hdiutil create \
  -volname "TeamTalk VO Client ${VERSION}" \
  -srcfolder "dist/TeamTalk VO Client.app" \
  -ov -format UDZO \
  "$DMG_PATH"
echo "    Größe: $(du -sh "$DMG_PATH" | cut -f1)"

# ---------------------------------------------------------------------------
# 7. Gitea-Release hochladen
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

  echo "==> Lade DMG hoch..."
  DMG_NAME_ENC=$(python3 -c "import urllib.parse; print(urllib.parse.quote('${DMG_NAME}'))")
  curl -s -X POST "$GITEA_BASE/releases/${RELEASE_ID}/assets?name=${DMG_NAME_ENC}" \
    -H "Authorization: token $GITEA_TOKEN" \
    -H "Content-Type: application/octet-stream" \
    --data-binary "@${DMG_PATH}" \
    | python3 -c "import sys,json; r=json.load(sys.stdin); print('    Asset:', r.get('name', r.get('message','?')))"
fi

# ---------------------------------------------------------------------------
echo ""
echo "============================================================"
echo " Fertig! dist/${DMG_NAME}"
if $UPLOAD; then
  echo " Release: https://git.garogaming.xyz/flarion/TeamTalk-VO-Client/releases/tag/v${VERSION}"
fi
echo "============================================================"
