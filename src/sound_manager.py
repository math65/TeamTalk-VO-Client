"""Sound-Manager: spielt Ereignis-Sounds wie im Original-TeamTalk-Client."""
from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path
from typing import Optional

# Pfad zum eingebetteten Sound-Pack (relativ zu dieser Datei bzw. _MEIPASS)
def _sounds_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "sounds"  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent / "sounds"


# Zuordnung: interner Ereignis-Schlüssel → Standard-Dateiname im Sound-Pack
DEFAULT_SOUNDS: dict[str, str] = {
    "user_join":         "newuser.wav",
    "user_leave":        "removeuser.wav",
    "server_connect":    "logged_on.wav",
    "server_disconnect": "serverlost.wav",
    "channel_join":      "newuser.wav",
    "msg_private_rx":    "user_msg.wav",
    "msg_private_tx":    "user_msg_sent.wav",
    "msg_channel_rx":    "channel_msg.wav",
    "msg_channel_tx":    "channel_msg_sent.wav",
    "ptt_on":            "hotkey.wav",
    "channel_active":    "voiceact_on.wav",
    "channel_silent":    "voiceact_off.wav",
    "file_transfer":     "filetx_complete.wav",
    "video_session":     "videosession.wav",
    "desktop_session":   "desktopsession.wav",
    "question_mode":     "questionmode.wav",
    "desktop_access":    "desktopaccessreq.wav",
    "user_login":        "logged_on.wav",
    "user_logout":       "logged_off.wav",
}

# Lesefreundliche Bezeichnungen für die UI
SOUND_EVENT_LABELS: dict[str, str] = {
    "user_join":         "Nutzer betritt Kanal",
    "user_leave":        "Nutzer verlässt Kanal",
    "server_connect":    "Verbindung hergestellt",
    "server_disconnect": "Verbindung getrennt",
    "channel_join":      "Kanal beigetreten",
    "msg_private_rx":    "Private Nachricht empfangen",
    "msg_private_tx":    "Private Nachricht gesendet",
    "msg_channel_rx":    "Kanalnachricht empfangen",
    "msg_channel_tx":    "Kanalnachricht gesendet",
    "ptt_on":            "PTT aktiviert",
    "channel_active":    "Kanal aktiv (Sprache)",
    "channel_silent":    "Kanal still",
    "file_transfer":     "Dateiübertragung",
    "video_session":     "Video-Session",
    "desktop_session":   "Desktop-Session",
    "question_mode":     "Frage-Modus",
    "desktop_access":    "Desktop-Zugriffsanfrage",
    "user_login":        "Nutzer eingeloggt",
    "user_logout":       "Nutzer ausgeloggt",
}


class SoundManager:
    """Spielt Ereignis-Sounds asynchron ab.

    Priorität:
      1. Benutzerdefinierter Einzelpfad (sound_events[key])
      2. Benutzerdefinierter Sound-Pack-Ordner (pack_dir / default_filename)
      3. Eingebettetes Standard-Sound-Pack
    """

    def __init__(self) -> None:
        self._enabled: bool = True
        self._pack_dir: Optional[Path] = None

    # ------------------------------------------------------------------
    # Öffentliche Schnittstelle
    # ------------------------------------------------------------------

    def play(self, event_key: str, custom_path: Optional[str] = None) -> None:
        """Spielt den Sound für *event_key* asynchron ab."""
        if not self._enabled:
            return
        path = self._resolve(event_key, custom_path)
        if path:
            self._play_async(path)

    def set_pack_dir(self, directory: Optional[str]) -> None:
        """Setzt den benutzerdefinierten Sound-Pack-Ordner."""
        if directory:
            p = Path(directory)
            self._pack_dir = p if p.is_dir() else None
        else:
            self._pack_dir = None

    @property
    def pack_dir(self) -> Optional[str]:
        return str(self._pack_dir) if self._pack_dir else None

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
        # 1. Benutzerdefinierter Einzelpfad aus den Einstellungen
        if custom_path:
            p = Path(custom_path)
            if p.is_file():
                return str(p)

        filename = DEFAULT_SOUNDS.get(event_key)
        if filename:
            # 2. Benutzerdefinierter Sound-Pack-Ordner
            if self._pack_dir:
                pack_file = self._pack_dir / filename
                if pack_file.is_file():
                    return str(pack_file)

            # 3. Eingebettetes Standard-Sound-Pack
            bundled = _sounds_dir() / filename
            if bundled.is_file():
                return str(bundled)

        return None

    @staticmethod
    def _play_async(path: str) -> None:
        """Spielt eine WAV-Datei in einem Hintergrund-Thread ab."""
        def _run():
            try:
                if sys.platform == "darwin":
                    proc = subprocess.Popen(
                        ["afplay", path],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    proc.wait()
                elif sys.platform == "win32":
                    import winsound  # noqa: PLC0415
                    winsound.PlaySound(path, winsound.SND_FILENAME)
                else:
                    for player in ("paplay", "aplay"):
                        try:
                            proc = subprocess.Popen(
                                [player, path],
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                            )
                            proc.wait()
                            break
                        except FileNotFoundError:
                            continue
            except Exception:
                pass

        threading.Thread(target=_run, daemon=True).start()
