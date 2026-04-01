"""WebhookManager – HTTP-POST bei App-Ereignissen (v4.3.0).

Sendet JSON-Payloads an eine konfigurierte URL wenn bestimmte Ereignisse eintreten.

Unterstützte Ereignisse (webhook_events-Liste in AppSettings):
  private_msg, channel_msg, user_join, user_leave, connect, disconnect, recording_start

v4.3.0 – Retry-Logik mit exponentiellem Backoff:
  3 Versuche: 1s, 2s, 4s Pause zwischen Versuchen.
"""
from __future__ import annotations

import json
import threading
import time
from typing import TYPE_CHECKING, Dict, Any, Optional

if TYPE_CHECKING:
    from app import MainFrame

_MAX_RETRIES = 3
_BASE_DELAY = 1.0  # Sekunden


class WebhookManager:
    """Sendet Ereignisse als HTTP-POST an eine externe URL."""

    def __init__(self, frame: "MainFrame") -> None:
        self._frame = frame
        # v4.3.0 – Statistiken
        self._sent_total: int = 0
        self._failed_total: int = 0

    def emit(self, event: str, payload: Dict[str, Any]) -> None:
        s = self._frame.settings_store.settings
        url = str(getattr(s, "webhook_url", "") or "").strip()
        if not url:
            return
        if not (url.startswith("http://") or url.startswith("https://")):
            print(f"[Webhook] Ungültige URL (nur http/https erlaubt): {url}")
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
        threading.Thread(
            target=self._post_with_retry,
            args=(url, data),
            daemon=True,
            name=f"Webhook-{event}",
        ).start()

    def _post_with_retry(self, url: str, data: Dict) -> None:
        """v4.3.0 – Sendet mit exponentiellem Backoff (max 3 Versuche)."""
        import urllib.request
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        last_exc: Optional[Exception] = None
        for attempt in range(_MAX_RETRIES):
            try:
                req = urllib.request.Request(
                    url,
                    data=body,
                    headers={
                        "Content-Type": "application/json",
                        "User-Agent": "TeamTalkVOClient/6.1.6",
                    },
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=5) as resp:  # noqa: S310
                    _ = resp.read()
                self._sent_total += 1
                return
            except Exception as exc:
                last_exc = exc
                if attempt < _MAX_RETRIES - 1:
                    delay = _BASE_DELAY * (2 ** attempt)
                    print(
                        f"[Webhook] Versuch {attempt + 1}/{_MAX_RETRIES} fehlgeschlagen "
                        f"({url}): {exc}  – Retry in {delay:.0f}s"
                    )
                    time.sleep(delay)
        self._failed_total += 1
        print(f"[Webhook] Alle {_MAX_RETRIES} Versuche fehlgeschlagen ({url}): {last_exc}")

    @property
    def sent_total(self) -> int:
        """Anzahl erfolgreich gesendeter Webhooks."""
        return self._sent_total

    @property
    def failed_total(self) -> int:
        """Anzahl endgültig fehlgeschlagener Webhooks."""
        return self._failed_total
