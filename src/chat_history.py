"""Persistente Chat-Verlauf-Speicherung pro Server."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict, List

MAX_HISTORY = 500


class ChatHistoryManager:
    """Speichert und lädt Chat-Nachrichten je Server als JSON."""

    def __init__(self, data_dir: Path) -> None:
        self._dir = data_dir / "chat_history"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._private_dir = data_dir / "private_chat_history"
        self._private_dir.mkdir(parents=True, exist_ok=True)

    def _safe_key(self, key: str) -> str:
        return key.replace(":", "_").replace("/", "_").replace(".", "_")

    def _path(self, server_key: str) -> Path:
        return self._dir / f"{self._safe_key(server_key)}.json"

    def _private_path(self, server_key: str, partner: str) -> Path:
        server_safe = self._safe_key(server_key)
        partner_safe = self._safe_key(partner)
        d = self._private_dir / server_safe
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{partner_safe}.json"

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
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
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

    # ------------------------------------------------------------------
    # Private chat history
    # ------------------------------------------------------------------

    def load_private(self, server_key: str, partner: str) -> List[Dict]:
        p = self._private_path(server_key, partner)
        if not p.exists():
            return []
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def append_private(self, server_key: str, partner: str, text: str, kind: str) -> None:
        entries = self.load_private(server_key, partner)
        entries.append({
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "text": text,
            "kind": kind,
        })
        if len(entries) > MAX_HISTORY:
            entries = entries[-MAX_HISTORY:]
        try:
            self._private_path(server_key, partner).write_text(
                json.dumps(entries, ensure_ascii=False), encoding="utf-8"
            )
        except Exception:
            pass

    def export_private(self, server_key: str, partner: str, out_path: Path) -> int:
        """Exportiert den privaten Chat-Verlauf als TXT. Gibt Zeilenanzahl zurück."""
        entries = self.load_private(server_key, partner)
        lines = [f"[{e.get('ts', '')}] {e.get('text', '')}" for e in entries]
        out_path.write_text("\n".join(lines), encoding="utf-8")
        return len(lines)

    def list_private_partners(self, server_key: str) -> List[str]:
        """Gibt alle Partner zurück, mit denen ein Privatverlauf gespeichert ist."""
        d = self._private_dir / self._safe_key(server_key)
        if not d.exists():
            return []
        return [p.stem for p in d.glob("*.json")]
