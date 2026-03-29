"""EqPresetsManager – Equalizer-Voreinstellungen Import/Export (v4.7.0).

Presets werden als JSON gespeichert und geladen.
Schema je Preset::

    {
        "name": "Mein Preset",
        "mic_gain_pct": 60,
        "out_volume_pct": 100
    }
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional


class EqPresetsManager:
    """Verwaltet benutzerdefinierte EQ-Voreinstellungen."""

    _BUILTIN_PRESETS = [
        {"name": "Standard",       "mic_gain_pct": 50, "out_volume_pct": 100},
        {"name": "Sprache (klar)", "mic_gain_pct": 65, "out_volume_pct": 90},
        {"name": "Musik",          "mic_gain_pct": 45, "out_volume_pct": 110},
        {"name": "Laut",           "mic_gain_pct": 70, "out_volume_pct": 120},
        {"name": "Leise",          "mic_gain_pct": 35, "out_volume_pct": 70},
        {"name": "Stille",         "mic_gain_pct": 0,  "out_volume_pct": 0},
    ]

    def __init__(self, app_dir: Path) -> None:
        self._path = app_dir / "eq_presets.json"
        self._user_presets: List[Dict] = []
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            self._user_presets = [
                {"name": str(p["name"]),
                 "mic_gain_pct": int(p.get("mic_gain_pct", 50)),
                 "out_volume_pct": int(p.get("out_volume_pct", 100))}
                for p in data
                if isinstance(p, dict) and "name" in p
            ]
        except Exception:
            self._user_presets = []

    def _save(self) -> None:
        try:
            self._path.write_text(
                json.dumps(self._user_presets, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    @property
    def all_presets(self) -> List[Dict]:
        """Gibt alle Presets (builtin + benutzerdefiniert) zurück."""
        return list(self._BUILTIN_PRESETS) + list(self._user_presets)

    def get(self, name: str) -> Optional[Dict]:
        """Gibt ein Preset nach Name zurück (builtin zuerst)."""
        for p in self.all_presets:
            if p["name"] == name:
                return dict(p)
        return None

    def add_or_update(self, name: str, mic_gain_pct: int, out_volume_pct: int) -> None:
        """Fügt ein Benutzerpresert hinzu oder aktualisiert es."""
        for p in self._user_presets:
            if p["name"] == name:
                p["mic_gain_pct"] = mic_gain_pct
                p["out_volume_pct"] = out_volume_pct
                self._save()
                return
        self._user_presets.append({
            "name": name,
            "mic_gain_pct": mic_gain_pct,
            "out_volume_pct": out_volume_pct,
        })
        self._save()

    def remove(self, name: str) -> bool:
        """Entfernt ein Benutzerpreset. Gibt True zurück wenn gefunden."""
        for i, p in enumerate(self._user_presets):
            if p["name"] == name:
                self._user_presets.pop(i)
                self._save()
                return True
        return False

    def export_to_file(self, path: Path) -> None:
        """Exportiert alle Presets (builtin + benutzerdefiniert) als JSON."""
        data = {
            "app": "TeamTalk VO Client",
            "version": "4.7.0",
            "presets": self.all_presets,
        }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def import_from_file(self, path: Path) -> int:
        """Importiert Presets aus einer JSON-Datei. Gibt Anzahl importierter Presets zurück."""
        data = json.loads(path.read_text(encoding="utf-8"))
        presets = data if isinstance(data, list) else data.get("presets", [])
        count = 0
        builtin_names = {p["name"] for p in self._BUILTIN_PRESETS}
        for p in presets:
            if not isinstance(p, dict) or "name" not in p:
                continue
            name = str(p["name"])
            if name in builtin_names:
                continue  # Builtin-Presets nicht überschreiben
            self.add_or_update(
                name,
                int(p.get("mic_gain_pct", 50)),
                int(p.get("out_volume_pct", 100)),
            )
            count += 1
        return count
