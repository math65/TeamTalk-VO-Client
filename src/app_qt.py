"""Qt main application — Windows/Linux entry point."""
from __future__ import annotations

import os
import sys
import threading
import time
import traceback
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QStatusBar, QMenuBar, QMenu, QLabel, QComboBox,
    QPushButton, QMessageBox, QDialog, QTextEdit, QDialogButtonBox,
    QInputDialog, QLineEdit, QSlider, QCheckBox, QScrollArea,
    QListWidget, QFormLayout, QTimeEdit,
)
from PySide6.QtCore import QTimer, Qt, Signal, QObject, QTime
from PySide6.QtGui import QAction, QKeySequence, QFont, QCloseEvent, QShortcut

from teamtalk_client.client import TeamTalkClient, ConnectResult
from ui.models import (
    FileLogger,
    ParsedTeamTalkFile,
    ServerStore,
    SettingsStore,
)
from settings_db import SettingsDB, SQLiteSettingsStore, SQLiteServerStore, migrate_from_json
from server_session import ServerManager
from braille_output import BrailleOutputManager
from ai_summary import ChatSummaryManager
from gemini_auth import GeminiAuthManager
from ui_qt.tray import TrayIcon
from ui_qt.call_after import call_after
from ui_qt.connect_dialog import ConnectDialog
from ui_qt.tabs.channels_chat import ChannelsChatTab
from ui_qt.tabs.media import MediaTab
from ui_qt.tabs.files import FilesTab
from ui_qt.tabs.admin import AdminTab
from ui_qt.tabs.speak import SpeakTab
from ui_qt.tabs.settings import SettingsTab
from ui_qt.tabs.desktop import DesktopTab
from ui_qt.tabs.video import VideoTab
from tts import TTSManager
from sound_manager import SoundManager
from platform_paths import log_dir as _log_dir, app_data_dir
from chat_history import ChatHistoryManager
from pronunciation import PronunciationManager
from bookmark_manager import BookmarkManager
from mute_scheduler import MuteScheduler
from macro_manager import MacroManager
from auto_reply import AutoReplyManager
from webhook_manager import WebhookManager
from http_api import HttpApiServer
from i18n import _, set_language, current_language
from saved_messages import SavedMessageManager
from channel_notes import ChannelNotesManager
from chat_translator import ChatTranslatorManager
from ai_reply import AiReplyManager
from async_bridge import AsyncBusBridge
from startup_profiler import StartupProfiler
from eq_presets import EqPresetsManager
from audit_log import AuditLog, A_SERVER_CONNECT, A_SERVER_DISCONNECT
from offline_queue import OfflineMessageQueue
from tls_verify import CertPinStore
from analytics import UsageAnalytics
from health_check import HealthChecker, check_disk_space, check_event_bus, check_settings_db
from platform_info import platform_info
from screen_reader import ScreenReaderAnnouncer

APP_VERSION = "7.0.0"


