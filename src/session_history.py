"""session_history – Persistente Sitzungshistorie (Events als JSONL-Datei)."""
from __future__ import annotations

import json
import time
from pathlib import Path

_MAX_ENTRIES = 5000
_EVENT_LABELS = {
    "connect":        "Verbunden",
    "disconnect":     "Getrennt",
    "channel_join":   "Kanal betreten",
    "channel_leave":  "Kanal verlassen",
    "user_login":     "Nutzer angemeldet",
    "user_logout":    "Nutzer abgemeldet",
    "kicked":         "Gekickt",
    "banned":         "Gebannt",
    "file_added":     "Datei hinzugefügt",
    "file_removed":   "Datei entfernt",
}


class SessionHistoryStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def log(
        self,
        event_type: str,
        desc: str,
        server: str = "",
        channel: str = "",
        user: str = "",
    ) -> None:
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "type": event_type,
            "desc": desc,
        }
        if server:
            entry["server"] = server
        if channel:
            entry["channel"] = channel
        if user:
            entry["user"] = user
        try:
            existing = []
            if self.path.exists():
                existing = self.path.read_text(encoding="utf-8").splitlines()
            existing.append(json.dumps(entry, ensure_ascii=False))
            if len(existing) > _MAX_ENTRIES:
                existing = existing[-_MAX_ENTRIES:]
            self.path.write_text("\n".join(existing) + "\n", encoding="utf-8")
        except Exception:
            pass

    def load_all(self) -> list[dict]:
        try:
            if not self.path.exists():
                return []
            out = []
            for line in self.path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except Exception:
                        pass
            return out
        except Exception:
            return []

    def export_text(self) -> str:
        entries = self.load_all()
        lines = []
        for e in entries:
            ts = e.get("ts", "")
            label = _EVENT_LABELS.get(e.get("type", ""), e.get("type", ""))
            desc = e.get("desc", "")
            parts = [f"[{ts}] [{label}] {desc}"]
            extras = []
            if e.get("server"):
                extras.append(f"Server: {e['server']}")
            if e.get("channel"):
                extras.append(f"Kanal: {e['channel']}")
            if e.get("user"):
                extras.append(f"Nutzer: {e['user']}")
            if extras:
                parts.append("  " + ", ".join(extras))
            lines.append("\n".join(parts))
        return "\n\n".join(lines)
