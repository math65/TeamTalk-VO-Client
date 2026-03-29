"""OfflineMessageQueue – Nachrichten-Warteschlange für Offline-Phasen (v4.5.0).

Nachrichten die während einer Verbindungsunterbrechung gesendet werden,
landen in der Warteschlange und werden nach dem nächsten Reconnect automatisch
übermittelt.

Gespeichert als JSON in app_data_dir (persistent zwischen Neustarts).
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional


@dataclass
class QueuedMessage:
    text: str
    target_type: str       # "channel" | "private"
    target_id: int         # channel_id oder user_id
    target_name: str       # Anzeigename für Status
    timestamp: float

    @property
    def age_seconds(self) -> float:
        return time.time() - self.timestamp

    @property
    def age_str(self) -> str:
        age = int(self.age_seconds)
        if age < 60:
            return f"{age}s"
        return f"{age // 60}m {age % 60}s"


class OfflineMessageQueue:
    """Puffert ausgehende Nachrichten während Verbindungsunterbrechungen."""

    MAX_ENTRIES = 100
    MAX_AGE_SECONDS = 3600  # Nachrichten älter als 1h werden verworfen

    def __init__(self, app_dir: Path) -> None:
        self._path = app_dir / "offline_queue.json"
        self._items: List[QueuedMessage] = []
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            self._items = [
                QueuedMessage(
                    text=str(d.get("text", "")),
                    target_type=str(d.get("target_type", "channel")),
                    target_id=int(d.get("target_id", 0)),
                    target_name=str(d.get("target_name", "")),
                    timestamp=float(d.get("timestamp", time.time())),
                )
                for d in data
                if isinstance(d, dict)
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

    def _prune_old(self) -> None:
        """Entfernt abgelaufene Nachrichten."""
        self._items = [
            m for m in self._items
            if m.age_seconds < self.MAX_AGE_SECONDS
        ]

    def enqueue(
        self,
        text: str,
        target_type: str,
        target_id: int,
        target_name: str = "",
    ) -> None:
        """Fügt eine Nachricht zur Warteschlange hinzu."""
        self._prune_old()
        if len(self._items) >= self.MAX_ENTRIES:
            self._items.pop(0)  # Älteste entfernen
        self._items.append(QueuedMessage(
            text=text,
            target_type=target_type,
            target_id=target_id,
            target_name=target_name,
            timestamp=time.time(),
        ))
        self._save()

    def dequeue_all(self) -> List[QueuedMessage]:
        """Gibt alle wartenden Nachrichten zurück und leert die Queue."""
        self._prune_old()
        items = list(self._items)
        self._items = []
        self._save()
        return items

    def peek(self) -> List[QueuedMessage]:
        """Gibt eine Kopie der Warteschlange zurück ohne sie zu leeren."""
        self._prune_old()
        return list(self._items)

    def clear(self) -> None:
        self._items = []
        self._save()

    def __len__(self) -> int:
        return len(self._items)
