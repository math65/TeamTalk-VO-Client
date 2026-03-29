"""Gespeicherte Chat-Nachrichten (v4.9.0).

Ermöglicht das Markieren und persistente Speichern einzelner Chat-Nachrichten
mit Zeitstempel und Serverkontext.

v4.9.0 – TTL-Ablauf: Nachrichten älter als ``max_age_days`` Tage werden beim
Laden und beim expliziten ``expire()``-Aufruf automatisch entfernt.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List


@dataclass
class SavedMessage:
    text: str
    timestamp: float
    server: str = ""

    @property
    def time_str(self) -> str:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.timestamp))


class SavedMessageManager:
    """Lädt und speichert markierte Chat-Nachrichten als JSON."""

    MAX_ENTRIES = 500
    DEFAULT_MAX_AGE_DAYS = 30  # v4.9.0 – Nachrichten älter als 30 Tage laufen ab

    def __init__(self, app_dir: Path, max_age_days: int = DEFAULT_MAX_AGE_DAYS) -> None:
        self._path = app_dir / "saved_messages.json"
        self._items: List[SavedMessage] = []
        self._max_age_seconds = max_age_days * 86400
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            now = time.time()
            self._items = [
                SavedMessage(
                    text=str(d.get("text", "")),
                    timestamp=float(d.get("timestamp", 0)),
                    server=str(d.get("server", "")),
                )
                for d in data
                if isinstance(d, dict)
                # v4.9.0 – abgelaufene Einträge beim Laden überspringen
                and (self._max_age_seconds <= 0 or now - float(d.get("timestamp", 0)) <= self._max_age_seconds)
            ]
        except Exception:
            self._items = []

    def _save(self) -> None:
        try:
            self._path.write_text(
                json.dumps([asdict(m) for m in self._items], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    def add(self, text: str, server: str = "") -> None:
        """Fügt eine Nachricht hinzu (Duplikate werden ignoriert)."""
        text = text.strip()
        if not text:
            return
        # Duplikat derselben Nachricht auf demselben Server ignorieren
        for m in self._items:
            if m.text == text and m.server == server:
                return
        self._items.append(SavedMessage(text=text, timestamp=time.time(), server=server))
        if len(self._items) > self.MAX_ENTRIES:
            self._items = self._items[-self.MAX_ENTRIES:]
        self._save()

    def remove(self, index: int) -> None:
        if 0 <= index < len(self._items):
            self._items.pop(index)
            self._save()

    def clear(self) -> None:
        self._items = []
        self._save()

    def expire(self) -> int:
        """Entfernt abgelaufene Nachrichten. Gibt Anzahl entfernter Einträge zurück.

        v4.9.0 – kann manuell aufgerufen werden, z. B. beim App-Start.
        """
        if self._max_age_seconds <= 0:
            return 0
        now = time.time()
        before = len(self._items)
        self._items = [m for m in self._items if now - m.timestamp <= self._max_age_seconds]
        removed = before - len(self._items)
        if removed > 0:
            self._save()
        return removed

    def items(self) -> List[SavedMessage]:
        return list(self._items)
