"""Einheitliche SQLite-Einstellungsdatenbank (v2.0.0).

Ersetzt die JSON-basierten SettingsStore / ServerStore durch eine einzige
SQLite-Datei.  Beim ersten Start wird automatisch aus den vorhandenen JSON-
Dateien migriert (sofern vorhanden).

Öffentliche API ist identisch mit den alten Stores aus ui/models.py:
  SQLiteSettingsStore  → drop-in für SettingsStore
  SQLiteServerStore    → drop-in für ServerStore
"""
from __future__ import annotations

import dataclasses
import json
import sqlite3
from dataclasses import asdict
from pathlib import Path
from typing import List, Optional

from ui.models import AppSettings, ServerProfile


# ---------------------------------------------------------------------------
# Datenbank-Kern
# ---------------------------------------------------------------------------

class SettingsDB:
    """Öffnet/erstellt die SQLite-Datenbank und stellt die Verbindung bereit."""

    def __init__(self, db_path: Path) -> None:
        self.path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS app_settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS server_profiles (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                sort_order INTEGER DEFAULT 0,
                data       TEXT    NOT NULL
            );
        """)
        self._conn.commit()

    def get(self, key: str, default: str = "") -> str:
        row = self._conn.execute(
            "SELECT value FROM app_settings WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else default

    def set(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO app_settings (key, value) VALUES (?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )

    def commit(self) -> None:
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------

def migrate_from_json(
    db: SettingsDB,
    settings_json_path: Path,
    servers_json_path: Path,
) -> bool:
    """Migriert vorhandene JSON-Daten in die SQLite-DB (einmalig).

    Gibt True zurück wenn eine Migration stattfand.
    """
    # Nur migrieren wenn DB noch leer ist
    count = db._conn.execute("SELECT COUNT(*) FROM app_settings").fetchone()[0]
    if count > 0:
        return False

    migrated = False

    # Einstellungen migrieren
    if settings_json_path.exists():
        try:
            data = json.loads(settings_json_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for key, value in data.items():
                    db.set(key, json.dumps(value))
                db.commit()
                migrated = True
        except Exception as exc:
            print(f"[SettingsDB] JSON-Migration Einstellungen fehlgeschlagen: {exc}")

    # Server migrieren
    srv_count = db._conn.execute("SELECT COUNT(*) FROM server_profiles").fetchone()[0]
    if srv_count == 0 and servers_json_path.exists():
        try:
            data = json.loads(servers_json_path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                valid_names = {f.name for f in dataclasses.fields(ServerProfile)}
                for i, item in enumerate(data):
                    filtered = {k: v for k, v in item.items() if k in valid_names}
                    profile = ServerProfile(**filtered)
                    db._conn.execute(
                        "INSERT INTO server_profiles (sort_order, data) VALUES (?, ?)",
                        (i, json.dumps(asdict(profile))),
                    )
                db.commit()
                migrated = True
        except Exception as exc:
            print(f"[SettingsDB] JSON-Migration Server fehlgeschlagen: {exc}")

    return migrated


# ---------------------------------------------------------------------------
# SQLiteSettingsStore – drop-in für SettingsStore
# ---------------------------------------------------------------------------

class SQLiteSettingsStore:
    """Liest/schreibt AppSettings-Felder in SQLite (drop-in für SettingsStore)."""

    def __init__(self, db: SettingsDB) -> None:
        self._db = db
        self.settings = AppSettings()
        self.load()

    def load(self) -> None:
        s = self.settings
        db = self._db

        def _bool(key: str, default: bool) -> bool:
            raw = db.get(key)
            if raw == "":
                return default
            try:
                return bool(json.loads(raw))
            except Exception:
                return default

        def _int(key: str, default: int) -> int:
            raw = db.get(key)
            if raw == "":
                return default
            try:
                v = json.loads(raw)
                return int(v) if v is not None else default
            except Exception:
                return default

        def _str(key: str, default: str) -> str:
            raw = db.get(key)
            if raw == "":
                return default
            try:
                v = json.loads(raw)
                return str(v) if v is not None else default
            except Exception:
                return default

        def _dict(key: str) -> dict:
            raw = db.get(key)
            if raw == "":
                return {}
            try:
                v = json.loads(raw)
                return v if isinstance(v, dict) else {}
            except Exception:
                return {}

        def _list(key: str) -> list:
            raw = db.get(key)
            if raw == "":
                return []
            try:
                v = json.loads(raw)
                return v if isinstance(v, list) else []
            except Exception:
                return []

        s.auto_apply_audio = _bool("auto_apply_audio", False)
        s.auto_apply_audio_on_device_change = _bool("auto_apply_audio_on_device_change", False)
        s.ptt_hotkey = _int("ptt_hotkey", 0)
        s.audio_prefs = _dict("audio_prefs")
        s.video_device_id = _str("video_device_id", "")
        s.video_format_index = _int("video_format_index", 0)
        s.video_bitrate_kbps = _int("video_bitrate_kbps", 256)
        s.video_deadline = _str("video_deadline", "realtime")
        s.hotkey_mute_all = _int("hotkey_mute_all", 0)
        s.hotkey_voice_activation = _int("hotkey_voice_activation", 0)
        s.hotkey_video_tx = _int("hotkey_video_tx", 0)
        s.gender = _str("gender", "")
        s.away_timer_min = _int("away_timer_min", 0)
        s.bearware_username = _str("bearware_username", "")
        s.bearware_password = _str("bearware_password", "")
        s.bearware_login = _bool("bearware_login", False)
        s.app_language = _str("app_language", "de")
        s.default_subscriptions = _int("default_subscriptions", 0)
        s.tcp_bind_port = _int("tcp_bind_port", 0)
        s.udp_bind_port = _int("udp_bind_port", 0)
        s.minimize_to_tray = _bool("minimize_to_tray", False)
        s.always_on_top = _bool("always_on_top", False)
        s.show_server_in_title = _bool("show_server_in_title", True)
        s.chat_history_format = _str("chat_history_format", "Liste")
        s.show_toolbar = _bool("show_toolbar", True)
        s.show_event_log = _bool("show_event_log", False)
        s.show_vu_meter = _bool("show_vu_meter", True)
        s.sound_events = _dict("sound_events")
        s.elevenlabs_api_key = _str("elevenlabs_api_key", "")
        s.tts_enabled = _bool("tts_enabled", False)
        s.tts_speak_chat = _bool("tts_speak_chat", True)
        s.tts_speak_private = _bool("tts_speak_private", True)
        s.tts_speak_system = _bool("tts_speak_system", True)
        s.tts_speak_own = _bool("tts_speak_own", True)
        s.tts_interrupt = _bool("tts_interrupt", False)
        s.tts_language = _str("tts_language", "de")
        s.tts_voice = _str("tts_voice", "")
        s.tts_rate = _int("tts_rate", 175)
        s.tts_volume = _int("tts_volume", 100)
        s.tts_espeak_path = _str("tts_espeak_path", "")
        s.save_chat_history = _bool("save_chat_history", False)
        s.auto_join_last_channel = _bool("auto_join_last_channel", False)
        lc = _dict("last_channel_per_server")
        s.last_channel_per_server = {str(k): int(v) for k, v in lc.items() if isinstance(v, int)}
        s.global_hotkeys_enabled = _bool("global_hotkeys_enabled", False)
        s.global_hotkey_ptt = _int("global_hotkey_ptt", 0)
        s.global_hotkey_mute = _int("global_hotkey_mute", 0)
        s.tts_speak_user_join = _bool("tts_speak_user_join", True)
        s.tts_speak_user_leave = _bool("tts_speak_user_leave", True)
        s.tts_speak_file_transfer = _bool("tts_speak_file_transfer", False)
        s.tts_speak_who_speaks = _bool("tts_speak_who_speaks", False)
        s.tts_speak_channel_topic = _bool("tts_speak_channel_topic", False)
        s.tts_connect_announce = _bool("tts_connect_announce", True)
        s.reconnect_max_attempts = _int("reconnect_max_attempts", 0)
        s.reconnect_delay_sec = _int("reconnect_delay_sec", 2)
        s.chat_highlight_keywords = _str("chat_highlight_keywords", "")
        s.chat_muted_users = _str("chat_muted_users", "")
        s.save_private_chat_history = _bool("save_private_chat_history", False)
        s.update_check_on_start = _bool("update_check_on_start", True)
        s.chat_show_timestamps = _bool("chat_show_timestamps", False)
        s.braille_compact_mode = _bool("braille_compact_mode", False)
        s.hotkey_announce_level = _int("hotkey_announce_level", 0)
        s.hotkey_announce_user_info = _int("hotkey_announce_user_info", 0)
        s.hotkey_announce_ping = _int("hotkey_announce_ping", 0)
        s.save_channel_passwords = _bool("save_channel_passwords", False)
        s.hotkey_reply_last_sender = _int("hotkey_reply_last_sender", 0)
        s.sound_profiles = _list("sound_profiles")
        s.active_sound_profile = _str("active_sound_profile", "Standard")
        s.hotkey_cycle_sound_profile = _int("hotkey_cycle_sound_profile", 0)
        # v2.0.0
        s.claude_api_key = _str("claude_api_key", "")
        s.voice_control_enabled = _bool("voice_control_enabled", False)
        s.transcription_enabled = _bool("transcription_enabled", False)
        s.braille_verbosity = _str("braille_verbosity", "normal")
        s.hotkey_cycle_braille_verbosity = _int("hotkey_cycle_braille_verbosity", 0)
        s.hotkey_ai_summary = _int("hotkey_ai_summary", 0)
        s.active_server_session = _str("active_server_session", "")
        # v2.0.2
        s.gemini_api_key = _str("gemini_api_key", "")

    def save(self) -> None:
        s = self.settings
        db = self._db

        def _set(key: str, value) -> None:
            db.set(key, json.dumps(value))

        _set("auto_apply_audio", bool(s.auto_apply_audio))
        _set("auto_apply_audio_on_device_change", bool(s.auto_apply_audio_on_device_change))
        _set("ptt_hotkey", int(s.ptt_hotkey or 0))
        _set("audio_prefs", s.audio_prefs or {})
        _set("video_device_id", str(s.video_device_id or ""))
        _set("video_format_index", int(s.video_format_index or 0))
        _set("video_bitrate_kbps", int(s.video_bitrate_kbps or 256))
        _set("video_deadline", str(s.video_deadline or "realtime"))
        _set("hotkey_mute_all", int(s.hotkey_mute_all or 0))
        _set("hotkey_voice_activation", int(s.hotkey_voice_activation or 0))
        _set("hotkey_video_tx", int(s.hotkey_video_tx or 0))
        _set("gender", str(s.gender or ""))
        _set("away_timer_min", int(s.away_timer_min or 0))
        _set("bearware_username", str(s.bearware_username or ""))
        _set("bearware_password", str(s.bearware_password or ""))
        _set("bearware_login", bool(s.bearware_login))
        _set("app_language", str(getattr(s, "app_language", "de") or "de"))
        _set("default_subscriptions", int(s.default_subscriptions or 0))
        _set("tcp_bind_port", int(s.tcp_bind_port or 0))
        _set("udp_bind_port", int(s.udp_bind_port or 0))
        _set("minimize_to_tray", bool(s.minimize_to_tray))
        _set("always_on_top", bool(s.always_on_top))
        _set("show_server_in_title", bool(s.show_server_in_title))
        _set("chat_history_format", str(s.chat_history_format or "Liste"))
        _set("show_toolbar", bool(s.show_toolbar))
        _set("show_event_log", bool(s.show_event_log))
        _set("show_vu_meter", bool(s.show_vu_meter))
        _set("sound_events", s.sound_events or {})
        _set("elevenlabs_api_key", str(s.elevenlabs_api_key or ""))
        _set("tts_enabled", bool(s.tts_enabled))
        _set("tts_speak_chat", bool(s.tts_speak_chat))
        _set("tts_speak_private", bool(s.tts_speak_private))
        _set("tts_speak_system", bool(s.tts_speak_system))
        _set("tts_speak_own", bool(s.tts_speak_own))
        _set("tts_interrupt", bool(s.tts_interrupt))
        _set("tts_language", str(s.tts_language or "de"))
        _set("tts_voice", str(s.tts_voice or ""))
        _set("tts_rate", int(s.tts_rate or 175))
        _set("tts_volume", int(s.tts_volume or 100))
        _set("tts_espeak_path", str(s.tts_espeak_path or ""))
        _set("save_chat_history", bool(s.save_chat_history))
        _set("auto_join_last_channel", bool(s.auto_join_last_channel))
        _set("last_channel_per_server", {str(k): int(v) for k, v in (s.last_channel_per_server or {}).items()})
        _set("global_hotkeys_enabled", bool(s.global_hotkeys_enabled))
        _set("global_hotkey_ptt", int(s.global_hotkey_ptt or 0))
        _set("global_hotkey_mute", int(s.global_hotkey_mute or 0))
        _set("tts_speak_user_join", bool(s.tts_speak_user_join))
        _set("tts_speak_user_leave", bool(s.tts_speak_user_leave))
        _set("tts_speak_file_transfer", bool(s.tts_speak_file_transfer))
        _set("tts_speak_who_speaks", bool(s.tts_speak_who_speaks))
        _set("tts_speak_channel_topic", bool(s.tts_speak_channel_topic))
        _set("tts_connect_announce", bool(s.tts_connect_announce))
        _set("reconnect_max_attempts", int(s.reconnect_max_attempts or 0))
        _set("reconnect_delay_sec", int(s.reconnect_delay_sec or 2))
        _set("chat_highlight_keywords", str(s.chat_highlight_keywords or ""))
        _set("chat_muted_users", str(s.chat_muted_users or ""))
        _set("save_private_chat_history", bool(s.save_private_chat_history))
        _set("update_check_on_start", bool(s.update_check_on_start))
        _set("chat_show_timestamps", bool(getattr(s, "chat_show_timestamps", False)))
        _set("braille_compact_mode", bool(s.braille_compact_mode))
        _set("hotkey_announce_level", int(s.hotkey_announce_level or 0))
        _set("hotkey_announce_user_info", int(s.hotkey_announce_user_info or 0))
        _set("hotkey_announce_ping", int(s.hotkey_announce_ping or 0))
        _set("save_channel_passwords", bool(s.save_channel_passwords))
        _set("hotkey_reply_last_sender", int(s.hotkey_reply_last_sender or 0))
        _set("sound_profiles", s.sound_profiles or [])
        _set("active_sound_profile", str(s.active_sound_profile or "Standard"))
        _set("hotkey_cycle_sound_profile", int(s.hotkey_cycle_sound_profile or 0))
        # v2.0.0
        _set("claude_api_key", str(getattr(s, "claude_api_key", "") or ""))
        _set("voice_control_enabled", bool(getattr(s, "voice_control_enabled", False)))
        _set("transcription_enabled", bool(getattr(s, "transcription_enabled", False)))
        _set("braille_verbosity", str(getattr(s, "braille_verbosity", "normal") or "normal"))
        _set("hotkey_cycle_braille_verbosity", int(getattr(s, "hotkey_cycle_braille_verbosity", 0) or 0))
        _set("hotkey_ai_summary", int(getattr(s, "hotkey_ai_summary", 0) or 0))
        _set("active_server_session", str(getattr(s, "active_server_session", "") or ""))
        # v2.0.2
        _set("gemini_api_key", str(getattr(s, "gemini_api_key", "") or ""))

        db.commit()

    # Kompatibilität: path-Attribut (wird in app.py nicht benötigt, aber der Vollständigkeit halber)
    @property
    def path(self) -> Path:
        return self._db.path


# ---------------------------------------------------------------------------
# SQLiteServerStore – drop-in für ServerStore
# ---------------------------------------------------------------------------

class SQLiteServerStore:
    """Liest/schreibt ServerProfile-Einträge in SQLite (drop-in für ServerStore)."""

    def __init__(self, db: SettingsDB) -> None:
        self._db = db
        self._items: List[ServerProfile] = []
        self.load()

    def load(self) -> None:
        valid_names = {f.name for f in dataclasses.fields(ServerProfile)}
        rows = self._db._conn.execute(
            "SELECT data FROM server_profiles ORDER BY sort_order, id"
        ).fetchall()
        items = []
        for row in rows:
            try:
                data = json.loads(row["data"])
                filtered = {k: v for k, v in data.items() if k in valid_names}
                items.append(ServerProfile(**filtered))
            except Exception:
                continue
        self._items = items

    def save(self) -> None:
        conn = self._db._conn
        conn.execute("DELETE FROM server_profiles")
        for i, profile in enumerate(self._items):
            conn.execute(
                "INSERT INTO server_profiles (sort_order, data) VALUES (?, ?)",
                (i, json.dumps(asdict(profile))),
            )
        self._db.commit()

    def items(self) -> List[ServerProfile]:
        return list(self._items)

    def add(self, profile: ServerProfile) -> None:
        self._items.append(profile)
        self.save()

    def update(self, index: int, profile: ServerProfile) -> None:
        self._items[index] = profile
        self.save()

    def remove(self, index: int) -> None:
        self._items.pop(index)
        self.save()

    def import_from(self, path: Path) -> None:
        data = json.loads(path.read_text(encoding="utf-8"))
        valid_names = {f.name for f in dataclasses.fields(ServerProfile)}
        self._items = []
        for item in data:
            filtered = {k: v for k, v in item.items() if k in valid_names}
            self._items.append(ServerProfile(**filtered))
        self.save()

    def export_to(self, path: Path) -> None:
        data = [asdict(p) for p in self._items]
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    @property
    def path(self) -> Path:
        return self._db.path
