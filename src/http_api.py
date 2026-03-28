"""HTTP-Steuer-API – lokaler HTTP-Server für externe Steuerung (v2.7.0).

Startet einen einfachen HTTP-Server auf localhost:PORT.
Nützlich für Streamdeck, Home Assistant, Skripte etc.

Endpunkte (alle GET):
  /ptt/on          – PTT aktivieren
  /ptt/off         – PTT deaktivieren
  /ptt/toggle      – PTT umschalten
  /mute/on         – Stummschalten
  /mute/off        – Stummschalten aufheben
  /mute/toggle     – Stummschalten umschalten
  /channel/<name>  – Kanal nach Name beitreten
  /status/<text>   – Statusnachricht setzen
  /speak/<text>    – Text per TTS vorlesen
  /info            – JSON: version, connected, channel, users
"""
from __future__ import annotations

import json
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app import MainFrame

_frame_ref: "MainFrame | None" = None


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args) -> None:
        pass  # kein stdout-Spam

    def do_GET(self) -> None:
        global _frame_ref
        path = urllib.parse.unquote(self.path.rstrip("/"))
        try:
            result = self._dispatch(path)
            body = json.dumps({"ok": True, "result": result}, ensure_ascii=False).encode()
            self.send_response(200)
        except Exception as exc:
            body = json.dumps({"ok": False, "error": str(exc)}).encode()
            self.send_response(500)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _dispatch(self, path: str) -> object:
        import wx
        f = _frame_ref
        if f is None:
            raise RuntimeError("App not ready")

        if path == "/ptt/on":
            wx.CallAfter(f.client.enable_voice_transmission, True)
            return "PTT on"
        if path == "/ptt/off":
            wx.CallAfter(f.client.enable_voice_transmission, False)
            return "PTT off"
        if path == "/ptt/toggle":
            new = not f._ptt_active
            wx.CallAfter(f.client.enable_voice_transmission, new)
            return f"PTT {'on' if new else 'off'}"
        if path == "/mute/on":
            wx.CallAfter(f.client.set_sound_output_mute, True)
            return "muted"
        if path == "/mute/off":
            wx.CallAfter(f.client.set_sound_output_mute, False)
            return "unmuted"
        if path == "/mute/toggle":
            new = not f._mute_all
            f._mute_all = new
            wx.CallAfter(f.client.set_sound_output_mute, new)
            return f"mute {'on' if new else 'off'}"
        if path.startswith("/channel/"):
            name = path[9:]
            wx.CallAfter(f._http_api_join_channel, name)
            return f"joining {name}"
        if path.startswith("/status/"):
            text = path[8:]
            wx.CallAfter(f.client.change_status, f._status_mode, text)
            return f"status set: {text}"
        if path.startswith("/speak/"):
            text = path[7:]
            wx.CallAfter(f.tts.speak, text, kind="system")
            return f"speaking: {text}"
        if path == "/info":
            return {
                "connected": f.client.is_connected(),
                "channel": getattr(f, "_current_server_key", ""),
            }
        raise ValueError(f"Unknown path: {path}")


class HttpApiServer:
    """Verwaltet den HTTP-Server-Thread."""

    def __init__(self, frame: "MainFrame") -> None:
        global _frame_ref
        _frame_ref = frame
        self._frame = frame
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self, port: int = 8765) -> None:
        if self._server is not None:
            return
        try:
            self._server = HTTPServer(("127.0.0.1", port), _Handler)
            self._thread = threading.Thread(
                target=self._server.serve_forever,
                name="HttpAPI",
                daemon=True,
            )
            self._thread.start()
            print(f"[HttpAPI] Läuft auf http://127.0.0.1:{port}")
        except Exception as exc:
            print(f"[HttpAPI] Start fehlgeschlagen: {exc}")
            self._server = None

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server = None
