"""MacroManager – Makro-Engine (v7.0).

Makro-Format in AppSettings.macros:
  [{"name": "Begrüßung", "hotkey": 0, "actions": [
      {"type": "speak",          "value": "Hallo {user}!"},
      {"type": "send_message",   "value": "Willkommen im Kanal, {user}!"},
      {"type": "send_broadcast", "value": "Broadcast-Text"},
      {"type": "send_private",   "value": "Nachricht an letzten Sender"},
      {"type": "play_sound",     "value": "/pfad/zur/datei.wav"},
      {"type": "channel",        "value": "Kanalname"},
      {"type": "ptt_on"},
      {"type": "ptt_off"},
      {"type": "mute_toggle"},
      {"type": "status",         "value": "Kurz weg"},
      {"type": "wait",           "value": "2"},
      {"type": "reply_last_private", "value": "Bin gleich zurück!"},
  ]}]

Template-Variablen (in Werten):  {user}  {channel}  {message}  {time}

Trigger-Format in AppSettings.macro_triggers:
  [{"event": "user_join",   "filter": "", "use_regex": false, "macro": "Begrüßung"}]

Ereignisse: user_join, user_leave, chat_message, channel_join, connected, disconnected

Zeitplan-Format in AppSettings.scheduled_macros:
  [{"time": "08:00", "macro": "Morgengruß"}]
"""
from __future__ import annotations

import datetime as _dt
import re as _re
import threading
import time
from typing import TYPE_CHECKING, Dict, List, Optional

if TYPE_CHECKING:
    from app import MainFrame


# Menschenlesbare Label für Aktions-Typen
ACTION_TYPES: List[tuple] = [
    ("speak",               "Ansagen (TTS)"),
    ("send_message",        "Kanalnachricht senden"),
    ("send_private",        "Privatnachricht (letzter Sender)"),
    ("send_broadcast",      "Broadcast senden"),
    ("play_sound",          "Sound abspielen (Dateipfad)"),
    ("channel",             "Kanal beitreten"),
    ("status",              "Status setzen"),
    ("wait",                "Warten (Sekunden)"),
    ("ptt_on",              "PTT einschalten"),
    ("ptt_off",             "PTT ausschalten"),
    ("mute_toggle",         "Stummschaltung umschalten"),
    ("reply_last_private",  "Letzte Privatnachricht beantworten"),
]

# Menschenlesbare Label für Trigger-Ereignisse
TRIGGER_EVENTS: List[tuple] = [
    ("user_join",    "Benutzer tritt bei"),
    ("user_leave",   "Benutzer verlässt Kanal"),
    ("chat_message", "Chat-Nachricht empfangen"),
    ("channel_join", "Kanal beigetreten"),
    ("connected",    "Mit Server verbunden"),
    ("disconnected", "Vom Server getrennt"),
]


