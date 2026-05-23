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

        def _json(key: str, default) -> object:
            raw = db.get(key)
            if raw == "":
                return default
            try:
                v = json.loads(raw)
                return v if v is not None else default
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
        s.app_language = _str("app_language", "")
        s.default_subscriptions = _int("default_subscriptions", 0)
        s.tcp_bind_port = _int("tcp_bind_port", 0)
        s.udp_bind_port = _int("udp_bind_port", 0)
        s.minimize_to_tray = _bool("minimize_to_tray", True)
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
        s.sound_pack_dir = _str("sound_pack_dir", "")
        s.user_stereo_settings = _dict("user_stereo_settings")
        # v2.0.0
        s.claude_api_key = _str("claude_api_key", "")
        s.voice_control_enabled = _bool("voice_control_enabled", False)
        s.transcription_enabled = _bool("transcription_enabled", False)
        s.transcription_autosave = _bool("transcription_autosave", False)
        s.translate_chat_enabled = _bool("translate_chat_enabled", False)
        s.translate_target_language = _str("translate_target_language", "Deutsch")
        s.braille_verbosity = _str("braille_verbosity", "normal")
        s.hotkey_cycle_braille_verbosity = _int("hotkey_cycle_braille_verbosity", 0)
        s.hotkey_ai_summary = _int("hotkey_ai_summary", 0)
        s.active_server_session = _str("active_server_session", "")
        # v2.0.2
        s.gemini_api_key = _str("gemini_api_key", "")
        # previously missing – persisted from here on
        s.auto_reply_enabled = _bool("auto_reply_enabled", False)
        s.auto_reply_message = _str("auto_reply_message", "Ich bin gerade nicht erreichbar.")
        s.alert_keywords_tts = _bool("alert_keywords_tts", True)
        s.braille_status_show_channel = _bool("braille_status_show_channel", True)
        s.braille_status_show_users = _bool("braille_status_show_users", True)
        s.braille_status_show_ping = _bool("braille_status_show_ping", True)
        s.braille_status_show_mute = _bool("braille_status_show_mute", False)
        s.braille_status_show_connection = _bool("braille_status_show_connection", True)
        s.connection_quality_announce = _bool("connection_quality_announce", False)
        s.connection_quality_threshold_ms = _int("connection_quality_threshold_ms", 300)
        s.noise_gate_enabled = _bool("noise_gate_enabled", False)
        s.noise_gate_threshold = _int("noise_gate_threshold", 500)
        s.ptt_max_seconds = _int("ptt_max_seconds", 0)
        s.recording_max_minutes = _int("recording_max_minutes", 0)
        s.recording_max_size_mb = _int("recording_max_size_mb", 0)
        s.server_info_in_titlebar = _bool("server_info_in_titlebar", False)
        s.silence_detection_enabled = _bool("silence_detection_enabled", False)
        s.silence_detection_threshold_pct = _int("silence_detection_threshold_pct", 2)
        s.silence_detection_timeout_sec = _int("silence_detection_timeout_sec", 30)
        s.macro_triggers = _list("macro_triggers")
        s.scheduled_macros = _list("scheduled_macros")
        s.eq_active_preset = _str("eq_active_preset", "Standard")
        s.eq_mic_gain_pct = _int("eq_mic_gain_pct", 50)
        s.eq_out_volume_pct = _int("eq_out_volume_pct", 100)
        s.tts_chat_rate = _int("tts_chat_rate", 0)
        s.tts_system_rate = _int("tts_system_rate", 0)
        s.tts_channel_rate = _int("tts_channel_rate", 0)
        s.tts_chat_voice = _str("tts_chat_voice", "")
        s.tts_system_voice = _str("tts_system_voice", "")
        s.vu_alert_enabled = _bool("vu_alert_enabled", False)
        s.vu_alert_threshold = _int("vu_alert_threshold", 90)
        s.webhook_url = _str("webhook_url", "")
        s.webhook_events = _json("webhook_events", [])
        # batch 2 – previously missing
        s.auto_reconnect_enabled = _bool("auto_reconnect_enabled", True)
        s.notifications_enabled = _bool("notifications_enabled", True)
        s.companion_server_enabled = _bool("companion_server_enabled", True)
        s.companion_server_port = _int("companion_server_port", 19880)
        s.channel_bookmarks = _list("channel_bookmarks")
        s.hotkey_bookmark_1 = _int("hotkey_bookmark_1", 0)
        s.hotkey_bookmark_2 = _int("hotkey_bookmark_2", 0)
        s.hotkey_bookmark_3 = _int("hotkey_bookmark_3", 0)
        s.hotkey_bookmark_4 = _int("hotkey_bookmark_4", 0)
        s.hotkey_bookmark_5 = _int("hotkey_bookmark_5", 0)
        s.hotkey_bookmark_6 = _int("hotkey_bookmark_6", 0)
        s.hotkey_bookmark_7 = _int("hotkey_bookmark_7", 0)
        s.hotkey_bookmark_8 = _int("hotkey_bookmark_8", 0)
        s.hotkey_bookmark_9 = _int("hotkey_bookmark_9", 0)
        s.hotkey_ai_reply_suggestions = _int("hotkey_ai_reply_suggestions", 0)
        s.pronunciation_dict = _dict("pronunciation_dict")
        s.pronunciation_rules = _list("pronunciation_rules")
        s.auto_join_channel_per_server = _dict("auto_join_channel_per_server")
        s.mute_schedule = _list("mute_schedule")
        s.macros = _list("macros")
        s.user_volume_presets = _dict("user_volume_presets")
        s.hotkey_record_toggle = _int("hotkey_record_toggle", 0)
        s.status_templates = _list("status_templates")
        s.hotkey_status_template_1 = _int("hotkey_status_template_1", 0)
        s.hotkey_status_template_2 = _int("hotkey_status_template_2", 0)
        s.hotkey_status_template_3 = _int("hotkey_status_template_3", 0)
        s.http_api_enabled = _bool("http_api_enabled", False)
        s.http_api_port = _int("http_api_port", 8765)
        s.user_notes = _dict("user_notes")
        s.recent_channels = _list("recent_channels")
        s.alert_keywords = _list("alert_keywords")
        s.hotkey_mic_boost_up = _int("hotkey_mic_boost_up", 0)
        s.hotkey_mic_boost_down = _int("hotkey_mic_boost_down", 0)
        s.server_groups = _dict("server_groups")
        s.tts_speak_channel_topic_on_join = _bool("tts_speak_channel_topic_on_join", True)
        s.disabled_plugins = _list("disabled_plugins")
        s.hotkey_tts_cancel = _int("hotkey_tts_cancel", 0)
        s.hotkey_announce_status = _int("hotkey_announce_status", 0)
        # v6.5.0
        s.watched_users = _list("watched_users")
        # v6.6.0
        s.server_audio_profiles = _dict("server_audio_profiles")
        # v6.7.0
        s.auto_channel_summary = _bool("auto_channel_summary", False)
        # v6.7.x – recording tab
        s.rec_format = _str("rec_format", "wav")
        s.rec_bitrate_kbps = _int("rec_bitrate_kbps", 128)
        s.rec_directory = _str("rec_directory", "")
        s.rec_filename_pattern = _str("rec_filename_pattern", "{date}_{server}_{channel}")
        s.rec_include_self = _bool("rec_include_self", True)
        s.rec_auto_start = _bool("rec_auto_start", False)
        s.rec_segment_minutes = _int("rec_segment_minutes", 0)
        s.rec_skip_silence = _bool("rec_skip_silence", False)
        # v6.7.x – braille tab
        s.braille_enabled = _bool("braille_enabled", False)
        s.braille_announce_channel = _bool("braille_announce_channel", True)
        s.braille_announce_user = _bool("braille_announce_user", True)
        s.braille_read_messages = _bool("braille_read_messages", True)
        s.braille_max_msg_len = _int("braille_max_msg_len", 80)
        # v6.7.x – chat filter tab extensions
        s.chat_filter_enabled = _bool("chat_filter_enabled", False)
        s.blocked_phrases = _str("blocked_phrases", "")
        s.filter_case_insensitive = _bool("filter_case_insensitive", True)
        s.filter_use_regex = _bool("filter_use_regex", False)
        # v6.7.x – mute scheduler
        s.mute_scheduler_enabled = _bool("mute_scheduler_enabled", False)
        s.mute_from_time = _str("mute_from_time", "22:00")
        s.mute_to_time = _str("mute_to_time", "07:00")
        s.auto_reply_text = _str("auto_reply_text", "Ich bin gerade nicht erreichbar.")
        # v7.1.0
        s.notification_rules = _list("notification_rules")

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
        _set("app_language", str(getattr(s, "app_language", "") or ""))
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
        _set("sound_pack_dir", str(getattr(s, "sound_pack_dir", "") or ""))
        _set("user_stereo_settings", dict(getattr(s, "user_stereo_settings", {}) or {}))
        # v2.0.0
        _set("claude_api_key", str(getattr(s, "claude_api_key", "") or ""))
        _set("voice_control_enabled", bool(getattr(s, "voice_control_enabled", False)))
        _set("transcription_enabled", bool(getattr(s, "transcription_enabled", False)))
        _set("transcription_autosave", bool(getattr(s, "transcription_autosave", False)))
        _set("translate_chat_enabled", bool(getattr(s, "translate_chat_enabled", False)))
        _set("translate_target_language", str(getattr(s, "translate_target_language", "Deutsch") or "Deutsch"))
        _set("braille_verbosity", str(getattr(s, "braille_verbosity", "normal") or "normal"))
        _set("hotkey_cycle_braille_verbosity", int(getattr(s, "hotkey_cycle_braille_verbosity", 0) or 0))
        _set("hotkey_ai_summary", int(getattr(s, "hotkey_ai_summary", 0) or 0))
        _set("active_server_session", str(getattr(s, "active_server_session", "") or ""))
        # v2.0.2
        _set("gemini_api_key", str(getattr(s, "gemini_api_key", "") or ""))
        # previously missing
        _set("auto_reply_enabled", bool(getattr(s, "auto_reply_enabled", False)))
        _set("auto_reply_message", str(getattr(s, "auto_reply_message", "") or ""))
        _set("alert_keywords_tts", bool(getattr(s, "alert_keywords_tts", True)))
        _set("braille_status_show_channel", bool(getattr(s, "braille_status_show_channel", True)))
        _set("braille_status_show_users", bool(getattr(s, "braille_status_show_users", True)))
        _set("braille_status_show_ping", bool(getattr(s, "braille_status_show_ping", True)))
        _set("braille_status_show_mute", bool(getattr(s, "braille_status_show_mute", False)))
        _set("braille_status_show_connection", bool(getattr(s, "braille_status_show_connection", True)))
        _set("connection_quality_announce", bool(getattr(s, "connection_quality_announce", False)))
        _set("connection_quality_threshold_ms", int(getattr(s, "connection_quality_threshold_ms", 300) or 300))
        _set("noise_gate_enabled", bool(getattr(s, "noise_gate_enabled", False)))
        _set("noise_gate_threshold", int(getattr(s, "noise_gate_threshold", 500) or 500))
        _set("ptt_max_seconds", int(getattr(s, "ptt_max_seconds", 0) or 0))
        _set("recording_max_minutes", int(getattr(s, "recording_max_minutes", 0) or 0))
        _set("recording_max_size_mb", int(getattr(s, "recording_max_size_mb", 0) or 0))
        _set("server_info_in_titlebar", bool(getattr(s, "server_info_in_titlebar", False)))
        _set("silence_detection_enabled", bool(getattr(s, "silence_detection_enabled", False)))
        _set("silence_detection_threshold_pct", int(getattr(s, "silence_detection_threshold_pct", 2) or 2))
        _set("silence_detection_timeout_sec", int(getattr(s, "silence_detection_timeout_sec", 30) or 30))
        _set("macro_triggers", list(getattr(s, "macro_triggers", []) or []))
        _set("scheduled_macros", list(getattr(s, "scheduled_macros", []) or []))
        _set("eq_active_preset", str(getattr(s, "eq_active_preset", "Standard") or "Standard"))
        _set("eq_mic_gain_pct", int(getattr(s, "eq_mic_gain_pct", 50) or 50))
        _set("eq_out_volume_pct", int(getattr(s, "eq_out_volume_pct", 100) or 100))
        _set("tts_chat_rate", int(getattr(s, "tts_chat_rate", 0) or 0))
        _set("tts_system_rate", int(getattr(s, "tts_system_rate", 0) or 0))
        _set("tts_channel_rate", int(getattr(s, "tts_channel_rate", 0) or 0))
        _set("tts_chat_voice", str(getattr(s, "tts_chat_voice", "") or ""))
        _set("tts_system_voice", str(getattr(s, "tts_system_voice", "") or ""))
        _set("vu_alert_enabled", bool(getattr(s, "vu_alert_enabled", False)))
        _set("vu_alert_threshold", int(getattr(s, "vu_alert_threshold", 90) or 90))
        _set("webhook_url", str(getattr(s, "webhook_url", "") or ""))
        _set("webhook_events", list(getattr(s, "webhook_events", []) or []))
        # batch 2 – previously missing
        _set("auto_reconnect_enabled", bool(getattr(s, "auto_reconnect_enabled", True)))
        _set("notifications_enabled", bool(getattr(s, "notifications_enabled", True)))
        _set("companion_server_enabled", bool(getattr(s, "companion_server_enabled", True)))
        _set("companion_server_port", int(getattr(s, "companion_server_port", 19880) or 19880))
        _set("channel_bookmarks", list(getattr(s, "channel_bookmarks", []) or []))
        _set("hotkey_bookmark_1", int(getattr(s, "hotkey_bookmark_1", 0) or 0))
        _set("hotkey_bookmark_2", int(getattr(s, "hotkey_bookmark_2", 0) or 0))
        _set("hotkey_bookmark_3", int(getattr(s, "hotkey_bookmark_3", 0) or 0))
        _set("hotkey_bookmark_4", int(getattr(s, "hotkey_bookmark_4", 0) or 0))
        _set("hotkey_bookmark_5", int(getattr(s, "hotkey_bookmark_5", 0) or 0))
        _set("hotkey_bookmark_6", int(getattr(s, "hotkey_bookmark_6", 0) or 0))
        _set("hotkey_bookmark_7", int(getattr(s, "hotkey_bookmark_7", 0) or 0))
        _set("hotkey_bookmark_8", int(getattr(s, "hotkey_bookmark_8", 0) or 0))
        _set("hotkey_bookmark_9", int(getattr(s, "hotkey_bookmark_9", 0) or 0))
        _set("hotkey_ai_reply_suggestions", int(getattr(s, "hotkey_ai_reply_suggestions", 0) or 0))
        _set("pronunciation_dict", dict(getattr(s, "pronunciation_dict", {}) or {}))
        _set("pronunciation_rules", list(getattr(s, "pronunciation_rules", []) or []))
        _set("auto_join_channel_per_server", dict(getattr(s, "auto_join_channel_per_server", {}) or {}))
        _set("mute_schedule", list(getattr(s, "mute_schedule", []) or []))
        _set("macros", list(getattr(s, "macros", []) or []))
        _set("user_volume_presets", dict(getattr(s, "user_volume_presets", {}) or {}))
        _set("hotkey_record_toggle", int(getattr(s, "hotkey_record_toggle", 0) or 0))
        _set("status_templates", list(getattr(s, "status_templates", []) or []))
        _set("hotkey_status_template_1", int(getattr(s, "hotkey_status_template_1", 0) or 0))
        _set("hotkey_status_template_2", int(getattr(s, "hotkey_status_template_2", 0) or 0))
        _set("hotkey_status_template_3", int(getattr(s, "hotkey_status_template_3", 0) or 0))
        _set("http_api_enabled", bool(getattr(s, "http_api_enabled", False)))
        _set("http_api_port", int(getattr(s, "http_api_port", 8765) or 8765))
        _set("user_notes", dict(getattr(s, "user_notes", {}) or {}))
        _set("recent_channels", list(getattr(s, "recent_channels", []) or []))
        _set("alert_keywords", list(getattr(s, "alert_keywords", []) or []))
        _set("hotkey_mic_boost_up", int(getattr(s, "hotkey_mic_boost_up", 0) or 0))
        _set("hotkey_mic_boost_down", int(getattr(s, "hotkey_mic_boost_down", 0) or 0))
        _set("server_groups", dict(getattr(s, "server_groups", {}) or {}))
        _set("tts_speak_channel_topic_on_join", bool(getattr(s, "tts_speak_channel_topic_on_join", True)))
        _set("disabled_plugins", list(getattr(s, "disabled_plugins", []) or []))
        _set("hotkey_tts_cancel", int(getattr(s, "hotkey_tts_cancel", 0) or 0))
        _set("hotkey_announce_status", int(getattr(s, "hotkey_announce_status", 0) or 0))
        # v6.5.0
        _set("watched_users", list(getattr(s, "watched_users", []) or []))
        # v6.6.0
        _set("server_audio_profiles", dict(getattr(s, "server_audio_profiles", {}) or {}))
        # v6.7.0
        _set("auto_channel_summary", bool(getattr(s, "auto_channel_summary", False)))
        # v6.7.x – recording tab
        _set("rec_format", str(getattr(s, "rec_format", "wav") or "wav"))
        _set("rec_bitrate_kbps", int(getattr(s, "rec_bitrate_kbps", 128) or 128))
        _set("rec_directory", str(getattr(s, "rec_directory", "") or ""))
        _set("rec_filename_pattern", str(getattr(s, "rec_filename_pattern", "{date}_{server}_{channel}") or "{date}_{server}_{channel}"))
        _set("rec_include_self", bool(getattr(s, "rec_include_self", True)))
        _set("rec_auto_start", bool(getattr(s, "rec_auto_start", False)))
        _set("rec_segment_minutes", int(getattr(s, "rec_segment_minutes", 0) or 0))
        _set("rec_skip_silence", bool(getattr(s, "rec_skip_silence", False)))
        # v6.7.x – braille tab
        _set("braille_enabled", bool(getattr(s, "braille_enabled", False)))
        _set("braille_announce_channel", bool(getattr(s, "braille_announce_channel", True)))
        _set("braille_announce_user", bool(getattr(s, "braille_announce_user", True)))
        _set("braille_read_messages", bool(getattr(s, "braille_read_messages", True)))
        _set("braille_max_msg_len", int(getattr(s, "braille_max_msg_len", 80) or 80))
        # v6.7.x – chat filter tab extensions
        _set("chat_filter_enabled", bool(getattr(s, "chat_filter_enabled", False)))
        _set("blocked_phrases", str(getattr(s, "blocked_phrases", "") or ""))
        _set("filter_case_insensitive", bool(getattr(s, "filter_case_insensitive", True)))
        _set("filter_use_regex", bool(getattr(s, "filter_use_regex", False)))
        # v6.7.x – mute scheduler
        _set("mute_scheduler_enabled", bool(getattr(s, "mute_scheduler_enabled", False)))
        _set("mute_from_time", str(getattr(s, "mute_from_time", "22:00") or "22:00"))
        _set("mute_to_time", str(getattr(s, "mute_to_time", "07:00") or "07:00"))
        _set("auto_reply_text", str(getattr(s, "auto_reply_text", "") or ""))
        # v7.1.0
        _set("notification_rules", list(getattr(s, "notification_rules", []) or []))

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
