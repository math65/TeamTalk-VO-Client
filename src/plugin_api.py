"""PluginAPI – öffentliche Schnittstelle für Plugins (ab v1.10.1).

Plugins erhalten eine Instanz dieser Klasse als zweiten Parameter in
ihrer `register(bus, api)`-Funktion und können darüber auf App-Funktionen
zugreifen, ohne direkt auf `MainFrame` zugreifen zu müssen.
"""
from __future__ import annotations

import threading
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from app import MainFrame
    from plugin_config import PluginConfig


class PluginAPI:
    """Thin wrapper around MainFrame für Plugin-Zugriff."""

    def __init__(self, frame: "MainFrame") -> None:
        self._frame = frame

    # ------------------------------------------------------------------
    # TTS / Ausgabe
    # ------------------------------------------------------------------

    def speak(self, text: str, kind: str = "system") -> None:
        """Spricht einen Text via TTS aus."""
        import wx
        wx.CallAfter(self._frame.tts.speak, text, kind=kind)

    # ------------------------------------------------------------------
    # Verbindungsstatus
    # ------------------------------------------------------------------

    def is_connected(self) -> bool:
        """Gibt True zurück wenn gerade eine Verbindung zum Server besteht."""
        try:
            return bool(self._frame.client.is_connected())
        except Exception:
            return False

    def get_server_name(self) -> str:
        """Gibt den Server-Namen zurück (leer wenn nicht verbunden)."""
        try:
            profile = getattr(self._frame, "_current_profile", None)
            if profile and hasattr(profile, "name"):
                return str(profile.name)
            return ""
        except Exception:
            return ""

    # ------------------------------------------------------------------
    # Nutzer & Kanal
    # ------------------------------------------------------------------

    def get_my_user_id(self) -> int:
        """Gibt die eigene User-ID zurück (0 wenn nicht verbunden)."""
        try:
            return int(self._frame.client.get_my_user_id() or 0)
        except Exception:
            return 0

    def get_my_channel_id(self) -> int:
        """Gibt die ID des eigenen aktuellen Kanals zurück (0 = kein Kanal)."""
        try:
            return int(self._frame.client.get_my_channel_id() or 0)
        except Exception:
            return 0

    def get_channel_users(self, channel_id: int) -> List[dict]:
        """Gibt eine Liste von Nutzern im Kanal zurück.

        Jeder Eintrag: ``{"id": int, "name": str, "is_admin": bool}``
        """
        result: List[dict] = []
        try:
            users = list(self._frame.client.get_channel_users(channel_id))
            for u in users:
                try:
                    name = self._frame.tt_str(u.szNickname) or self._frame.tt_str(u.szUsername) or ""
                    is_admin = bool(getattr(u, "uUserType", 0) & 2)
                    result.append({"id": int(u.nUserID), "name": name, "is_admin": is_admin})
                except Exception:
                    pass
        except Exception:
            pass
        return result

    # ------------------------------------------------------------------
    # Nachrichten senden
    # ------------------------------------------------------------------

    def send_channel_message(self, text: str, channel_id: int = 0) -> bool:
        """Sendet eine Nachricht in einen Kanal (default: eigener Kanal).

        Muss aus einem Hintergrundthread aufgerufen werden, nicht aus dem
        GUI-Thread (blockiert kurz für den SDK-Aufruf).
        """
        try:
            chan_id = channel_id or self.get_my_channel_id()
            if not chan_id:
                return False
            return bool(self._frame.client.send_channel_message(int(chan_id), text))
        except Exception:
            return False

    def send_private_message(self, user_id: int, text: str) -> bool:
        """Sendet eine Privatnachricht an einen Nutzer."""
        try:
            return bool(self._frame.client.send_private_message(int(user_id), text))
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Kanal beitreten
    # ------------------------------------------------------------------

    def join_channel(self, channel_id: int, password: str = "") -> None:
        """Wechselt in einen Kanal. Läuft im Hintergrund."""
        import wx
        wx.CallAfter(self._frame.join_channel, channel_id, password)

    # ------------------------------------------------------------------
    # Plugin-Konfiguration
    # ------------------------------------------------------------------

    def get_config(self, plugin_name: str) -> "PluginConfig":
        """Gibt einen persistenten Key-Value-Store für das Plugin zurück."""
        from plugin_config import PluginConfig
        return PluginConfig(plugin_name)
