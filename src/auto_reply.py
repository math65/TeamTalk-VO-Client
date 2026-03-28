"""AutoReplyManager – Automatische Antwort auf Privatnachrichten (v2.5.0).

Sendet eine konfigurierbare Antwort wenn:
  - auto_reply_enabled = True
  - Nutzer hat Abwesend-Status gesetzt
  - Privatnachricht empfangen
  - Gleicher Absender bekommt max. 1x pro Sitzung eine Antwort.
"""
from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING, Set

if TYPE_CHECKING:
    from app import MainFrame


class AutoReplyManager:
    """Schickt automatische Antworten auf Privatnachrichten."""

    COOLDOWN_SEC = 300  # 5 Minuten zwischen zwei Antworten an denselben Nutzer

    def __init__(self, frame: "MainFrame") -> None:
        self._frame = frame
        self._replied: dict[int, float] = {}  # user_id -> last_reply_ts
        self._lock = threading.Lock()

    def handle_private_message(self, from_id: int, from_user: str) -> None:
        """Aufrufen wenn eine Privatnachricht empfangen wurde."""
        s = self._frame.settings_store.settings
        if not getattr(s, "auto_reply_enabled", False):
            return
        # Nur antworten wenn Abwesend-Status aktiv
        if self._frame._status_mode != 1:  # 1 = Away
            return
        # Anti-Flood: max. alle 5 Minuten
        now = time.time()
        with self._lock:
            last = self._replied.get(from_id, 0)
            if now - last < self.COOLDOWN_SEC:
                return
            self._replied[from_id] = now

        msg = str(getattr(s, "auto_reply_message", "") or "Ich bin gerade nicht erreichbar.")
        threading.Thread(
            target=self._send,
            args=(from_id, msg),
            daemon=True,
        ).start()

    def _send(self, to_id: int, text: str) -> None:
        try:
            self._frame.client.send_private_message(to_id, text)
        except Exception as exc:
            print(f"[AutoReply] Senden fehlgeschlagen: {exc}")

    def reset(self) -> None:
        """Zurücksetzen bei Verbindungsaufbau."""
        with self._lock:
            self._replied.clear()
