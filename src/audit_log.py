"""AuditLog – Protokollierung sicherheitsrelevanter Aktionen (v4.9.0).

Alle sensitiven Aktionen (API-Key gespeichert/gelöscht, Verbindung zu Server,
Plugin geladen/entladen, Webhook-Konfiguration geändert) werden als JSONL in
``audit.jsonl`` im App-Verzeichnis protokolliert.

Schema je Eintrag::

    {
        "ts": "2026-03-29T12:00:00",
        "action": "api_key_saved",
        "detail": "claude_api_key",
        "user": "florian"
    }
"""
from __future__ import annotations

import getpass
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Optional


class AuditLog:
    """Schreibt Audit-Einträge als JSONL-Datei."""

    def __init__(self, app_dir: Path) -> None:
        self._path = app_dir / "audit.jsonl"
        try:
            self._user: str = getpass.getuser()
        except Exception:
            self._user = "unknown"

    def log(self, action: str, detail: str = "", extra: Optional[dict] = None) -> None:
        """Schreibt einen Audit-Eintrag.

        Args:
            action: Kurzer Aktions-Bezeichner, z. B. ``'api_key_saved'``.
            detail: Optionaler Detailtext (kein sensitiver Wert, nur Bezeichner).
            extra:  Zusätzliche JSON-serialisierbare Felder (optional).
        """
        entry: dict = {
            "ts": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"),
            "action": action,
            "user": self._user,
        }
        if detail:
            entry["detail"] = detail
        if extra:
            for k, v in extra.items():
                if k not in entry:
                    entry[k] = v
        try:
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def read_all(self) -> list:
        """Liest alle Audit-Einträge. Gibt Liste von Dicts zurück."""
        if not self._path.exists():
            return []
        entries = []
        try:
            for line in self._path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        except Exception:
            pass
        return entries

    def purge_older_than_days(self, days: int) -> int:
        """Löscht Einträge älter als ``days`` Tage. Gibt Anzahl gelöschter Einträge zurück."""
        if days <= 0:
            return 0
        cutoff = time.time() - days * 86400
        entries = self.read_all()
        kept = []
        removed = 0
        for entry in entries:
            try:
                ts = datetime.strptime(entry["ts"], "%Y-%m-%dT%H:%M:%S").timestamp()
                if ts >= cutoff:
                    kept.append(entry)
                else:
                    removed += 1
            except Exception:
                kept.append(entry)
        if removed > 0:
            try:
                with self._path.open("w", encoding="utf-8") as fh:
                    for entry in kept:
                        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
            except Exception:
                pass
        return removed


# ---------------------------------------------------------------------------
# Vordefinierte Aktions-Konstanten
# ---------------------------------------------------------------------------

A_API_KEY_SAVED = "api_key_saved"
A_API_KEY_DELETED = "api_key_deleted"
A_SERVER_CONNECT = "server_connect"
A_SERVER_DISCONNECT = "server_disconnect"
A_PLUGIN_LOADED = "plugin_loaded"
A_PLUGIN_UNLOADED = "plugin_unloaded"
A_PLUGIN_RELOAD = "plugin_reload"
A_WEBHOOK_ADDED = "webhook_added"
A_WEBHOOK_REMOVED = "webhook_removed"
A_SETTINGS_CHANGED = "settings_changed"
A_SAVED_MSG_EXPIRED = "saved_messages_expired"
A_SAVED_MSG_CLEARED = "saved_messages_cleared"
