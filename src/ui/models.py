from __future__ import annotations

import dataclasses
import json
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class ServerProfile:
    name: str
    host: str
    tcp_port: int
    udp_port: int
    nickname: str
    username: str
    password: str
    client_name: str
    encrypted: bool = False
    elevenlabs_api_key: str = ""
    display_name: str = ""


@dataclass
class ParsedTeamTalkFile:
    profile: ServerProfile
    channel_path: Optional[str] = None
    channel_id: Optional[int] = None
    channel_password: Optional[str] = None
    encrypted: bool = False
    join_last_channel: bool = False
    verify_peer: Optional[bool] = None
    ca_certificate_pem: str = ""
    client_certificate_pem: str = ""
    client_private_key_pem: str = ""


class FileLogger:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, line: str) -> None:
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with self.path.open("a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {line}\n")


class ServerStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._items: List[ServerProfile] = []
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            self._items = []
            return
        try:
            valid_names = {f.name for f in dataclasses.fields(ServerProfile)}
            data = json.loads(self.path.read_text(encoding="utf-8"))
            items = []
            for item in data:
                try:
                    filtered = {k: v for k, v in item.items() if k in valid_names}
                    items.append(ServerProfile(**filtered))
                except Exception:
                    continue
            self._items = items
        except Exception:
            self._items = []

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = [asdict(item) for item in self._items]
        self.path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

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
        self._items = [ServerProfile(**item) for item in data]
        self.save()

    def export_to(self, path: Path) -> None:
        data = [asdict(item) for item in self._items]
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