def _start_demo_dialog_suppressor() -> None:
    """Schließt TeamTalk-SDK-Demo-Dialoge automatisch (Windows only)."""
    import os
    import threading
    import ctypes
    import ctypes.wintypes
    import time

    user32 = ctypes.windll.user32
    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
    _own_pid = os.getpid()
    _KEYWORDS = ("teamtalk", "demo", "sdk", "bearware", "trial", "lizenz", "license")

    def _close_demo_windows(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        # Nur Dialoge des eigenen Prozesses schließen
        pid = ctypes.wintypes.DWORD(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value != _own_pid:
            return True
        cls = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(hwnd, cls, 64)
        if cls.value != "#32770":
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True
        title = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, title, length + 1)
        title_lower = title.value.lower()
        if any(kw in title_lower for kw in _KEYWORDS):
            user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
            user32.PostMessageW(hwnd, 0x0111, 1, 0)  # WM_COMMAND IDOK (Fallback)
        return True

    def _worker():
        cb = EnumWindowsProc(_close_demo_windows)
        while True:
            time.sleep(0.1)  # 100 ms statt 1 s — Dialog verschwindet bevor er sichtbar wird
            try:
                user32.EnumWindows(cb, 0)
            except Exception:
                pass

    t = threading.Thread(target=_worker, daemon=True, name="demo-suppressor")
    t.start()

TT_TRANSMITUSERS_MAX = 128
TT_TRANSMITUSERS_FREEFORALL = 0xFFF

_startup_profiler: "StartupProfiler | None" = None


def _get_startup_profiler() -> StartupProfiler:
    global _startup_profiler
    if _startup_profiler is None:
        _startup_profiler = StartupProfiler()
    return _startup_profiler


def _upd_tok() -> str:
    import base64 as _b
    return bytes(x ^ 0x37 for x in _b.b64decode(
        b"UlYDU1VWVVFUBFRVVlFRAAAGUQQAU1NTAlUFUQQEVgNWAwMOUVFTDw=="
    )).decode()


class MainWindow(QMainWindow):
    """Qt main window — equivalent of MainFrame in app_wx.py."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"TeamTalk VoiceOver Client {APP_VERSION}")
        self.resize(1100, 750)

        self.client = TeamTalkClient()

        # Shared state
        self._app_version = APP_VERSION
        self._closing = False
        self._auto_reconnect = False
        self._reconnect_attempts = 0
        self._ptt_enabled = False
        self._ptt_active = False
        self._message_buffers: Dict[Tuple[int, int, int, int], List] = {}
        self._pending_join: Optional[ParsedTeamTalkFile] = None
        self._recording_active = False
        self._recording_path: Optional[str] = None
        self._video_tx_enabled = False
        self._mute_all = False
        self._move_target_channel_id: int = 0
        self._last_private_sender_id: Optional[int] = None
        self._last_private_message_text: str = ""
        self._status_message = ""
        self._status_mode: int = 0
        self._capture_hotkey_target: Optional[str] = None
        self._user_volume_levels: Dict[int, int] = {}
        self._user_media_muted: Dict[int, bool] = {}
        self._user_media_volumes: Dict[int, int] = {}
        self._user_stereo: Dict[str, str] = {}  # username -> "left"/"both"/"right"
        self._known_audio_devices: List[str] = []
        self._speaking_log: List[dict] = []  # {"nick": ..., "ts": ..., "seconds": ...}
        self._speaking_start: Dict[int, float] = {}  # user_id -> start_time
        self._channel_message_log: List[str] = []
        self._current_channel_name: str = ""
        self._server_session_ids: List[str] = []

        # Paths
        _app_dir = app_data_dir()
        _app_dir.mkdir(parents=True, exist_ok=True)

        # Database / settings
        self._settings_db = SettingsDB(_app_dir / "settings.db")
        migrate_from_json(
            self._settings_db,
            _app_dir / "settings.json",
            _app_dir / "servers.json",
        )
        self.settings_store = SQLiteSettingsStore(self._settings_db)
        self.store = SQLiteServerStore(self._settings_db)
        _lang = getattr(self.settings_store.settings, "app_language", "de") or "de"
        set_language(_lang)

        _log_path = _log_dir()
        _log_path.mkdir(parents=True, exist_ok=True)
        self.logger = FileLogger(_log_path / "client.log")
        self.logger.write(f"Programmstart — Version {APP_VERSION} — AppData: {_app_dir}")
        self._chat_history = ChatHistoryManager(_app_dir)
        self._saved_messages = SavedMessageManager(_app_dir)
        self._channel_notes = ChannelNotesManager(_app_dir)
        self._translator = ChatTranslatorManager(self.settings_store)
        self._ai_reply = AiReplyManager(self.settings_store)
        self._eq_presets = EqPresetsManager(_app_dir)
        self._offline_queue = OfflineMessageQueue(_app_dir)
        self._audit_log = AuditLog(_app_dir)
        self._cert_pins = CertPinStore(_app_dir)
        self._analytics = UsageAnalytics(_app_dir)
        self._health = HealthChecker()
        self._health.register("disk_space", check_disk_space)
        self._health.register("settings_db", lambda: check_settings_db(self._settings_db.path))

        # Event bus + plugins
        from event_bus import EventBus
        self.bus = EventBus()
        self._async_bridge = AsyncBusBridge(self.bus)
        self._async_bridge.start()
        from scheduled_recordings import ScheduledRecordingManager
        self._scheduled_rec_manager = ScheduledRecordingManager(_app_dir)
        from plugin_api import PluginAPI
        from plugin_loader import PluginLoader
        self._plugin_api = PluginAPI(self)
        self.server_manager = ServerManager(self.bus)
        self._ai_summary: Optional[ChatSummaryManager] = None
        self.bus.on("active_server_changed", self._on_active_server_changed)
        self.bus.on("server_state_changed", self._on_server_state_changed)
        plugins_dir = Path(__file__).parent.parent / "plugins"
        self._plugin_loader = PluginLoader(self.bus, plugins_dir, api=self._plugin_api)
        self._plugin_loader.load_all()
        self._current_server_key = ""

        # TTS
        self.tts = TTSManager(self)
        _ts = self.settings_store.settings
        self.tts.settings.enabled = _ts.tts_enabled
        self.tts.settings.speak_chat = _ts.tts_speak_chat
        self.tts.settings.speak_private = _ts.tts_speak_private
        self.tts.settings.speak_system = _ts.tts_speak_system
        self.tts.settings.speak_own = _ts.tts_speak_own
        self.tts.settings.interrupt = _ts.tts_interrupt
        self.tts.settings.language = _ts.tts_language
        self.tts.settings.voice = _ts.tts_voice
        self.tts.settings.rate = _ts.tts_rate
        self.tts.settings.volume = _ts.tts_volume
        self.tts.settings.espeak_path = _ts.tts_espeak_path
        self.tts.settings.speak_user_join = _ts.tts_speak_user_join
        self.tts.settings.speak_user_leave = _ts.tts_speak_user_leave
        self.tts.settings.speak_file_transfer = _ts.tts_speak_file_transfer
        self.tts.settings.speak_channel_topic = _ts.tts_speak_channel_topic
        self.tts.settings.connect_announce = _ts.tts_connect_announce
        self.tts.settings.chat_rate = getattr(_ts, "tts_chat_rate", 0) or 0
        self.tts.settings.system_rate = getattr(_ts, "tts_system_rate", 0) or 0
        self.tts.settings.channel_rate = getattr(_ts, "tts_channel_rate", 0) or 0
        self.tts.settings.chat_voice = getattr(_ts, "tts_chat_voice", "") or ""
        self.tts.settings.system_voice = getattr(_ts, "tts_system_voice", "") or ""

        self._screen_reader = ScreenReaderAnnouncer()

        self.sound_manager = SoundManager()
        self.sound_manager.set_pack_dir(getattr(_ts, "sound_pack_dir", "") or "")
        self._user_stereo = dict(getattr(_ts, "user_stereo_settings", {}) or {})
        _pron_rules = list(getattr(_ts, "pronunciation_rules", []) or [])
        if not _pron_rules:
            _pron_rules = dict(getattr(_ts, "pronunciation_dict", {}) or {})
        self._pronunciation = PronunciationManager(_pron_rules)
        self._bookmarks = BookmarkManager(self.settings_store)
        self._mute_scheduler = MuteScheduler(self)
        self._macros = MacroManager(self)
        self._auto_reply = AutoReplyManager(self)
        self._webhook = WebhookManager(self)
        self._http_api = HttpApiServer(self)
        self.braille = BrailleOutputManager(self.tts)
        _braille_verbosity = getattr(_ts, "braille_verbosity", "normal")
        self.braille.verbosity = _braille_verbosity if _braille_verbosity in ("compact", "normal", "verbose") else "normal"
        self._gemini_auth = GeminiAuthManager(_app_dir)
        self._ai_summary = ChatSummaryManager(self.settings_store, self._chat_history, self._gemini_auth)
        self._auto_reconnect = bool(getattr(_ts, "auto_reconnect_enabled", True))
        self._global_hotkey_mgr = None
        self._global_capture_target: Optional[str] = None

        # Build UI
        self._build_ui()
        self._build_menu()
        self._setup_tab_shortcuts()
        self.tray = TrayIcon(self)
        # Show Sprechen tab only when ElevenLabs API key is configured
        _eleven_key = getattr(self.settings_store.settings, "elevenlabs_api_key", "") or ""
        self._update_speak_tab(_eleven_key)

        # Status bar
        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._status_bar.showMessage(f"TeamTalk VoiceOver Client {APP_VERSION}")

        # Reconnect timer
        self._reconnect_timer = QTimer(self)
        self._reconnect_timer.timeout.connect(self._on_reconnect_tick)

        # Auto-away timer
        self._away_timer = QTimer(self)
        self._away_timer.timeout.connect(self._on_away_check)
        self._away_active = False
        self._activity_time = time.time()
        _away_min = int(getattr(_ts, "away_timer_min", 0) or 0)
        if _away_min > 0:
            self._away_timer.start(_away_min * 60 * 1000)

        # Start HTTP API if enabled
        if bool(getattr(_ts, "http_api_enabled", False)):
            try:
                self._http_api.start()
            except Exception as exc:
                self.logger.write(f"HTTP-API konnte nicht gestartet werden: {exc}")

        # AI summary after TTS ready
        self.bus.on("chat_message", lambda **kw: self._macros.fire_event("chat_message", **kw))
        self.bus.on("user_joined", lambda **kw: self._macros.fire_event("user_join", **kw))
        self.bus.on("user_left", lambda **kw: self._macros.fire_event("user_leave", **kw))
        self.bus.on("channel_joined", lambda **kw: self._macros.fire_event("channel_join", **kw))

        # Global hotkeys (macOS: NSEvent / Windows: GetAsyncKeyState polling)
        self.apply_global_hotkeys()

        # Audio device hotplug monitoring (5 s interval)
        self._audio_hotplug_timer = QTimer(self)
        self._audio_hotplug_timer.setInterval(5000)
        self._audio_hotplug_timer.timeout.connect(self._check_audio_hotplug)
        self._audio_hotplug_timer.start()
        self._known_audio_devices = self._get_audio_device_names()

        # Accessible name for main window (NVDA announces this)
        self.setAccessibleName(f"TeamTalk VoiceOver Client {APP_VERSION}")
        self.notebook.setAccessibleName("Registerkarten")
        self.notebook.setAccessibleDescription(
            "Hauptnavigation. Tab/Shift+Tab wechselt zwischen Registerkarten."
        )

        # Show
        if not bool(getattr(_ts, "start_minimized", False)):
            self.show()

    # ------------------------------------------------------------------
    # UI Construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(4, 4, 4, 4)

        # Connection status bar
        status_bar = QHBoxLayout()
        self._conn_label = QLabel("Nicht verbunden")
        self._conn_label.setAccessibleName("Verbindungsstatus")
        self._srv_disconnect_btn = QPushButton("&Trennen")
        self._srv_disconnect_btn.setAccessibleName("Vom Server trennen")
        self._srv_disconnect_btn.clicked.connect(self.on_menu_disconnect)
        self._srv_disconnect_btn.setEnabled(False)
        status_bar.addWidget(self._conn_label, 1)
        status_bar.addWidget(self._srv_disconnect_btn)
        root.addLayout(status_bar)

        # Quick-action toolbar (NVDA-accessible toggle buttons)
        tb_layout = QHBoxLayout()

        self._tb_ptt = QPushButton("PTT")
        self._tb_ptt.setCheckable(True)
        self._tb_ptt.setFixedWidth(50)
        self._tb_ptt.setAccessibleName("Push-to-Talk umschalten")
        self._tb_ptt.setAccessibleDescription("Aktiviert oder deaktiviert Push-to-Talk")
        self._tb_ptt.toggled.connect(self._on_toggle_ptt)
        tb_layout.addWidget(self._tb_ptt)

        self._tb_va = QPushButton("VA")
        self._tb_va.setCheckable(True)
        self._tb_va.setFixedWidth(50)
        self._tb_va.setAccessibleName("Sprachaktivierung umschalten")
        self._tb_va.setAccessibleDescription("Aktiviert oder deaktiviert die Sprachaktivierung")
        self._tb_va.toggled.connect(self._on_toggle_va)
        tb_layout.addWidget(self._tb_va)

        self._tb_mute = QPushButton("Stumm")
        self._tb_mute.setCheckable(True)
        self._tb_mute.setFixedWidth(60)
        self._tb_mute.setAccessibleName("Alle stummschalten")
        self._tb_mute.setAccessibleDescription("Schaltet alle Audioausgaben stumm")
        self._tb_mute.toggled.connect(self._on_toggle_mute_all)
        tb_layout.addWidget(self._tb_mute)

        self._tb_record = QPushButton("Aufn.")
        self._tb_record.setCheckable(True)
        self._tb_record.setFixedWidth(55)
        self._tb_record.setAccessibleName("Aufnahme starten oder stoppen")
        self._tb_record.toggled.connect(self._on_tb_record)
        tb_layout.addWidget(self._tb_record)

        self._tb_question = QPushButton("Frage")
        self._tb_question.setCheckable(True)
        self._tb_question.setFixedWidth(60)
        self._tb_question.setAccessibleName("Fragenmodus umschalten")
        self._tb_question.setAccessibleDescription("Hebt die Hand im Kanal")
        self._tb_question.toggled.connect(self._on_toggle_question_mode)
        tb_layout.addWidget(self._tb_question)

        vol_lbl = QLabel("Vol:")
        vol_lbl.setAccessibleName("Lautstärke")
        tb_layout.addWidget(vol_lbl)
        self._vol_slider = QSlider(Qt.Orientation.Horizontal)
        self._vol_slider.setRange(0, 200)
        self._vol_slider.setValue(100)
        self._vol_slider.setFixedWidth(80)
        self._vol_slider.setAccessibleName("Hauptlautstärke")
        self._vol_slider.setAccessibleDescription("Ausgabelautstärke, 0 bis 200 Prozent")
        self._vol_slider.valueChanged.connect(self._on_master_volume)
        tb_layout.addWidget(self._vol_slider)

        mic_lbl = QLabel("Mic:")
        mic_lbl.setAccessibleName("Mikrofon")
        tb_layout.addWidget(mic_lbl)
        self._mic_slider = QSlider(Qt.Orientation.Horizontal)
        self._mic_slider.setRange(0, 200)
        self._mic_slider.setValue(100)
        self._mic_slider.setFixedWidth(80)
        self._mic_slider.setAccessibleName("Mikrofonverstärkung")
        self._mic_slider.setAccessibleDescription("Mikrofonverstärkung, 0 bis 200 Prozent")
        self._mic_slider.valueChanged.connect(self._on_mic_gain)
        tb_layout.addWidget(self._mic_slider)

        tb_layout.addStretch()
        root.addLayout(tb_layout)

        # Tab widget — no connection tab, starts with channels
        self.notebook = QTabWidget()
        self.notebook.currentChanged.connect(self._on_tab_changed)
        root.addWidget(self.notebook, 1)

        # Channels + Chat (first tab — main view when connected)
        self._cc_tab = ChannelsChatTab(self.notebook, self)
        self.channels_tab = self._cc_tab.channels_tab
        self.chat_tab = self._cc_tab.chat_tab
        self.notebook.addTab(self._cc_tab, "Kanäle && Chat")

        # Media
        self.media_tab = MediaTab(self.notebook, self)
        self.notebook.addTab(self.media_tab, "Medien")

        # Files
        self.files_tab = FilesTab(self.notebook, self)
        self.notebook.addTab(self.files_tab, "Dateien")

        # Admin
        self.admin_tab = AdminTab(self.notebook, self)
        self.notebook.addTab(self.admin_tab, "Administration")

        # Speak (ElevenLabs) — added/removed dynamically by _update_speak_tab
        self.speak_tab = SpeakTab(self.notebook, self)
        self._speak_tab_added = False

        # Desktop share
        self.desktop_tab = DesktopTab(self.notebook, self)
        self.notebook.addTab(self.desktop_tab, "Desktop")

        # Settings — kein Tab mehr, sondern eigenständiges Fenster (Strg+,)
        self.settings_tab_widget = SettingsTab(self, self)
        self.audio_tab = self.settings_tab_widget.audio_tab
        self.video_tab = self.settings_tab_widget.video_tab
        self.shortcuts_tab = self.settings_tab_widget.shortcuts_tab
        self.system_tab = self.settings_tab_widget.system_tab
        from PySide6.QtWidgets import QDialog, QDialogButtonBox
        self._settings_dialog = QDialog(self)
        self._settings_dialog.setWindowTitle("Einstellungen")
        self._settings_dialog.resize(860, 640)
        _sdlg_layout = QVBoxLayout(self._settings_dialog)
        _sdlg_layout.addWidget(self.settings_tab_widget, 1)
        _sdlg_close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        _sdlg_close.rejected.connect(self._settings_dialog.hide)
        _sdlg_layout.addWidget(_sdlg_close)

    def _build_menu(self) -> None:
        mb = self.menuBar()

        # --- Datei ---
        datei = mb.addMenu("&Datei")
        self._add_action(datei, "&Verbinden...", self.on_menu_connect, "Ctrl+Return")
        self._add_action(datei, "&Trennen", self.on_menu_disconnect, "Ctrl+W")
        self._add_action(datei, "Neu &verbinden", self.reconnect, "Ctrl+Shift+R")
        self._auto_reconnect_action = self._add_checkable(datei, "Auto-&Reconnect",
            self._on_toggle_auto_reconnect,
            bool(getattr(self.settings_store.settings, "auto_reconnect_enabled", True)))
        datei.addSeparator()
        self._fav_menu = datei.addMenu("&Schnellverbindung")
        self._rebuild_favorites_menu()
        datei.addSeparator()
        self._add_action(datei, "&TT-Datei öffnen...", self.on_menu_open_tt_file)
        self._add_action(datei, "TT-&URL kopieren", self.copy_tt_url)
        datei.addSeparator()
        self._add_action(datei, "Neuen Client &starten", self.on_menu_new_client)
        datei.addSeparator()
        self._add_action(datei, "Server &prüfen", self.on_menu_server_check)
        datei.addSeparator()
        self._add_action(datei, "Serverliste &importieren...", self.on_menu_import_servers)
        self._add_action(datei, "Serverliste &exportieren...", self.on_menu_export_servers)
        datei.addSeparator()
        sound_sub = datei.addMenu("&Sound-Konfiguration")
        self._add_action(sound_sub, "Audio-Einstellungen...", self.on_menu_audio_settings)
        self._add_action(sound_sub, "Geräte a&ktualisieren", self.on_menu_audio_refresh)
        datei.addSeparator()
        self._add_action(datei, "Einstellungen &sichern (Backup)...", self.on_menu_settings_backup)
        self._add_action(datei, "Einstellungen &wiederherstellen...", self.on_menu_settings_restore)
        datei.addSeparator()
        self._add_action(datei, "&Beenden", self.force_close, "Ctrl+Q")

        # --- Kanal ---
        kanal = mb.addMenu("&Kanal")
        self._add_action(kanal, "Kanal &beitreten", self.on_menu_join_channel, "Ctrl+J")
        self._add_action(kanal, "&Root-Kanal beitreten", self.on_menu_join_root)
        self._add_action(kanal, "Kanal &verlassen", self.on_menu_leave_channel, "Ctrl+L")
        kanal.addSeparator()
        self._add_action(kanal, "Kanal &erstellen...", self.on_menu_create_channel, "F7")
        self._add_action(kanal, "Kanal &bearbeiten...", self.on_menu_edit_channel)
        self._add_action(kanal, "Kanal &löschen", self.on_menu_delete_channel)
        kanal.addSeparator()
        self._add_action(kanal, "Kanal&info vorlesen", self.on_menu_channel_info, "Ctrl+S")
        self._add_action(kanal, "Kanal-Statistiken &ansagen", self.on_menu_channel_stats_speak)
        self._add_action(kanal, "Kanalzustand &ansagen", self.on_menu_channel_state_speak)
        self._add_action(kanal, "Kanal-&Notiz bearbeiten...", self.on_menu_channel_note)
        self._add_action(kanal, "Kanal&nachricht senden...", self.on_menu_send_channel_msg, "F3")
        kanal.addSeparator()
        self._add_action(kanal, "&Datei hochladen...", self.on_menu_upload_file)
        self._add_action(kanal, "Datei &herunterladen", self.on_menu_download_file)
        kanal.addSeparator()
        self._add_action(kanal, "Sperren im Kanal anzeigen...", self.on_menu_channel_bans)
        self._add_action(kanal, "Kanal&nachrichten anzeigen...", self.on_menu_channel_view_msgs)
        self._add_action(kanal, "Kanal&verlauf...", self.on_menu_channel_history)
        self._recent_ch_menu = kanal.addMenu("&Zuletzt besucht")
        self._refresh_recent_channels_menu()
        kanal.addSeparator()
        stream_m = kanal.addMenu("&Streamen")
        for _label, _mode in [
            ("&YouTube/URL...", "url"),
            ("&SoundCloud...", "soundcloud"),
            ("&Twitch...", "twitch"),
            ("&Bandcamp...", "bandcamp"),
            ("&Vimeo...", "vimeo"),
            ("M&ixcloud...", "mixcloud"),
            ("&Webradio...", "radio"),
            ("&Podcast...", "podcast"),
            ("&Datei...", "file"),
            ("&Playlist...", "playlist"),
        ]:
            self._add_action(stream_m, _label,
                lambda checked=False, m=_mode: self._on_channel_stream_mode(m))
        stream_m.addSeparator()
        self._add_action(stream_m, "Audio-&Datei direkt streamen...", self.on_menu_stream_audio_file)

        # --- Benutzer ---
        benutzer = mb.addMenu("&Benutzer")
        self._add_action(benutzer, "&Benutzerinfo vorlesen", self.on_menu_user_info, "Ctrl+I")
        self._add_action(benutzer, "&Private Nachricht...", self.on_menu_private_msg, "Ctrl+T")
        benutzer.addSeparator()
        self._add_action(benutzer, "S&tummschalten (Sprache)", self.on_menu_mute_voice, "Ctrl+M")
        self._add_action(benutzer, "Stummschalten (&Mediendatei)", self.on_menu_mute_media)
        self._add_action(benutzer, "Lautstärke &einstellen...", self.on_menu_user_volume)
        self._add_action(benutzer, "Stereo-&Position...", self.on_menu_user_stereo)
        self._add_action(benutzer, "Lautstärke &hoch", self.on_menu_user_volume_up, "Ctrl+Right")
        self._add_action(benutzer, "Lautstärke &runter", self.on_menu_user_volume_down, "Ctrl+Left")
        self._add_action(benutzer, "Medien-Lautstärke h&och", self.on_menu_user_media_volume_up, "Ctrl+Alt+Up")
        self._add_action(benutzer, "Medien-Lautstärke &runter", self.on_menu_user_media_volume_down, "Ctrl+Alt+Down")
        benutzer.addSeparator()
        self._add_action(benutzer, "Aus Kanal &kicken", self.on_menu_kick, "Ctrl+K")
        self._add_action(benutzer, "Kicken + &Sperren", self.on_menu_kick_ban, "Ctrl+Shift+K")
        self._add_action(benutzer, "Vom &Server kicken", self.on_menu_kick_server)
        self._add_action(benutzer, "Vom Server kicken + &Bannen", self.on_menu_kick_ban_server)
        benutzer.addSeparator()
        self._add_action(benutzer, "Benutzer &verschieben", self.on_menu_move_user)
        self._add_action(benutzer, "Verschiebe-&Ziel merken", self.on_menu_store_move_target)
        self._add_action(benutzer, "Zum &Ziel verschieben", self.on_menu_move_to_target)
        self._add_action(benutzer, "&Operator geben/nehmen", self.on_menu_toggle_operator)
        benutzer.addSeparator()
        self._add_action(benutzer, "&Abonnements...", self.on_menu_subscriptions)
        self._add_action(benutzer, "Benutzer &positionieren...", self.on_menu_user_position)
        adv_m = benutzer.addMenu("Er&weitert")
        self._add_action(adv_m, "&Sprachstream weiterleiten", self.on_menu_relay_voice)
        self._add_action(adv_m, "&Medienstream weiterleiten", self.on_menu_relay_media)
        benutzer.addSeparator()
        self._all_mute_action = self._add_checkable(benutzer, "Alle &stummschalten",
            self._on_toggle_mute_all, self._mute_all)
        benutzer.addSeparator()
        tx_m = benutzer.addMenu("&Sendekontrolle")
        for _tx_label, _stype in [
            ("Sprache erlauben/sperren", "voice"),
            ("Video erlauben/sperren", "video"),
            ("Desktop erlauben/sperren", "desktop"),
            ("Mediendatei erlauben/sperren", "media"),
        ]:
            self._add_action(tx_m, _tx_label,
                lambda checked=False, st=_stype: self.on_menu_toggle_user_tx(st))

        # --- Profil ---
        profil = mb.addMenu("&Profil")
        self._add_action(profil, "&Nickname ändern...", self.on_menu_change_nick, "Ctrl+R")
        self._add_action(profil, "&Status setzen...", self.on_menu_status)
        profil.addSeparator()
        self._self_hear_action = self._add_checkable(profil, "Mich selbst &hören",
            self._on_toggle_self_hear,
            bool(getattr(self.settings_store.settings, "self_hear", False)))
        self._question_mode_action = self._add_checkable(profil, "&Frage-Modus",
            self._on_toggle_question_mode, False)
        profil.addSeparator()
        self._tts_active_action = self._add_checkable(profil, "&TTS aktiv",
            self._on_toggle_tts,
            bool(getattr(self.settings_store.settings, "tts_enabled", True)))
        _s = self.settings_store.settings
        self._tts_flag_chat = self._add_checkable(profil, "TTS: &Chat vorlesen",
            lambda checked: self._on_toggle_tts_flag("chat", checked),
            bool(getattr(_s, "tts_speak_chat", True)))
        self._tts_flag_private = self._add_checkable(profil, "TTS: &Privat vorlesen",
            lambda checked: self._on_toggle_tts_flag("private", checked),
            bool(getattr(_s, "tts_speak_private", True)))
        self._tts_flag_system = self._add_checkable(profil, "TTS: &System vorlesen",
            lambda checked: self._on_toggle_tts_flag("system", checked),
            bool(getattr(_s, "tts_speak_system", True)))
        self._tts_flag_own = self._add_checkable(profil, "TTS: &Eigene vorlesen",
            lambda checked: self._on_toggle_tts_flag("own", checked),
            bool(getattr(_s, "tts_speak_own", False)))
        profil.addSeparator()
        self._add_action(profil, "TTS-&Mitschrift...", self.on_menu_tts_transcript)

        # --- Audio ---
        audio_m = mb.addMenu("&Audio")
        self._ptt_action = self._add_checkable(audio_m, "&Push-to-Talk",
            self._on_toggle_ptt,
            bool(getattr(self.settings_store.settings, "ptt_enabled", False)), "F9")
        self._va_action = self._add_checkable(audio_m, "&Sprachaktivierung",
            self._on_toggle_va,
            bool(getattr(self.settings_store.settings, "voice_activation", False)))
        audio_m.addSeparator()
        self._agc_action = self._add_checkable(audio_m, "&AGC",
            self._on_toggle_agc,
            bool(getattr(self.settings_store.settings, "agc", False)))
        self._denoise_action = self._add_checkable(audio_m, "&Rauschunterdrückung",
            self._on_toggle_denoise,
            bool(getattr(self.settings_store.settings, "denoise", False)))
        self._echo_action = self._add_checkable(audio_m, "&Echounterdrückung",
            self._on_toggle_echo,
            bool(getattr(self.settings_store.settings, "echo_cancel", False)))
        self._loopback_action = self._add_checkable(audio_m, "&Mikrofontest",
            self._on_toggle_loopback_menu, False)
        audio_m.addSeparator()
        self._add_action(audio_m, "Audio-Einstellungen...", self.on_menu_audio_settings)
        self._add_action(audio_m, "Audio &anwenden", self.apply_audio_prefs)
        self._add_action(audio_m, "Geräte a&ktualisieren", self.on_menu_audio_refresh)
        self._add_action(audio_m, "Effekte &anwenden", self.on_menu_audio_effects)
        audio_m.addSeparator()
        self._add_action(audio_m, "&Equalizer-Voreinstellungen...", self.on_menu_equalizer)
        self._add_action(audio_m, "&Per-Server-Soundprofile...", self.on_menu_server_audio_profiles)

        # --- Chat ---
        chat_m = mb.addMenu("&Chat")
        self._add_action(chat_m, "Chat-Log &exportieren...", self.on_menu_chat_export)
        self._add_action(chat_m, "Letzte &TTS-Ansage wiederholen", self.on_menu_tts_repeat, "Ctrl+Shift+S")

        # --- Aufnahmen ---
        aufn = mb.addMenu("A&ufnahmen")
        self._add_action(aufn, "Aufnahme &starten...", self.on_menu_start_recording)
        self._add_action(aufn, "Aufnahme &stoppen", self.on_menu_stop_recording)
        aufn.addSeparator()
        self._add_action(aufn, "Konversationen au&fzeichnen...", self.on_menu_user_recording)
        aufn.addSeparator()
        self._add_action(aufn, "Geplante &Aufnahmen...", self.on_menu_scheduled_recordings)
        aufn.addSeparator()
        self._add_action(aufn, "Aufnahmen-&Browser...", self.on_menu_recordings_browser)

        # --- Server ---
        server_m = mb.addMenu("&Server")
        self._add_action(server_m, "&Online-Nutzer...", self.on_menu_online_users, "Ctrl+U")
        self._add_action(server_m, "Server&nachricht senden...", self.on_menu_server_message)
        self._add_action(server_m, "Server-&Statistiken...", self.on_menu_server_stats)
        server_m.addSeparator()
        self._add_action(server_m, "&Sperrliste...", self.on_menu_ban_list, "Ctrl+B")
        self._add_action(server_m, "&Administration...", self.on_menu_admin, "Ctrl+A")
        self._add_action(server_m, "Server&eigenschaften...", self.on_menu_server_properties)
        server_m.addSeparator()
        self._add_action(server_m, "&Wer-spricht-Protokoll...", self.on_menu_speaking_log)
        self._add_action(server_m, "&Sitzungsübersicht...", self.on_menu_session_overview)
        server_m.addSeparator()
        self._add_action(server_m, "&Ping ansagen", self.on_menu_announce_ping, "Ctrl+P")
        self._add_action(server_m, "Konfiguration &speichern", self.on_menu_server_save_config)

        # --- Automation ---
        auto_m = mb.addMenu("A&utomation")
        self._add_action(auto_m, "&Makro-Editor...", self.on_menu_macros, "Ctrl+Shift+M")
        self._add_action(auto_m, "Geplante &Makros...", self.on_menu_scheduled_macros)
        auto_m.addSeparator()
        self._add_action(auto_m, "&Trigger-Regeln...", self.on_menu_trigger_editor)
        self._add_action(auto_m, "&Aussprache-Wörterbuch...", self.on_menu_pronunciation)
        auto_m.addSeparator()
        self._add_action(auto_m, "&Chat-Suche...", self.on_menu_chat_search, "Ctrl+F")
        self._add_action(auto_m, "&Nutzerwatcher...", self.on_menu_user_watcher)
        self._add_action(auto_m, "&Offline-Warteschlange...", self.on_menu_offline_queue)
        auto_m.addSeparator()
        self._translation_action = self._add_checkable(auto_m, "Chat-&Übersetzung",
            self._on_toggle_translation,
            bool(getattr(self.settings_store.settings, "translation_enabled", False)))
        self._auto_channel_sum_action = self._add_checkable(auto_m, "Auto-&Kanal-Zusammenfassung",
            self._on_toggle_channel_summary,
            bool(getattr(self.settings_store.settings, "auto_channel_summary", False)))
        auto_m.addSeparator()
        self._add_action(auto_m, "&Plugin-Manager...", self.on_menu_plugin_manager)
        self._add_action(auto_m, "Per-Server-&Soundprofile...", self.on_menu_server_audio_profiles)
        auto_m.addSeparator()
        self._add_action(auto_m, "&Einstellungen...", self.on_menu_settings, "F4")

        # --- Hilfe ---
        hlp = mb.addMenu("&Hilfe")
        self._add_action(hlp, "Logs &exportieren...", self.on_menu_export_logs)
        self._add_action(hlp, "&Gesundheitsbericht...", self.on_menu_health_report)
        self._add_action(hlp, "Verbindungs&statistiken...", self.on_menu_client_stats)
        self._add_action(hlp, "Statistiken &vorlesen", self.on_menu_client_stats_speak)
        self._add_action(hlp, "&Gespeicherte Nachrichten...", self.on_menu_saved_messages)
        self._add_action(hlp, "Auf &Updates prüfen...", self.on_menu_check_updates)
        self._add_action(hlp, "Updates && &Versionen...", self.on_menu_update_manager)
        hlp.addSeparator()
        self._add_action(hlp, "&Handbuch...", self.on_menu_manual, "F1")
        self._add_action(hlp, "&Tastenkürzel-Referenz...", self.on_menu_shortcut_reference)
        self._add_action(hlp, "&Changelog...", self.on_menu_changelog)
        hlp.addSeparator()
        self._add_action(hlp, "&Startup-Profiler...", self.on_menu_startup_profiler)
        self._add_action(hlp, "&Nutzungsbericht...", self.on_menu_analytics_report)
        self._add_action(hlp, "&Info...", self.on_menu_about)

    def _add_checkable(self, menu: QMenu, label: str, slot, checked: bool = False, shortcut: str = "") -> QAction:
        action = QAction(label, self)
        action.setCheckable(True)
        action.setChecked(checked)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        action.triggered.connect(slot)
        menu.addAction(action)
        return action

    def _add_action(self, menu: QMenu, label: str, slot, shortcut: str = "") -> QAction:
        action = QAction(label, self)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        action.triggered.connect(slot)
        menu.addAction(action)
        return action

    def _setup_tab_shortcuts(self) -> None:
        for i in range(1, 10):
            sc = QShortcut(QKeySequence(f"Alt+{i}"), self)
            tab_idx = i - 1
            sc.activated.connect(lambda idx=tab_idx: self.notebook.setCurrentIndex(idx))

    # ------------------------------------------------------------------
    # tt_str helper
    # ------------------------------------------------------------------

    def tt_str(self, s) -> str:
        try:
            if isinstance(s, str):
                return s
            if isinstance(s, (bytes, bytearray)):
                return s.decode("utf-8", errors="replace")
            return str(s)
        except Exception:
            return ""

    # ------------------------------------------------------------------
    # Status bar
    # ------------------------------------------------------------------

    def set_status(self, text: str) -> None:
        self._status_bar.showMessage(text)
        if hasattr(self, "system_tab"):
            self.system_tab.append_system(text)
        if hasattr(self, "_screen_reader"):
            self._screen_reader.speak(text)

    # ------------------------------------------------------------------
    # TeamTalk Event Loop (driven by client.start_event_loop)
    # ------------------------------------------------------------------

    def _handle_tt_message(self, msg) -> None:
        tt = self.client.tt
        mtype = int(msg.nClientEvent)

        if mtype == int(tt.ClientEvent.CLIENTEVENT_CON_LOST):
            call_after(self._on_connection_lost)
        elif mtype == int(tt.ClientEvent.CLIENTEVENT_CMD_MYSELF_LOGGEDOUT):
            call_after(self._on_logged_out)
        elif mtype == int(tt.ClientEvent.CLIENTEVENT_CMD_CHANNEL_NEW):
            call_after(self._on_channel_update)
        elif mtype == int(tt.ClientEvent.CLIENTEVENT_CMD_CHANNEL_UPDATE):
            call_after(self._on_channel_update)
        elif mtype == int(tt.ClientEvent.CLIENTEVENT_CMD_CHANNEL_REMOVE):
            call_after(self._on_channel_update)
        elif mtype == int(tt.ClientEvent.CLIENTEVENT_CMD_USER_LOGGEDIN):
            call_after(self._on_user_loggedin, msg)
        elif mtype == int(tt.ClientEvent.CLIENTEVENT_CMD_USER_LOGGEDOUT):
            call_after(self._on_user_loggedout, msg)
        elif mtype == int(tt.ClientEvent.CLIENTEVENT_CMD_USER_JOINED):
            call_after(self._on_user_joined, msg)
        elif mtype == int(tt.ClientEvent.CLIENTEVENT_CMD_USER_LEFT):
            call_after(self._on_user_left, msg)
        elif mtype == int(tt.ClientEvent.CLIENTEVENT_CMD_USER_UPDATE):
            call_after(self._on_user_update, msg)
        elif mtype == int(tt.ClientEvent.CLIENTEVENT_CMD_MYSELF_JOINED):
            call_after(self._on_myself_joined, msg)
        elif mtype == int(tt.ClientEvent.CLIENTEVENT_CMD_MYSELF_LEFT):
            call_after(self._on_myself_left, msg)
        elif mtype == int(tt.ClientEvent.CLIENTEVENT_CMD_PROCESSINGMESSAGE):
            call_after(self._on_processing_message, msg)
        elif mtype == int(tt.ClientEvent.CLIENTEVENT_CMD_ERROR):
            call_after(self._on_cmd_error, msg)
        elif mtype == int(tt.ClientEvent.CLIENTEVENT_CMD_FILE_NEW):
            call_after(self._on_file_new, msg)
        elif mtype == int(tt.ClientEvent.CLIENTEVENT_CMD_FILE_REMOVE):
            call_after(self._on_file_remove, msg)
        elif mtype == int(tt.ClientEvent.CLIENTEVENT_FILETRANSFER):
            call_after(self._on_file_transfer, msg)
        elif mtype == int(tt.ClientEvent.CLIENTEVENT_USER_STATECHANGE):
            call_after(self._on_user_statechange, msg)
        elif mtype == int(tt.ClientEvent.CLIENTEVENT_CMD_USER_TEXTMESSAGE):
            call_after(self._on_text_message, msg)

    # ------------------------------------------------------------------
    # Connection Events
    # ------------------------------------------------------------------

    def _update_conn_bar(self, text: str, connected: bool = False) -> None:
        self._conn_label.setText(text)
        self._srv_disconnect_btn.setEnabled(connected)

    def _on_connection_lost(self) -> None:
        self._update_conn_bar("Verbindung verloren")
        self.set_status("Verbindung verloren")
        self.tts.speak("Verbindung verloren", kind="system")
        self.sound_manager.play("server_disconnect", self.settings_store.settings.sound_events.get("server_disconnect"))
        call_after(self._refresh_channels)
        if self._auto_reconnect:
            self._schedule_reconnect()

    def _handle_connect_result(self, result) -> None:
        if result.ok:
            self.notebook.setCurrentIndex(0)
            profile = getattr(self, "_last_profile", None)
            if profile:
                self._current_server_key = f"{profile.host}:{getattr(profile, 'tcp_port', 10333)}"
            server_name = (getattr(profile, "name", "") or getattr(profile, "host", "Server")) if profile else "Server"
            nick = getattr(profile, "nickname", "") if profile else ""
            self._update_conn_bar(f"Verbunden: {server_name}  |  Nickname: {nick}", connected=True)
            self.set_status(f"Angemeldet an {server_name}")
            self.tts.speak("Angemeldet", kind="system")
            self.sound_manager.play("server_connect", self.settings_store.settings.sound_events.get("server_connect"))
            self._audit_log.log(A_SERVER_CONNECT)
            self._drain_offline_queue()
            self._refresh_channels()
            self.client.start_event_loop(self._handle_tt_message)
        else:
            self._update_conn_bar("Verbindung fehlgeschlagen")
            self.set_status(result.message)
            if self._auto_reconnect:
                self._schedule_reconnect()

    def _on_logged_out(self) -> None:
        self._update_conn_bar("Nicht verbunden")
        self.set_status("Abgemeldet")
        self._refresh_channels()

    def _join_channel_by_path(self, path: str, password: str = "") -> None:
        try:
            channels = list(self.client.get_server_channels() or [])
            for ch in channels:
                name = self.tt_str(ch.szName)
                if name == path or f"/{name}" == path:
                    self.client.join_channel_by_id(int(ch.nChannelID), password)
                    return
        except Exception:
            pass

    # ------------------------------------------------------------------
    # User Events
    # ------------------------------------------------------------------

    def _on_user_loggedin(self, msg) -> None:
        pass

    def _on_user_loggedout(self, msg) -> None:
        pass

    def _on_user_joined(self, msg) -> None:
        try:
            user = msg.user
            uid = int(user.nUserID)
            my_id = int(self.client.get_my_user_id() or 0)
            if uid == my_id:
                return
            name = self.tt_str(user.szNickname) or self.tt_str(user.szUsername) or f"User#{uid}"
            ch_id = int(user.nChannelID)
            my_ch = int(self.client.get_my_channel_id() or 0)
            _muted_raw = str(getattr(self.settings_store.settings, "tts_muted_join_users", "") or "")
            _muted_list = [u.strip().lower() for u in _muted_raw.split(",") if u.strip()]
            _tts_muted = name.lower() in _muted_list if _muted_list else False
            if ch_id == my_ch:
                if self.tts.settings.speak_user_join and not _tts_muted:
                    self.tts.speak(f"{name} hat den Kanal betreten", kind="user_join")
                self.sound_manager.play("user_join", self.settings_store.settings.sound_events.get("user_join"))
                self._refresh_channels()
        except Exception:
            pass

    def _on_user_left(self, msg) -> None:
        try:
            user = msg.user
            uid = int(user.nUserID)
            my_id = int(self.client.get_my_user_id() or 0)
            if uid == my_id:
                return
            name = self.tt_str(user.szNickname) or self.tt_str(user.szUsername) or f"User#{uid}"
            _muted_raw = str(getattr(self.settings_store.settings, "tts_muted_join_users", "") or "")
            _muted_list = [u.strip().lower() for u in _muted_raw.split(",") if u.strip()]
            _tts_muted = name.lower() in _muted_list if _muted_list else False
            if self.tts.settings.speak_user_leave and not _tts_muted:
                self.tts.speak(f"{name} hat den Kanal verlassen", kind="user_leave")
            self.sound_manager.play("user_leave", self.settings_store.settings.sound_events.get("user_leave"))
            self._refresh_channels()
        except Exception:
            pass

    def _on_user_update(self, msg) -> None:
        # USER_UPDATE fires on every voice state change — no channel refresh here (too expensive).
        pass

    def _on_user_statechange(self, msg) -> None:
        try:
            tt = self.client.tt
            user = msg.user
            uid = int(user.nUserID)
            nick = self.tt_str(user.szNickname) or self.tt_str(user.szUsername) or f"User#{uid}"
            ustate = int(user.uUserState)
            voice_flag = int(tt.UserState.USERSTATE_VOICE)
            is_talking = bool(ustate & voice_flag)
            if is_talking:
                if uid not in self._speaking_start:
                    self._speaking_start[uid] = time.time()
            else:
                start = self._speaking_start.pop(uid, None)
                if start is not None:
                    duration_s = round(time.time() - start, 1)
                    self._speaking_log.append({
                        "nick": nick,
                        "ts": time.strftime("%H:%M:%S"),
                        "seconds": duration_s,
                    })
                    if len(self._speaking_log) > 200:
                        self._speaking_log = self._speaking_log[-200:]
        except Exception:
            pass

    def _on_channel_update(self) -> None:
        self._refresh_channels()

    def _on_myself_joined(self, msg) -> None:
        try:
            ch_id = int(msg.nChannelID)
            ch = self.client.get_channel(ch_id)
            if ch:
                self._current_channel_name = self.tt_str(ch.szName)
                topic = self.tt_str(ch.szTopic)
                announce = self._current_channel_name
                if topic:
                    announce += f" — {topic}"
                self.tts.speak(announce, kind="system")
                self._add_to_recent_channels(ch_id, self._current_channel_name)
        except Exception:
            pass
        if getattr(self.settings_store.settings, "auto_channel_summary", False):
            QTimer.singleShot(0, self._auto_channel_summary)
        self._refresh_channels()

    def _on_myself_left(self, msg) -> None:
        self._current_channel_name = ""
        self._refresh_channels()

    def _on_cmd_error(self, msg) -> None:
        try:
            err = msg.clienterrormsg
            code = int(err.nErrorNo)
            txt = self.tt_str(err.szErrorMsg)
            self.set_status(f"Server-Fehler {code}: {txt}")
        except Exception:
            pass

    def _on_processing_message(self, msg) -> None:
        pass

    # ------------------------------------------------------------------
    # Chat
    # ------------------------------------------------------------------

    def _on_text_message(self, msg) -> None:
        try:
            tt = self.client.tt
            tmsg = msg.textmessage
            content_parts = [tmsg]
            key = (int(tmsg.nMsgType), int(tmsg.nFromUserID), int(tmsg.nChannelID), 0)
            bucket = self._message_buffers.setdefault(key, [])
            bucket.append(tmsg)
            if not tmsg.bMore:
                content = tt.rebuildTextMessage(bucket)
                from_user = self.tt_str(tmsg.szFromUsername)
                msg_type = int(tmsg.nMsgType)
                from_id = int(tmsg.nFromUserID)
                my_id = int(self.client.get_my_user_id() or 0)
                is_own = bool(from_id and my_id and from_id == my_id)

                if msg_type == int(tt.TextMsgType.MSGTYPE_USER):
                    kind = "private"
                elif msg_type == int(tt.TextMsgType.MSGTYPE_CHANNEL):
                    kind = "chat"
                elif msg_type == int(tt.TextMsgType.MSGTYPE_BROADCAST):
                    kind = "system"
                else:
                    kind = "chat"

                self.chat_tab.append_message(
                    from_user, content,
                    private=(kind == "private"),
                    own=is_own,
                    kind=kind,
                )

                # Route private messages to the dedicated dialog if open
                if kind == "private" and not is_own:
                    try:
                        from ui_qt.private_chat_dialog import _open_dialogs
                        if from_id in _open_dialogs:
                            _open_dialogs[from_id].append_message(from_user, content, own=False)
                    except Exception:
                        pass

                if not is_own:
                    speak_text = f"{from_user}: {content}"
                    if kind == "private":
                        speak_text = f"Privat von {from_user}: {content}"
                        self._last_private_sender_id = from_id
                        self._last_private_message_text = str(content or "")
                        self.sound_manager.play("msg_private_rx", self.settings_store.settings.sound_events.get("msg_private_rx"))
                    else:
                        self.sound_manager.play("msg_channel_rx", self.settings_store.settings.sound_events.get("msg_channel_rx"))
                        # Keyword detection
                        kw_str = getattr(self.settings_store.settings, "highlight_keywords", "") or ""
                        if kw_str:
                            content_lower = content.lower()
                            for kw in kw_str.split(","):
                                kw = kw.strip().lower()
                                if kw and kw in content_lower:
                                    self.tts.speak(f"Stichwort: {kw}", kind="system")
                                    break
                    self.tts.speak(speak_text, kind=kind)
                else:
                    if kind == "private":
                        self.sound_manager.play("msg_private_tx", self.settings_store.settings.sound_events.get("msg_private_tx"))
                    else:
                        self.sound_manager.play("msg_channel_tx", self.settings_store.settings.sound_events.get("msg_channel_tx"))

                if kind == "chat":
                    ts = time.strftime("%H:%M:%S")
                    self._channel_message_log.append(f"[{ts}] {from_user}: {content}")
                    if len(self._channel_message_log) > 200:
                        self._channel_message_log = self._channel_message_log[-200:]

                self.bus.emit("chat_message", text=content, kind=kind,
                              from_user=from_user, from_id=from_id)
                self._message_buffers.pop(key, None)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Files
    # ------------------------------------------------------------------

    def _on_file_new(self, msg) -> None:
        self._refresh_files()

    def _on_file_remove(self, msg) -> None:
        self._refresh_files()

    def _on_file_transfer(self, msg) -> None:
        try:
            ft = msg.filetransfer
            pct = int(ft.nTransferred * 100 / max(1, ft.nFileSize))
            name = self.tt_str(ft.szRemoteFileName)
            self.files_tab.update_transfer_progress(name, pct)
            if pct >= 100:
                self.sound_manager.play("file_transfer", self.settings_store.settings.sound_events.get("file_transfer"))
                if getattr(self.tts.settings, "speak_file_transfer", True):
                    self.tts.speak(f"Dateitransfer abgeschlossen: {name}", kind="system")
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Refresh helpers
    # ------------------------------------------------------------------

    def _refresh_channels(self) -> None:
        try:
            self.channels_tab.refresh_channels_and_users()
        except Exception:
            pass

    def _refresh_files(self) -> None:
        try:
            ch_id = int(self.client.get_my_channel_id() or 0)
            if not ch_id:
                return
            files = list(self.client.get_channel_files(ch_id) or [])
            self.files_tab.update_file_list(files, self.tt_str)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Connection actions
    # ------------------------------------------------------------------

    def connect_to_server(self, profile) -> None:
        self._last_profile = profile
        self.set_status(f"Verbinde mit {profile.host}:{profile.tcp_port}...")
        self._update_conn_bar(f"Verbinde mit {profile.host}...")

        def worker():
            try:
                self.client.stop_event_loop_and_wait()
            except Exception:
                pass
            result = self.client.connect_and_login(
                host=profile.host,
                tcp_port=int(getattr(profile, "tcp_port", 10333) or 10333),
                udp_port=int(getattr(profile, "udp_port", 10333) or 10333),
                nickname=getattr(profile, "nickname", "") or "Gast",
                username=getattr(profile, "username", "") or "",
                password=getattr(profile, "password", "") or "",
                client_name="TeamTalk VO Client",
                encrypted=bool(getattr(profile, "encrypted", False)),
                timeout_ms=8000,
            )
            if result.ok:
                join_ch = getattr(profile, "channel", "") or ""
                ch_pw = getattr(profile, "channel_password", "") or ""
                if not join_ch:
                    server_key = f"{profile.host}:{getattr(profile, 'tcp_port', 10333)}"
                    ajc_map = getattr(self.settings_store.settings, "auto_join_channel_per_server", {}) or {}
                    join_ch = ajc_map.get(server_key, "")
                try:
                    if join_ch:
                        self.client.join_channel_by_path(join_ch, ch_pw)
                    else:
                        root_id = self.client.get_root_channel_id()
                        if root_id:
                            self.client.join_channel_by_id(root_id, "")
                except Exception as exc:
                    self.logger.write(f"Auto-join fehlgeschlagen: {exc}")
            call_after(self._handle_connect_result, result)

        threading.Thread(target=worker, daemon=True).start()

    def reconnect(self) -> None:
        profile = getattr(self, "_last_profile", None)
        if profile:
            self.connect_to_server(profile)

    def join_channel(self, channel_id: int, password: str = "") -> None:
        def _worker():
            try:
                self.client.join_channel_by_id(channel_id, password)
            except Exception as exc:
                call_after(self.set_status, f"Kanal-Beitritt fehlgeschlagen: {exc}")
        threading.Thread(target=_worker, daemon=True).start()

    def join_root_channel(self) -> None:
        try:
            root_id = self.client.get_root_channel_id()
            if root_id:
                self.join_channel(root_id)
        except Exception:
            pass

    def leave_channel(self) -> None:
        try:
            self.client.leave_channel()
        except Exception:
            pass

    def logout(self) -> None:
        try:
            self.client.stop_event_loop()
        except Exception:
            pass
        try:
            self.client.logout()
        except Exception:
            pass
        try:
            self.client.disconnect()
        except Exception:
            pass

    def copy_tt_url(self) -> None:
        profile = getattr(self, "_last_profile", None)
        if not profile:
            return
        try:
            from ui.tt_file_parser import build_teamtalk_url
            url = build_teamtalk_url(profile)
            QApplication.clipboard().setText(url)
            self.set_status("TT-URL in Zwischenablage kopiert")
        except Exception:
            pass

    def apply_global_hotkeys(self) -> None:
        import sys
        s = self.settings_store.settings
        enabled = bool(getattr(s, "global_hotkeys_enabled", False))
        if sys.platform == "darwin":
            from global_hotkeys import GlobalHotkeyManager
            from PySide6.QtCore import QTimer
            if not enabled:
                if self._global_hotkey_mgr is not None:
                    self._global_hotkey_mgr.stop()
                return
            if self._global_hotkey_mgr is None:
                self._global_hotkey_mgr = GlobalHotkeyManager()

            def _qt_call_after(fn):
                QTimer.singleShot(0, fn)

            self._global_hotkey_mgr.start(
                ptt_vk=int(getattr(s, "global_hotkey_ptt", 0) or 0),
                mute_vk=int(getattr(s, "global_hotkey_mute", 0) or 0),
                on_ptt_down=self._on_global_ptt_down,
                on_ptt_up=self._on_global_ptt_up,
                on_mute=self._on_global_mute,
                call_after=_qt_call_after,
            )
        elif sys.platform == "win32":
            try:
                from win32_hotkeys import Win32GlobalHotkeyManager
                from PySide6.QtCore import QTimer
                if hasattr(self, "_win32_hotkey_mgr") and self._win32_hotkey_mgr is not None:
                    self._win32_hotkey_mgr.stop()
                    self._win32_hotkey_mgr = None
                if not enabled:
                    return
                self._win32_hotkey_mgr = Win32GlobalHotkeyManager()

                def _qt_call_after(fn):
                    QTimer.singleShot(0, fn)

                self._win32_hotkey_mgr.start(
                    ptt_vk=int(getattr(s, "global_hotkey_ptt", 0) or 0),
                    mute_vk=int(getattr(s, "global_hotkey_mute", 0) or 0),
                    on_ptt_down=self._on_global_ptt_down,
                    on_ptt_up=self._on_global_ptt_up,
                    on_mute=self._on_global_mute,
                    call_after=_qt_call_after,
                )
            except Exception as exc:
                self.logger.write(f"Win32 globale Hotkeys: {exc}")

    def _on_global_ptt_down(self) -> None:
        try:
            self.client.enable_voice_transmission(True)
            self.set_status("Sprechen (global)")
        except Exception:
            pass

    def _on_global_ptt_up(self) -> None:
        try:
            self.client.enable_voice_transmission(False)
        except Exception:
            pass

    def _on_global_mute(self) -> None:
        self._mute_all = not self._mute_all
        try:
            self.client.set_sound_output_mute(self._mute_all)
            if hasattr(self, "_tb_mute"):
                self._tb_mute.setChecked(self._mute_all)
            if hasattr(self, "_all_mute_action"):
                self._all_mute_action.setChecked(self._mute_all)
        except Exception:
            pass
        self.set_status("Stummgeschaltet" if self._mute_all else "Stummschaltung aufgehoben")

    def _on_global_key_captured(self, vk: int) -> None:
        target = self._global_capture_target
        self._global_capture_target = None
        if not target:
            return
        if vk == 53:  # ESC (macOS VK)
            if hasattr(self, "shortcuts_tab"):
                self.shortcuts_tab.set_global_capture_label(target, False)
            self.set_status("Globaler Hotkey: Abgebrochen")
            return
        try:
            setattr(self.settings_store.settings, target, vk)
            self.settings_store.save()
        except Exception:
            pass
        if hasattr(self, "shortcuts_tab"):
            self.shortcuts_tab.set_global_capture_label(target, False)
            self.shortcuts_tab.update_labels()
        self.apply_global_hotkeys()
        self.set_status("Globales Tastenkürzel gespeichert")

    def start_hotkey_capture(self, key: str) -> None:
        self._capture_hotkey_target = key
        if hasattr(self, "shortcuts_tab"):
            self.shortcuts_tab.set_capture_label(key, True)
        self.set_status(f"Taste für '{key}' drücken...")

    def start_global_hotkey_capture(self, key: str) -> None:
        self._global_capture_target = key
        if hasattr(self, "shortcuts_tab"):
            self.shortcuts_tab.set_global_capture_label(key, True)
        import sys
        if sys.platform == "darwin":
            if self._global_hotkey_mgr is None:
                from global_hotkeys import GlobalHotkeyManager
                self._global_hotkey_mgr = GlobalHotkeyManager()
            from PySide6.QtCore import QTimer
            self._global_hotkey_mgr._call_after = lambda fn: QTimer.singleShot(0, fn)
            self._global_hotkey_mgr.capture_key_vk(self._on_global_key_captured)
            self.set_status("Globaler Hotkey: Taste drücken (ESC = Abbruch)...")
        else:
            self.set_status(f"Globaler Hotkey '{key}': Taste drücken (App muss Fokus haben)...")

    def keyPressEvent(self, event) -> None:
        if self._capture_hotkey_target:
            key = event.key()
            target = self._capture_hotkey_target
            self._capture_hotkey_target = None
            try:
                setattr(self.settings_store.settings, target, key)
                self.settings_store.save()
            except Exception:
                pass
            if hasattr(self, "shortcuts_tab"):
                self.shortcuts_tab.set_capture_label(target, False)
            if target == "ptt_key" and hasattr(self, "audio_tab"):
                self.audio_tab.update_ptt_hotkey_label()
            self.set_status("Tastenkürzel gespeichert")
            return
        if self._global_capture_target:
            import sys
            if sys.platform == "win32":
                vk = int(event.nativeVirtualKey() or event.key())
                target = self._global_capture_target
                self._global_capture_target = None
                try:
                    setattr(self.settings_store.settings, target, vk)
                    self.settings_store.save()
                except Exception:
                    pass
                if hasattr(self, "shortcuts_tab"):
                    self.shortcuts_tab.set_global_capture_label(target, False)
                    self.shortcuts_tab.update_labels()
                self.apply_global_hotkeys()
                self.set_status("Globales Tastenkürzel gespeichert")
                return
        key = event.key()
        # Feste F-Tasten (wie wx/math65)
        if key == Qt.Key.Key_F2:
            if self.client.is_connected():
                self.on_menu_disconnect()
            else:
                self.on_menu_connect()
            return
        if key == Qt.Key.Key_F5:
            if self.client.is_connected():
                self._refresh_channels()
            return
        if key == Qt.Key.Key_F6:
            self.on_menu_private_msg()
            return
        if key == Qt.Key.Key_F9:
            self._on_toggle_ptt(not self._ptt_enabled)
            return
        # Hold-to-Talk PTT-Taste
        ptt_key = getattr(self.settings_store.settings, "ptt_key", None)
        if ptt_key and key == ptt_key and not event.isAutoRepeat() and not self._ptt_active:
            self._ptt_active = True
            try:
                self.client.enable_voice_transmission(True)
            except Exception:
                pass
            return
        # Konfigurierbare Hotkeys (nur wenn kein Textfeld fokussiert)
        fw = self.focusWidget()
        from PySide6.QtWidgets import QLineEdit, QTextEdit, QPlainTextEdit
        if not isinstance(fw, (QLineEdit, QTextEdit, QPlainTextEdit)):
            settings = self.settings_store.settings
            if key and key == int(getattr(settings, "hotkey_mute_all", 0) or 0):
                new_mute = not self._mute_all
                self._all_mute_action.setChecked(new_mute)
                self._on_toggle_mute_all(new_mute)
                return
            if key and key == int(getattr(settings, "hotkey_voice_activation", 0) or 0):
                new_va = not bool(getattr(settings, "voice_activation", False))
                self._va_action.setChecked(new_va)
                self._on_toggle_va(new_va)
                return
            if key and key == int(getattr(settings, "hotkey_announce_ping", 0) or 0):
                self.on_menu_announce_ping()
                return
            if key and key == int(getattr(settings, "hotkey_cycle_braille_verbosity", 0) or 0):
                self.braille.cycle_verbosity()
                return
            for idx, hk_attr in enumerate([
                "hotkey_bookmark_1", "hotkey_bookmark_2", "hotkey_bookmark_3",
                "hotkey_bookmark_4", "hotkey_bookmark_5", "hotkey_bookmark_6",
                "hotkey_bookmark_7", "hotkey_bookmark_8", "hotkey_bookmark_9",
            ]):
                hk = int(getattr(settings, hk_attr, 0) or 0)
                if key and key == hk:
                    self._bookmarks.jump(self, idx)
                    return
            macro = self._macros.find_by_hotkey(key)
            if macro:
                self._macros.execute(macro)
                return
            if key and key == int(getattr(settings, "hotkey_tts_cancel", 0) or 0):
                self.tts._stop_current()
                self.tts.clear_queue()
                self.set_status("TTS abgebrochen")
                return
            if key and key == int(getattr(settings, "hotkey_volume_up", 0) or 0):
                new_vol = min(200, self._vol_slider.value() + 5)
                self._vol_slider.setValue(new_vol)
                self.set_status(f"Lautstärke: {new_vol}%")
                return
            if key and key == int(getattr(settings, "hotkey_volume_down", 0) or 0):
                new_vol = max(0, self._vol_slider.value() - 5)
                self._vol_slider.setValue(new_vol)
                self.set_status(f"Lautstärke: {new_vol}%")
                return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event) -> None:
        ptt_key = getattr(self.settings_store.settings, "ptt_key", None)
        if ptt_key and event.key() == ptt_key and not event.isAutoRepeat() and self._ptt_active:
            self._ptt_active = False
            try:
                self.client.enable_voice_transmission(False)
            except Exception:
                pass
            return
        super().keyReleaseEvent(event)

    # ------------------------------------------------------------------
    # Chat sending
    # ------------------------------------------------------------------

    def send_chat_message(self, text: str, private: bool = False, target_id: int = 0) -> None:
        self._reset_away()
        if not self.client.is_connected():
            oq = self._offline_queue
            if private and target_id:
                oq.enqueue(text, "private", target_id, f"User#{target_id}")
            else:
                oq.enqueue(text, "channel", 0, "Kanal")
            self.set_status("[Offline] Nachricht in Warteschlange gespeichert")
            return
        try:
            if private and target_id:
                self.client.send_user_message(target_id, text)
                self.sound_manager.play("msg_private_tx", self.settings_store.settings.sound_events.get("msg_private_tx"))
            else:
                self.client.send_channel_message(text)
                self.sound_manager.play("msg_channel_tx", self.settings_store.settings.sound_events.get("msg_channel_tx"))
        except Exception as exc:
            self.set_status(f"Senden fehlgeschlagen: {exc}")

    def save_message(self, text: str) -> None:
        try:
            self._saved_messages.add(text)
            self.set_status("Nachricht gespeichert")
        except Exception:
            pass

    # ------------------------------------------------------------------
    # File operations
    # ------------------------------------------------------------------

    def upload_file(self, path: str) -> None:
        try:
            ch_id = int(self.client.get_my_channel_id() or 0)
            if ch_id:
                self.client.send_file(ch_id, path)
        except Exception as exc:
            self.set_status(f"Upload fehlgeschlagen: {exc}")

    def download_file(self, file_id: int, save_path: str) -> None:
        try:
            self.client.receive_file(file_id, save_path)
        except Exception as exc:
            self.set_status(f"Download fehlgeschlagen: {exc}")

    def delete_file(self, file_id: int) -> None:
        try:
            self.client.delete_file(file_id)
        except Exception as exc:
            self.set_status(f"Löschen fehlgeschlagen: {exc}")

    def refresh_files(self) -> None:
        self._refresh_files()

    def show_file_history(self) -> None:
        if hasattr(self, "files_tab"):
            self.files_tab.on_history()

    # ------------------------------------------------------------------
    # Audio
    # ------------------------------------------------------------------

    def apply_audio_prefs(self) -> None:
        try:
            in_idx = self.audio_tab.input_device.currentIndex()
            out_idx = self.audio_tab.output_device.currentIndex()
            in_devs = self.audio_tab._input_devices
            out_devs = self.audio_tab._output_devices
            if in_devs and 0 <= in_idx < len(in_devs):
                self.client.close_sound_input_device()
                self.client.init_sound_input_device(int(in_devs[in_idx].nDeviceID))
            if out_devs and 0 <= out_idx < len(out_devs):
                self.client.close_sound_output_device()
                self.client.init_sound_output_device(int(out_devs[out_idx].nDeviceID))
            self.set_status("Audio-Einstellungen übernommen")
        except Exception as exc:
            self.set_status(f"Audio-Fehler: {exc}")

    def set_voice_activation(self, enabled: bool) -> None:
        try:
            self.client.enable_voice_activation(enabled)
        except Exception:
            pass

    def set_voice_activation_level(self, level: int) -> None:
        try:
            self.client.set_voice_activation_level(level)
        except Exception:
            pass

    def set_va_delay(self, ms: int) -> None:
        try:
            self.client.set_voice_activation_stop_delay(ms)
        except Exception:
            pass

    def _apply_noise_gate(self) -> None:
        try:
            enabled = bool(getattr(self.settings_store.settings, "noise_gate_enabled", False))
            fn = getattr(self.client, "enable_denoiser", None)
            if fn is not None:
                fn(enabled)
        except Exception:
            pass

    def set_mic_gain(self, db: int) -> None:
        try:
            level = max(0, min(32000, int(10000 * (10 ** (db / 20.0)))))
            self.client.set_sound_input_gain(level)
        except Exception:
            pass

    def set_out_gain(self, db: int) -> None:
        try:
            level = max(0, min(32000, int(10000 * (10 ** (db / 20.0)))))
            self.client.set_sound_output_volume(level)
        except Exception:
            pass

    def install_loopback(self) -> None:
        self.set_status("BlackHole-Installation: nur auf macOS verfügbar")

    # ------------------------------------------------------------------
    # Media / Recording
    # ------------------------------------------------------------------

    def start_recording(self, path: str, fmt: str = "wav") -> None:
        try:
            # AudioFileFormat: 1=wav, 2=ogg
            fmt_id = 2 if fmt.lower() == "ogg" else 1
            ok = self.client.start_recording_muxed(path, fmt_id)
            if ok:
                self._recording_active = True
                self._recording_path = path
                self.set_status(f"Aufnahme gestartet: {path}")
            else:
                self.set_status("Aufnahme konnte nicht gestartet werden")
        except Exception as exc:
            self.set_status(f"Aufnahme-Fehler: {exc}")

    def stop_recording(self) -> None:
        try:
            self.client.stop_recording_muxed()
            self._recording_active = False
            self.set_status("Aufnahme gestoppt")
        except Exception as exc:
            self.set_status(f"Aufnahme-Stopp-Fehler: {exc}")

    def start_media_stream(self, url: str, gain: float = 1.0) -> None:
        try:
            ok = self.client.start_streaming_media_to_channel(url, preamp_gain=gain)
            if ok:
                self.set_status(f"Streaming gestartet: {url}")
            else:
                self.set_status("Streaming konnte nicht gestartet werden")
        except Exception as exc:
            self.set_status(f"Streaming fehlgeschlagen: {exc}")

    def stop_media_stream(self) -> None:
        try:
            self.client.stop_streaming_media()
            self.set_status("Streaming gestoppt")
        except Exception:
            pass

    def configure_user_recording(self, enabled: bool, folder: str, pattern: str, fmt: int, include_self: bool) -> None:
        try:
            if enabled and folder:
                self.client.enable_user_recording(folder, pattern or "%Y%m%d-%H%M%S", fmt, include_self)
                self.set_status(f"Konversationsaufnahme aktiv: {folder}")
            else:
                self.client.disable_user_recording()
                self.set_status("Konversationsaufnahme deaktiviert")
        except Exception as exc:
            self.set_status(f"Aufnahme-Konfiguration fehlgeschlagen: {exc}")

    # ------------------------------------------------------------------
    # Admin
    # ------------------------------------------------------------------

    def load_user_accounts(self, list_widget) -> None:
        try:
            accounts = list(self.client.get_user_accounts() or [])
            self.admin_tab._accounts = accounts
            self.admin_tab.update_accounts(accounts, self.tt_str)
        except Exception as exc:
            self.set_status(f"Konten laden fehlgeschlagen: {exc}")

    def add_user_account(self) -> None:
        idx = self.notebook.indexOf(self.admin_tab)
        if idx >= 0:
            self.notebook.setCurrentIndex(idx)
        if hasattr(self, "admin_tab"):
            self.admin_tab.on_new_account()

    def delete_user_account(self, account) -> None:
        try:
            self.client.delete_user_account(self.tt_str(account.szUsername))
        except Exception as exc:
            self.set_status(f"Konto löschen fehlgeschlagen: {exc}")

    def load_ban_list(self, list_widget) -> None:
        try:
            bans = list(self.client.get_ban_list() or [])
            self.admin_tab._bans = bans
            self.admin_tab.update_bans(bans, self.tt_str)
        except Exception as exc:
            self.set_status(f"Sperren laden fehlgeschlagen: {exc}")

    def unban_entry(self, ban) -> None:
        try:
            ip = self.tt_str(ban.szIPAddress) if hasattr(ban, "szIPAddress") else ""
            if ip:
                self.client.unban_user(ip)
        except Exception as exc:
            self.set_status(f"Entsperren fehlgeschlagen: {exc}")

    def ban_ip_address(self) -> None:
        ip, ok = QInputDialog.getText(self, "IP-Adresse bannen", "IP-Adresse:")
        if ok and ip:
            try:
                self.client.do_ban_ip_address(ip)
                self.set_status(f"IP gebannt: {ip}")
            except Exception as exc:
                self.set_status(f"Bannen fehlgeschlagen: {exc}")

    def edit_server_properties(self) -> None:
        if not self.client.is_connected():
            self.set_status("Nicht verbunden")
            return
        idx = self.notebook.indexOf(self.admin_tab)
        if idx >= 0:
            self.notebook.setCurrentIndex(idx)
            try:
                self.admin_tab.srv_name.setFocus()
            except Exception:
                pass
        else:
            self.set_status("Administration-Tab nicht verfügbar")

    # ------------------------------------------------------------------
    # Desktop / Video
    # ------------------------------------------------------------------

    def start_desktop_share(self, monitor_idx: int, fps: int) -> None:
        self.set_status(f"Desktop-Freigabe gestartet (Monitor {monitor_idx}, {fps} fps)")

    def stop_desktop_share(self) -> None:
        self.set_status("Desktop-Freigabe gestoppt")

    def set_desktop_receive(self, enabled: bool) -> None:
        pass

    def start_video(self, cam_idx: int, fps: int) -> None:
        self.set_status(f"Video gestartet (Kamera {cam_idx}, {fps} fps)")

    def stop_video(self) -> None:
        self.set_status("Video gestoppt")

    def set_video_receive(self, enabled: bool) -> None:
        pass

    # ------------------------------------------------------------------
    # ElevenLabs
    # ------------------------------------------------------------------

    def _update_speak_tab(self, api_key: str) -> None:
        """Add/remove the Sprechen tab depending on whether an API key is configured."""
        if api_key:
            self.speak_tab.set_api_key(api_key)
            if not self._speak_tab_added:
                # Insert before Desktop so order stays: ..., Sprechen, Desktop
                desktop_idx = self.notebook.indexOf(self.desktop_tab)
                if desktop_idx >= 0:
                    self.notebook.insertTab(desktop_idx, self.speak_tab, "Sprechen")
                else:
                    self.notebook.addTab(self.speak_tab, "Sprechen")
                self._speak_tab_added = True
        else:
            if self._speak_tab_added:
                idx = self.notebook.indexOf(self.speak_tab)
                if idx >= 0:
                    self.notebook.removeTab(idx)
                self._speak_tab_added = False

    def refresh_elevenlabs_voices(self, tab=None) -> None:
        try:
            self.speak_tab.on_refresh()
        except Exception:
            pass

    def elevenlabs_generate_and_send(self, *args, **kwargs) -> None:
        try:
            self.speak_tab.on_speak()
        except Exception:
            pass

    def elevenlabs_stop(self) -> None:
        try:
            self.speak_tab.on_stop()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Server management
    # ------------------------------------------------------------------

    def add_server(self) -> None:
        self.set_status("Server hinzufügen: Formular verwenden")
        self.notebook.setCurrentIndex(0)

    def edit_server(self, idx: int) -> None:
        pass

    def remove_server(self, idx: int) -> None:
        profiles = self.store.items()
        if 0 <= idx < len(profiles):
            self.store.remove(idx)
            pass  # ConnectDialog reloads from store on open

    def enter_join_code(self) -> None:
        code, ok = QInputDialog.getText(self, "Beitrittscode", "Code eingeben:")
        if ok and code:
            self.set_status(f"Beitrittscode: {code}")

    def open_server_browser(self) -> None:
        from ui_qt.server_browser import ServerBrowserDialog
        dlg = ServerBrowserDialog(self)
        dlg.exec()
        self._refocus_channel_list()

    def manage_server_groups(self) -> None:
        from ui_qt.server_groups_dialog import ServerGroupsDialog
        dlg = ServerGroupsDialog(self)
        dlg.exec()
        self._refocus_channel_list()

    def import_tt_file(self, path: str) -> None:
        try:
            from ui.tt_file_parser import parse_teamtalk_file
            result = parse_teamtalk_file(Path(path))
            if result and result.profile and result.profile.host:
                profile = result.profile
                if not profile.name:
                    profile.name = Path(path).stem
                if result.channel_path:
                    profile.channel = result.channel_path
                if result.channel_password:
                    profile.channel_password = result.channel_password
                self.store.add(profile)
                self._rebuild_favorites_menu()
                self.set_status(f"TT-Datei importiert: {profile.name}")
            else:
                self.set_status("TT-Datei konnte nicht gelesen werden.")
        except Exception as exc:
            self.set_status(f"Import fehlgeschlagen: {exc}")

    def export_tt_file(self, idx: int) -> None:
        try:
            items = self.server_store.items()
            if idx < 0 or idx >= len(items):
                self.set_status("Kein Server ausgewählt")
                return
            profile = items[idx]
            from ui.tt_file_parser import build_teamtalk_xml
            default_name = f"{profile.name or profile.host}.tt"
            path, _ = QFileDialog.getSaveFileName(
                self, "Server als TT-Datei exportieren", default_name,
                "TeamTalk Datei (*.tt);;Alle Dateien (*.*)"
            )
            if not path:
                return
            xml_text = build_teamtalk_xml(profile)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(xml_text)
            self.set_status(f"Exportiert: {path}")
        except Exception as exc:
            self.set_status(f"Export fehlgeschlagen: {exc}")

    def open_private_chat(self, user_id: int) -> None:
        """Open a dedicated private chat dialog for user_id (non-modal)."""
        from ui_qt.private_chat_dialog import open_private_chat as _open
        nick = ""
        try:
            u = self.client.get_user(user_id)
            if u:
                nick = self.tt_str(u.szNickname) or self.tt_str(u.szUsername)
        except Exception:
            pass
        _open(self, user_id, nick)

    def kick_user(self, user_id: int) -> None:
        try:
            ch_id = int(self.client.get_my_channel_id() or 0)
            self.client.do_kick_user(user_id, ch_id)
        except Exception as exc:
            self.set_status(f"Kick fehlgeschlagen: {exc}")

    def mute_user(self, user_id: int) -> None:
        try:
            tt = self.client.tt
            stream_type = int(tt.StreamType.STREAMTYPE_VOICE)
            muted = self._user_volume_levels.get(user_id, 1) > 0
            self.client.set_user_mute(user_id, stream_type, muted)
            self._user_volume_levels[user_id] = 0 if muted else 16384
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Multi-server bus handlers
    # ------------------------------------------------------------------

    def _on_active_server_changed(self, **kwargs) -> None:
        pass

    def _on_server_state_changed(self, **kwargs) -> None:
        pass

    # ------------------------------------------------------------------
    # Offline queue
    # ------------------------------------------------------------------

    def _drain_offline_queue(self) -> None:
        try:
            messages = self._offline_queue.dequeue_all()
            if not messages:
                return
            for msg in messages:
                try:
                    if msg.get("kind") == "private" and msg.get("target_id"):
                        self.client.send_user_message(msg["target_id"], msg["text"])
                    else:
                        self.client.send_channel_message(msg["text"])
                except Exception:
                    pass
            count = len(messages)
            self.tts.speak(f"{count} Offline-Nachrichten gesendet", kind="system")
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Reconnect
    # ------------------------------------------------------------------

    def _schedule_reconnect(self) -> None:
        delay = int(getattr(self.settings_store.settings, "reconnect_delay_seconds", 10) or 10)
        self._reconnect_timer.start(delay * 1000)

    def _on_reconnect_tick(self) -> None:
        self._reconnect_timer.stop()
        self.reconnect()

    # ------------------------------------------------------------------
    # Auto-away
    # ------------------------------------------------------------------

    def _on_away_check(self) -> None:
        if self._away_active:
            return
        try:
            away_msg = getattr(self.settings_store.settings, "away_status", "") or "Abwesend"
            self.client.change_status(1, away_msg)
            self._away_active = True
            self.set_status(f"Auto-Abwesend: {away_msg}")
        except Exception:
            pass

    def _reset_away(self) -> None:
        if self._away_active:
            try:
                self.client.change_status(0, self._status_message)
                self._away_active = False
            except Exception:
                pass
        self._activity_time = time.time()

    # ------------------------------------------------------------------
    # Tab change
    # ------------------------------------------------------------------

    def _on_tab_changed(self, idx: int) -> None:
        tab_name = self.notebook.tabText(idx).replace("&&", "&")
        if hasattr(self, "tts"):
            self.tts.speak(tab_name, kind="system")

    def _on_server_choice_changed(self, idx: int) -> None:
        pass

    # ------------------------------------------------------------------
    # Menu handlers
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Datei-Menü
    # ------------------------------------------------------------------

    def _refocus_channel_list(self) -> None:
        try:
            self.channels_tab.channel_list.setFocus()
        except Exception:
            pass

    def on_menu_connect(self) -> None:
        dlg = ConnectDialog(self)
        dlg.exec()
        self._refocus_channel_list()

    def on_menu_disconnect(self) -> None:
        self._update_conn_bar("Nicht verbunden")
        self.logout()

    def on_menu_open_tt_file(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self, "TeamTalk-Datei öffnen", "", "TeamTalk-Dateien (*.tt);;Alle Dateien (*.*)"
        )
        if path:
            self.import_tt_file(path)

    def on_menu_new_client(self) -> None:
        try:
            if getattr(sys, "frozen", False):
                cmd = [sys.executable]
                cwd = None
            else:
                cmd = [sys.executable, os.path.abspath(__file__)]
                cwd = os.path.dirname(os.path.abspath(__file__))
            import subprocess
            subprocess.Popen(cmd, cwd=cwd)
            self.set_status("Neuer Client gestartet")
        except Exception as exc:
            self.set_status(f"Neuer Client konnte nicht gestartet werden: {exc}")

    def on_menu_server_check(self) -> None:
        dlg = ConnectDialog(self)
        dlg.exec()
        self._refocus_channel_list()

    def on_menu_import_servers(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self, "Serverliste importieren", "", "JSON (*.json);;Alle Dateien (*.*)"
        )
        if not path:
            return
        try:
            self.store.import_from(Path(path))
            self._rebuild_favorites_menu()
            self.set_status("Serverliste importiert")
        except Exception as exc:
            self.set_status(f"Import fehlgeschlagen: {exc}")

    def on_menu_export_servers(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(
            self, "Serverliste exportieren", "servers.json", "JSON (*.json);;Alle Dateien (*.*)"
        )
        if not path:
            return
        try:
            self.store.export_to(Path(path))
            self.set_status("Serverliste exportiert")
        except Exception as exc:
            self.set_status(f"Export fehlgeschlagen: {exc}")

    def on_menu_settings_backup(self) -> None:
        import zipfile as _zip
        import time as _time
        from platform_paths import app_data_dir as _app_data_dir
        from PySide6.QtWidgets import QFileDialog
        app_dir = _app_data_dir()
        default_name = f"teamtalk_backup_{_time.strftime('%Y%m%d_%H%M%S')}.zip"
        path, _ = QFileDialog.getSaveFileName(
            self, "Einstellungen sichern", default_name, "ZIP-Backup (*.zip);;Alle Dateien (*.*)"
        )
        if not path:
            return
        try:
            _BACKUP_EXTENSIONS = {".db", ".json", ".txt"}
            with _zip.ZipFile(path, "w", _zip.ZIP_DEFLATED) as zf:
                for f in app_dir.iterdir():
                    if f.is_file() and f.suffix.lower() in _BACKUP_EXTENSIONS:
                        zf.write(f, f.name)
            self.set_status(f"Backup erstellt: {Path(path).name}")
        except Exception as exc:
            self.set_status(f"Backup fehlgeschlagen: {exc}")

    def on_menu_settings_restore(self) -> None:
        import zipfile as _zip
        from platform_paths import app_data_dir as _app_data_dir
        from PySide6.QtWidgets import QFileDialog
        app_dir = _app_data_dir()
        path, _ = QFileDialog.getOpenFileName(
            self, "Backup wiederherstellen", "", "ZIP-Backup (*.zip);;Alle Dateien (*.*)"
        )
        if not path:
            return
        answer = QMessageBox.warning(
            self,
            "Backup wiederherstellen",
            "Achtung: Die aktuellen Einstellungen werden überschrieben.\n"
            "Die App wird danach neu gestartet.\n\nFortfahren?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            with _zip.ZipFile(path, "r") as zf:
                zf.extractall(app_dir)
            self.set_status("Backup wiederhergestellt – App wird neu gestartet…")
            QTimer.singleShot(1500, self._restart_app)
        except Exception as exc:
            self.set_status(f"Wiederherstellung fehlgeschlagen: {exc}")

    def _restart_app(self) -> None:
        import subprocess
        subprocess.Popen([sys.executable] + sys.argv)
        self.force_close()

    def _on_toggle_auto_reconnect(self, checked: bool) -> None:
        self._auto_reconnect = checked
        try:
            self.settings_store.settings.auto_reconnect_enabled = checked
            self.settings_store.save()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Kanal-Menü
    # ------------------------------------------------------------------

    def _get_selected_channel_id(self) -> int:
        try:
            return self.channels_tab.get_selected_channel_id() or 0
        except Exception:
            return 0

    def _build_codec_from_data(self, data: dict, parent_channel=None):
        codec_mode = data.get("audio_codec_mode", "inherit")
        if codec_mode == "keep":
            return None
        if codec_mode == "inherit" and parent_channel is not None:
            return getattr(parent_channel, "audiocodec", None)
        if codec_mode == "opus":
            codec = self.client.build_default_opus_codec()
            try:
                codec.opus.nSampleRate = int(data.get("opus_samplerate", 48000))
                codec.opus.nChannels = int(data.get("opus_channels", 1))
                codec.opus.nBitRate = int(data.get("opus_bitrate", 64)) * 1000
                codec.opus.bVBR = bool(data.get("opus_vbr", True))
                codec.opus.bDTX = bool(data.get("opus_dtx", False))
                codec.opus.nTxIntervalMSec = int(data.get("opus_tx_interval", 40))
                codec.opus.nFrameSizeMSec = int(data.get("opus_frame_size", 0))
                tt_mod = self.client.tt
                codec.opus.nApplication = int(
                    tt_mod.OPUS_APPLICATION_VOIP if data.get("opus_app", 0) == 0
                    else tt_mod.OPUS_APPLICATION_MUSIC
                )
            except Exception:
                pass
            return codec
        if codec_mode == "speex":
            codec = self.client.build_default_speex_codec()
            try:
                sr = int(data.get("speex_samplerate", 16000))
                codec.speex.nBandmode = {8000: 0, 16000: 1, 32000: 2}.get(sr, 1)
                codec.speex.nQuality = int(data.get("speex_quality", 4))
                codec.speex.nTxIntervalMSec = int(data.get("speex_tx_interval", 40))
            except Exception:
                pass
            return codec
        if codec_mode == "speex_vbr":
            codec = self.client.build_default_speex_vbr_codec()
            try:
                sr = int(data.get("speex_samplerate", 16000))
                codec.speex_vbr.nBandmode = {8000: 0, 16000: 1, 32000: 2}.get(sr, 1)
                codec.speex_vbr.nQuality = int(data.get("speex_quality", 4))
                codec.speex_vbr.nTxIntervalMSec = int(data.get("speex_tx_interval", 40))
                codec.speex_vbr.nMaxBitRate = int(data.get("speex_max_bitrate", 0))
                codec.speex_vbr.bDTX = bool(data.get("speex_dtx", True))
            except Exception:
                pass
            return codec
        if codec_mode == "none":
            return self.client.build_no_audio_codec()
        return None

    def on_menu_join_channel(self) -> None:
        try:
            self.channels_tab._on_join_btn()
        except Exception:
            pass

    def on_menu_join_root(self) -> None:
        self.join_root_channel()

    def on_menu_leave_channel(self) -> None:
        self.leave_channel()

    def on_menu_create_channel(self) -> None:
        if not self.client.is_connected():
            self.set_status("Nicht verbunden")
            return
        from ui_qt.channel_dialog import ChannelDialog
        parent_id = self._get_selected_channel_id() or int(self.client.get_root_channel_id() or 0)
        parent_ch = self.client.get_channel(parent_id) if parent_id else None
        default_codec = "opus"
        perm = False
        ch_type = 0
        quota = 0
        max_u = 0
        if parent_ch is not None:
            try:
                perm = bool(parent_ch.uChannelType & int(self.client.tt.ChannelType.CHANNEL_PERMANENT))
                ch_type = int(parent_ch.uChannelType or 0)
                quota = int(getattr(parent_ch, "nDiskQuota", 0) or 0) // (1024 * 1024)
                max_u = int(getattr(parent_ch, "nMaxUsers", 0) or 0)
                default_codec = "inherit"
            except Exception:
                pass
        dlg = ChannelDialog(
            self, title="Kanal erstellen",
            allow_password=True, permanent=perm,
            channel_type=ch_type, disk_quota_mb=quota, max_users=max_u,
            audio_codec_mode=default_codec,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        data = dlg.get_data()
        if not data["name"]:
            self.set_status("Kanalname fehlt")
            return
        try:
            rights = int(self.client.get_my_user_rights() or 0)
            can_modify = bool(rights & int(self.client.tt.UserRight.USERRIGHT_MODIFY_CHANNELS))
        except Exception:
            can_modify = False
        channel_type = int(data.get("channel_type", 0) or 0)
        if data.get("permanent") and can_modify:
            channel_type |= int(self.client.tt.ChannelType.CHANNEL_PERMANENT)
        audio_codec = self._build_codec_from_data(data, parent_ch)
        try:
            if can_modify:
                result = self.client.make_channel(
                    name=data["name"], parent_id=parent_id,
                    topic=data.get("topic", ""),
                    password=data.get("password", "") if data.get("set_password") else "",
                    permanent=bool(data.get("permanent") and can_modify),
                    channel_type=channel_type,
                    audio_codec=audio_codec,
                    disk_quota=int(data.get("disk_quota_mb", 0)) * 1024 * 1024,
                    max_users=int(data.get("max_users", 0)),
                    op_password=str(data.get("op_password", "")),
                )
            else:
                result = self.client.make_temporary_channel(
                    name=data["name"], parent_id=parent_id,
                    topic=data.get("topic", ""),
                    password=data.get("password", "") if data.get("set_password") else "",
                    channel_type=channel_type,
                    audio_codec=audio_codec,
                )
            self.set_status(result.message)
            if result.ok:
                self.channels_tab.refresh_channels_and_users()
        except Exception as exc:
            self.set_status(f"Kanal erstellen fehlgeschlagen: {exc}")
        self._refocus_channel_list()

    def on_menu_edit_channel(self) -> None:
        if not self.client.is_connected():
            self.set_status("Nicht verbunden")
            return
        chan_id = self._get_selected_channel_id()
        if not chan_id:
            self.set_status("Kein Kanal ausgewählt")
            return
        channel = self.client.get_channel(chan_id)
        if not channel:
            self.set_status("Kanal nicht gefunden")
            return
        try:
            rights = int(self.client.get_my_user_rights() or 0)
            can_modify = bool(rights & int(self.client.tt.UserRight.USERRIGHT_MODIFY_CHANNELS))
        except Exception:
            can_modify = False
        try:
            users_in_channel = list(self.client.get_channel_users(chan_id))
        except Exception:
            users_in_channel = []
        from ui_qt.channel_dialog import ChannelDialog
        dlg = ChannelDialog(
            self, title="Kanal bearbeiten",
            name=self.tt_str(channel.szName),
            topic=self.tt_str(channel.szTopic),
            permanent=bool(channel.uChannelType & int(self.client.tt.ChannelType.CHANNEL_PERMANENT)),
            allow_password=True,
            channel_type=int(channel.uChannelType or 0),
            disk_quota_mb=int(getattr(channel, "nDiskQuota", 0) or 0) // (1024 * 1024),
            max_users=int(getattr(channel, "nMaxUsers", 0) or 0),
            op_password=self.tt_str(getattr(channel, "szOpPassword", "")),
            audio_codec_mode="keep",
            audio_codec_locked=bool(users_in_channel),
            edit_mode=True,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        data = dlg.get_data()
        if not data["name"]:
            self.set_status("Kanalname fehlt")
            return
        try:
            channel.szName = self.client.tt.ttstr(data["name"])
            channel.szTopic = self.client.tt.ttstr(data.get("topic", ""))
            if data.get("set_password"):
                pw = data.get("password", "")
                channel.szPassword = self.client.tt.ttstr(pw)
                channel.bPassword = bool(pw)
            if can_modify:
                channel_type = int(data.get("channel_type", 0) or 0)
                if data.get("permanent"):
                    channel_type |= int(self.client.tt.ChannelType.CHANNEL_PERMANENT)
                channel.uChannelType = channel_type
                channel.nDiskQuota = int(data.get("disk_quota_mb", 0)) * 1024 * 1024
                channel.nMaxUsers = int(data.get("max_users", 0))
                op_pw = str(data.get("op_password", "")).strip()
                if op_pw:
                    channel.szOpPassword = self.client.tt.ttstr(op_pw)
                codec_mode = data.get("audio_codec_mode")
                if not users_in_channel and codec_mode and codec_mode != "keep":
                    new_codec = self._build_codec_from_data(data, None)
                    if new_codec is not None:
                        channel.audiocodec = new_codec
            result = self.client.update_channel(channel)
            self.set_status(result.message)
            if result.ok:
                self.channels_tab.refresh_channels_and_users()
        except Exception as exc:
            self.set_status(f"Kanal bearbeiten fehlgeschlagen: {exc}")
        self._refocus_channel_list()

    def on_menu_delete_channel(self) -> None:
        if not self.client.is_connected():
            self.set_status("Nicht verbunden")
            return
        chan_id = self._get_selected_channel_id()
        if not chan_id:
            self.set_status("Kein Kanal ausgewählt")
            return
        channel = self.client.get_channel(chan_id)
        name = self.tt_str(channel.szName) if channel else str(chan_id)
        reply = QMessageBox.question(
            self, "Kanal löschen",
            f'Kanal "{name}" wirklich löschen?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            result = self.client.remove_channel(chan_id)
            self.set_status(result.message)
            if result.ok:
                self.channels_tab.refresh_channels_and_users()
        except Exception as exc:
            self.set_status(f"Kanal löschen fehlgeschlagen: {exc}")

    def on_menu_channel_info(self) -> None:
        try:
            ch_id = self._get_selected_channel_id() or int(self.client.get_my_channel_id() or 0)
            if not ch_id:
                self.set_status("Kein Kanal")
                return
            ch = self.client.get_channel(ch_id)
            if ch:
                name = self.tt_str(ch.szName)
                topic = self.tt_str(ch.szTopic)
                max_users = int(getattr(ch, "nMaxUsers", 0) or 0)
                disk_mb = int(getattr(ch, "nDiskQuota", 0) or 0) // (1024 * 1024)
                try:
                    users = list(self.client.get_channel_users(ch_id) or [])
                    user_count = len(users)
                except Exception:
                    user_count = 0
                info = f"Kanal: {name}, {user_count} Nutzer, maximal {max_users}, Diskquota {disk_mb} MB"
                if topic:
                    info += f", Thema: {topic}"
                self.tts.speak(info, kind="system")
                self.set_status(info)
        except Exception as exc:
            self.set_status(f"Kanalinfo Fehler: {exc}")

    def on_menu_channel_stats_speak(self) -> None:
        try:
            ch_id = int(self.client.get_my_channel_id() or 0)
            if not ch_id:
                self.set_status("Kein Kanal")
                return
            users = list(self.client.get_channel_users(ch_id) or [])
            count = len(users)
            text = f"{count} Nutzer im Kanal"
            self.tts.speak(text, kind="system")
            self.set_status(text)
        except Exception as exc:
            self.set_status(f"Kanalstatistiken Fehler: {exc}")

    def on_menu_channel_state_speak(self) -> None:
        try:
            tt = self.client.tt
            ch_id = int(self.client.get_my_channel_id() or 0)
            if not ch_id:
                self.set_status("Kein Kanal")
                return
            users = list(self.client.get_channel_users(ch_id) or [])
            voice_flag = int(tt.UserState.USERSTATE_VOICE)
            media_flag = int(getattr(tt.UserState, "USERSTATE_MEDIAFILE_AUDIO", 0) or 0)
            transmitting = []
            for user in users:
                ustate = int(user.uUserState)
                if ustate & voice_flag or (media_flag and ustate & media_flag):
                    nick = self.tt_str(user.szNickname) or self.tt_str(user.szUsername) or f"User#{int(user.nUserID)}"
                    transmitting.append(nick)
            text = ("Spricht: " + ", ".join(transmitting)) if transmitting else "Niemand spricht"
            self.tts.speak(text, kind="system")
            self.set_status(text)
        except Exception as exc:
            self.set_status(f"Kanalzustand Fehler: {exc}")

    def on_menu_channel_note(self) -> None:
        ch_id = int(self.client.get_my_channel_id() or 0)
        key = f"channel_note_{ch_id}"
        current = getattr(self.settings_store.settings, key, "") or ""
        text, ok = QInputDialog.getMultiLineText(self, "Kanal-Notiz", "Notiz:", current)
        if ok:
            try:
                setattr(self.settings_store.settings, key, text)
                self.settings_store.save()
                self.set_status("Kanal-Notiz gespeichert")
            except Exception:
                pass

    def on_menu_send_channel_msg(self) -> None:
        text, ok = QInputDialog.getText(self, "Kanalnachricht", "Nachricht:")
        if ok and text:
            self.send_chat_message(text)

    def on_menu_upload_file(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(self, "Datei hochladen", "", "Alle Dateien (*.*)")
        if path:
            self.upload_file(path)

    def on_menu_download_file(self) -> None:
        try:
            self.files_tab._on_download()
        except Exception:
            self.set_status("Datei herunterladen: Dateien-Tab öffnen")

    def on_menu_stream_audio_file(self) -> None:
        if not self._require_connected("Audio-Datei streamen"):
            return
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self, "Audio-Datei auswählen", "",
            "Audio-Dateien (*.wav *.mp3 *.ogg *.flac *.aac *.m4a);;Alle Dateien (*.*)")
        if not path:
            return
        try:
            fn = getattr(self.client, "start_media_file_stream", None)
            if fn:
                fn(path)
                self.set_status(f"Streaming: {path}")
            else:
                self.set_status("Audio-Streaming nicht verfügbar (SDK)")
        except Exception as exc:
            self.set_status(f"Stream-Fehler: {exc}")

    def on_menu_channel_bans(self) -> None:
        if not self.client.is_connected():
            self.set_status("Nicht verbunden")
            return
        try:
            ch_id = int(self.client.get_my_channel_id() or 0)
        except Exception:
            ch_id = 0
        if not ch_id:
            self.set_status("Kein Kanal ausgewählt")
            return
        try:
            from ui_qt.dialogs import BanListDialog
            dlg = BanListDialog(self, self)
            dlg.setWindowTitle("Sperren im Kanal")
            self.ban_dialog = dlg
            dlg.clear()
            def worker():
                try:
                    self.client.do_list_bans(int(ch_id))
                except Exception as exc:
                    call_after(lambda: self.set_status(f"Sperren laden fehlgeschlagen: {exc}"))
            threading.Thread(target=worker, daemon=True).start()
            dlg.exec()
            self.ban_dialog = None
        except ImportError:
            self.set_status("Sperren im Kanal: Dialog nicht verfügbar")
        self._refocus_channel_list()

    def on_menu_channel_view_msgs(self) -> None:
        if not self._channel_message_log:
            QMessageBox.information(self, "Kanalnachrichten", "Keine Kanalnachrichten gespeichert.")
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Kanalnachrichten")
        dlg.resize(640, 420)
        layout = QVBoxLayout(dlg)
        te = QTextEdit()
        te.setReadOnly(True)
        te.setPlainText("\n".join(self._channel_message_log))
        layout.addWidget(te, 1)
        btn_layout = QHBoxLayout()
        clear_btn = QPushButton("&Leeren")
        close_btn = QPushButton("&Schließen")
        btn_layout.addWidget(clear_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)
        clear_btn.clicked.connect(lambda: (self._channel_message_log.clear(), te.clear()))
        close_btn.clicked.connect(dlg.accept)
        dlg.exec()
        self._refocus_channel_list()

    def on_menu_channel_history(self) -> None:
        s = self.settings_store.settings
        channels = list(getattr(s, "recent_channels", []) or [])
        dlg = QDialog(self)
        dlg.setWindowTitle("Kanalverlauf")
        dlg.resize(560, 380)
        layout = QVBoxLayout(dlg)
        if not channels:
            layout.addWidget(QLabel("Noch keine Kanäle besucht."))
        else:
            layout.addWidget(QLabel(f"{len(channels)} zuletzt besuchte Kanal/Kanäle:"))
            lw = QListWidget()
            for entry in channels:
                name = entry.get("name", "") or str(entry.get("channel_id", "?"))
                server = entry.get("server_key", "")
                label = f"{name}  [{server}]" if server else name
                lw.addItem(label)
            layout.addWidget(lw, 1)
            btn_layout = QHBoxLayout()
            join_btn = QPushButton("&Beitreten")
            clear_btn = QPushButton("&Verlauf leeren")
            btn_layout.addWidget(join_btn)
            btn_layout.addWidget(clear_btn)
            layout.addLayout(btn_layout)

            def _on_join():
                idx = lw.currentRow()
                if 0 <= idx < len(channels):
                    entry = channels[idx]
                    ch_id = entry.get("channel_id")
                    if ch_id and self.client.is_connected():
                        dlg.accept()
                        self.join_channel(int(ch_id))
                    else:
                        self.set_status("Nicht verbunden oder keine Kanal-ID")

            def _on_clear():
                answer = QMessageBox.question(dlg, "Verlauf leeren", "Kanalverlauf wirklich leeren?")
                if answer == QMessageBox.StandardButton.Yes:
                    self.settings_store.settings.recent_channels = []
                    self.settings_store.save()
                    lw.clear()
                    channels.clear()

            join_btn.clicked.connect(_on_join)
            clear_btn.clicked.connect(_on_clear)
            lw.itemDoubleClicked.connect(lambda _: _on_join())

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(dlg.reject)
        layout.addWidget(bb)
        dlg.exec()
        self._refocus_channel_list()

    # ------------------------------------------------------------------
    # Benutzer-Menü
    # ------------------------------------------------------------------

    def _get_selected_user_id(self) -> int:
        try:
            return self.channels_tab.get_selected_user_id() or 0
        except Exception:
            return 0

    def on_menu_user_info(self) -> None:
        uid = self._get_selected_user_id()
        if not uid:
            self.set_status("Bitte Benutzer auswählen")
            return
        try:
            user = self.client.get_user(uid)
            if user:
                nick = self.tt_str(user.szNickname) or self.tt_str(user.szUsername) or "Benutzer"
                ch_id = int(getattr(user, "nChannelID", 0) or 0)
                channel_name = ""
                if ch_id:
                    ch = self.client.get_channel(ch_id)
                    if ch is not None:
                        channel_name = self.tt_str(ch.szName)
                info = f"{nick} in Kanal {channel_name or ch_id}"
                self.tts.speak(info, kind="system")
                self.set_status(info)
        except Exception as exc:
            self.set_status(f"Benutzerinfo Fehler: {exc}")

    def on_menu_private_msg(self) -> None:
        uid = self._get_selected_user_id()
        if not uid:
            self.set_status("Bitte Benutzer auswählen")
            return
        text, ok = QInputDialog.getText(self, "Private Nachricht", "Nachricht:")
        if ok and text:
            self.send_chat_message(text, private=True, target_id=uid)

    def on_menu_mute_voice(self) -> None:
        uid = self._get_selected_user_id()
        if uid:
            self.mute_user(uid)

    def on_menu_mute_media(self) -> None:
        uid = self._get_selected_user_id()
        if not uid:
            self.set_status("Bitte Benutzer auswählen")
            return
        try:
            tt = self.client.tt
            user = self.client.get_user(uid)
            try:
                muted = bool(int(user.uUserState) & int(tt.UserState.USERSTATE_MUTE_MEDIAFILE))
            except AttributeError:
                muted = self._user_media_muted.get(uid, False)
            self.client.set_user_mute(uid, int(tt.StreamType.STREAMTYPE_MEDIAFILE_AUDIO), not muted)
            self._user_media_muted[uid] = not muted
            self.set_status("Medienstream entstummt" if muted else "Medienstream stummgeschaltet")
        except Exception as exc:
            self.set_status(f"Medienstumm Fehler: {exc}")

    def on_menu_user_volume(self) -> None:
        uid = self._get_selected_user_id()
        if not uid:
            self.set_status("Bitte Benutzer auswählen")
            return
        current = self._user_volume_levels.get(uid, 16384)
        vol, ok = QInputDialog.getInt(self, "Lautstärke", f"Lautstärke für User#{uid} (0–32000):", current, 0, 32000)
        if ok:
            try:
                tt = self.client.tt
                self.client.set_user_volume(uid, int(tt.StreamType.STREAMTYPE_VOICE), vol)
                self._user_volume_levels[uid] = vol
                self.set_status(f"Lautstärke für User#{uid}: {vol}")
            except Exception as exc:
                self.set_status(f"Lautstärke-Fehler: {exc}")

    def _get_user_volume_level(self, uid: int) -> int:
        return self._user_volume_levels.get(uid, 16384)

    def _set_user_volume_level(self, uid: int, level: int) -> int:
        level = max(0, min(32000, level))
        try:
            tt = self.client.tt
            self.client.set_user_volume(uid, int(tt.StreamType.STREAMTYPE_VOICE), level)
            self._user_volume_levels[uid] = level
        except Exception:
            pass
        return level

    def on_menu_user_volume_up(self) -> None:
        uid = self._get_selected_user_id()
        if not uid:
            self.set_status("Bitte Benutzer auswählen")
            return
        new_level = self._set_user_volume_level(uid, self._get_user_volume_level(uid) + 1000)
        self.set_status(f"Lautstärke: {new_level}")

    def on_menu_user_volume_down(self) -> None:
        uid = self._get_selected_user_id()
        if not uid:
            self.set_status("Bitte Benutzer auswählen")
            return
        new_level = self._set_user_volume_level(uid, self._get_user_volume_level(uid) - 1000)
        self.set_status(f"Lautstärke: {new_level}")

    def on_menu_user_media_volume_up(self) -> None:
        uid = self._get_selected_user_id()
        if not uid:
            self.set_status("Bitte Benutzer auswählen")
            return
        current = self._user_media_volumes.get(uid, 16384)
        new_level = max(0, min(32000, current + 1000))
        try:
            tt = self.client.tt
            self.client.set_user_volume(uid, int(tt.StreamType.STREAMTYPE_MEDIAFILE_AUDIO), new_level)
            self._user_media_volumes[uid] = new_level
            self.set_status(f"Medien-Lautstärke: {new_level}")
        except Exception as exc:
            self.set_status(f"Medien-Lautstärke Fehler: {exc}")

    def on_menu_user_media_volume_down(self) -> None:
        uid = self._get_selected_user_id()
        if not uid:
            self.set_status("Bitte Benutzer auswählen")
            return
        current = self._user_media_volumes.get(uid, 16384)
        new_level = max(0, min(32000, current - 1000))
        try:
            tt = self.client.tt
            self.client.set_user_volume(uid, int(tt.StreamType.STREAMTYPE_MEDIAFILE_AUDIO), new_level)
            self._user_media_volumes[uid] = new_level
            self.set_status(f"Medien-Lautstärke: {new_level}")
        except Exception as exc:
            self.set_status(f"Medien-Lautstärke Fehler: {exc}")

    def on_menu_user_stereo(self) -> None:
        uid = self._get_selected_user_id()
        if not uid:
            self.set_status("Bitte Benutzer auswählen")
            return
        try:
            user = self.client.get_user(uid)
            username = self.tt_str(getattr(user, "szUsername", "")) if user else str(uid)
        except Exception:
            username = str(uid)
        current = self._user_stereo.get(username, "both")
        options = ["Links", "Beide", "Rechts"]
        idx_map = {"left": 0, "both": 1, "right": 2}
        cur_idx = idx_map.get(current, 1)
        item, ok = QInputDialog.getItem(self, "Stereo-Position",
            f"Wo soll {username or uid} zu hören sein?",
            options, cur_idx, False)
        if not ok:
            return
        pos_map = {"Links": "left", "Beide": "both", "Rechts": "right"}
        pos = pos_map.get(item, "both")
        self._user_stereo[username] = pos
        self.settings_store.settings.user_stereo_settings[username] = pos
        self.settings_store.save()
        try:
            from TeamTalkPy import TeamTalk5 as _tt5
            left = pos in ("left", "both")
            right = pos in ("right", "both")
            st_voice = int(self.client.tt.StreamType.STREAMTYPE_VOICE)
            st_media = int(self.client.tt.StreamType.STREAMTYPE_MEDIAFILE_AUDIO)
            _tt5._SetUserStereo(self.client.tt._tt, uid, st_voice, left, right)
            _tt5._SetUserStereo(self.client.tt._tt, uid, st_media, left, right)
            self.set_status(f"Stereo-Position {username}: {item}")
        except Exception as exc:
            self.set_status(f"Stereo Fehler: {exc}")

    def on_menu_kick(self) -> None:
        uid = self._get_selected_user_id()
        if not uid:
            self.set_status("Bitte Benutzer auswählen")
            return
        try:
            ch_id = int(self.client.get_my_channel_id() or 0)
            self.client.do_kick_user(uid, ch_id)
            self.set_status(f"User#{uid} gekickt")
        except Exception as exc:
            self.set_status(f"Kick Fehler: {exc}")

    def on_menu_kick_ban(self) -> None:
        uid = self._get_selected_user_id()
        if not uid:
            return
        try:
            tt = self.client.tt
            ch_id = int(self.client.get_my_channel_id() or 0)
            ban_types = int(tt.BanType.BANTYPE_USERNAME)
            self.client.do_ban_user_ex(uid, ban_types)
            if ch_id:
                self.client.do_kick_user(uid, ch_id)
            self.set_status(f"User#{uid} gekickt und gesperrt")
        except Exception as exc:
            self.set_status(f"Kick+Ban Fehler: {exc}")

    def on_menu_kick_server(self) -> None:
        uid = self._get_selected_user_id()
        if not uid:
            self.set_status("Bitte Benutzer auswählen")
            return
        try:
            self.client.do_kick_user(uid, 0)
            self.set_status(f"User#{uid} vom Server gekickt")
        except Exception as exc:
            self.set_status(f"Kick Fehler: {exc}")

    def on_menu_kick_ban_server(self) -> None:
        uid = self._get_selected_user_id()
        if not uid:
            self.set_status("Bitte Benutzer auswählen")
            return
        btn = QMessageBox.question(self, "Vom Server kicken + Bannen",
            "Benutzer wirklich vom Server kicken und bannen?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if btn != QMessageBox.StandardButton.Yes:
            return
        try:
            tt = self.client.tt
            ban_types = int(tt.BanType.BANTYPE_USERNAME)
            self.client.do_ban_user_ex(uid, ban_types)
            self.client.do_kick_user(uid, 0)
            self.set_status(f"User#{uid} vom Server gekickt und gebannt")
        except Exception as exc:
            self.set_status(f"Kick+Ban Server Fehler: {exc}")

    def on_menu_store_move_target(self) -> None:
        ch_id = self._get_selected_channel_id()
        if not ch_id:
            self.set_status("Kein Kanal ausgewählt")
            return
        self._move_target_channel_id = ch_id
        try:
            ch = self.client.get_channel(ch_id)
            name = self.tt_str(getattr(ch, "szName", "")) if ch else str(ch_id)
        except Exception:
            name = str(ch_id)
        self.set_status(f"Zielkanal gespeichert: {name}")

    def on_menu_move_to_target(self) -> None:
        if not self._move_target_channel_id:
            self.set_status("Kein Zielkanal gespeichert — erst 'Ziel merken' ausführen")
            return
        uid = self._get_selected_user_id()
        if not uid:
            self.set_status("Bitte Benutzer auswählen")
            return
        try:
            cmdid = self.client.do_move_user(uid, self._move_target_channel_id)
            if cmdid < 0:
                self.set_status("Benutzer verschieben fehlgeschlagen")
            else:
                self.set_status("Benutzer verschoben")
        except Exception as exc:
            self.set_status(f"Verschieben Fehler: {exc}")

    def on_menu_move_user(self) -> None:
        if not self.client.is_connected():
            self.set_status("Nicht verbunden")
            return
        uid = self._get_selected_user_id()
        if not uid:
            self.set_status("Kein Benutzer ausgewählt")
            return
        from ui_qt.channel_dialog import MoveUserDialog
        dlg = MoveUserDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        target_id = dlg.get_channel_id()
        if not target_id:
            return
        try:
            cmdid = self.client.do_move_user(uid, target_id)
            if cmdid < 0:
                self.set_status("Benutzer verschieben fehlgeschlagen")
            else:
                ch = self.client.get_channel(target_id)
                ch_name = self.tt_str(ch.szName) if ch else str(target_id)
                self.set_status(f'Benutzer in Kanal "{ch_name}" verschoben')
        except Exception as exc:
            self.set_status(f"Verschieben fehlgeschlagen: {exc}")
        self._refocus_channel_list()

    def on_menu_toggle_operator(self) -> None:
        uid = self._get_selected_user_id()
        if not uid:
            return
        try:
            ch_id = int(self.client.get_my_channel_id() or 0)
            is_op = self.client.is_channel_operator(ch_id, uid)
            self.client.do_channel_op(ch_id, uid, not is_op)
            self.set_status(f"User#{uid} {'zum Operator gemacht' if not is_op else 'Operator entfernt'}")
        except Exception as exc:
            self.set_status(f"Operator-Fehler: {exc}")

    def _on_toggle_mute_all(self, checked: bool) -> None:
        self._mute_all = checked
        try:
            self.client.set_sound_output_mute(checked)
            self.set_status("Ausgabe stummgeschaltet" if checked else "Ausgabe aktiv")
        except Exception:
            pass

    def on_menu_subscriptions(self) -> None:
        if not self.client.is_connected():
            self.set_status("Nicht verbunden")
            return
        uid = self._get_selected_user_id()
        if not uid:
            self.set_status("Kein Benutzer ausgewählt")
            return
        try:
            tt = self.client.tt
            user = self.client.get_user(uid)
            flags = [
                ("Sprache", tt.Subscription.SUBSCRIBE_VOICE),
                ("Video", tt.Subscription.SUBSCRIBE_VIDEOCAPTURE),
                ("Mediendatei", tt.Subscription.SUBSCRIBE_MEDIAFILE),
                ("Benutzernachrichten", tt.Subscription.SUBSCRIBE_USER_MSG),
                ("Kanalnachrichten", tt.Subscription.SUBSCRIBE_CHANNEL_MSG),
                ("Rundnachricht", tt.Subscription.SUBSCRIBE_BROADCAST_MSG),
                ("Desktop", tt.Subscription.SUBSCRIBE_DESKTOP),
                ("Desktopzugriff", tt.Subscription.SUBSCRIBE_DESKTOPINPUT),
                ("Benutzernachrichten abfangen", tt.Subscription.SUBSCRIBE_INTERCEPT_USER_MSG),
                ("Kanalnachrichten abfangen", tt.Subscription.SUBSCRIBE_INTERCEPT_CHANNEL_MSG),
                ("Sprache abfangen", tt.Subscription.SUBSCRIBE_INTERCEPT_VOICE),
                ("Video abfangen", tt.Subscription.SUBSCRIBE_INTERCEPT_VIDEOCAPTURE),
                ("Desktop abfangen", tt.Subscription.SUBSCRIBE_INTERCEPT_DESKTOP),
                ("Mediendatei abfangen", tt.Subscription.SUBSCRIBE_INTERCEPT_MEDIAFILE),
            ]
            current = int(getattr(user, "uLocalSubscriptions", 0) or 0)
            dlg = QDialog(self)
            dlg.setWindowTitle("Abonnements")
            layout = QVBoxLayout(dlg)
            checks = []
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            inner = QWidget()
            inner_layout = QVBoxLayout(inner)
            for label, flag in flags:
                cb = QCheckBox(label)
                cb.setChecked(bool(current & int(flag)))
                checks.append((cb, int(flag)))
                inner_layout.addWidget(cb)
            scroll.setWidget(inner)
            layout.addWidget(scroll)
            bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
            bb.accepted.connect(dlg.accept)
            bb.rejected.connect(dlg.reject)
            layout.addWidget(bb)
            dlg.resize(360, 450)
            if dlg.exec() == QDialog.DialogCode.Accepted:
                for cb, flag in checks:
                    want = cb.isChecked()
                    have = bool(current & flag)
                    if want and not have:
                        self.client.do_subscribe(uid, flag)
                    elif not want and have:
                        self.client.do_unsubscribe(uid, flag)
                self.set_status("Abonnements geändert")
        except Exception as exc:
            self.set_status(f"Abonnements Fehler: {exc}")
        self._refocus_channel_list()

    def on_menu_user_position(self) -> None:
        if not self.client.is_connected():
            self.set_status("Nicht verbunden")
            return
        uid = self._get_selected_user_id()
        if not uid:
            self.set_status("Kein Benutzer ausgewählt")
            return
        try:
            from PySide6.QtWidgets import QDoubleSpinBox
            tt = self.client.tt
            choices = [("Sprache", int(tt.StreamType.STREAMTYPE_VOICE))]
            media_st = getattr(tt.StreamType, "STREAMTYPE_MEDIAFILE", None) or \
                       getattr(tt.StreamType, "STREAMTYPE_MEDIAFILE_AUDIO", None)
            if media_st is not None:
                choices.append(("Mediendatei", int(media_st)))
            choices.append(("Sprache + Medien", 0))

            dlg = QDialog(self)
            dlg.setWindowTitle("Benutzer positionieren")
            layout = QVBoxLayout(dlg)
            form = QFormLayout()
            stream_combo = QComboBox()
            for label, _ in choices:
                stream_combo.addItem(label)
            form.addRow("Stream-Typ:", stream_combo)
            x_spin = QDoubleSpinBox()
            x_spin.setRange(-1000.0, 1000.0)
            x_spin.setSingleStep(0.1)
            y_spin = QDoubleSpinBox()
            y_spin.setRange(-1000.0, 1000.0)
            y_spin.setSingleStep(0.1)
            z_spin = QDoubleSpinBox()
            z_spin.setRange(-1000.0, 1000.0)
            z_spin.setSingleStep(0.1)
            form.addRow("X:", x_spin)
            form.addRow("Y:", y_spin)
            form.addRow("Z:", z_spin)
            layout.addLayout(form)
            bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
            bb.accepted.connect(dlg.accept)
            bb.rejected.connect(dlg.reject)
            layout.addWidget(bb)
            if dlg.exec() == QDialog.DialogCode.Accepted:
                idx = stream_combo.currentIndex()
                st = choices[idx][1]
                x, y, z = x_spin.value(), y_spin.value(), z_spin.value()
                if st == 0:
                    for _, stype in choices[:-1]:
                        self.client.set_user_position(uid, stype, x, y, z)
                else:
                    self.client.set_user_position(uid, st, x, y, z)
                self.set_status(f"Benutzer #{uid} positioniert: ({x:.1f}, {y:.1f}, {z:.1f})")
        except Exception as exc:
            self.set_status(f"Positionieren Fehler: {exc}")
        self._refocus_channel_list()

    def on_menu_relay_voice(self) -> None:
        if not self.client.is_connected():
            self.set_status("Nicht verbunden")
            return
        uid = self._get_selected_user_id()
        if not uid:
            self.set_status("Kein Benutzer ausgewählt")
            return
        try:
            tt = self.client.tt
            user = self.client.get_user(uid)
            current = int(getattr(user, "uLocalSubscriptions", 0) or 0)
            flag = int(tt.Subscription.SUBSCRIBE_INTERCEPT_VOICE)
            if current & flag:
                self.client.do_unsubscribe(uid, flag)
                self.set_status("Sprachstream-Weiterleitung deaktiviert")
            else:
                self.client.do_subscribe(uid, flag)
                self.set_status("Sprachstream wird weitergeleitet")
        except Exception as exc:
            self.set_status(f"Relay Fehler: {exc}")

    def on_menu_relay_media(self) -> None:
        if not self.client.is_connected():
            self.set_status("Nicht verbunden")
            return
        uid = self._get_selected_user_id()
        if not uid:
            self.set_status("Kein Benutzer ausgewählt")
            return
        try:
            tt = self.client.tt
            user = self.client.get_user(uid)
            current = int(getattr(user, "uLocalSubscriptions", 0) or 0)
            flag = int(tt.Subscription.SUBSCRIBE_INTERCEPT_MEDIAFILE)
            if current & flag:
                self.client.do_unsubscribe(uid, flag)
                self.set_status("Medienstream-Weiterleitung deaktiviert")
            else:
                self.client.do_subscribe(uid, flag)
                self.set_status("Medienstream wird weitergeleitet")
        except Exception as exc:
            self.set_status(f"Relay Fehler: {exc}")

    # ------------------------------------------------------------------
    # Profil-Menü
    # ------------------------------------------------------------------

    def on_menu_change_nick(self) -> None:
        nick, ok = QInputDialog.getText(self, "Nickname", "Neuer Nickname:")
        if ok and nick:
            try:
                self.client.change_nickname(nick)
                profile = getattr(self, "_last_profile", None)
                if profile:
                    self._update_conn_bar(
                        f"Verbunden: {getattr(profile, 'name', '')}  |  Nickname: {nick}", connected=True
                    )
                self.set_status(f"Nickname geändert: {nick}")
            except Exception as exc:
                self.set_status(f"Nickname-Fehler: {exc}")

    def on_menu_status(self) -> None:
        if not self._require_connected("Status setzen"):
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Status setzen")
        layout = QFormLayout(dlg)
        mode_cb = QComboBox()
        mode_cb.addItems(["Verfügbar", "Abwesend", "Frage"])
        current_mode = getattr(self, "_status_mode", 0)
        try:
            from teamtalk_client import tt as _tt
            if current_mode == int(_tt.UserStatusMode.STATUSMODE_AWAY):
                mode_cb.setCurrentIndex(1)
            elif current_mode == int(_tt.UserStatusMode.STATUSMODE_QUESTION):
                mode_cb.setCurrentIndex(2)
            else:
                mode_cb.setCurrentIndex(0)
        except Exception:
            pass
        msg_edit = QLineEdit(getattr(self, "_status_message", ""))
        layout.addRow("Modus", mode_cb)
        layout.addRow("Nachricht", msg_edit)
        bb = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        layout.addRow(bb)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            from teamtalk_client import tt as _tt
            mode_map = {
                0: int(_tt.UserStatusMode.STATUSMODE_AVAILABLE),
                1: int(_tt.UserStatusMode.STATUSMODE_AWAY),
                2: int(_tt.UserStatusMode.STATUSMODE_QUESTION),
            }
            mode = mode_map.get(mode_cb.currentIndex(), 0)
            message = msg_edit.text().strip()
            self._status_mode = mode
            self._status_message = message
            cmdid = self.client.change_status(mode, message)
            if cmdid < 0:
                self.set_status("Status konnte nicht gesetzt werden")
            else:
                self.set_status(f"Status gesetzt: {message or mode_cb.currentText()}")
        except Exception:
            pass

    def _on_toggle_self_hear(self, checked: bool) -> None:
        try:
            s = self.settings_store.settings
            indev = int(getattr(s, "input_device_id", 0) or 0)
            outdev = int(getattr(s, "output_device_id", 0) or 0)
            if checked:
                h = self.client.start_sound_loopback_test(indev, outdev)
                self._loopback_handle = h if h >= 0 else None
            else:
                h = getattr(self, "_loopback_handle", None)
                if h is not None:
                    self.client.close_sound_loopback_test(h)
                    self._loopback_handle = None
            self.set_status("Mikrofon-Rückhörmodus: " + ("an" if checked else "aus"))
        except Exception:
            pass

    def _on_toggle_question_mode(self, checked: bool) -> None:
        try:
            mode = 1 if checked else 0
            my_id = int(self.client.get_my_user_id() or 0)
            if my_id:
                self.client.change_status(mode, self._status_message)
        except Exception:
            pass

    def _on_toggle_tts(self, checked: bool) -> None:
        try:
            self.settings_store.settings.tts_enabled = checked
            self.settings_store.save()
        except Exception:
            pass
        self.set_status("TTS aktiviert" if checked else "TTS deaktiviert")

    def _on_toggle_tts_flag(self, flag: str, checked: bool) -> None:
        try:
            attr_map = {
                "chat": "tts_speak_chat",
                "private": "tts_speak_private",
                "system": "tts_speak_system",
                "own": "tts_speak_own",
            }
            attr = attr_map.get(flag)
            if attr:
                setattr(self.settings_store.settings, attr, checked)
                setattr(self.tts.settings, f"speak_{flag}" if flag != "own" else "speak_own", checked)
                self.settings_store.save()
            try:
                tab = self.system_tab
                widget_map = {
                    "chat": tab.tts_chat,
                    "private": tab.tts_private,
                    "system": tab.tts_system,
                    "own": tab.tts_own,
                }
                w = widget_map.get(flag)
                if w and w.isChecked() != checked:
                    w.blockSignals(True)
                    w.setChecked(checked)
                    w.blockSignals(False)
            except Exception:
                pass
            self.set_status("Benachrichtigung gespeichert")
        except Exception:
            self.set_status("Benachrichtigung konnte nicht umgestellt werden")

    # ------------------------------------------------------------------
    # Audio-Menü
    # ------------------------------------------------------------------

    def _on_toggle_ptt(self, checked: bool) -> None:
        self._ptt_enabled = checked
        for _w in (self._ptt_action, self._tb_ptt):
            try:
                _w.blockSignals(True)
                _w.setChecked(checked)
                _w.blockSignals(False)
            except Exception:
                pass
        try:
            self.settings_store.settings.ptt_enabled = checked
            self.settings_store.save()
        except Exception:
            pass
        if not checked and self._ptt_active:
            self._ptt_active = False
            try:
                self.client.enable_voice_transmission(False)
            except Exception:
                pass

    def _on_toggle_va(self, checked: bool) -> None:
        self.set_voice_activation(checked)
        try:
            self.settings_store.settings.voice_activation = checked
            self.settings_store.save()
        except Exception:
            pass

    def _on_tb_record(self, checked: bool) -> None:
        if checked:
            from PySide6.QtWidgets import QFileDialog
            path, _ = QFileDialog.getSaveFileName(self, "Aufnahme", "", "WAV (*.wav);;MP3 (*.mp3)")
            if path:
                fmt = "mp3" if path.lower().endswith(".mp3") else "wav"
                self.start_recording(path, fmt)
                self.set_status("Aufnahme gestartet")
            else:
                self._tb_record.setChecked(False)
        else:
            self.stop_recording()
            self.set_status("Aufnahme gestoppt")

    def _on_master_volume(self, value: int) -> None:
        try:
            self.client.set_sound_output_volume(value)
        except Exception:
            pass
        try:
            self.settings_store.settings.master_volume = value
            self.settings_store.save()
        except Exception:
            pass

    def _on_mic_gain(self, value: int) -> None:
        try:
            self.client.set_sound_input_gain(value)
        except Exception:
            pass
        try:
            self.settings_store.settings.mic_gain = value
            self.settings_store.save()
        except Exception:
            pass

    def on_menu_audio_settings(self) -> None:
        self.settings_tab_widget.inner.setCurrentWidget(self.settings_tab_widget.audio_tab)
        self.on_menu_settings()

    def on_menu_equalizer(self) -> None:
        self.set_status("Equalizer-Voreinstellungen: Einstellungen → Audio")
        self.on_menu_audio_settings()

    def on_menu_audio_refresh(self) -> None:
        try:
            self.audio_tab.refresh_devices()
            self.set_status("Audio-Geräte aktualisiert")
        except Exception as exc:
            self.set_status(f"Geräte aktualisieren Fehler: {exc}")

    def _get_audio_device_names(self) -> List[str]:
        try:
            devs = list(self.client.get_sound_devices() or [])
            return [str(getattr(d, "szDeviceName", "")) for d in devs]
        except Exception:
            return []

    def _check_audio_hotplug(self) -> None:
        current = self._get_audio_device_names()
        if current != self._known_audio_devices:
            self._known_audio_devices = current
            try:
                self.audio_tab.refresh_devices()
                self.set_status("Audio-Gerät geändert — Geräteliste aktualisiert")
            except Exception:
                pass

    def on_menu_audio_effects(self) -> None:
        try:
            self.audio_tab.on_apply_effects()
        except Exception as exc:
            self.set_status(f"Effekte anwenden Fehler: {exc}")

    def _on_toggle_agc(self, checked: bool) -> None:
        try:
            self.audio_tab.agc_check.setChecked(checked)
            self.audio_tab._on_preprocess_changed()
        except Exception:
            pass

    def _on_toggle_denoise(self, checked: bool) -> None:
        try:
            self.audio_tab.denoise_check.setChecked(checked)
            self.audio_tab._on_preprocess_changed()
        except Exception:
            pass

    def _on_toggle_echo(self, checked: bool) -> None:
        try:
            self.audio_tab.echo_check.setChecked(checked)
            self.audio_tab._on_preprocess_changed()
        except Exception:
            pass

    def _on_toggle_loopback_menu(self, checked: bool) -> None:
        try:
            self.audio_tab.loopback_check.setChecked(checked)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Aufnahmen-Menü
    # ------------------------------------------------------------------

    def on_menu_start_recording(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(
            self, "Aufnahme speichern unter", "", "WAV-Dateien (*.wav);;MP3 (*.mp3)"
        )
        if path:
            fmt = "mp3" if path.lower().endswith(".mp3") else "wav"
            self.start_recording(path, fmt)

    def on_menu_stop_recording(self) -> None:
        self.stop_recording()

    def on_menu_user_recording(self) -> None:
        idx = self.notebook.indexOf(self.media_tab)
        if idx >= 0:
            self.notebook.setCurrentIndex(idx)

    def on_menu_scheduled_recordings(self) -> None:
        try:
            from ui_qt.scheduled_recordings_dialog import ScheduledRecordingsDialog
            dlg = ScheduledRecordingsDialog(self, getattr(self, "_scheduled_rec_manager", None))
            dlg.exec()
        except ImportError:
            self.set_status("Geplante Aufnahmen: Dialog nicht verfügbar")

    def on_menu_recordings_browser(self) -> None:
        from ui_qt.recordings_browser import RecordingsBrowserDialog
        dlg = RecordingsBrowserDialog(self, self.settings_store)
        dlg.exec()
        self._refocus_channel_list()

    # ------------------------------------------------------------------
    # Server-Menü
    # ------------------------------------------------------------------

    def on_menu_server_message(self) -> None:
        text, ok = QInputDialog.getText(self, "Servernachricht", "Nachricht an alle:")
        if ok and text:
            try:
                self.client.send_broadcast_message(text)
                self.set_status("Servernachricht gesendet")
            except Exception as exc:
                self.set_status(f"Servernachricht fehlgeschlagen: {exc}")

    def on_menu_server_save_config(self) -> None:
        fn = getattr(self.client, "do_save_config", None)
        if fn is None:
            self.set_status("Server-Konfiguration speichern: nicht unterstützt")
            return
        try:
            result = fn()
            if result >= 0:
                self.set_status("Server-Konfiguration gespeichert")
            else:
                self.set_status("Server-Konfiguration speichern fehlgeschlagen")
        except Exception as exc:
            self.set_status(f"Speichern fehlgeschlagen: {exc}")

    def on_menu_admin(self) -> None:
        idx = self.notebook.indexOf(self.admin_tab)
        if idx >= 0:
            self.notebook.setCurrentIndex(idx)

    def on_menu_server_properties(self) -> None:
        self.edit_server_properties()

    # ------------------------------------------------------------------
    # Recent channels
    # ------------------------------------------------------------------

    def _add_to_recent_channels(self, ch_id: int, ch_name: str) -> None:
        server_key = getattr(self, "_current_server_key", "")
        s = self.settings_store.settings
        recent = list(getattr(s, "recent_channels", []) or [])
        recent = [e for e in recent if not (e.get("channel_id") == ch_id and e.get("server_key") == server_key)]
        recent.insert(0, {"channel_id": ch_id, "name": ch_name, "server_key": server_key})
        if len(recent) > 8:
            recent = recent[:8]
        s.recent_channels = recent
        try:
            self.settings_store.save()
        except Exception:
            pass
        self._refresh_recent_channels_menu()

    def _refresh_recent_channels_menu(self) -> None:
        if not hasattr(self, "_recent_ch_menu"):
            return
        try:
            s = self.settings_store.settings
            recent = list(getattr(s, "recent_channels", []) or [])
        except Exception:
            return
        self._recent_ch_menu.clear()
        if not recent:
            act = self._recent_ch_menu.addAction("(Leer)")
            act.setEnabled(False)
            return
        for entry in recent:
            ch_id = entry.get("channel_id")
            name = entry.get("name", "") or str(ch_id or "?")
            server = entry.get("server_key", "")
            label = f"{name}  [{server}]" if server else name
            act = QAction(label, self)
            if ch_id:
                act.triggered.connect(
                    lambda checked=False, cid=ch_id: self.join_channel(int(cid)) if self.client.is_connected() else self.set_status("Nicht verbunden")
                )
            else:
                act.setEnabled(False)
            self._recent_ch_menu.addAction(act)

    # ------------------------------------------------------------------
    # Favorites / Schnellverbindung
    # ------------------------------------------------------------------

    def _rebuild_favorites_menu(self) -> None:
        self._fav_menu.clear()
        profiles = list(self.store.items())
        for i, p in enumerate(profiles[:9]):
            label = getattr(p, "name", "") or getattr(p, "host", f"Server {i + 1}")
            action = QAction(f"&{i + 1}: {label}", self)
            action.setShortcut(QKeySequence(f"Ctrl+{i + 1}"))
            action.triggered.connect(lambda checked=False, pr=p: self.connect_to_server(pr))
            self._fav_menu.addAction(action)
        if not profiles:
            empty_action = self._fav_menu.addAction("(Keine gespeicherten Server)")
            empty_action.setEnabled(False)

    # ------------------------------------------------------------------
    # Channel Stream Mode
    # ------------------------------------------------------------------

    def _on_channel_stream_mode(self, mode: str) -> None:
        idx = self.notebook.indexOf(self.media_tab)
        if idx >= 0:
            self.notebook.setCurrentIndex(idx)
        try:
            self.media_tab.switch_to_mode(mode)
        except Exception:
            self.set_status(f"Medien → {mode}")

    # ------------------------------------------------------------------
    # User Transmission Control
    # ------------------------------------------------------------------

    def on_menu_toggle_user_tx(self, stream_type: str) -> None:
        uid = self._get_selected_user_id()
        if not uid:
            self.set_status("Bitte Benutzer auswählen")
            return
        try:
            tt = self.client.tt
            ch_id = int(self.client.get_my_channel_id() or 0)
            type_map = {
                "voice": int(tt.StreamType.STREAMTYPE_VOICE),
                "video": int(tt.StreamType.STREAMTYPE_VIDEOCAPTURE),
                "desktop": int(tt.StreamType.STREAMTYPE_DESKTOP),
                "media": int(tt.StreamType.STREAMTYPE_MEDIAFILE_AUDIO),
            }
            st = type_map.get(stream_type, 0)
            if st and ch_id:
                self.client.do_channel_user_transmit(uid, ch_id, st)
                self.set_status(f"Sendekontrolle {stream_type} für User#{uid} umgeschaltet")
        except Exception as exc:
            self.set_status(f"Sendekontrolle Fehler: {exc}")

    # ------------------------------------------------------------------
    # Automation-Menü
    # ------------------------------------------------------------------

    def _on_toggle_translation(self, checked: bool) -> None:
        try:
            self.settings_store.settings.translation_enabled = checked
            self.settings_store.save()
            self.set_status("Übersetzung: " + ("aktiviert" if checked else "deaktiviert"))
        except Exception:
            pass

    def _on_toggle_channel_summary(self, checked: bool) -> None:
        try:
            self.settings_store.settings.auto_channel_summary = checked
            self.settings_store.save()
            self.set_status("Auto-Kanal-Zusammenfassung: " + ("aktiviert" if checked else "deaktiviert"))
        except Exception:
            pass

    def _auto_channel_summary(self) -> None:
        if self._ai_summary is None:
            return
        server_key = getattr(self, "_current_server_key", "")
        if not server_key:
            return
        since = time.time() - 1800

        def _work():
            text = self._ai_summary.summarize_missed(server_key, since)
            if text and text != "Keine neuen Nachrichten.":
                call_after(lambda: self.tts.speak(f"Zusammenfassung: {text}", kind="system"))

        threading.Thread(target=_work, daemon=True).start()

    # ------------------------------------------------------------------
    # Einstellungen / Navigation
    # ------------------------------------------------------------------

    def on_menu_settings(self) -> None:
        self._settings_dialog.show()
        self._settings_dialog.raise_()
        self._settings_dialog.activateWindow()
        try:
            self.settings_tab_widget.inner.setFocus()
        except Exception:
            pass

    def on_menu_connection_window(self) -> None:
        self.on_menu_connect()

    # ------------------------------------------------------------------
    # Dialoge
    # ------------------------------------------------------------------

    def on_menu_tts_transcript(self) -> None:
        from ui_qt.dialogs import TTSTranscriptDialog
        dlg = TTSTranscriptDialog(self, self.tts)
        dlg.exec()
        self._refocus_channel_list()

    def on_menu_chat_search(self) -> None:
        from ui_qt.dialogs import ChatSearchDialog
        dlg = ChatSearchDialog(self, self._chat_history, self._current_server_key)
        dlg.exec()
        self._refocus_channel_list()

    def on_menu_user_watcher(self) -> None:
        from ui_qt.dialogs import UserWatcherDialog
        dlg = UserWatcherDialog(self, self.settings_store)
        dlg.exec()
        self._refocus_channel_list()

    def on_menu_offline_queue(self) -> None:
        from ui_qt.dialogs import OfflineQueueDialog
        dlg = OfflineQueueDialog(self, self._offline_queue)
        dlg.exec()
        self._refocus_channel_list()

    def on_menu_server_audio_profiles(self) -> None:
        from ui_qt.dialogs import ServerAudioProfileDialog
        dlg = ServerAudioProfileDialog(self, self.settings_store)
        dlg.exec()
        self._refocus_channel_list()

    def on_menu_online_users(self) -> None:
        from ui_qt.dialogs import OnlineUsersDialog
        dlg = OnlineUsersDialog(self, self.client, self.tt_str)
        dlg.exec()
        self._refocus_channel_list()

    def on_menu_server_stats(self) -> None:
        from ui_qt.dialogs import ServerStatsDialog
        dlg = ServerStatsDialog(self, self.client)
        dlg.exec()
        self._refocus_channel_list()

    def on_menu_speaking_log(self) -> None:
        from ui_qt.dialogs import SpeakingLogDialog
        dlg = SpeakingLogDialog(self, self._speaking_log)
        dlg.exec()
        self._refocus_channel_list()

    def on_menu_session_overview(self) -> None:
        try:
            data = self.server_manager.per_session_stats()
        except Exception:
            data = {}
        dlg = QDialog(self)
        dlg.setWindowTitle("Sitzungsübersicht")
        dlg.resize(640, 420)
        layout = QVBoxLayout(dlg)
        te = QTextEdit()
        te.setReadOnly(True)
        if data:
            lines = []
            for sid, info in data.items():
                active = "aktiv" if info.get("is_active") else "inaktiv"
                lines.append(f"{info.get('profile', '?')} | {info.get('state', '?')} | {active} | {sid}")
            te.setPlainText("\n".join(lines))
        else:
            te.setPlainText("Keine Sitzungen vorhanden.")
        layout.addWidget(te, 1)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(dlg.reject)
        layout.addWidget(bb)
        dlg.exec()
        self._refocus_channel_list()

    def on_menu_announce_ping(self) -> None:
        try:
            stats = self.client.get_client_statistics()
            udp_ms = int(stats.nUdpPingTimeMs)
            tcp_ms = int(stats.nTcpPingTimeMs)
            text = f"Ping: UDP {udp_ms} ms, TCP {tcp_ms} ms"
        except Exception:
            text = "Ping nicht verfügbar"
        self.tts.speak(text, kind="system")
        self.set_status(text)

    def on_menu_ban_list(self) -> None:
        idx = self.notebook.indexOf(self.admin_tab)
        if idx >= 0:
            self.notebook.setCurrentIndex(idx)

    def on_menu_macros(self) -> None:
        from ui_qt.macro_dialog import MacroDialog
        MacroDialog(self, initial_tab=0).exec()
        self._refocus_channel_list()

    def on_menu_scheduled_macros(self) -> None:
        from ui_qt.macro_dialog import MacroDialog
        MacroDialog(self, initial_tab=2).exec()
        self._refocus_channel_list()

    def on_menu_trigger_editor(self) -> None:
        from ui_qt.macro_dialog import MacroDialog
        MacroDialog(self, initial_tab=1).exec()
        self._refocus_channel_list()

    def on_menu_pronunciation(self) -> None:
        from ui_qt.pronunciation_dialog import PronunciationDialog
        PronunciationDialog(self).exec()
        self._refocus_channel_list()

    def on_menu_plugin_manager(self) -> None:
        try:
            from ui_qt.plugin_manager import PluginManagerDialog
            dlg = PluginManagerDialog(self)
            dlg.exec()
        except ImportError:
            self.set_status("Plugin-Manager: Dialog nicht verfügbar")

    def on_menu_manual(self) -> None:
        try:
            import webbrowser
            manual_path = Path(__file__).parent / "manual.html"
            if manual_path.exists():
                webbrowser.open(str(manual_path))
        except Exception:
            pass

    def on_menu_changelog(self) -> None:
        try:
            import webbrowser
            cl_path = Path(__file__).parent.parent / "CHANGELOG.txt"
            if cl_path.exists():
                webbrowser.open(str(cl_path))
        except Exception:
            pass

    def on_menu_chat_export(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        if not self._channel_message_log:
            QMessageBox.information(self, "Chat-Export", "Keine Kanalnachrichten zum Exportieren.")
            return
        path, sel = QFileDialog.getSaveFileName(
            self, "Chat-Log exportieren", "chat_log.txt",
            "Textdatei (*.txt);;HTML (*.html *.htm);;Alle Dateien (*.*)"
        )
        if not path:
            return
        try:
            if path.lower().endswith((".html", ".htm")):
                import html as _html
                lines = [
                    "<!DOCTYPE html><html><head><meta charset='utf-8'>"
                    "<title>Chat-Log</title></head><body><pre>"
                ] + [_html.escape(l) for l in self._channel_message_log] + ["</pre></body></html>"]
                content = "\n".join(lines)
            else:
                content = "\n".join(self._channel_message_log)
            Path(path).write_text(content, encoding="utf-8")
            self.set_status(f"Chat-Log exportiert: {Path(path).name}")
        except Exception as exc:
            self.set_status(f"Chat-Export fehlgeschlagen: {exc}")

    def on_menu_tts_repeat(self) -> None:
        last = getattr(self.tts, "last_text", "")
        if last:
            self.tts.speak(last, kind="system")
        else:
            self.set_status("Keine letzte TTS-Ansage vorhanden")

    def on_menu_shortcut_reference(self) -> None:
        _SHORTCUTS = [
            ("VERBINDUNG", [
                ("Verbinden / Trennen (Toggle)",   "F2"),
                ("Verbindungsdialog öffnen",       "Ctrl+Return"),
                ("Trennen",                        "Ctrl+W"),
                ("Neu verbinden",                  "Ctrl+Shift+R"),
                ("Schnellverbindung 1–9",          "Ctrl+1–9"),
            ]),
            ("KANAL", [
                ("Kanal erstellen",                "F7"),
                ("Kanal beitreten",                "Ctrl+J"),
                ("Kanal verlassen",                "Ctrl+L"),
                ("Kanalinfo vorlesen",             "Ctrl+S"),
                ("Kanalnachricht senden",          "F3"),
                ("Kanäle & Nutzer aktualisieren",  "F5"),
                ("Kanal-Statistiken ansagen",      "(Menü Kanal)"),
                ("Kanalzustand ansagen",           "(Menü Kanal)"),
            ]),
            ("BENUTZER", [
                ("Benutzerinfo vorlesen",          "Ctrl+I"),
                ("Private Nachricht",              "F6 / Ctrl+T"),
                ("Stummschalten (Sprache)",        "Ctrl+M"),
                ("Kicken",                         "Ctrl+K"),
                ("Kicken + Bannen",                "Ctrl+Shift+K"),
                ("Benutzer verschieben",           "(Menü Benutzer)"),
                ("Sprach-Lautstärke hoch",         "Ctrl+Rechts"),
                ("Sprach-Lautstärke runter",       "Ctrl+Links"),
                ("Medien-Lautstärke hoch",         "Ctrl+Alt+Auf"),
                ("Medien-Lautstärke runter",       "Ctrl+Alt+Ab"),
                ("Alle stummschalten",             "(Menü Benutzer)"),
            ]),
            ("PROFIL", [
                ("Nickname ändern",                "Ctrl+R"),
                ("Mich selbst hören",              "(Menü Profil)"),
                ("TTS aktivieren/deaktivieren",    "(Menü Profil)"),
            ]),
            ("AUDIO", [
                ("Push-to-Talk",                   "F9"),
                ("Sprachaktivierung",              "(Menü Audio)"),
                ("Ping ansagen",                   "Ctrl+P"),
            ]),
            ("AUTOMATION", [
                ("Einstellungen",                  "F4"),
                ("Makro-Manager",                  "Ctrl+Shift+M"),
            ]),
            ("CHAT", [
                ("Chat-Log exportieren",           "(Menü Chat)"),
                ("Letzte TTS-Ansage wiederholen",  "Ctrl+Shift+S"),
                ("Chat-Suche",                     "Ctrl+F"),
            ]),
            ("SERVER", [
                ("Online-Nutzer",                  "Ctrl+U"),
                ("Sperrliste",                     "Ctrl+B"),
                ("Administration",                 "Ctrl+A"),
                ("Servernachricht senden",         "(Menü Server)"),
                ("Konfiguration speichern",        "(Menü Server)"),
            ]),
            ("TABS", [
                ("Tab 1–9 direkt",                 "Alt+1–9"),
            ]),
            ("HILFE", [
                ("Handbuch",                       "F1"),
                ("Tastenkürzel-Referenz",          "(Menü Hilfe)"),
            ]),
        ]
        lines = []
        for section, entries in _SHORTCUTS:
            lines.append(f"── {section} ──")
            for desc, keys in entries:
                lines.append(f"  {desc:<40} {keys}")
            lines.append("")
        text = "\n".join(lines)

        dlg = QDialog(self)
        dlg.setWindowTitle("Tastenkürzel-Referenz")
        dlg.resize(600, 560)
        layout = QVBoxLayout(dlg)
        te = QTextEdit()
        te.setReadOnly(True)
        te.setAccessibleName("Tastenkürzel-Referenz")
        from PySide6.QtGui import QFont as _QFont
        te.setFont(_QFont("Courier New", 10))
        te.setPlainText(text)
        layout.addWidget(te, 1)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(dlg.reject)
        layout.addWidget(bb)
        dlg.exec()
        self._refocus_channel_list()

    def on_menu_analytics_report(self) -> None:
        try:
            report_text = self._analytics.text_report()
        except Exception as exc:
            report_text = f"Bericht konnte nicht erstellt werden: {exc}"
        dlg = QDialog(self)
        dlg.setWindowTitle("Nutzungsbericht")
        dlg.resize(720, 460)
        layout = QVBoxLayout(dlg)
        te = QTextEdit()
        te.setReadOnly(True)
        te.setAccessibleName("Nutzungsbericht")
        te.setPlainText(report_text)
        layout.addWidget(te, 1)
        btn_row = QHBoxLayout()
        export_btn = QPushButton("&Exportieren")
        export_btn.setAccessibleName("Nutzungsbericht exportieren")
        btn_row.addWidget(export_btn)
        btn_row.addStretch()
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(dlg.reject)
        btn_row.addWidget(bb)
        layout.addLayout(btn_row)

        def _on_export():
            from PySide6.QtWidgets import QFileDialog
            import time as _time
            default_name = f"analytics_{_time.strftime('%Y%m%d_%H%M%S')}.json"
            path, _ = QFileDialog.getSaveFileName(
                dlg, "Nutzungsbericht exportieren", default_name,
                "JSON-Dateien (*.json);;Alle Dateien (*.*)"
            )
            if not path:
                return
            try:
                self._analytics.export(path)
                dlg.setWindowTitle(f"Nutzungsbericht — exportiert: {Path(path).name}")
            except Exception as exc2:
                QMessageBox.warning(dlg, "Export fehlgeschlagen", str(exc2))

        export_btn.clicked.connect(_on_export)
        dlg.exec()
        self._refocus_channel_list()

    def on_menu_about(self) -> None:
        QMessageBox.information(
            self, "Info",
            f"TeamTalk VoiceOver Client {APP_VERSION}\n"
            f"© Flarion (Florian Lichteblau)\n"
            f"Plattform: {platform_info()}"
        )

    # ------------------------------------------------------------------
    # Hilfe-Menü
    # ------------------------------------------------------------------

    def on_menu_export_logs(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(
            self, "Logs exportieren", "client.log", "Logdateien (*.log *.txt)"
        )
        if path:
            try:
                import shutil
                shutil.copy(self.logger.path, path)
                self.set_status(f"Log exportiert: {path}")
            except Exception as exc:
                self.set_status(f"Export fehlgeschlagen: {exc}")

    def on_menu_health_report(self) -> None:
        try:
            results = self._health.run_all()
            lines = [
                f"{k}: {'OK' if v.ok else 'FEHLER — ' + v.message}"
                for k, v in results.items()
            ]
            report = "\n".join(lines) or "Keine Prüfungen registriert"
        except Exception as exc:
            report = f"Fehler: {exc}"
        QMessageBox.information(self, "Gesundheitsbericht", report)

    def on_menu_client_stats(self) -> None:
        try:
            stats = self.client.get_client_statistics()
            lines = []
            for attr in dir(stats):
                if attr.startswith("n") or attr.startswith("f"):
                    try:
                        lines.append(f"{attr}: {getattr(stats, attr)}")
                    except Exception:
                        pass
            text = "\n".join(lines[:30]) or "Keine Statistiken verfügbar"
        except Exception as exc:
            text = f"Fehler: {exc}"
        dlg = QDialog(self)
        dlg.setWindowTitle("Verbindungsstatistiken")
        layout = QVBoxLayout(dlg)
        te = QTextEdit()
        te.setReadOnly(True)
        te.setPlainText(text)
        layout.addWidget(te)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(dlg.reject)
        layout.addWidget(bb)
        dlg.resize(400, 300)
        dlg.exec()
        self._refocus_channel_list()

    def on_menu_startup_profiler(self) -> None:
        prof = _get_startup_profiler()
        phases = prof.phases
        if phases:
            lines = [f"{name}: {dur:.1f} ms" for name, dur in phases if dur > 0]
            text = "\n".join(lines) or "Keine Phasen aufgezeichnet."
        else:
            text = "Keine Profiling-Daten verfügbar."
        dlg = QDialog(self)
        dlg.setWindowTitle("Startup-Profiler")
        layout = QVBoxLayout(dlg)
        te = QTextEdit()
        te.setReadOnly(True)
        te.setPlainText(text)
        layout.addWidget(te)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(dlg.reject)
        layout.addWidget(bb)
        dlg.resize(400, 300)
        dlg.exec()

    def on_menu_client_stats_speak(self) -> None:
        if not self.client.is_connected():
            self.set_status("Nicht verbunden")
            return
        try:
            stats = self.client.get_client_statistics()
            if stats is None:
                self.set_status("Keine Statistik verfügbar")
                return
            udp = int(getattr(stats, "nUdpPingTimeMs", 0) or 0)
            tcp = int(getattr(stats, "nTcpPingTimeMs", 0) or 0)
            text = f"UDP Ping {udp} Millisekunden, TCP Ping {tcp} Millisekunden."
            self.tts.speak(text, kind="system")
        except Exception:
            self.set_status("Statistik nicht verfügbar")

    def on_menu_saved_messages(self) -> None:
        try:
            msgs = self._saved_messages.get_all()
        except Exception:
            msgs = []
        dlg = QDialog(self)
        dlg.setWindowTitle("Gespeicherte Nachrichten")
        layout = QVBoxLayout(dlg)
        lw = QListWidget()
        for m in (msgs or []):
            lw.addItem(str(m)[:120])
        layout.addWidget(lw, 1)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(dlg.reject)
        layout.addWidget(bb)
        dlg.resize(500, 350)
        dlg.exec()
        self._refocus_channel_list()

    def on_menu_update_manager(self) -> None:
        from ui_qt.update_dialog import UpdateManagerDialog
        dlg = UpdateManagerDialog(self, APP_VERSION)
        dlg.exec()

    def on_menu_check_updates(self) -> None:
        self.set_status("Update-Prüfung gestartet...")
        import threading

        def worker():
            try:
                import urllib.request
                import json as _json
                TOKEN = _upd_tok()
                url = "https://git.garogaming.xyz/api/v1/repos/flarion/TeamTalk-VO-Client/releases/latest"
                req = urllib.request.Request(url, headers={"Authorization": f"token {TOKEN}"})
                with urllib.request.urlopen(req, timeout=10) as r:
                    data = _json.loads(r.read())
                latest = data.get("tag_name", "").lstrip("v")
                if latest and latest > APP_VERSION:
                    call_after(lambda: QMessageBox.information(
                        self, "Update verfügbar",
                        f"Version {latest} ist verfügbar.\nAktuelle Version: {APP_VERSION}"
                    ))
                else:
                    call_after(lambda: self.set_status(
                        f"Kein Update verfügbar (aktuell: {APP_VERSION})"
                    ))
            except Exception as exc:
                call_after(lambda: self.set_status(f"Update-Prüfung fehlgeschlagen: {exc}"))

        threading.Thread(target=worker, daemon=True).start()

    # ------------------------------------------------------------------
    # Transcription
    # ------------------------------------------------------------------

    def _on_transcription_result(self, **kwargs) -> None:
        text = kwargs.get("text", "")
        if text:
            self.tts.speak(text, kind="system")

    # ------------------------------------------------------------------
    # Close
    # ------------------------------------------------------------------

    def closeEvent(self, event: QCloseEvent) -> None:
        close_to_tray = bool(getattr(self.settings_store.settings, "close_to_tray", True))
        if close_to_tray and not self._closing:
            self.hide()
            event.ignore()
        else:
            self.force_close()
            event.accept()

    def force_close(self) -> None:
        self._closing = True
        self._reconnect_timer.stop()
        try:
            self.client.stop_event_loop()
        except Exception:
            pass
        try:
            self.speak_tab.cleanup()
        except Exception:
            pass
        try:
            self.media_tab.stop_all()
        except Exception:
            pass
        try:
            self.tray.hide()
        except Exception:
            pass
        try:
            self.client.disconnect()
        except Exception:
            pass
        try:
            self.client.close()
        except Exception:
            pass
        try:
            self._screen_reader.stop()
        except Exception:
            pass
        try:
            self._http_api.stop()
        except Exception:
            pass
        try:
            self._async_bridge.stop()
        except Exception:
            pass
        try:
            self._mute_scheduler.stop()
        except Exception:
            pass
        QApplication.quit()
        import os as _os
        _os._exit(0)


class App(QApplication):
    def __init__(self) -> None:
        super().__init__(sys.argv)
        self.setApplicationName("TeamTalk VO Client")
        self.setOrganizationName("Flarion")

        # Windows: Segoe UI font for modern look
        if sys.platform == "win32":
            font = QFont("Segoe UI", 10)
            self.setFont(font)
            self._apply_windows_polish()

        if sys.platform == "win32":
            _start_demo_dialog_suppressor()

        self.window = MainWindow()

    def _apply_windows_polish(self) -> None:
        try:
            import winreg
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
            ) as key:
                use_light, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
                if not use_light:
                    self.setStyle("Fusion")
                    from PySide6.QtGui import QPalette, QColor
                    palette = QPalette()
                    palette.setColor(QPalette.ColorRole.Window, QColor(32, 32, 32))
                    palette.setColor(QPalette.ColorRole.WindowText, QColor(220, 220, 220))
                    palette.setColor(QPalette.ColorRole.Base, QColor(25, 25, 25))
                    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(53, 53, 53))
                    palette.setColor(QPalette.ColorRole.Text, QColor(220, 220, 220))
                    palette.setColor(QPalette.ColorRole.Button, QColor(53, 53, 53))
                    palette.setColor(QPalette.ColorRole.ButtonText, QColor(220, 220, 220))
                    palette.setColor(QPalette.ColorRole.Highlight, QColor(0, 120, 215))
                    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
                    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(53, 53, 53))
                    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(220, 220, 220))
                    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(120, 120, 120))
                    self.setPalette(palette)
        except Exception:
            pass


def run_app() -> None:
    app = App()
    sys.exit(app.exec())
