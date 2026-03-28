"""WebhookManager – HTTP-POST bei App-Ereignissen (v2.7.0).

Sendet JSON-Payloads an eine konfigurierte URL wenn bestimmte Ereignisse eintreten.

Unterstützte Ereignisse (webhook_events-Liste in AppSettings):
  private_msg, channel_msg, user_join, user_leave, connect, disconnect, recording_start
"""
from __future__ import annotations

import json
import threading
import time
from typing import TYPE_CHECKING, Dict, Any

if TYPE_CHECKING:
    from app import MainFrame


class WebhookManager:
    """Sendet Ereignisse als HTTP-POST an eine externe URL."""

    def __init__(self, frame: "MainFrame") -> None:
        self._frame = frame

    def emit(self, event: str, payload: Dict[str, Any]) -> None:
        s = self._frame.settings_store.settings
        url = str(getattr(s, "webhook_url", "") or "").strip()
        if not url:
            return
        allowed = list(getattr(s, "webhook_events", []) or [])
        if allowed and event not in allowed:
            return
        data = {
            "event": event,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "app": "TeamTalk VO Client",
            **payload,
        }
        threading.Thread(target=self._post, args=(url, data), daemon=True).start()

    def _post(self, url: str, data: Dict) -> None:
        try:
            import urllib.request
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=body,
                headers={"Content-Type": "application/json", "User-Agent": "TeamTalkVOClient/2.7"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5) as resp:  # noqa: S310
                pass
        except Exception as exc:
            print(f"[Webhook] POST fehlgeschlagen ({url}): {exc}")
