"""PluginConfig – persistenter Key-Value-Store je Plugin (ab v1.10.1).

Daten werden als JSON in
``~/Library/Application Support/TeamTalkVOClient/plugin_configs/<plugin_name>.json``
gespeichert.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional


def _config_dir() -> Path:
    base = Path.home() / "Library" / "Application Support" / "TeamTalkVOClient" / "plugin_configs"
    base.mkdir(parents=True, exist_ok=True)
    return base


class PluginConfig:
    """Einfacher persistenter Key-Value-Store für ein Plugin."""

    def __init__(self, plugin_name: str) -> None:
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in plugin_name)
        self._path = _config_dir() / f"{safe}.json"
        self._data: dict = {}
        self._load()

    def _load(self) -> None:
        try:
            if self._path.exists():
                self._data = json.loads(self._path.read_text("utf-8"))
        except Exception:
            self._data = {}

    def _save(self) -> None:
        try:
            self._path.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), "utf-8")
        except Exception:
            pass

    def get(self, key: str, default: Any = None) -> Any:
        """Liest einen Wert aus dem Store."""
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Setzt einen Wert und speichert sofort."""
        self._data[key] = value
        self._save()

    def delete(self, key: str) -> None:
        """Entfernt einen Schlüssel."""
        self._data.pop(key, None)
        self._save()

    def all(self) -> dict:
        """Gibt alle gespeicherten Schlüssel-Wert-Paare zurück."""
        return dict(self._data)
