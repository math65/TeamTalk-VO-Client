"""MacroManager – Makros (v2.3.0).

Makro-Format in AppSettings.macros:
  [{"name": "Begrüßung", "hotkey": 123, "actions": [
      {"type": "speak", "value": "Hallo zusammen!"},
      {"type": "channel", "value": "Allgemein"},
      {"type": "ptt_on"},
      {"type": "ptt_off"},
      {"type": "mute_toggle"},
      {"type": "status", "value": "Kurz weg"},
  ]}]
"""
from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING, Dict, List, Optional

if TYPE_CHECKING:
    from app import MainFrame


class MacroManager:
    """Führt konfigurierbare Makros per Hotkey aus."""

    def __init__(self, frame: "MainFrame") -> None:
        self._frame = frame

    def get_macros(self) -> List[Dict]:
        return list(self._frame.settings_store.settings.macros or [])

    def find_by_hotkey(self, keycode: int) -> Optional[Dict]:
        if not keycode:
            return None
        for macro in self.get_macros():
            if int(macro.get("hotkey", 0) or 0) == keycode:
                return macro
        return None

    def execute(self, macro: Dict) -> None:
        """Führt ein Makro in einem Hintergrundthread aus."""
        threading.Thread(
            target=self._run,
            args=(macro,),
            daemon=True,
            name=f"Macro:{macro.get('name', '?')}",
        ).start()

    def _run(self, macro: Dict) -> None:
        import wx
        name = macro.get("name", "Makro")
        for action in macro.get("actions", []):
            atype = action.get("type", "")
            value = action.get("value", "")
            try:
                if atype == "speak":
                    wx.CallAfter(self._frame.tts.speak, value, kind="system")
                elif atype == "channel":
                    wx.CallAfter(self._join_channel_by_name, value)
                elif atype == "ptt_on":
                    wx.CallAfter(self._ptt, True)
                elif atype == "ptt_off":
                    wx.CallAfter(self._ptt, False)
                elif atype == "mute_toggle":
                    wx.CallAfter(self._mute_toggle)
                elif atype == "status":
                    wx.CallAfter(self._frame.client.change_status, 0, value)
                elif atype == "wait":
                    time.sleep(max(0.0, float(value or 0)))
            except Exception as exc:
                print(f"[Macro:{name}] Aktion {atype!r} fehlgeschlagen: {exc}")

    def _join_channel_by_name(self, name: str) -> None:
        try:
            channels = list(self._frame.client.get_server_channels() or [])
            name_l = name.lower()
            for ch in channels:
                ch_name = (self._frame.tt_str(getattr(ch, "szName", "")) or "").lower()
                if ch_name == name_l or name_l in ch_name:
                    self._frame.join_channel(int(getattr(ch, "nChannelID", 0)))
                    return
        except Exception as exc:
            print(f"[Macro] Kanal-Join fehlgeschlagen: {exc}")

    def _ptt(self, active: bool) -> None:
        try:
            self._frame.client.enable_voice_transmission(active)
        except Exception:
            pass

    def _mute_toggle(self) -> None:
        try:
            new_val = not self._frame._mute_all
            self._frame._mute_all = new_val
            self._frame.client.set_sound_output_mute(new_val)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # v3.5.0 – Trigger-System
    # ------------------------------------------------------------------

    def fire_event(self, event_name: str, **kwargs) -> None:
        """Prüft alle Trigger-Regeln und führt passende Makros aus."""
        triggers = list(
            (self._frame.settings_store.settings.macro_triggers or [])
        )
        for rule in triggers:
            if not isinstance(rule, dict):
                continue
            if rule.get("event") != event_name:
                continue
            # Optional filter: user name / channel name
            filter_val = str(rule.get("filter", "") or "").strip().lower()
            if filter_val:
                match_val = str(
                    kwargs.get("user", "")
                    or kwargs.get("from_user", "")
                    or kwargs.get("channel", "")
                ).lower()
                if filter_val not in match_val:
                    continue
            macro_name = str(rule.get("macro", "") or "")
            macro = self._find_by_name(macro_name)
            if macro:
                self.execute(macro)

    def _find_by_name(self, name: str) -> Optional[Dict]:
        for m in self.get_macros():
            if m.get("name", "") == name:
                return m
        return None

    # ------------------------------------------------------------------
    # v3.5.0 – Geplante Makros
    # ------------------------------------------------------------------

    def check_scheduled(self) -> None:
        """Wird periodisch aufgerufen; führt fällige Makros aus."""
        import datetime as _dt
        now = _dt.datetime.now().strftime("%H:%M")
        scheduled = list(
            (self._frame.settings_store.settings.scheduled_macros or [])
        )
        for entry in scheduled:
            if not isinstance(entry, dict):
                continue
            if entry.get("time") != now:
                continue
            # Avoid double-firing within the same minute
            last_fired = entry.get("_last_fired", "")
            if last_fired == now:
                continue
            entry["_last_fired"] = now
            macro_name = str(entry.get("macro", "") or "")
            macro = self._find_by_name(macro_name)
            if macro:
                self.execute(macro)
