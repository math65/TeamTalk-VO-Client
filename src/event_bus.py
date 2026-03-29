"""Einfacher synchroner Event-Bus als Vorbereitung für Plugin-System und Multi-Server.

Alle Handler werden im aufrufenden Thread aufgerufen (kein eigener Thread).
Thread-Sicherheit für UI-Updates bleibt Verantwortung der Handler (wx.CallAfter).

v5.8.0 – Wartbarkeit: emit_count, handler_count, metrics() hinzugefügt.

Verwendung:
    bus = EventBus()
    bus.on("user_joined", my_handler)
    bus.emit("user_joined", user=user_obj, channel_id=42)
    bus.off("user_joined", my_handler)
    bus.metrics()  # {"total_emitted": 5, "handler_errors": 0, ...}
"""
from __future__ import annotations

from typing import Callable, Dict, List


class EventBus:
    def __init__(self) -> None:
        self._handlers: Dict[str, List[Callable]] = {}
        # v4.0.0 – Wildcard-Handler empfangen alle Events
        self._any_handlers: List[Callable] = []
        # v5.8.0 – Metriken
        self._emit_counts: Dict[str, int] = {}
        self._total_emitted: int = 0
        self._handler_errors: int = 0

    def on(self, event: str, handler: Callable) -> None:
        """Registriert einen Handler für ein Event."""
        if event not in self._handlers:
            self._handlers[event] = []
        if handler not in self._handlers[event]:
            self._handlers[event].append(handler)

    def on_any(self, handler: Callable) -> None:
        """Registriert einen Wildcard-Handler der alle Events empfängt.

        Signatur: handler(event: str, **kwargs) -> None
        """
        if handler not in self._any_handlers:
            self._any_handlers.append(handler)

    def off(self, event: str, handler: Callable) -> None:
        """Entfernt einen Handler für ein Event."""
        try:
            self._handlers[event].remove(handler)
        except (KeyError, ValueError):
            pass

    def off_any(self, handler: Callable) -> None:
        """Entfernt einen Wildcard-Handler."""
        try:
            self._any_handlers.remove(handler)
        except ValueError:
            pass

    def emit(self, event: str, **kwargs) -> None:
        """Feuert ein Event und ruft alle registrierten Handler auf.

        Handler-Exceptions werden geloggt aber nicht weitergegeben,
        damit ein fehlerhafter Handler andere Handler nicht blockiert.
        """
        # v5.8.0 – Metriken
        self._total_emitted += 1
        self._emit_counts[event] = self._emit_counts.get(event, 0) + 1

        for handler in list(self._handlers.get(event, [])):
            try:
                handler(**kwargs)
            except Exception as exc:
                import traceback
                traceback.print_exc()
                print(f"[EventBus] Handler {handler} für '{event}' fehlgeschlagen: {exc}")
                self._handler_errors += 1
        # v4.0.0 – Wildcard-Handler
        for handler in list(self._any_handlers):
            try:
                handler(event, **kwargs)
            except Exception as exc:
                print(f"[EventBus] Wildcard-Handler {handler} für '{event}' fehlgeschlagen: {exc}")
                self._handler_errors += 1

    def clear(self, event: str = "") -> None:
        """Entfernt alle Handler (für ein bestimmtes Event oder alle)."""
        if event:
            self._handlers.pop(event, None)
        else:
            self._handlers.clear()
            self._any_handlers.clear()

    # ------------------------------------------------------------------
    # v5.8.0 – Metriken
    # ------------------------------------------------------------------

    def metrics(self) -> dict:
        """Gibt Bus-Metriken zurück: emit-Zähler, Handler-Fehler, aktive Events."""
        return {
            "total_emitted": self._total_emitted,
            "handler_errors": self._handler_errors,
            "active_events": len(self._handlers),
            "wildcard_handlers": len(self._any_handlers),
            "top_events": sorted(
                self._emit_counts.items(), key=lambda x: x[1], reverse=True
            )[:10],
        }

    def handler_count(self, event: str = "") -> int:
        """Gibt die Anzahl registrierter Handler zurück (für ein Event oder insgesamt)."""
        if event:
            return len(self._handlers.get(event, []))
        return sum(len(v) for v in self._handlers.values()) + len(self._any_handlers)
