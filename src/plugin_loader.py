"""Plugin-Loader – lädt Plugins aus dem `plugins/`-Verzeichnis (ab v1.10.1).

Plugins müssen eine Funktion `register(bus, api)` exportieren.
Rückwärtskompatibilität: `register(bus)` (nur ein Parameter) wird ebenfalls akzeptiert.

Optionales Modul-Attribut `metadata` (dict):
    {
        "name": "Mein Plugin",
        "version": "1.0",
        "description": "Was das Plugin macht",
        "author": "Autor",
    }
"""
from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path
from typing import Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from event_bus import EventBus
    from plugin_api import PluginAPI

_DEFAULT_META: Dict[str, str] = {
    "name": "",
    "version": "",
    "description": "",
    "author": "",
}


class PluginLoader:
    def __init__(self, bus: "EventBus", plugins_dir: Path, api: Optional["PluginAPI"] = None) -> None:
        self._bus = bus
        self._dir = plugins_dir
        self._api = api
        self._loaded: List[str] = []
        # filename -> metadata dict
        self._metadata: Dict[str, Dict[str, str]] = {}

    def load_all(self) -> int:
        """Lädt alle Plugins aus dem Plugins-Verzeichnis. Gibt Anzahl zurück."""
        if not self._dir.exists():
            return 0
        count = 0
        for path in sorted(self._dir.glob("*.py")):
            if path.name.startswith("_"):
                continue
            try:
                spec = importlib.util.spec_from_file_location(f"plugin_{path.stem}", path)
                if spec is None or spec.loader is None:
                    continue
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)  # type: ignore[attr-defined]
                if hasattr(module, "register") and callable(module.register):
                    self._call_register(module)
                    self._loaded.append(path.name)
                    # Metadaten einlesen
                    meta = dict(_DEFAULT_META)
                    raw = getattr(module, "metadata", None)
                    if isinstance(raw, dict):
                        for k in _DEFAULT_META:
                            if k in raw:
                                meta[k] = str(raw[k])
                    if not meta["name"]:
                        meta["name"] = path.stem
                    self._metadata[path.name] = meta
                    count += 1
            except Exception as exc:
                print(f"[PluginLoader] Fehler beim Laden von {path.name}: {exc}")
        return count

    def _call_register(self, module) -> None:
        """Ruft register(bus, api) oder register(bus) auf (Rückwärtskompatibilität)."""
        fn = module.register
        try:
            sig = inspect.signature(fn)
            n_params = len(sig.parameters)
        except (ValueError, TypeError):
            n_params = 1
        if n_params >= 2 and self._api is not None:
            fn(self._bus, self._api)
        else:
            fn(self._bus)

    @property
    def loaded_plugins(self) -> List[str]:
        return list(self._loaded)

    def get_metadata(self, filename: str) -> Dict[str, str]:
        """Gibt die Metadaten eines geladenen Plugins zurück."""
        return dict(self._metadata.get(filename, _DEFAULT_META))

    def all_metadata(self) -> Dict[str, Dict[str, str]]:
        """Gibt Metadaten aller geladenen Plugins zurück."""
        return {k: dict(v) for k, v in self._metadata.items()}
