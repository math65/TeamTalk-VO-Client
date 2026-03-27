"""Geplante Aufnahmen – Datenmodell und Manager."""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional


@dataclass
class ScheduledRecording:
    id: str
    label: str
    weekdays: List[int]   # 0=Mo … 6=So; leer = täglich
    start_time: str        # "HH:MM"
    duration_min: int
    enabled: bool = True

    @staticmethod
    def new(label: str, weekdays: List[int], start_time: str, duration_min: int) -> "ScheduledRecording":
        return ScheduledRecording(
            id=str(uuid.uuid4()),
            label=label,
            weekdays=weekdays,
            start_time=start_time,
            duration_min=duration_min,
            enabled=True,
        )


_WEEKDAY_NAMES = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]


def format_weekdays(weekdays: List[int]) -> str:
    if not weekdays:
        return "täglich"
    return ", ".join(_WEEKDAY_NAMES[d] for d in sorted(weekdays) if 0 <= d <= 6)


class ScheduledRecordingManager:
    def __init__(self, data_dir: Path) -> None:
        self._path = data_dir / "scheduled_recordings.json"
        self._items: List[ScheduledRecording] = []
        self._fired: dict = {}  # id -> last fired minute string "YYYY-MM-DD HH:MM"
        self.load()

    def load(self) -> None:
        if not self._path.exists():
            self._items = []
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            items = []
            for d in data:
                try:
                    items.append(ScheduledRecording(
                        id=str(d.get("id", uuid.uuid4())),
                        label=str(d.get("label", "")),
                        weekdays=[int(x) for x in d.get("weekdays", [])],
                        start_time=str(d.get("start_time", "00:00")),
                        duration_min=int(d.get("duration_min", 60)),
                        enabled=bool(d.get("enabled", True)),
                    ))
                except Exception:
                    continue
            self._items = items
        except Exception:
            self._items = []

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps([asdict(r) for r in self._items], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def items(self) -> List[ScheduledRecording]:
        return list(self._items)

    def add(self, rec: ScheduledRecording) -> None:
        self._items.append(rec)
        self.save()

    def update(self, idx: int, rec: ScheduledRecording) -> None:
        self._items[idx] = rec
        self.save()

    def remove(self, idx: int) -> None:
        self._items.pop(idx)
        self.save()

    def toggle_enabled(self, idx: int) -> None:
        self._items[idx].enabled = not self._items[idx].enabled
        self.save()

    def check_due(self) -> Optional[ScheduledRecording]:
        """Gibt eine fällige Aufnahme zurück (max. einmal pro Minute)."""
        now = datetime.now()
        minute_key = now.strftime("%Y-%m-%d %H:%M")
        current_time = now.strftime("%H:%M")
        current_weekday = now.weekday()  # 0=Mo

        for rec in self._items:
            if not rec.enabled:
                continue
            if rec.start_time != current_time:
                continue
            if rec.weekdays and current_weekday not in rec.weekdays:
                continue
            # Nicht zweimal in derselben Minute feuern
            if self._fired.get(rec.id) == minute_key:
                continue
            self._fired[rec.id] = minute_key
            return rec
        return None

    def display_label(self, rec: ScheduledRecording) -> str:
        days = format_weekdays(rec.weekdays)
        state = "" if rec.enabled else " [inaktiv]"
        return f"{rec.label}, {days}, {rec.start_time}, {rec.duration_min} min{state}"