class MacroManager:
    """Führt konfigurierbare Makros per Hotkey, Trigger und Zeitplan aus."""

    def __init__(self, frame: "MainFrame") -> None:
        self._frame = frame

    # ------------------------------------------------------------------
    # Makro-Zugriff
    # ------------------------------------------------------------------

    def get_macros(self) -> List[Dict]:
        return list(self._frame.settings_store.settings.macros or [])

    def find_by_hotkey(self, keycode: int) -> Optional[Dict]:
        if not keycode:
            return None
        for macro in self.get_macros():
            if int(macro.get("hotkey", 0) or 0) == keycode:
                return macro
        return None

    def _find_by_name(self, name: str) -> Optional[Dict]:
        for m in self.get_macros():
            if m.get("name", "") == name:
                return m
        return None

    # ------------------------------------------------------------------
    # Ausführung
    # ------------------------------------------------------------------

    def execute(self, macro: Dict, **ctx) -> None:
        """Führt ein Makro in einem Hintergrundthread aus."""
        threading.Thread(
            target=self._run,
            args=(macro,),
            kwargs={"ctx": ctx},
            daemon=True,
            name=f"Macro:{macro.get('name', '?')}",
        ).start()

    def _expand(self, text: str, ctx: Dict) -> str:
        """Ersetzt {user}, {channel}, {message}, {time} in Text."""
        ctx.setdefault("time", _dt.datetime.now().strftime("%H:%M"))
        for key, val in ctx.items():
            text = text.replace(f"{{{key}}}", str(val or ""))
        return text

    def _run(self, macro: Dict, ctx: Dict = None) -> None:
        import wx
        if ctx is None:
            ctx = {}
        name = macro.get("name", "Makro")
        for action in macro.get("actions", []):
            atype = action.get("type", "")
            raw = action.get("value", "") or ""
            value = self._expand(raw, dict(ctx))
            try:
                if atype == "speak":
                    wx.CallAfter(self._frame.tts.speak, value, kind="system")
                elif atype == "send_message":
                    wx.CallAfter(self._send_channel_message, value)
                elif atype == "send_private":
                    wx.CallAfter(self._reply_last_private, value)
                elif atype == "send_broadcast":
                    wx.CallAfter(self._send_broadcast, value)
                elif atype == "play_sound":
                    wx.CallAfter(self._play_sound, value)
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
                elif atype == "reply_last_private":
                    wx.CallAfter(self._reply_last_private, value)
            except Exception as exc:
                print(f"[Macro:{name}] Aktion {atype!r} fehlgeschlagen: {exc}")

    # ------------------------------------------------------------------
    # Aktions-Hilfsmethoden
    # ------------------------------------------------------------------

    def _send_channel_message(self, text: str) -> None:
        try:
            if not text or not self._frame.client.is_connected():
                return
            ch_id = self._frame.client.get_my_channel_id()
            if ch_id:
                self._frame.client.send_channel_message(int(ch_id), text)
        except Exception as exc:
            print(f"[Macro] Kanalnachricht fehlgeschlagen: {exc}")

    def _send_broadcast(self, text: str) -> None:
        try:
            if text and self._frame.client.is_connected():
                self._frame.client.send_broadcast_message(text)
        except Exception as exc:
            print(f"[Macro] Broadcast fehlgeschlagen: {exc}")

    def _play_sound(self, path: str) -> None:
        try:
            if path:
                self._frame.sound_manager.play("macro", path)
        except Exception as exc:
            print(f"[Macro] Sound fehlgeschlagen: {exc}")

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

    def _reply_last_private(self, message: str) -> None:
        uid = getattr(self._frame, "_last_private_sender_id", None)
        if not uid:
            return
        try:
            if message and self._frame.client.is_connected():
                self._frame.client.send_user_message(uid, message)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Trigger-System
    # ------------------------------------------------------------------

    def fire_event(self, event_name: str, **kwargs) -> None:
        """Prüft alle Trigger-Regeln und führt passende Makros aus."""
        triggers = list(self._frame.settings_store.settings.macro_triggers or [])
        for rule in triggers:
            if not isinstance(rule, dict):
                continue
            if rule.get("event") != event_name:
                continue

            filter_val = str(rule.get("filter", "") or "").strip()
            if filter_val:
                # chat_message: Filter prüft Nachrichteninhalt
                if event_name == "chat_message":
                    match_val = str(kwargs.get("text", "") or kwargs.get("message", ""))
                else:
                    match_val = str(
                        kwargs.get("user", "")
                        or kwargs.get("from_user", "")
                        or kwargs.get("channel_name", "")
                        or kwargs.get("channel", "")
                    )

                if rule.get("use_regex"):
                    try:
                        if not _re.search(filter_val, match_val, _re.IGNORECASE):
                            continue
                    except _re.error:
                        if filter_val.lower() not in match_val.lower():
                            continue
                else:
                    if filter_val.lower() not in match_val.lower():
                        continue

            macro_name = str(rule.get("macro", "") or "")
            macro = self._find_by_name(macro_name)
            if macro:
                self.execute(macro, **kwargs)

    # ------------------------------------------------------------------
    # Zeitplan-System
    # ------------------------------------------------------------------

    def check_scheduled(self) -> None:
        """Wird jede Minute aufgerufen; führt fällige Makros aus."""
        now = _dt.datetime.now().strftime("%H:%M")
        scheduled = list(self._frame.settings_store.settings.scheduled_macros or [])
        for entry in scheduled:
            if not isinstance(entry, dict):
                continue
            if entry.get("time") != now:
                continue
            last_fired = entry.get("_last_fired", "")
            if last_fired == now:
                continue
            entry["_last_fired"] = now
            macro = self._find_by_name(str(entry.get("macro", "") or ""))
            if macro:
                self.execute(macro)
