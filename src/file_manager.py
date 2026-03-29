"""FileManager – Erweiterte Dateiverwaltung für TeamTalk (v5.5.0).

Verwaltet den lokalen Download-Verlauf, Datei-Kategorisierung, automatische
Benennung und Transferstatistiken.

Daten werden in ``file_history.json`` im App-Verzeichnis gespeichert.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class FileRecord:
    """Eintrag im Download-/Upload-Verlauf."""
    filename: str
    size_bytes: int
    direction: str       # "download" | "upload"
    channel_name: str
    sender: str
    timestamp: float
    local_path: str = ""
    completed: bool = False

    def size_human(self) -> str:
        """Gibt die Dateigröße in menschenlesbarer Form zurück."""
        n = self.size_bytes
        for unit in ("B", "KB", "MB", "GB"):
            if n < 1024:
                return f"{n:.1f} {unit}"
            n /= 1024
        return f"{n:.1f} TB"

    def age_days(self) -> float:
        return (time.time() - self.timestamp) / 86400

    def as_dict(self) -> Dict:
        return {
            "filename": self.filename,
            "size_bytes": self.size_bytes,
            "direction": self.direction,
            "channel_name": self.channel_name,
            "sender": self.sender,
            "timestamp": self.timestamp,
            "local_path": self.local_path,
            "completed": self.completed,
        }


# Datei-Kategorien anhand Erweiterung
_CATEGORIES: Dict[str, str] = {
    "audio": {".mp3", ".wav", ".ogg", ".flac", ".aac", ".m4a"},
    "video": {".mp4", ".mkv", ".avi", ".mov", ".webm"},
    "bild":  {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".svg", ".webp"},
    "dokument": {".pdf", ".docx", ".doc", ".odt", ".txt", ".rtf", ".md"},
    "archiv": {".zip", ".tar", ".gz", ".7z", ".rar"},
    "code": {".py", ".js", ".ts", ".html", ".css", ".json", ".xml"},
}


def categorize_file(filename: str) -> str:
    """Gibt die Kategorie einer Datei anhand ihrer Erweiterung zurück.

    Mögliche Rückgabewerte: audio, video, bild, dokument, archiv, code, sonstiges.
    """
    ext = Path(filename).suffix.lower()
    for category, extensions in _CATEGORIES.items():
        if ext in extensions:
            return category
    return "sonstiges"


def safe_filename(filename: str) -> str:
    """Bereinigt einen Dateinamen von ungültigen Zeichen.

    Ersetzt ``/\\:*?"<>|`` durch ``_`` und kürzt auf 200 Zeichen.
    """
    invalid = '/\\:*?"<>|'
    clean = "".join("_" if c in invalid else c for c in filename)
    return clean[:200]


def auto_rename(filename: str, dest_dir: Path) -> str:
    """Gibt einen freien Dateinamen zurück (fügt ``_2``, ``_3`` etc. an bei Kollision)."""
    p = dest_dir / filename
    if not p.exists():
        return filename
    stem = p.stem
    suffix = p.suffix
    counter = 2
    while True:
        candidate = f"{stem}_{counter}{suffix}"
        if not (dest_dir / candidate).exists():
            return candidate
        counter += 1


class FileManager:
    """Verwaltet Download-Verlauf, Statistiken und Datei-Kategorisierung."""

    MAX_HISTORY = 1000
    DEFAULT_DOWNLOAD_DIR = Path.home() / "Downloads" / "TeamTalk"

    def __init__(self, app_dir: Path, download_dir: Optional[Path] = None) -> None:
        self._path = app_dir / "file_history.json"
        self._download_dir = download_dir or self.DEFAULT_DOWNLOAD_DIR
        self._records: List[FileRecord] = []
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            self._records = [
                FileRecord(
                    filename=str(d.get("filename", "")),
                    size_bytes=int(d.get("size_bytes", 0)),
                    direction=str(d.get("direction", "download")),
                    channel_name=str(d.get("channel_name", "")),
                    sender=str(d.get("sender", "")),
                    timestamp=float(d.get("timestamp", 0)),
                    local_path=str(d.get("local_path", "")),
                    completed=bool(d.get("completed", False)),
                )
                for d in data
                if isinstance(d, dict)
            ]
        except Exception:
            self._records = []

    def _save(self) -> None:
        try:
            self._path.write_text(
                json.dumps([r.as_dict() for r in self._records], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    def add(
        self,
        filename: str,
        size_bytes: int,
        direction: str,
        channel_name: str,
        sender: str,
        local_path: str = "",
        completed: bool = False,
    ) -> FileRecord:
        """Fügt einen Eintrag zum Verlauf hinzu."""
        rec = FileRecord(
            filename=safe_filename(filename),
            size_bytes=size_bytes,
            direction=direction,
            channel_name=channel_name,
            sender=sender,
            timestamp=time.time(),
            local_path=local_path,
            completed=completed,
        )
        self._records.insert(0, rec)
        if len(self._records) > self.MAX_HISTORY:
            self._records = self._records[:self.MAX_HISTORY]
        self._save()
        return rec

    def mark_completed(self, filename: str, local_path: str = "") -> None:
        """Markiert den neuesten Eintrag mit ``filename`` als abgeschlossen."""
        for r in self._records:
            if r.filename == filename and not r.completed:
                r.completed = True
                if local_path:
                    r.local_path = local_path
                break
        self._save()

    def recent(self, n: int = 20) -> List[FileRecord]:
        """Gibt die letzten ``n`` Einträge zurück."""
        return self._records[:n]

    def by_category(self, category: str) -> List[FileRecord]:
        """Gibt alle Einträge einer Kategorie zurück."""
        return [r for r in self._records if categorize_file(r.filename) == category]

    def purge_older_than_days(self, days: int) -> int:
        """Entfernt Einträge älter als ``days`` Tage."""
        cutoff = time.time() - days * 86400
        before = len(self._records)
        self._records = [r for r in self._records if r.timestamp >= cutoff]
        removed = before - len(self._records)
        if removed:
            self._save()
        return removed

    def stats(self) -> Dict:
        """Gibt Transferstatistiken zurück."""
        downloads = [r for r in self._records if r.direction == "download" and r.completed]
        uploads = [r for r in self._records if r.direction == "upload" and r.completed]
        return {
            "total_downloads": len(downloads),
            "total_uploads": len(uploads),
            "downloaded_bytes": sum(r.size_bytes for r in downloads),
            "uploaded_bytes": sum(r.size_bytes for r in uploads),
            "categories": {
                cat: len([r for r in self._records if categorize_file(r.filename) == cat])
                for cat in list(_CATEGORIES) + ["sonstiges"]
            },
        }

    def suggest_local_path(self, filename: str) -> Path:
        """Schlägt einen lokalen Speicherpfad vor (Download-Dir + freier Name)."""
        self._download_dir.mkdir(parents=True, exist_ok=True)
        safe = safe_filename(filename)
        free = auto_rename(safe, self._download_dir)
        return self._download_dir / free
