"""Einfacher synchroner Event-Bus als Vorbereitung für Plugin-System und Multi-Server.

Alle Handler werden im aufrufenden Thread aufgerufen (kein eigener Thread).
Thread-Sicherheit für UI-Updates bleibt Verantwortung der Handler (wx.CallAfter).

Verwendung:
    bus = EventBus()
    bus.on("user_joined", my_handler)
    bus.emit("user_joined", user=user_obj, channel_id=42)
    bus.off("user_joined", my_handler)
"""
from __future__ import annotations

from typing import Callable, Dict, List


class EventBus:
    def __init__(self) -> None:
        self._handlers: Dict[str, List[Callable]] = {}

    def on(self, event: str, handler: Callable) -> None:
        """Registriert einen Handler für ein Event."""
        if event not in self._handlers:
            self._handlers[event] = []
        if handler not in self._handlers[event]:
            self._handlers[event].append(handler)

    def off(self, event: str, handler: Callable) -> None:
        """Entfernt einen Handler für ein Event."""
        try:
            self._handlers[event].remove(handler)
        except (KeyError, ValueError):
            pass

    def emit(self, event: str, **kwargs) -> None:
        """Feuert ein Event und ruft alle registrierten Handler auf.

        Handler-Exceptions werden geloggt aber nicht weitergegeben,
        damit ein fehlerhafter Handler andere Handler nicht blockiert.
        """
        for handler in list(self._handlers.get(event, [])):
            try:
                handler(**kwargs)
            except Exception as exc:
                import traceback
                traceback.print_exc()
                print(f"[EventBus] Handler {handler} für '{event}' fehlgeschlagen: {exc}")

    def clear(self, event: str = "") -> None:
        """Entfernt alle Handler (für ein bestimmtes Event oder alle)."""
        if event:
            self._handlers.pop(event, None)
        else:
            self._handlers.clear()