@dataclass
class AppSettings:
    auto_apply_audio: bool = False
    auto_apply_audio_on_device_change: bool = False
    ptt_hotkey: int = 0
    audio_prefs: Dict[str, Any] = field(default_factory=dict)
    video_device_id: str = ""
    video_format_index: int = 0
    video_bitrate_kbps: int = 256
    video_deadline: str = "realtime"
    hotkey_mute_all: int = 0
    hotkey_voice_activation: int = 0
    hotkey_video_tx: int = 0
    # Allgemein
    gender: str = ""
    away_timer_min: int = 0
    bearware_username: str = ""
    bearware_password: str = ""
    bearware_login: bool = False
    app_language: str = "de"
    # Verbindung
    default_subscriptions: int = 0
    tcp_bind_port: int = 0
    udp_bind_port: int = 0
    # Anzeige
    minimize_to_tray: bool = True
    always_on_top: bool = False
    show_server_in_title: bool = True
    chat_history_format: str = "Liste"
    show_toolbar: bool = True        # Standard: sichtbar (jetzt unten, Screen-reader-freundlich)
    show_event_log: bool = False     # Standard: versteckt (Screenreader-freundlich)
    show_vu_meter: bool = True
    # Sound-Ereignisse
    sound_events: Dict[str, str] = field(default_factory=dict)
    # ElevenLabs
    elevenlabs_api_key: str = ""
    # TTS (espeak-ng)
    tts_enabled: bool = False
    tts_speak_chat: bool = True
    tts_speak_private: bool = True
    tts_speak_system: bool = True
    tts_speak_own: bool = True
    tts_interrupt: bool = False
    tts_language: str = "de"
    tts_voice: str = ""
    tts_rate: int = 175
    tts_volume: int = 100
    tts_espeak_path: str = ""
    # v1.3.0 features
    save_chat_history: bool = False
    auto_join_last_channel: bool = False
    last_channel_per_server: Dict[str, int] = field(default_factory=dict)
    global_hotkeys_enabled: bool = False
    global_hotkey_ptt: int = 0
    global_hotkey_mute: int = 0
    # v1.5.0 features
    tts_speak_user_join: bool = True
    tts_speak_user_leave: bool = True
    tts_speak_file_transfer: bool = False
    tts_speak_who_speaks: bool = False
    tts_speak_channel_topic: bool = False
    tts_connect_announce: bool = True
    reconnect_max_attempts: int = 0
    reconnect_delay_sec: int = 2
    chat_highlight_keywords: str = ""
    chat_muted_users: str = ""
    save_private_chat_history: bool = False
    update_check_on_start: bool = True
    chat_show_timestamps: bool = False
    braille_compact_mode: bool = False
    hotkey_announce_level: int = 0
    # v1.6.0 features
    hotkey_announce_user_info: int = 0
    hotkey_announce_ping: int = 0
    # v1.7.0 features
    save_channel_passwords: bool = False
    hotkey_reply_last_sender: int = 0
    # v1.9.0 features
    sound_profiles: List[Dict[str, str]] = field(default_factory=list)
    active_sound_profile: str = "Standard"
    hotkey_cycle_sound_profile: int = 0
    # v2.0.0 features
    claude_api_key: str = ""
    voice_control_enabled: bool = False
    transcription_enabled: bool = False
    braille_verbosity: str = "normal"
    hotkey_cycle_braille_verbosity: int = 0
    hotkey_ai_summary: int = 0
    active_server_session: str = ""
    # v2.0.2 features
    gemini_api_key: str = ""
    # v2.1.0 features
    auto_reconnect_enabled: bool = True
    notifications_enabled: bool = True
    companion_server_enabled: bool = True
    companion_server_port: int = 19880
    # v2.2.0 features
    tts_chat_rate: int = 0
    tts_system_rate: int = 0
    tts_channel_rate: int = 0
    tts_chat_voice: str = ""
    tts_system_voice: str = ""
    channel_bookmarks: List[Dict[str, Any]] = field(default_factory=list)
    hotkey_bookmark_1: int = 0
    hotkey_bookmark_2: int = 0
    hotkey_bookmark_3: int = 0
    # v3.8.0 features
    hotkey_bookmark_4: int = 0
    hotkey_bookmark_5: int = 0
    hotkey_bookmark_6: int = 0
    hotkey_bookmark_7: int = 0
    hotkey_bookmark_8: int = 0
    hotkey_bookmark_9: int = 0
    # v3.9.0 features
    translate_chat_enabled: bool = False
    translate_target_language: str = "Deutsch"
    hotkey_ai_reply_suggestions: int = 0
    transcription_autosave: bool = False
    pronunciation_dict: Dict[str, str] = field(default_factory=dict)
    # v2.3.0 features
    auto_join_channel_per_server: Dict[str, str] = field(default_factory=dict)
    mute_schedule: List[Dict] = field(default_factory=list)
    macros: List[Dict] = field(default_factory=list)
    # v2.4.0 features
    user_volume_presets: Dict[str, int] = field(default_factory=dict)
    noise_gate_enabled: bool = False
    noise_gate_threshold: int = 500
    hotkey_record_toggle: int = 0
    # v2.5.0 features
    auto_reply_enabled: bool = False
    auto_reply_message: str = "Ich bin gerade nicht erreichbar."
    status_templates: List[str] = field(default_factory=list)
    hotkey_status_template_1: int = 0
    hotkey_status_template_2: int = 0
    hotkey_status_template_3: int = 0
    # v2.6.0 features
    connection_quality_announce: bool = False
    connection_quality_threshold_ms: int = 300
    server_info_in_titlebar: bool = False
    # v2.7.0 features
    webhook_url: str = ""
    webhook_events: List[str] = field(default_factory=list)
    http_api_enabled: bool = False
    http_api_port: int = 8765
    # v2.8.0 features
    user_notes: Dict[str, str] = field(default_factory=dict)
    ptt_max_seconds: int = 0
    recent_channels: List[Dict[str, Any]] = field(default_factory=list)
    alert_keywords: List[str] = field(default_factory=list)
    alert_keywords_tts: bool = True
    # v2.9.0 features
    hotkey_mic_boost_up: int = 0
    hotkey_mic_boost_down: int = 0
    hotkey_volume_up: int = 0
    hotkey_volume_down: int = 0
    vu_alert_enabled: bool = False
    vu_alert_threshold: int = 90
    recording_max_size_mb: int = 0
    recording_max_minutes: int = 0
    # v3.0.0 features
    server_groups: Dict[str, List[str]] = field(default_factory=dict)
    tts_speak_channel_topic_on_join: bool = True
    disabled_plugins: List[str] = field(default_factory=list)
    hotkey_tts_cancel: int = 0
    hotkey_announce_status: int = 0
    # v3.1.0 features
    braille_status_show_channel: bool = True
    braille_status_show_users: bool = True
    braille_status_show_ping: bool = True
    braille_status_show_mute: bool = False
    braille_status_show_connection: bool = True
    silence_detection_enabled: bool = False
    silence_detection_threshold_pct: int = 2
    silence_detection_timeout_sec: int = 30
    # v3.5.0 features
    macro_triggers: List[Dict] = field(default_factory=list)
    scheduled_macros: List[Dict] = field(default_factory=list)
    # EQ preset persistence
    eq_active_preset: str = "Standard"
    eq_mic_gain_pct: int = 50
    eq_out_volume_pct: int = 100
    # v6.5.0 features
    watched_users: List[str] = field(default_factory=list)
    # v6.6.0 features
    server_audio_profiles: Dict[str, str] = field(default_factory=dict)
    # v6.7.0 features
    auto_channel_summary: bool = False
    # v6.10.0 (ttaccessible-inspired)
    away_status_message: str = ""
    tts_speak_kicked: bool = True
    tts_speak_broadcast: bool = True
    tts_speak_user_away: bool = False
    tts_backend: str = "espeak"
    tts_muted_channels: List[int] = field(default_factory=list)
    chat_relative_timestamps: bool = False
    server_list_sort: str = "manual"
    skip_kick_confirmation: bool = False
    adaptive_jitter_buffer: bool = False
    notify_background_private: bool = True
    notify_background_channel: bool = False
    notify_background_broadcast: bool = True
    # v6.9.7
    tts_muted_join_users: str = ""
    channel_favorites: List[int] = field(default_factory=list)
    # v6.10.2 (ttaccessible-inspired)
    tts_speak_user_login: bool = True
    tts_speak_file_event: bool = True
    tts_macos_voice: str = ""
    recording_mode: str = "muxed"  # "muxed" | "separate" | "both"
    # v6.10.3 (ttaccessible-inspired)
    tts_macos_rate: float = 0.5
    tts_macos_volume: float = 1.0
    notify_background_private_mode: str = "notification"   # "off"|"notification"|"tts"|"voiceover"
    notify_background_channel_mode: str = "off"
    notify_background_broadcast_mode: str = "notification"
    auto_join_root_channel: bool = False


class SettingsStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.settings = AppSettings()
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return
        if isinstance(data, dict):
            self.settings.auto_apply_audio = bool(data.get("auto_apply_audio", False))
            self.settings.auto_apply_audio_on_device_change = bool(
                data.get("auto_apply_audio_on_device_change", False)
            )
            self.settings.ptt_hotkey = int(data.get("ptt_hotkey", 0) or 0)
            prefs = data.get("audio_prefs", {})
            self.settings.audio_prefs = prefs if isinstance(prefs, dict) else {}
            self.settings.video_device_id = str(data.get("video_device_id", "") or "")
            self.settings.video_format_index = int(data.get("video_format_index", 0) or 0)
            self.settings.video_bitrate_kbps = int(data.get("video_bitrate_kbps", 256) or 256)
            self.settings.video_deadline = str(data.get("video_deadline", "realtime") or "realtime")
            self.settings.hotkey_mute_all = int(data.get("hotkey_mute_all", 0) or 0)
            self.settings.hotkey_voice_activation = int(data.get("hotkey_voice_activation", 0) or 0)
            self.settings.hotkey_video_tx = int(data.get("hotkey_video_tx", 0) or 0)
            self.settings.gender = str(data.get("gender", "") or "")
            self.settings.away_timer_min = int(data.get("away_timer_min", 0) or 0)
            self.settings.bearware_username = str(data.get("bearware_username", "") or "")
            self.settings.bearware_password = str(data.get("bearware_password", "") or "")
            self.settings.bearware_login = bool(data.get("bearware_login", False))
            self.settings.app_language = str(data.get("app_language", "de") or "de")
            self.settings.default_subscriptions = int(data.get("default_subscriptions", 0) or 0)
            self.settings.tcp_bind_port = int(data.get("tcp_bind_port", 0) or 0)
            self.settings.udp_bind_port = int(data.get("udp_bind_port", 0) or 0)
            self.settings.minimize_to_tray = bool(data.get("minimize_to_tray", False))
            self.settings.always_on_top = bool(data.get("always_on_top", False))
            self.settings.show_server_in_title = bool(data.get("show_server_in_title", True))
            self.settings.chat_history_format = str(data.get("chat_history_format", "Liste") or "Liste")
            self.settings.show_toolbar = bool(data.get("show_toolbar", True))
            self.settings.show_event_log = bool(data.get("show_event_log", False))
            self.settings.show_vu_meter = bool(data.get("show_vu_meter", True))
            sound_events = data.get("sound_events", {})
            self.settings.sound_events = sound_events if isinstance(sound_events, dict) else {}
            self.settings.elevenlabs_api_key = str(data.get("elevenlabs_api_key", "") or "")
            self.settings.tts_enabled = bool(data.get("tts_enabled", False))
            self.settings.tts_speak_chat = bool(data.get("tts_speak_chat", True))
            self.settings.tts_speak_private = bool(data.get("tts_speak_private", True))
            self.settings.tts_speak_system = bool(data.get("tts_speak_system", True))
            self.settings.tts_speak_own = bool(data.get("tts_speak_own", True))
            self.settings.tts_interrupt = bool(data.get("tts_interrupt", False))
            self.settings.tts_language = str(data.get("tts_language", "de") or "de")
            self.settings.tts_voice = str(data.get("tts_voice", "") or "")
            self.settings.tts_rate = int(data.get("tts_rate", 175) or 175)
            self.settings.tts_volume = int(data.get("tts_volume", 100) or 100)
            self.settings.tts_espeak_path = str(data.get("tts_espeak_path", "") or "")
            self.settings.save_chat_history = bool(data.get("save_chat_history", False))
            self.settings.auto_join_last_channel = bool(data.get("auto_join_last_channel", False))
            lc = data.get("last_channel_per_server", {})
            self.settings.last_channel_per_server = {
                str(k): int(v) for k, v in lc.items() if isinstance(v, int)
            } if isinstance(lc, dict) else {}
            self.settings.global_hotkeys_enabled = bool(data.get("global_hotkeys_enabled", False))
            self.settings.global_hotkey_ptt = int(data.get("global_hotkey_ptt", 0) or 0)
            self.settings.global_hotkey_mute = int(data.get("global_hotkey_mute", 0) or 0)
            # v1.5.0
            self.settings.tts_speak_user_join = bool(data.get("tts_speak_user_join", True))
            self.settings.tts_speak_user_leave = bool(data.get("tts_speak_user_leave", True))
            self.settings.tts_speak_file_transfer = bool(data.get("tts_speak_file_transfer", False))
            self.settings.tts_speak_who_speaks = bool(data.get("tts_speak_who_speaks", False))
            self.settings.tts_speak_channel_topic = bool(data.get("tts_speak_channel_topic", False))
            self.settings.tts_connect_announce = bool(data.get("tts_connect_announce", True))
            self.settings.reconnect_max_attempts = int(data.get("reconnect_max_attempts", 0) or 0)
            self.settings.reconnect_delay_sec = int(data.get("reconnect_delay_sec", 2) or 2)
            self.settings.chat_highlight_keywords = str(data.get("chat_highlight_keywords", "") or "")
            self.settings.chat_muted_users = str(data.get("chat_muted_users", "") or "")
            self.settings.save_private_chat_history = bool(data.get("save_private_chat_history", False))
            self.settings.update_check_on_start = bool(data.get("update_check_on_start", True))
            self.settings.chat_show_timestamps = bool(data.get("chat_show_timestamps", False))
            self.settings.braille_compact_mode = bool(data.get("braille_compact_mode", False))
            self.settings.hotkey_announce_level = int(data.get("hotkey_announce_level", 0) or 0)
            # v1.6.0
            self.settings.hotkey_announce_user_info = int(data.get("hotkey_announce_user_info", 0) or 0)
            self.settings.hotkey_announce_ping = int(data.get("hotkey_announce_ping", 0) or 0)
            # v1.7.0
            self.settings.save_channel_passwords = bool(data.get("save_channel_passwords", False))
            self.settings.hotkey_reply_last_sender = int(data.get("hotkey_reply_last_sender", 0) or 0)
            # v1.9.0
            raw_profiles = data.get("sound_profiles", [])
            self.settings.sound_profiles = raw_profiles if isinstance(raw_profiles, list) else []
            self.settings.active_sound_profile = str(data.get("active_sound_profile", "Standard") or "Standard")
            self.settings.hotkey_cycle_sound_profile = int(data.get("hotkey_cycle_sound_profile", 0) or 0)
            # v2.0.0
            self.settings.claude_api_key = str(data.get("claude_api_key", "") or "")
            self.settings.voice_control_enabled = bool(data.get("voice_control_enabled", False))
            self.settings.transcription_enabled = bool(data.get("transcription_enabled", False))
            self.settings.braille_verbosity = str(data.get("braille_verbosity", "normal") or "normal")
            self.settings.hotkey_cycle_braille_verbosity = int(data.get("hotkey_cycle_braille_verbosity", 0) or 0)
            self.settings.hotkey_ai_summary = int(data.get("hotkey_ai_summary", 0) or 0)
            self.settings.active_server_session = str(data.get("active_server_session", "") or "")
            # v2.0.2
            self.settings.gemini_api_key = str(data.get("gemini_api_key", "") or "")
            # v2.1.0
            self.settings.auto_reconnect_enabled = bool(data.get("auto_reconnect_enabled", True))
            self.settings.notifications_enabled = bool(data.get("notifications_enabled", True))
            # v2.2.0
            self.settings.tts_chat_rate = int(data.get("tts_chat_rate", 0) or 0)
            self.settings.tts_system_rate = int(data.get("tts_system_rate", 0) or 0)
            self.settings.tts_channel_rate = int(data.get("tts_channel_rate", 0) or 0)
            self.settings.tts_chat_voice = str(data.get("tts_chat_voice", "") or "")
            self.settings.tts_system_voice = str(data.get("tts_system_voice", "") or "")
            raw_bm = data.get("channel_bookmarks", [])
            self.settings.channel_bookmarks = raw_bm if isinstance(raw_bm, list) else []
            self.settings.hotkey_bookmark_1 = int(data.get("hotkey_bookmark_1", 0) or 0)
            self.settings.hotkey_bookmark_2 = int(data.get("hotkey_bookmark_2", 0) or 0)
            self.settings.hotkey_bookmark_3 = int(data.get("hotkey_bookmark_3", 0) or 0)
            raw_pd = data.get("pronunciation_dict", {})
            self.settings.pronunciation_dict = raw_pd if isinstance(raw_pd, dict) else {}
            # v2.3.0
            raw_ajc = data.get("auto_join_channel_per_server", {})
            self.settings.auto_join_channel_per_server = raw_ajc if isinstance(raw_ajc, dict) else {}
            raw_ms = data.get("mute_schedule", [])
            self.settings.mute_schedule = raw_ms if isinstance(raw_ms, list) else []
            raw_mac = data.get("macros", [])
            self.settings.macros = raw_mac if isinstance(raw_mac, list) else []
            # v2.4.0
            raw_uvp = data.get("user_volume_presets", {})
            self.settings.user_volume_presets = raw_uvp if isinstance(raw_uvp, dict) else {}
            self.settings.noise_gate_enabled = bool(data.get("noise_gate_enabled", False))
            self.settings.noise_gate_threshold = int(data.get("noise_gate_threshold", 500) or 500)
            self.settings.hotkey_record_toggle = int(data.get("hotkey_record_toggle", 0) or 0)
            # v2.5.0
            self.settings.auto_reply_enabled = bool(data.get("auto_reply_enabled", False))
            self.settings.auto_reply_message = str(data.get("auto_reply_message", "Ich bin gerade nicht erreichbar.") or "")
            raw_st = data.get("status_templates", [])
            self.settings.status_templates = raw_st if isinstance(raw_st, list) else []
            self.settings.hotkey_status_template_1 = int(data.get("hotkey_status_template_1", 0) or 0)
            self.settings.hotkey_status_template_2 = int(data.get("hotkey_status_template_2", 0) or 0)
            self.settings.hotkey_status_template_3 = int(data.get("hotkey_status_template_3", 0) or 0)
            # v2.6.0
            self.settings.connection_quality_announce = bool(data.get("connection_quality_announce", False))
            self.settings.connection_quality_threshold_ms = int(data.get("connection_quality_threshold_ms", 300) or 300)
            self.settings.server_info_in_titlebar = bool(data.get("server_info_in_titlebar", False))
            # v2.7.0
            self.settings.webhook_url = str(data.get("webhook_url", "") or "")
            raw_we = data.get("webhook_events", [])
            self.settings.webhook_events = raw_we if isinstance(raw_we, list) else []
            self.settings.http_api_enabled = bool(data.get("http_api_enabled", False))
            self.settings.http_api_port = int(data.get("http_api_port", 8765) or 8765)
            # v2.8.0
            raw_un = data.get("user_notes", {})
            self.settings.user_notes = raw_un if isinstance(raw_un, dict) else {}
            self.settings.ptt_max_seconds = int(data.get("ptt_max_seconds", 0) or 0)
            raw_rc = data.get("recent_channels", [])
            self.settings.recent_channels = raw_rc if isinstance(raw_rc, list) else []
            raw_ak = data.get("alert_keywords", [])
            self.settings.alert_keywords = raw_ak if isinstance(raw_ak, list) else []
            self.settings.alert_keywords_tts = bool(data.get("alert_keywords_tts", True))
            # v2.9.0
            self.settings.hotkey_mic_boost_up = int(data.get("hotkey_mic_boost_up", 0) or 0)
            self.settings.hotkey_mic_boost_down = int(data.get("hotkey_mic_boost_down", 0) or 0)
            self.settings.hotkey_volume_up = int(data.get("hotkey_volume_up", 0) or 0)
            self.settings.hotkey_volume_down = int(data.get("hotkey_volume_down", 0) or 0)
            self.settings.vu_alert_enabled = bool(data.get("vu_alert_enabled", False))
            self.settings.vu_alert_threshold = int(data.get("vu_alert_threshold", 90) or 90)
            self.settings.recording_max_size_mb = int(data.get("recording_max_size_mb", 0) or 0)
            self.settings.recording_max_minutes = int(data.get("recording_max_minutes", 0) or 0)
            # v3.0.0
            raw_sg = data.get("server_groups", {})
            self.settings.server_groups = raw_sg if isinstance(raw_sg, dict) else {}
            self.settings.tts_speak_channel_topic_on_join = bool(data.get("tts_speak_channel_topic_on_join", True))
            raw_dp = data.get("disabled_plugins", [])
            self.settings.disabled_plugins = raw_dp if isinstance(raw_dp, list) else []
            # v6.10.0
            self.settings.away_status_message = str(data.get("away_status_message", "") or "")
            self.settings.tts_speak_kicked = bool(data.get("tts_speak_kicked", True))
            self.settings.tts_speak_broadcast = bool(data.get("tts_speak_broadcast", True))
            self.settings.tts_speak_user_away = bool(data.get("tts_speak_user_away", False))
            self.settings.tts_backend = str(data.get("tts_backend", "espeak") or "espeak")
            raw_tmc = data.get("tts_muted_channels", [])
            self.settings.tts_muted_channels = [int(x) for x in raw_tmc if isinstance(x, (int, float))] if isinstance(raw_tmc, list) else []
            self.settings.chat_relative_timestamps = bool(data.get("chat_relative_timestamps", False))
            self.settings.server_list_sort = str(data.get("server_list_sort", "manual") or "manual")
            self.settings.skip_kick_confirmation = bool(data.get("skip_kick_confirmation", False))
            self.settings.adaptive_jitter_buffer = bool(data.get("adaptive_jitter_buffer", False))
            self.settings.notify_background_private = bool(data.get("notify_background_private", True))
            self.settings.notify_background_channel = bool(data.get("notify_background_channel", False))
            self.settings.notify_background_broadcast = bool(data.get("notify_background_broadcast", True))
            # v6.9.7
            self.settings.tts_muted_join_users = str(data.get("tts_muted_join_users", "") or "")
            raw_cf = data.get("channel_favorites", [])
            self.settings.channel_favorites = [int(x) for x in raw_cf if isinstance(x, (int, float))] if isinstance(raw_cf, list) else []
            # v6.10.2
            self.settings.tts_speak_user_login = bool(data.get("tts_speak_user_login", True))
            self.settings.tts_speak_file_event = bool(data.get("tts_speak_file_event", True))
            self.settings.tts_macos_voice = str(data.get("tts_macos_voice", "") or "")
            self.settings.recording_mode = str(data.get("recording_mode", "muxed") or "muxed")
            # v6.10.3
            self.settings.tts_macos_rate = float(data.get("tts_macos_rate", 0.5) or 0.5)
            self.settings.tts_macos_volume = float(data.get("tts_macos_volume", 1.0) or 1.0)
            _old_priv = bool(data.get("notify_background_private", True))
            self.settings.notify_background_private_mode = str(
                data.get("notify_background_private_mode", "notification" if _old_priv else "off") or "notification"
            )
            _old_chan = bool(data.get("notify_background_channel", False))
            self.settings.notify_background_channel_mode = str(
                data.get("notify_background_channel_mode", "notification" if _old_chan else "off") or "off"
            )
            _old_bc = bool(data.get("notify_background_broadcast", True))
            self.settings.notify_background_broadcast_mode = str(
                data.get("notify_background_broadcast_mode", "notification" if _old_bc else "off") or "notification"
            )
            self.settings.auto_join_root_channel = bool(data.get("auto_join_root_channel", False))
            # v3.5.0
            raw_mt = data.get("macro_triggers", [])
            self.settings.macro_triggers = raw_mt if isinstance(raw_mt, list) else []
            raw_sm = data.get("scheduled_macros", [])
            self.settings.scheduled_macros = raw_sm if isinstance(raw_sm, list) else []
            # EQ preset
            self.settings.eq_active_preset = str(data.get("eq_active_preset", "Standard") or "Standard")
            self.settings.eq_mic_gain_pct = int(data.get("eq_mic_gain_pct", 50) or 50)
            self.settings.eq_out_volume_pct = int(data.get("eq_out_volume_pct", 100) or 100)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "auto_apply_audio": bool(self.settings.auto_apply_audio),
            "auto_apply_audio_on_device_change": bool(self.settings.auto_apply_audio_on_device_change),
            "ptt_hotkey": int(self.settings.ptt_hotkey or 0),
            "audio_prefs": self.settings.audio_prefs or {},
            "video_device_id": str(self.settings.video_device_id or ""),
            "video_format_index": int(self.settings.video_format_index or 0),
            "video_bitrate_kbps": int(self.settings.video_bitrate_kbps or 256),
            "video_deadline": str(self.settings.video_deadline or "realtime"),
            "hotkey_mute_all": int(self.settings.hotkey_mute_all or 0),
            "hotkey_voice_activation": int(self.settings.hotkey_voice_activation or 0),
            "hotkey_video_tx": int(self.settings.hotkey_video_tx or 0),
            "gender": str(self.settings.gender or ""),
            "away_timer_min": int(self.settings.away_timer_min or 0),
            "bearware_username": str(self.settings.bearware_username or ""),
            "bearware_password": str(self.settings.bearware_password or ""),
            "bearware_login": bool(self.settings.bearware_login),
            "app_language": str(self.settings.app_language or "de"),
            "default_subscriptions": int(self.settings.default_subscriptions or 0),
            "tcp_bind_port": int(self.settings.tcp_bind_port or 0),
            "udp_bind_port": int(self.settings.udp_bind_port or 0),
            "minimize_to_tray": bool(self.settings.minimize_to_tray),
            "always_on_top": bool(self.settings.always_on_top),
            "show_server_in_title": bool(self.settings.show_server_in_title),
            "chat_history_format": str(self.settings.chat_history_format or "Liste"),
            "show_toolbar": bool(self.settings.show_toolbar),
            "show_event_log": bool(self.settings.show_event_log),
            "show_vu_meter": bool(self.settings.show_vu_meter),
            "sound_events": self.settings.sound_events or {},
            "elevenlabs_api_key": str(self.settings.elevenlabs_api_key or ""),
            "tts_enabled": bool(self.settings.tts_enabled),
            "tts_speak_chat": bool(self.settings.tts_speak_chat),
            "tts_speak_private": bool(self.settings.tts_speak_private),
            "tts_speak_system": bool(self.settings.tts_speak_system),
            "tts_speak_own": bool(self.settings.tts_speak_own),
            "tts_interrupt": bool(self.settings.tts_interrupt),
            "tts_language": str(self.settings.tts_language or "de"),
            "tts_voice": str(self.settings.tts_voice or ""),
            "tts_rate": int(self.settings.tts_rate or 175),
            "tts_volume": int(self.settings.tts_volume or 100),
            "tts_espeak_path": str(self.settings.tts_espeak_path or ""),
            "save_chat_history": bool(self.settings.save_chat_history),
            "auto_join_last_channel": bool(self.settings.auto_join_last_channel),
            "last_channel_per_server": {
                str(k): int(v) for k, v in (self.settings.last_channel_per_server or {}).items()
            },
            "global_hotkeys_enabled": bool(self.settings.global_hotkeys_enabled),
            "global_hotkey_ptt": int(self.settings.global_hotkey_ptt or 0),
            "global_hotkey_mute": int(self.settings.global_hotkey_mute or 0),
            # v1.5.0
            "tts_speak_user_join": bool(self.settings.tts_speak_user_join),
            "tts_speak_user_leave": bool(self.settings.tts_speak_user_leave),
            "tts_speak_file_transfer": bool(self.settings.tts_speak_file_transfer),
            "tts_speak_who_speaks": bool(self.settings.tts_speak_who_speaks),
            "tts_speak_channel_topic": bool(self.settings.tts_speak_channel_topic),
            "tts_connect_announce": bool(self.settings.tts_connect_announce),
            "reconnect_max_attempts": int(self.settings.reconnect_max_attempts or 0),
            "reconnect_delay_sec": int(self.settings.reconnect_delay_sec or 2),
            "chat_highlight_keywords": str(self.settings.chat_highlight_keywords or ""),
            "chat_muted_users": str(self.settings.chat_muted_users or ""),
            "save_private_chat_history": bool(self.settings.save_private_chat_history),
            "update_check_on_start": bool(self.settings.update_check_on_start),
            "chat_show_timestamps": bool(self.settings.chat_show_timestamps),
            "braille_compact_mode": bool(self.settings.braille_compact_mode),
            "hotkey_announce_level": int(self.settings.hotkey_announce_level or 0),
            # v1.6.0
            "hotkey_announce_user_info": int(self.settings.hotkey_announce_user_info or 0),
            "hotkey_announce_ping": int(self.settings.hotkey_announce_ping or 0),
            # v1.7.0
            "save_channel_passwords": bool(self.settings.save_channel_passwords),
            "hotkey_reply_last_sender": int(self.settings.hotkey_reply_last_sender or 0),
            # v1.9.0
            "sound_profiles": self.settings.sound_profiles or [],
            "active_sound_profile": str(self.settings.active_sound_profile or "Standard"),
            "hotkey_cycle_sound_profile": int(self.settings.hotkey_cycle_sound_profile or 0),
            # v2.0.0
            "claude_api_key": str(self.settings.claude_api_key or ""),
            "voice_control_enabled": bool(self.settings.voice_control_enabled),
            "transcription_enabled": bool(self.settings.transcription_enabled),
            "braille_verbosity": str(self.settings.braille_verbosity or "normal"),
            "hotkey_cycle_braille_verbosity": int(self.settings.hotkey_cycle_braille_verbosity or 0),
            "hotkey_ai_summary": int(self.settings.hotkey_ai_summary or 0),
            "active_server_session": str(self.settings.active_server_session or ""),
            # v2.0.2
            "gemini_api_key": str(self.settings.gemini_api_key or ""),
            # v2.1.0
            "auto_reconnect_enabled": bool(self.settings.auto_reconnect_enabled),
            "notifications_enabled": bool(self.settings.notifications_enabled),
            # v2.2.0
            "tts_chat_rate": int(self.settings.tts_chat_rate or 0),
            "tts_system_rate": int(self.settings.tts_system_rate or 0),
            "tts_channel_rate": int(self.settings.tts_channel_rate or 0),
            "tts_chat_voice": str(self.settings.tts_chat_voice or ""),
            "tts_system_voice": str(self.settings.tts_system_voice or ""),
            "channel_bookmarks": list(self.settings.channel_bookmarks or []),
            "hotkey_bookmark_1": int(self.settings.hotkey_bookmark_1 or 0),
            "hotkey_bookmark_2": int(self.settings.hotkey_bookmark_2 or 0),
            "hotkey_bookmark_3": int(self.settings.hotkey_bookmark_3 or 0),
            "pronunciation_dict": dict(self.settings.pronunciation_dict or {}),
            # v2.3.0
            "auto_join_channel_per_server": dict(self.settings.auto_join_channel_per_server or {}),
            "mute_schedule": list(self.settings.mute_schedule or []),
            "macros": list(self.settings.macros or []),
            "macro_triggers": list(self.settings.macro_triggers or []),
            "scheduled_macros": list(self.settings.scheduled_macros or []),
            "eq_active_preset": str(self.settings.eq_active_preset or "Standard"),
            "eq_mic_gain_pct": int(self.settings.eq_mic_gain_pct or 50),
            "eq_out_volume_pct": int(self.settings.eq_out_volume_pct or 100),
            # v2.4.0
            "user_volume_presets": dict(self.settings.user_volume_presets or {}),
            "noise_gate_enabled": bool(self.settings.noise_gate_enabled),
            "noise_gate_threshold": int(self.settings.noise_gate_threshold or 500),
            "hotkey_record_toggle": int(self.settings.hotkey_record_toggle or 0),
            # v2.5.0
            "auto_reply_enabled": bool(self.settings.auto_reply_enabled),
            "auto_reply_message": str(self.settings.auto_reply_message or ""),
            "status_templates": list(self.settings.status_templates or []),
            "hotkey_status_template_1": int(self.settings.hotkey_status_template_1 or 0),
            "hotkey_status_template_2": int(self.settings.hotkey_status_template_2 or 0),
            "hotkey_status_template_3": int(self.settings.hotkey_status_template_3 or 0),
            # v2.6.0
            "connection_quality_announce": bool(self.settings.connection_quality_announce),
            "connection_quality_threshold_ms": int(self.settings.connection_quality_threshold_ms or 300),
            "server_info_in_titlebar": bool(self.settings.server_info_in_titlebar),
            # v2.7.0
            "webhook_url": str(self.settings.webhook_url or ""),
            "webhook_events": list(self.settings.webhook_events or []),
            "http_api_enabled": bool(self.settings.http_api_enabled),
            "http_api_port": int(self.settings.http_api_port or 8765),
            # v2.8.0
            "user_notes": dict(self.settings.user_notes or {}),
            "ptt_max_seconds": int(self.settings.ptt_max_seconds or 0),
            "recent_channels": list(self.settings.recent_channels or []),
            "alert_keywords": list(self.settings.alert_keywords or []),
            "alert_keywords_tts": bool(self.settings.alert_keywords_tts),
            # v2.9.0
            "hotkey_mic_boost_up": int(self.settings.hotkey_mic_boost_up or 0),
            "hotkey_mic_boost_down": int(self.settings.hotkey_mic_boost_down or 0),
            "hotkey_volume_up": int(self.settings.hotkey_volume_up or 0),
            "hotkey_volume_down": int(self.settings.hotkey_volume_down or 0),
            "vu_alert_enabled": bool(self.settings.vu_alert_enabled),
            "vu_alert_threshold": int(self.settings.vu_alert_threshold or 90),
            "recording_max_size_mb": int(self.settings.recording_max_size_mb or 0),
            "recording_max_minutes": int(self.settings.recording_max_minutes or 0),
            # v3.0.0
            "server_groups": dict(self.settings.server_groups or {}),
            "tts_speak_channel_topic_on_join": bool(self.settings.tts_speak_channel_topic_on_join),
            "disabled_plugins": list(self.settings.disabled_plugins or []),
            # v6.10.0
            "away_status_message": str(self.settings.away_status_message or ""),
            "tts_speak_kicked": bool(self.settings.tts_speak_kicked),
            "tts_speak_broadcast": bool(self.settings.tts_speak_broadcast),
            "tts_speak_user_away": bool(self.settings.tts_speak_user_away),
            "tts_backend": str(self.settings.tts_backend or "espeak"),
            "tts_muted_channels": list(self.settings.tts_muted_channels or []),
            "chat_relative_timestamps": bool(self.settings.chat_relative_timestamps),
            "server_list_sort": str(self.settings.server_list_sort or "manual"),
            "skip_kick_confirmation": bool(self.settings.skip_kick_confirmation),
            "adaptive_jitter_buffer": bool(self.settings.adaptive_jitter_buffer),
            "notify_background_private": bool(self.settings.notify_background_private),
            "notify_background_channel": bool(self.settings.notify_background_channel),
            "notify_background_broadcast": bool(self.settings.notify_background_broadcast),
            # v6.9.7
            "tts_muted_join_users": str(self.settings.tts_muted_join_users or ""),
            "channel_favorites": list(self.settings.channel_favorites or []),
            # v6.10.2
            "tts_speak_user_login": bool(self.settings.tts_speak_user_login),
            "tts_speak_file_event": bool(self.settings.tts_speak_file_event),
            "tts_macos_voice": str(self.settings.tts_macos_voice or ""),
            "recording_mode": str(self.settings.recording_mode or "muxed"),
            # v6.10.3
            "tts_macos_rate": float(self.settings.tts_macos_rate if self.settings.tts_macos_rate is not None else 0.5),
            "tts_macos_volume": float(self.settings.tts_macos_volume if self.settings.tts_macos_volume is not None else 1.0),
            "notify_background_private_mode": str(self.settings.notify_background_private_mode or "notification"),
            "notify_background_channel_mode": str(self.settings.notify_background_channel_mode or "off"),
            "notify_background_broadcast_mode": str(self.settings.notify_background_broadcast_mode or "notification"),
            "auto_join_root_channel": bool(self.settings.auto_join_root_channel),
        }
        self.path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
