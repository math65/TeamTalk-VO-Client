"""ServerSession und ServerManager – Multi-Server-Unterstützung (v2.0.0).

Jede ServerSession kapselt einen eigenen TeamTalkClient und dessen Zustand.
Der ServerManager verwaltet bis zu N Sessions gleichzeitig und steuert
welche Session die Haupt-UI beliefert (aktive Session).

Verwendung in app.py:
    self.server_manager = ServerManager(self.bus)
    sid = self.server_manager.add_session(profile)
    self.server_manager.switch_to(sid)
    session = self.server_manager.get_active()
    session.client.connect(...)

Bus-Events:
    "active_server_changed"   → session_id=str, session=ServerSession
    "server_state_changed"    → session_id=str, state=str, session=ServerSession
"""
from __future__ import annotations

import uuid
from typing import Dict, List, Optional

from event_bus import EventBus
from teamtalk_client.client import TeamTalkClient
from ui.models import ServerProfile


class ServerSession:
    """Kapselt einen einzelnen TeamTalk-Server-Kontext."""

    def __init__(self, session_id: str, profile: ServerProfile) -> None:
        self.session_id = session_id
        self.profile = profile
        self.client = TeamTalkClient()
        self.bus = EventBus()
        self.state: str = "disconnected"  # "disconnected" | "connecting" | "connected"

    def display_label(self) -> str:
        """Lesbare Bezeichnung mit State-Emoji für Menüs / Listeneinträge."""
        emoji = {"disconnected": "🔴", "connecting": "🟡", "connected": "🟢"}.get(
            self.state, "⚪"
        )
        return f"{self.profile.name} {emoji}"

    def display_label_ascii(self) -> str:
        """ASCII-Variante für Braillezeilen / Systeme ohne Emoji."""
        abbrev = {"disconnected": "[--]", "connecting": "[..]", "connected": "[OK]"}.get(
            self.state, "[?]"
        )
        return f"{self.profile.name} {abbrev}"

    def __repr__(self) -> str:
        return f"<ServerSession id={self.session_id!r} profile={self.profile.name!r} state={self.state!r}>"


class ServerManager:
    """Verwaltet mehrere Server-Sessions und eine aktive Session."""

    def __init__(self, global_bus: EventBus) -> None:
        self._sessions: Dict[str, ServerSession] = {}
        self._active_id: Optional[str] = None
        self._global_bus = global_bus

    # ------------------------------------------------------------------
    # Session-Verwaltung
    # ------------------------------------------------------------------

    def add_session(self, profile: ServerProfile) -> str:
        """Erstellt eine neue Session für das Profil und gibt die ID zurück."""
        session_id = str(uuid.uuid4())
        session = ServerSession(session_id, profile)
        self._sessions[session_id] = session
        # Erste Session automatisch aktiv setzen
        if self._active_id is None:
            self._active_id = session_id
            self._global_bus.emit(
                "active_server_changed",
                session_id=session_id,
                session=session,
            )
        return session_id

    def remove_session(self, session_id: str) -> None:
        """Trennt und entfernt eine Session."""
        session = self._sessions.pop(session_id, None)
        if session is None:
            return
        try:
            if session.client.is_connected():
                session.client.disconnect()
        except Exception:
            pass
        # Falls aktive Session entfernt: auf eine andere wechseln
        if self._active_id == session_id:
            remaining = list(self._sessions.keys())
            self._active_id = remaining[0] if remaining else None
            if self._active_id:
                self._global_bus.emit(
                    "active_server_changed",
                    session_id=self._active_id,
                    session=self._sessions[self._active_id],
                )

    def get_active(self) -> Optional[ServerSession]:
        """Gibt die aktive Session zurück (oder None wenn keine vorhanden)."""
        if self._active_id and self._active_id in self._sessions:
            return self._sessions[self._active_id]
        return None

    def switch_to(self, session_id: str) -> None:
        """Macht eine andere Session zur aktiven Session."""
        if session_id not in self._sessions:
            raise KeyError(f"Unbekannte Session-ID: {session_id!r}")
        self._active_id = session_id
        self._global_bus.emit(
            "active_server_changed",
            session_id=session_id,
            session=self._sessions[session_id],
        )

    # ------------------------------------------------------------------
    # Zustandsaktualisierung
    # ------------------------------------------------------------------

    def update_state(self, session_id: str, state: str) -> None:
        """Setzt den Verbindungsstatus einer Session und feuert ein Bus-Event."""
        session = self._sessions.get(session_id)
        if session is None:
            return
        session.state = state
        self._global_bus.emit(
            "server_state_changed",
            session_id=session_id,
            state=state,
            session=session,
        )

    # ------------------------------------------------------------------
    # Abfragen
    # ------------------------------------------------------------------

    def all_sessions(self) -> List[ServerSession]:
        """Gibt alle Sessions in Einfügereihenfolge zurück."""
        return list(self._sessions.values())

    def get_session(self, session_id: str) -> Optional[ServerSession]:
        return self._sessions.get(session_id)

    @property
    def active_id(self) -> Optional[str]:
        return self._active_id

    def session_count(self) -> int:
        return len(self._sessions)

    def connected_count(self) -> int:
        return sum(1 for s in self._sessions.values() if s.state == "connected")
