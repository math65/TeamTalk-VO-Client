"""Sound-Manager: spielt Ereignis-Sounds wie im Original-TeamTalk-Client."""
from __future__ import annotations

import sys
import threading
from pathlib import Path
from typing import Optional

import wx
import wx.adv

# Pfad zum eingebetteten Sound-Pack (relativ zu dieser Datei bzw. _MEIPASS)
def _sounds_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "sounds"  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent / "sounds"


# Zuordnung: interner Ereignis-Schlüssel → Standard-Dateiname im Sound-Pack
DEFAULT_SOUNDS: dict[str, str] = {
    "user_join":        "newuser.wav",
    "user_leave":       "removeuser.wav",
    "server_disconnect":"serverlost.wav",
    "msg_private_rx":   "user_msg.wav",
    "msg_private_tx":   "user_msg_sent.wav",
    "msg_channel_rx":   "channel_msg.wav",
    "msg_channel_tx":   "channel_msg_sent.wav",
    "ptt_on":           "hotkey.wav",
    "channel_silent":   "voiceact_off.wav",
    "file_transfer":    "filetx_complete.wav",
    "video_session":    "videosession.wav",
    "desktop_session":  "desktopsession.wav",
    "question_mode":    "questionmode.wav",
    "desktop_access":   "desktopaccessreq.wav",
    "user_login":       "logged_on.wav",
    "user_logout":      "logged_off.wav",
}


class SoundManager:
    """Spielt Ereignis-Sounds asynchron ab.

    Priorität: benutzerdefinierter Pfad (aus Einstellungen) →
               eingebettetes Standard-Sound-Pack → kein Ton.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._enabled: bool = True

    # ------------------------------------------------------------------
    # Öffentliche Schnittstelle
    # ------------------------------------------------------------------

    def play(self, event_key: str, custom_path: Optional[str] = None) -> None:
        """Spielt den Sound für *event_key* asynchron ab."""
        if not self._enabled:
            return
        path = self._resolve(event_key, custom_path)
        if path:
            wx.CallAfter(self._play_file, path)

    def play_file(self, path: str) -> None:
        """Spielt eine beliebige WAV-Datei direkt ab (für den Test-Button)."""
        if path:
            wx.CallAfter(self._play_file, path)

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = bool(value)

    # ------------------------------------------------------------------
    # Interne Hilfsmethoden
    # ------------------------------------------------------------------

    def _resolve(self, event_key: str, custom_path: Optional[str]) -> Optional[str]:
        # 1. Benutzerdefinierter Pfad aus den Einstellungen
        if custom_path:
            p = Path(custom_path)
            if p.is_file():
                return str(p)

        # 2. Eingebettetes Standard-Sound-Pack
        filename = DEFAULT_SOUNDS.get(event_key)
        if filename:
            bundled = _sounds_dir() / filename
            if bundled.is_file():
                return str(bundled)

        return None

    @staticmethod
    def _play_file(path: str) -> None:
        try:
            sound = wx.adv.Sound(path)
            if sound.IsOk():
                sound.Play(wx.adv.SOUND_ASYNC)
        except Exception:
            pass
