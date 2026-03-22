"""Persistente Chat-Verlauf-Speicherung pro Server."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict, List

MAX_HISTORY = 200


class ChatHistoryManager:
    """Speichert und lädt Chat-Nachrichten je Server als JSON."""

    def __init__(self, data_dir: Path) -> None:
        self._dir = data_dir / "chat_history"
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, server_key: str) -> Path:
        safe = server_key.replace(":", "_").replace("/", "_").replace(".", "_")
        return self._dir / f"{safe}.json"

    def load(self, server_key: str) -> List[Dict]:
        p = self._path(server_key)
        if not p.exists():
            return []
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def clear(self, server_key: str) -> None:
        try:
            p = self._path(server_key)
            if p.exists():
                p.unlink()
        except Exception:
            pass

    def append(self, server_key: str, text: str, kind: str) -> None:
        entries = self.load(server_key)
        entries.append({
            "ts": time.strftime("%H:%M:%S"),
            "text": text,
            "kind": kind,
        })
        if len(entries) > MAX_HISTORY:
            entries = entries[-MAX_HISTORY:]
        try:
            self._path(server_key).write_text(
                json.dumps(entries, ensure_ascii=False), encoding="utf-8"
            )
        except Exception:
            pass
