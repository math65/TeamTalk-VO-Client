"""MuteScheduler – Zeitgesteuerte Stille (v2.3.0).

Deaktiviert den Mikrofoneingang in konfigurierten Zeitfenstern.
Schedule-Format: [{"start": "HH:MM", "end": "HH:MM", "label": "Mittagspause"}]
"""
from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING, List, Dict

if TYPE_CHECKING:
    from app import MainFrame


class MuteScheduler:
    """Hintergrundthread, der zur konfigurierten Uhrzeit das Mikrofon stummschaltet."""

    CHECK_INTERVAL = 30  # Sekunden zwischen Prüfungen

    def __init__(self, frame: "MainFrame") -> None:
        self._frame = frame
        self._running = False
        self._thread: threading.Thread | None = None
        self._muted_by_schedule = False

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="MuteScheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._muted_by_schedule:
            self._set_mute(False)

    def _loop(self) -> None:
        while self._running:
            try:
                self._check()
            except Exception as exc:
                print(f"[MuteScheduler] Fehler: {exc}")
            time.sleep(self.CHECK_INTERVAL)

    def _check(self) -> None:
        schedule: List[Dict] = self._frame.settings_store.settings.mute_schedule or []
        if not schedule:
            if self._muted_by_schedule:
                self._set_mute(False)
            return

        now = time.strftime("%H:%M")
        should_mute = any(self._in_window(now, r) for r in schedule)

        if should_mute and not self._muted_by_schedule:
            self._set_mute(True)
            label = next((r.get("label", "") for r in schedule if self._in_window(now, r)), "")
            import wx
            wx.CallAfter(self._frame.tts.speak,
                         f"Stummschaltung aktiv{': ' + label if label else ''}",
                         kind="system")
        elif not should_mute and self._muted_by_schedule:
            self._set_mute(False)
            import wx
            wx.CallAfter(self._frame.tts.speak, "Stummschaltung aufgehoben", kind="system")

    def _set_mute(self, mute: bool) -> None:
        self._muted_by_schedule = mute
        import wx
        try:
            wx.CallAfter(self._frame.client.set_sound_output_mute, mute)
        except Exception:
            pass

    @staticmethod
    def _in_window(now: str, rule: Dict) -> bool:
        start = rule.get("start", "")
        end = rule.get("end", "")
        if not start or not end:
            return False
        try:
            if start <= end:
                return start <= now < end
            else:
                return now >= start or now < end
        except Exception:
            return False
