"""update_manager – GitHub-Release-Abfrage und Asset-Download.

Öffentliche API:
    fetch_releases(limit)        -> List[Release]
    get_platform_asset(release)  -> Optional[ReleaseAsset]
    download_asset(asset, dest_dir, progress_cb) -> str  (Pfad zur Datei)
    open_file_or_folder(path)    -> None
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, List, Optional

_GITHUB_API = "https://api.github.com/repos/fla-rion/TeamTalk-VO-Client/releases"
_HEADERS = {"User-Agent": "TeamTalk-VO-Client-UpdateManager"}


@dataclass
class ReleaseAsset:
    name: str
    download_url: str
    size: int  # Bytes


@dataclass
class Release:
    tag: str
    name: str
    date: str        # "YYYY-MM-DD"
    body: str        # Changelog-Text
    assets: List[ReleaseAsset] = field(default_factory=list)

    @property
    def platform_asset(self) -> Optional[ReleaseAsset]:
        return get_platform_asset(self)


def fetch_releases(limit: int = 50) -> List[Release]:
    """Holt alle Releases von der GitHub-API (kein Token nötig)."""
    url = f"{_GITHUB_API}?per_page={limit}"
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    result: List[Release] = []
    for r in data:
        if r.get("draft") or r.get("prerelease"):
            continue
        assets = [
            ReleaseAsset(
                name=a["name"],
                download_url=a["browser_download_url"],
                size=int(a.get("size", 0)),
            )
            for a in r.get("assets", [])
        ]
        result.append(Release(
            tag=r["tag_name"],
            name=r.get("name") or r["tag_name"],
            date=(r.get("published_at") or "")[:10],
            body=(r.get("body") or "").strip(),
            assets=assets,
        ))
    return result


def get_platform_asset(release: Release) -> Optional[ReleaseAsset]:
    """Gibt das passende Asset für die aktuelle Plattform zurück."""
    for asset in release.assets:
        n = asset.name.lower()
        if sys.platform == "darwin" and n.endswith(".dmg"):
            return asset
        if sys.platform == "win32" and n.endswith(".zip"):
            return asset
    return None


def download_asset(
    asset: ReleaseAsset,
    dest_dir: str,
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> str:
    """Lädt ein Asset herunter und gibt den Zielpfad zurück.

    progress_cb(downloaded_bytes, total_bytes) wird regelmäßig aufgerufen.
    """
    os.makedirs(dest_dir, exist_ok=True)
    dest_path = os.path.join(dest_dir, asset.name)
    req = urllib.request.Request(asset.download_url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=120) as resp:
        total = int(resp.headers.get("Content-Length") or asset.size or 0)
        downloaded = 0
        with open(dest_path, "wb") as f:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if progress_cb:
                    progress_cb(downloaded, total)
    return dest_path


def open_file_or_folder(path: str) -> None:
    """Öffnet eine Datei oder ihren übergeordneten Ordner im Dateimanager."""
    import subprocess
    if sys.platform == "darwin":
        subprocess.Popen(["open", path])
    elif sys.platform == "win32":
        os.startfile(path)  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", os.path.dirname(path)])


def reveal_in_finder(path: str) -> None:
    """Zeigt die Datei im Finder / Explorer an (markiert)."""
    import subprocess
    if sys.platform == "darwin":
        subprocess.Popen(["open", "-R", path])
    elif sys.platform == "win32":
        subprocess.Popen(["explorer", "/select,", path])
    else:
        open_file_or_folder(path)


def format_size(n: int) -> str:
    if n >= 1_048_576:
        return f"{n / 1_048_576:.1f} MB"
    if n >= 1024:
        return f"{n / 1024:.0f} KB"
    return f"{n} B"
