"""CompanionServer – HTTP-Companion-Dienst für Mobile Apps (v5.1.0).

Stellt einen lokalen HTTP-Server bereit, der eine vereinfachte JSON-API für
externe Companion-Apps (iOS, Android, Web) anbietet. Läuft als Thread neben
dem Haupt-Event-Loop.

Endpunkte:
    GET  /status        – Verbindungsstatus + aktiver Server
    GET  /channels      – Kanalliste der aktiven Session
    GET  /users         – Nutzerliste der aktiven Session
    POST /say           – Nachricht in den aktiven Kanal senden
                          Body: {"text": "...", "channel_id": <int>}
    GET  /events        – SSE-Stream der letzten Bus-Events (Companion-Subset)
    POST /push_token    – Push-Token registrieren (iOS/Android)
                          Body: {"token": "...", "platform": "ios"|"android"}

Authentifizierung: identisch mit HttpApiServer (X-Companion-Token Header).
"""
from __future__ import annotations

import json
import queue
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Callable, Dict, List, Optional

_DEFAULT_PORT = 19880
_EVENT_QUEUE_MAX = 200


class CompanionServer:
    """Lokaler HTTP-Companion-Server."""

    def __init__(
        self,
        get_status_fn: Callable[[], Dict],
        get_channels_fn: Callable[[], List[Dict]],
        get_users_fn: Callable[[], List[Dict]],
        send_message_fn: Callable[[str, int], bool],
        token: Optional[str] = None,
        port: int = _DEFAULT_PORT,
    ) -> None:
        self._get_status = get_status_fn
        self._get_channels = get_channels_fn
        self._get_users = get_users_fn
        self._send_message = send_message_fn
        self._token = token
        self._port = port
        self._server: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._event_queue: queue.Queue = queue.Queue(maxsize=_EVENT_QUEUE_MAX)
        self._push_tokens: List[Dict] = []  # {token, platform, registered_at}

    def push_event(self, event_type: str, data: Dict) -> None:
        """Stellt ein Bus-Event in die SSE-Queue (non-blocking, verwirft bei voll)."""
        try:
            self._event_queue.put_nowait({"type": event_type, "data": data, "ts": time.time()})
        except queue.Full:
            pass

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        server = self
        port = self._port

        class _Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass  # Kein stdout-Logging

            def _check_auth(self) -> bool:
                if not server._token:
                    return True
                hdr = self.headers.get("X-Companion-Token", "")
                return hdr == server._token

            def _send_json(self, data, code: int = 200):
                body = json.dumps(data, ensure_ascii=False).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _send_unauth(self):
                self._send_json({"error": "Unauthorized"}, 401)

            def do_GET(self):
                path = self.path.split("?")[0]
                if not self._check_auth():
                    self._send_unauth()
                    return
                if path == "/status":
                    self._send_json(server._get_status())
                elif path == "/channels":
                    self._send_json(server._get_channels())
                elif path == "/users":
                    self._send_json(server._get_users())
                elif path == "/events":
                    self._serve_sse()
                else:
                    self._send_json({"error": "Not Found"}, 404)

            def do_POST(self):
                path = self.path.split("?")[0]
                if not self._check_auth():
                    self._send_unauth()
                    return
                length = int(self.headers.get("Content-Length", 0))
                try:
                    body = json.loads(self.rfile.read(length).decode("utf-8"))
                except Exception:
                    self._send_json({"error": "Invalid JSON"}, 400)
                    return
                if path == "/say":
                    text = str(body.get("text", ""))
                    ch_id = int(body.get("channel_id", 0))
                    if not text:
                        self._send_json({"error": "text is required"}, 400)
                        return
                    ok = server._send_message(text, ch_id)
                    self._send_json({"ok": ok})
                elif path == "/push_token":
                    tok = str(body.get("token", ""))
                    platform = str(body.get("platform", ""))
                    if tok:
                        server._push_tokens.append({
                            "token": tok,
                            "platform": platform,
                            "registered_at": time.time(),
                        })
                    self._send_json({"ok": bool(tok)})
                else:
                    self._send_json({"error": "Not Found"}, 404)

            def _serve_sse(self):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.end_headers()
                try:
                    while True:
                        try:
                            event = server._event_queue.get(timeout=15)
                            data = json.dumps(event, ensure_ascii=False)
                            self.wfile.write(
                                f"event: {event['type']}\ndata: {data}\n\n".encode("utf-8")
                            )
                            self.wfile.flush()
                        except queue.Empty:
                            self.wfile.write(b": keepalive\n\n")
                            self.wfile.flush()
                except Exception:
                    pass

        self._server = HTTPServer(("127.0.0.1", port), _Handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="CompanionServer",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        if self._server:
            self._server.shutdown()
            self._server = None

    @property
    def port(self) -> int:
        return self._port

    @property
    def push_tokens(self) -> List[Dict]:
        return list(self._push_tokens)
