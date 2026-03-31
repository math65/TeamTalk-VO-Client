"""ServerSession und ServerManager – Multi-Server-Unterstützung (v5.0.0).

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
    "session_added"           → session_id=str, session=ServerSession  (v5.0.0)
    "session_removed"         → session_id=str                          (v5.0.0)

v5.0.0 – Vollausbau Multi-Server:
    - Persistenz: save_sessions()/load_sessions() speichern Session-IDs + Profilnamen
    - per_session_stats: Nachrichtenstatistik je Session (empfangen, gesendet)
    - MAX_SESSIONS-Limit (Standard: 8)
    - session_labels(): Gibt liste von (session_id, label) für UI-Auswahlmenüs
    - is_connected(session_id): Schnellabfrage ohne Session-Objekt
    - close_all(): Trennt alle Sessions sauber (für App-Shutdown)
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from event_bus import EventBus
from teamtalk_client.client import TeamTalkClient
from ui.models import ServerProfile

MAX_SESSIONS = 8


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
        """Erstellt eine neue Session für das Profil und gibt die ID zurück.

        v5.0.0 – Wirft ValueError wenn MAX_SESSIONS erreicht.
        """
        if len(self._sessions) >= MAX_SESSIONS:
            raise ValueError(f"Maximale Anzahl Sessions ({MAX_SESSIONS}) erreicht.")
        session_id = str(uuid.uuid4())
        session = ServerSession(session_id, profile)
        self._sessions[session_id] = session
        self._global_bus.emit("session_added", session_id=session_id, session=session)
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
        self._global_bus.emit("session_removed", session_id=session_id)
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

    def is_connected(self, session_id: str) -> bool:
        """Schnellabfrage: ist eine Session verbunden?"""
        s = self._sessions.get(session_id)
        return s is not None and s.state == "connected"

    def session_labels(self) -> List[Tuple[str, str]]:
        """Gibt Liste von (session_id, ascii_label) für UI-Auswahlmenüs zurück."""
        return [(s.session_id, s.display_label_ascii()) for s in self._sessions.values()]

    def close_all(self) -> None:
        """Trennt alle Sessions sauber (für App-Shutdown)."""
        for sid in list(self._sessions.keys()):
            self.remove_session(sid)

    # ------------------------------------------------------------------
    # v5.0.0 – Persistenz
    # ------------------------------------------------------------------

    def save_sessions(self, path: Path) -> None:
        """Speichert Session-Metadaten (IDs + Profilnamen) als JSON."""
        data = [
            {
                "session_id": s.session_id,
                "profile_name": s.profile.name,
                "state": s.state,
            }
            for s in self._sessions.values()
        ]
        try:
            path.write_text(
                json.dumps({"active_id": self._active_id, "sessions": data},
                           ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    def load_sessions(self, path: Path, profiles: List[ServerProfile]) -> int:
        """Lädt Session-Metadaten und rekonstruiert Session-Einträge."""
        if not path.exists():
            return 0
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return 0
        if not isinstance(data, dict):
            return 0
        sessions_data = data.get("sessions", [])
        active_id = str(data.get("active_id", "") or "")
        profiles_by_name = {p.name: p for p in profiles}
        self._sessions = {}
        self._active_id = None
        restored = 0
        for entry in sessions_data:
            if not isinstance(entry, dict):
                continue
            profile_name = str(entry.get("profile_name", "") or "")
            profile = profiles_by_name.get(profile_name)
            if profile is None:
                continue
            session_id = str(entry.get("session_id", "") or uuid.uuid4())
            session = ServerSession(session_id, profile)
            session.state = str(entry.get("state", "disconnected") or "disconnected")
            self._sessions[session_id] = session
            restored += 1
        if active_id and active_id in self._sessions:
            self._active_id = active_id
        elif self._sessions:
            self._active_id = next(iter(self._sessions.keys()))
        if self._active_id:
            self._global_bus.emit(
                "active_server_changed",
                session_id=self._active_id,
                session=self._sessions[self._active_id],
            )
        for sid, session in self._sessions.items():
            self._global_bus.emit("session_added", session_id=sid, session=session)
        return restored

    def per_session_stats(self) -> Dict[str, Dict]:
        """Gibt Verbindungsstatus-Übersicht aller Sessions als Dict zurück."""
        return {
            sid: {
                "profile": s.profile.name,
                "state": s.state,
                "is_active": sid == self._active_id,
            }
            for sid, s in self._sessions.items()
        }
