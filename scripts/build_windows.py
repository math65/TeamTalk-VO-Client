#!/usr/bin/env python3
"""
TeamTalk VO Client - Windows Build Script
Aufruf: python scripts\\build_windows.py
Kein Upload: python scripts\\build_windows.py --no-upload
"""

import os
import re
import sys
import shutil
import subprocess
import zipfile
import urllib.parse
import urllib.request
import json
import argparse
from pathlib import Path

GITEA_TOKEN = "e91faa5c35310a376937604fffba15a8d7c66345"
GITEA_API   = "https://git.garogaming.xyz/api/v1/repos/flarion/TeamTalk-VO-Client"

# Projektverzeichnis = Elternordner von scripts/
ROOT = Path(__file__).resolve().parent.parent

def run(*args, **kwargs):
    """Fuehrt einen Befehl aus und bricht bei Fehler ab."""
    print("   $", " ".join(str(a) for a in args))
    subprocess.run(list(args), check=True, **kwargs)

def step(title):
    print(f"\n==> {title}")

# -----------------------------------------------------------------------
# 1. Python pruefen
# -----------------------------------------------------------------------
step("Python pruefen")
print(f"   Python {sys.version.split()[0]}  ({sys.executable})")
major, minor = sys.version_info[:2]
if major != 3 or not (9 <= minor <= 12):
    print("FEHLER: Python 3.9-3.12 benoetigt.")
    sys.exit(1)

# -----------------------------------------------------------------------
# 2. Virtuelle Umgebung anlegen
# -----------------------------------------------------------------------
step("Virtuelle Umgebung")
venv_dir  = ROOT / ".venv"
pip_exe   = venv_dir / "Scripts" / "pip.exe"
pyins_exe = venv_dir / "Scripts" / "pyinstaller.exe"

if not venv_dir.exists():
    print("   Erstelle .venv ...")
    run(sys.executable, "-m", "venv", str(venv_dir))
else:
    print("   .venv bereits vorhanden.")

print("   Installiere requirements_windows.txt ...")
run(str(pip_exe), "install", "--upgrade", "pip", "--quiet")
run(str(pip_exe), "install", "-r", str(ROOT / "requirements_windows.txt"), "--quiet")
print("   Fertig.")

# -----------------------------------------------------------------------
# 3. Version auslesen
# -----------------------------------------------------------------------
step("Version auslesen")
app_py = (ROOT / "src" / "app.py").read_text(encoding="utf-8")
match  = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', app_py)
if not match:
    print("FEHLER: APP_VERSION nicht in src/app.py gefunden.")
    sys.exit(1)
VERSION = match.group(1)
print(f"   Version: {VERSION}")

# -----------------------------------------------------------------------
# 4. PyInstaller
# -----------------------------------------------------------------------
step("PyInstaller-Build")
spec_file = ROOT / "TeamTalk VO Client_win.spec"
run(str(pyins_exe), "-y", str(spec_file), cwd=str(ROOT))
print("   Build fertig.")

# -----------------------------------------------------------------------
# 5. ZIP erstellen
# -----------------------------------------------------------------------
step("ZIP erstellen")
app_dir  = ROOT / "dist" / "TeamTalk VO Client"
zip_name = f"TeamTalk VO Client {VERSION} Windows.zip"
zip_path = ROOT / "dist" / zip_name

if zip_path.exists():
    zip_path.unlink()

print(f"   Packe {app_dir} ...")
with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
    for f in app_dir.rglob("*"):
        zf.write(f, f.relative_to(app_dir.parent))

size_mb = round(zip_path.stat().st_size / 1_048_576, 1)
print(f"   {zip_name}  ({size_mb} MB)")

# -----------------------------------------------------------------------
# 6. Gitea-Release + Upload
# -----------------------------------------------------------------------
def gitea_get(path):
    req = urllib.request.Request(
        f"{GITEA_API}{path}",
        headers={"Authorization": f"token {GITEA_TOKEN}"}
    )
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())
    except Exception:
        return None

def gitea_post_json(path, payload):
    data = json.dumps(payload).encode()
    req  = urllib.request.Request(
        f"{GITEA_API}{path}",
        data=data,
        headers={
            "Authorization": f"token {GITEA_TOKEN}",
            "Content-Type":  "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())

def gitea_upload(path, file_path):
    data = file_path.read_bytes()
    req  = urllib.request.Request(
        f"{GITEA_API}{path}",
        data=data,
        headers={
            "Authorization": f"token {GITEA_TOKEN}",
            "Content-Type":  "application/octet-stream",
        },
        method="POST",
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())

def upload(no_upload):
    if no_upload:
        return
    step("Gitea-Release")

    existing = gitea_get(f"/releases/tags/v{VERSION}")
    if existing and existing.get("id"):
        release_id = existing["id"]
        print(f"   Release v{VERSION} existiert bereits (ID {release_id}).")
    else:
        print(f"   Lege Release v{VERSION} an ...")
        resp = gitea_post_json("/releases", {
            "tag_name": f"v{VERSION}",
            "name":     f"v{VERSION}",
            "is_draft": False,
        })
        release_id = resp["id"]
        print(f"   Release-ID: {release_id}")

    print(f"   Lade {zip_name} hoch ...")
    name_enc = urllib.parse.quote(zip_name)
    resp = gitea_upload(f"/releases/{release_id}/assets?name={name_enc}", zip_path)
    print(f"   Asset: {resp.get('name', '?')}")

parser = argparse.ArgumentParser()
parser.add_argument("--no-upload", action="store_true")
args = parser.parse_args()

upload(args.no_upload)

# -----------------------------------------------------------------------
print()
print("=" * 60)
print(f" Fertig!  dist/{zip_name}")
if not args.no_upload:
    print(f" https://git.garogaming.xyz/flarion/TeamTalk-VO-Client/releases/tag/v{VERSION}")
print("=" * 60)
