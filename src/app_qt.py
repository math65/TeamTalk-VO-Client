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
from PySide6.QtGui import QAction, QKeySequence, QFont, QCloseEvent

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

APP_VERSION = "6.7.6"

TT_TRANSMITUSERS_MAX = 128
TT_TRANSMITUSERS_FREEFORALL = 0xFFF


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
        self._last_private_sender_id: Optional[int] = None
        self._last_private_message_text: str = ""
        self._status_message = ""
        self._capture_hotkey_target: Optional[str] = None
        self._user_volume_levels: Dict[int, int] = {}
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

        self.logger = FileLogger(_app_dir / "client.log")
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

        self._screen_reader = ScreenReaderAnnouncer()

        self.sound_manager = SoundManager()
        self._pronunciation = PronunciationManager(dict(getattr(_ts, "pronunciation_dict", {}) or {}))
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
        _away_min = int(getattr(_ts, "away_timer", 0) or 0)
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

        # Windows dark mode detection
        self._apply_windows_dark_mode()

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
    # Windows Dark Mode
    # ------------------------------------------------------------------

    def _apply_windows_dark_mode(self) -> None:
        """Detect Windows dark mode via registry and apply a dark Qt palette."""
        if sys.platform != "win32":
            return
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            )
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            winreg.CloseKey(key)
            is_dark = value == 0
        except Exception:
            return
        if not is_dark:
            return
        from PySide6.QtGui import QPalette, QColor
        p = QPalette()
        dark   = QColor(30, 30, 30)
        darker = QColor(20, 20, 20)
        mid    = QColor(45, 45, 45)
        light  = QColor(220, 220, 220)
        highlight = QColor(0, 120, 212)
        p.setColor(QPalette.ColorRole.Window,          dark)
        p.setColor(QPalette.ColorRole.WindowText,      light)
        p.setColor(QPalette.ColorRole.Base,            darker)
        p.setColor(QPalette.ColorRole.AlternateBase,   mid)
        p.setColor(QPalette.ColorRole.Text,            light)
        p.setColor(QPalette.ColorRole.Button,          mid)
        p.setColor(QPalette.ColorRole.ButtonText,      light)
        p.setColor(QPalette.ColorRole.Highlight,       highlight)
        p.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
        p.setColor(QPalette.ColorRole.ToolTipBase,     mid)
        p.setColor(QPalette.ColorRole.ToolTipText,     light)
        p.setColor(QPalette.ColorRole.PlaceholderText, QColor(120, 120, 120))
        from PySide6.QtWidgets import QApplication
        QApplication.instance().setPalette(p)
        self.logger.write("Windows dark mode erkannt — dunkles Farbschema aktiv")

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
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QDialogButtonBox
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
        self._add_action(datei, "&Trennen", self.on_menu_disconnect)
        self._add_action(datei, "Neu &verbinden", self.reconnect)
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
        self._add_action(datei, "Einstellungen &sichern (Backup)...", self.on_menu_settings_backup)
        self._add_action(datei, "Einstellungen &wiederherstellen...", self.on_menu_settings_restore)
        datei.addSeparator()
        self._add_action(datei, "&Beenden", self.force_close, "Ctrl+Q")

        # --- Kanal ---
        kanal = mb.addMenu("&Kanal")
        self._add_action(kanal, "Kanal &beitreten", self.on_menu_join_channel)
        self._add_action(kanal, "&Root-Kanal beitreten", self.on_menu_join_root)
        self._add_action(kanal, "Kanal &verlassen", self.on_menu_leave_channel)
        kanal.addSeparator()
        self._add_action(kanal, "Kanal &erstellen...", self.on_menu_create_channel)
        self._add_action(kanal, "Kanal &bearbeiten...", self.on_menu_edit_channel)
        self._add_action(kanal, "Kanal &löschen", self.on_menu_delete_channel)
        kanal.addSeparator()
        self._add_action(kanal, "Kanal&info vorlesen", self.on_menu_channel_info)
        self._add_action(kanal, "Kanal-&Notiz bearbeiten...", self.on_menu_channel_note)
        self._add_action(kanal, "Kanal&nachricht senden...", self.on_menu_send_channel_msg)
        kanal.addSeparator()
        self._add_action(kanal, "&Datei hochladen...", self.on_menu_upload_file)
        self._add_action(kanal, "Datei &herunterladen", self.on_menu_download_file)
        kanal.addSeparator()
        self._add_action(kanal, "Sperren im Kanal anzeigen...", self.on_menu_channel_bans)
        self._add_action(kanal, "Kanal&nachrichten anzeigen...", self.on_menu_channel_view_msgs)
        self._add_action(kanal, "Kanal&verlauf...", self.on_menu_channel_history)
        kanal.addSeparator()
        stream_m = kanal.addMenu("&Streamen")
        for _label, _mode in [
            ("&YouTube/URL...", "url"),
            ("&SoundCloud...", "soundcloud"),
            ("&Twitch...", "twitch"),
            ("&Webradio...", "radio"),
            ("&Podcast...", "podcast"),
            ("&Datei...", "file"),
            ("&Playlist...", "playlist"),
        ]:
            self._add_action(stream_m, _label,
                lambda checked=False, m=_mode: self._on_channel_stream_mode(m))

        # --- Benutzer ---
        benutzer = mb.addMenu("&Benutzer")
        self._add_action(benutzer, "&Benutzerinfo vorlesen", self.on_menu_user_info)
        self._add_action(benutzer, "&Private Nachricht...", self.on_menu_private_msg)
        benutzer.addSeparator()
        self._add_action(benutzer, "S&tummschalten (Sprache)", self.on_menu_mute_voice)
        self._add_action(benutzer, "Lautstärke &einstellen...", self.on_menu_user_volume)
        benutzer.addSeparator()
        self._add_action(benutzer, "Aus Kanal &kicken", self.on_menu_kick)
        self._add_action(benutzer, "Kicken + &Sperren", self.on_menu_kick_ban)
        self._add_action(benutzer, "Vom &Server kicken", self.on_menu_kick_server)
        benutzer.addSeparator()
        self._add_action(benutzer, "Benutzer &verschieben", self.on_menu_move_user)
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
        self._add_action(profil, "&Nickname ändern...", self.on_menu_change_nick)
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
        profil.addSeparator()
        self._add_action(profil, "TTS-&Mitschrift...", self.on_menu_tts_transcript)

        # --- Audio ---
        audio_m = mb.addMenu("&Audio")
        self._ptt_action = self._add_checkable(audio_m, "&Push-to-Talk",
            self._on_toggle_ptt,
            bool(getattr(self.settings_store.settings, "ptt_enabled", False)))
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

        # --- Aufnahmen ---
        aufn = mb.addMenu("A&ufnahmen")
        self._add_action(aufn, "Aufnahme &starten...", self.on_menu_start_recording)
        self._add_action(aufn, "Aufnahme &stoppen", self.on_menu_stop_recording)
        aufn.addSeparator()
        self._add_action(aufn, "Konversationen au&fzeichnen...", self.on_menu_user_recording)
        aufn.addSeparator()
        self._add_action(aufn, "Geplante &Aufnahmen...", self.on_menu_scheduled_recordings)

        # --- Server ---
        server_m = mb.addMenu("&Server")
        self._add_action(server_m, "&Online-Nutzer...", self.on_menu_online_users)
        self._add_action(server_m, "Server&nachricht senden...", self.on_menu_server_message)
        self._add_action(server_m, "Server-&Statistiken...", self.on_menu_server_stats)
        server_m.addSeparator()
        self._add_action(server_m, "&Sperrliste...", self.on_menu_ban_list)
        self._add_action(server_m, "&Administration...", self.on_menu_admin)
        self._add_action(server_m, "Server&eigenschaften...", self.on_menu_server_properties)
        server_m.addSeparator()
        self._add_action(server_m, "&Wer-spricht-Protokoll...", self.on_menu_speaking_log)
        self._add_action(server_m, "&Sitzungsübersicht...", self.on_menu_session_overview)

        # --- Automation ---
        auto_m = mb.addMenu("A&utomation")
        self._add_action(auto_m, "&Makro-Manager...", self.on_menu_macros)
        self._add_action(auto_m, "Geplante &Makros...", self.on_menu_scheduled_macros)
        auto_m.addSeparator()
        self._add_action(auto_m, "&Trigger-Regeln...", self.on_menu_trigger_editor)
        auto_m.addSeparator()
        self._add_action(auto_m, "&Chat-Suche...", self.on_menu_chat_search)
        self._add_action(auto_m, "&Nutzerwatcher...", self.on_menu_user_watcher)
        self._add_action(auto_m, "&Offline-Warteschlange...", self.on_menu_offline_queue)
        auto_m.addSeparator()
        self._translation_action = self._add_checkable(auto_m, "Chat-&Übersetzung",
            self._on_toggle_translation,
            bool(getattr(self.settings_store.settings, "translation_enabled", False)))
        auto_m.addSeparator()
        self._add_action(auto_m, "&Plugin-Manager...", self.on_menu_plugin_manager)
        auto_m.addSeparator()
        self._add_action(auto_m, "&Einstellungen...", self.on_menu_settings, "Ctrl+,")

        # --- Hilfe ---
        hlp = mb.addMenu("&Hilfe")
        self._add_action(hlp, "Logs &exportieren...", self.on_menu_export_logs)
        self._add_action(hlp, "&Gesundheitsbericht...", self.on_menu_health_report)
        self._add_action(hlp, "Verbindungs&statistiken...", self.on_menu_client_stats)
        self._add_action(hlp, "&Gespeicherte Nachrichten...", self.on_menu_saved_messages)
        self._add_action(hlp, "Auf &Updates prüfen...", self.on_menu_check_updates)
        hlp.addSeparator()
        self._add_action(hlp, "&Handbuch...", self.on_menu_manual)
        self._add_action(hlp, "&Changelog...", self.on_menu_changelog)
        hlp.addSeparator()
        self._add_action(hlp, "&Info...", self.on_menu_about)

    def _add_checkable(self, menu: QMenu, label: str, slot, checked: bool = False) -> QAction:
        action = QAction(label, self)
        action.setCheckable(True)
        action.setChecked(checked)
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
        self.sound_manager.play("server_disconnect")
        call_after(self._refresh_channels)
        if self._auto_reconnect:
            self._schedule_reconnect()

    def _handle_connect_result(self, result) -> None:
        if result.ok:
            profile = getattr(self, "_last_profile", None)
            server_name = (getattr(profile, "name", "") or getattr(profile, "host", "Server")) if profile else "Server"
            nick = getattr(profile, "nickname", "") if profile else ""
            self._update_conn_bar(f"Verbunden: {server_name}  |  Nickname: {nick}", connected=True)
            self.set_status(f"Angemeldet an {server_name}")
            self.tts.speak("Angemeldet", kind="system")
            self.sound_manager.play("server_connect")
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
            if ch_id == my_ch:
                if self.tts.settings.speak_user_join:
                    self.tts.speak(f"{name} hat den Kanal betreten", kind="system")
                self.sound_manager.play("user_join")
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
            if self.tts.settings.speak_user_leave:
                self.tts.speak(f"{name} hat den Kanal verlassen", kind="system")
            self.sound_manager.play("user_leave")
            self._refresh_channels()
        except Exception:
            pass

    def _on_user_update(self, msg) -> None:
        self._refresh_channels()

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
        except Exception:
            pass
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
                        self.sound_manager.play("msg_private_rx")
                    else:
                        self.sound_manager.play("msg_channel_rx")
                    self.tts.speak(speak_text, kind=kind)
                else:
                    if kind == "private":
                        self.sound_manager.play("msg_private_tx")
                    else:
                        self.sound_manager.play("msg_channel_tx")

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
                self.sound_manager.play("file_transfer")
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
        pass

    def start_hotkey_capture(self, key: str) -> None:
        self._capture_hotkey_target = key
        if hasattr(self, "shortcuts_tab"):
            self.shortcuts_tab.set_capture_label(key, True)
        self.set_status(f"Taste für '{key}' drücken...")

    def start_global_hotkey_capture(self, key: str) -> None:
        self._global_capture_target = key
        if hasattr(self, "shortcuts_tab"):
            self.shortcuts_tab.set_global_capture_label(key, True)

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
            self.set_status("Tastenkürzel gespeichert")
            return
        ptt_key = getattr(self.settings_store.settings, "ptt_key", None)
        if ptt_key and event.key() == ptt_key and not event.isAutoRepeat() and not self._ptt_active:
            self._ptt_active = True
            try:
                self.client.enable_voice_transmission(True)
            except Exception:
                pass
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
                self.sound_manager.play("msg_private_tx")
            else:
                self.client.send_channel_message(text)
                self.sound_manager.play("msg_channel_tx")
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
        self.set_status("Dateiübertragungsverlauf: nicht implementiert")

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
        self.set_status("Konto hinzufügen: nicht implementiert")

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
        self.set_status("Servereigenschaften bearbeiten: nicht implementiert")

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
        self.set_status("Öffentliche Serverliste: nicht implementiert")

    def manage_server_groups(self) -> None:
        self.set_status("Server-Gruppen verwalten: nicht implementiert")

    def import_tt_file(self, path: str) -> None:
        try:
            from ui.tt_file_parser import parse_teamtalk_file
            result = parse_teamtalk_file(path)
            if result:
                self.set_status(f"TT-Datei importiert: {path}")
        except Exception as exc:
            self.set_status(f"Import fehlgeschlagen: {exc}")

    def export_tt_file(self, idx: int) -> None:
        self.set_status("TT-Datei exportieren: nicht implementiert")

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
        pass

    def _on_server_choice_changed(self, idx: int) -> None:
        pass

    # ------------------------------------------------------------------
    # Menu handlers
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Datei-Menü
    # ------------------------------------------------------------------

    def on_menu_connect(self) -> None:
        dlg = ConnectDialog(self)
        dlg.exec()

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
        self.set_status("Kanal erstellen: nicht implementiert")

    def on_menu_edit_channel(self) -> None:
        self.set_status("Kanal bearbeiten: nicht implementiert")

    def on_menu_delete_channel(self) -> None:
        self.set_status("Kanal löschen: nicht implementiert")

    def on_menu_channel_info(self) -> None:
        try:
            ch_id = int(self.client.get_my_channel_id() or 0)
            if not ch_id:
                self.set_status("Kein Kanal")
                return
            ch = self.client.get_channel(ch_id)
            if ch:
                name = self.tt_str(ch.szName)
                topic = self.tt_str(ch.szTopic)
                info = f"Kanal: {name}"
                if topic:
                    info += f"  Thema: {topic}"
                self.tts.speak(info, kind="system")
                self.set_status(info)
        except Exception as exc:
            self.set_status(f"Kanalinfo Fehler: {exc}")

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
                nick = self.tt_str(user.szNickname) or self.tt_str(user.szUsername)
                ch_id = int(user.nChannelID)
                info = f"Benutzer: {nick}, Kanal-ID: {ch_id}"
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

    def on_menu_move_user(self) -> None:
        self.set_status("Benutzer verschieben: Kanal aus Kanalliste wählen")

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
        msg, ok = QInputDialog.getText(self, "Status", "Status-Meldung:")
        if ok:
            try:
                self.client.change_status(0, msg)
                self.set_status(f"Status gesetzt: {msg}")
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

    # ------------------------------------------------------------------
    # Audio-Menü
    # ------------------------------------------------------------------

    def _on_toggle_ptt(self, checked: bool) -> None:
        self._ptt_enabled = checked
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

    def on_menu_audio_effects(self) -> None:
        try:
            self.audio_tab._on_preprocess_changed()
            self.set_status("Audio-Effekte angewendet")
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

    def on_menu_admin(self) -> None:
        idx = self.notebook.indexOf(self.admin_tab)
        if idx >= 0:
            self.notebook.setCurrentIndex(idx)

    def on_menu_server_properties(self) -> None:
        self.edit_server_properties()

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

    # ------------------------------------------------------------------
    # Einstellungen / Navigation
    # ------------------------------------------------------------------

    def on_menu_settings(self) -> None:
        self._settings_dialog.show()
        self._settings_dialog.raise_()
        self._settings_dialog.activateWindow()

    def on_menu_connection_window(self) -> None:
        self.on_menu_connect()

    # ------------------------------------------------------------------
    # Dialoge
    # ------------------------------------------------------------------

    def on_menu_tts_transcript(self) -> None:
        from ui_qt.dialogs import TTSTranscriptDialog
        dlg = TTSTranscriptDialog(self, self.tts)
        dlg.exec()

    def on_menu_chat_search(self) -> None:
        from ui_qt.dialogs import ChatSearchDialog
        dlg = ChatSearchDialog(self, self._chat_history, self._current_server_key)
        dlg.exec()

    def on_menu_user_watcher(self) -> None:
        from ui_qt.dialogs import UserWatcherDialog
        dlg = UserWatcherDialog(self, self.settings_store)
        dlg.exec()

    def on_menu_offline_queue(self) -> None:
        from ui_qt.dialogs import OfflineQueueDialog
        dlg = OfflineQueueDialog(self, self._offline_queue)
        dlg.exec()

    def on_menu_server_audio_profiles(self) -> None:
        from ui_qt.dialogs import ServerAudioProfileDialog
        dlg = ServerAudioProfileDialog(self, self.settings_store)
        dlg.exec()

    def on_menu_online_users(self) -> None:
        from ui_qt.dialogs import OnlineUsersDialog
        dlg = OnlineUsersDialog(self, self.client, self.tt_str)
        dlg.exec()

    def on_menu_server_stats(self) -> None:
        from ui_qt.dialogs import ServerStatsDialog
        dlg = ServerStatsDialog(self, self.client)
        dlg.exec()

    def on_menu_speaking_log(self) -> None:
        from ui_qt.dialogs import SpeakingLogDialog
        dlg = SpeakingLogDialog(self, self._speaking_log)
        dlg.exec()

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

    def on_menu_ban_list(self) -> None:
        idx = self.notebook.indexOf(self.admin_tab)
        if idx >= 0:
            self.notebook.setCurrentIndex(idx)

    def on_menu_macros(self) -> None:
        from ui_qt.dialogs import MacroManagerDialog
        dlg = MacroManagerDialog(self, self._macros)
        dlg.exec()

    def on_menu_scheduled_macros(self) -> None:
        s = self.settings_store.settings
        scheduled = list(s.scheduled_macros or [])
        macro_names = [m.get("name", "?") for m in (s.macros or [])]

        dlg = QDialog(self)
        dlg.setWindowTitle("Geplante Makros")
        layout = QVBoxLayout(dlg)
        layout.addWidget(QLabel("Format HH:MM – täglich ausführen"))
        lw = QListWidget()
        for e in scheduled:
            lw.addItem(f"{e.get('time', '?')}, Makro: {e.get('macro', '?')}")
        lw.setMinimumHeight(160)
        layout.addWidget(lw, 1)
        form = QFormLayout()
        time_edit = QTimeEdit()
        time_edit.setDisplayFormat("HH:mm")
        form.addRow("Zeit:", time_edit)
        macro_combo = QComboBox()
        for name in macro_names:
            macro_combo.addItem(name)
        form.addRow("Makro:", macro_combo)
        layout.addLayout(form)
        btn_row = QHBoxLayout()
        add_btn = QPushButton("&Hinzufügen")
        del_btn = QPushButton("&Entfernen")
        btn_row.addWidget(add_btn)
        btn_row.addWidget(del_btn)
        layout.addLayout(btn_row)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        layout.addWidget(bb)

        def _add():
            t = time_edit.time().toString("HH:mm")
            m = macro_combo.currentText() if macro_names else ""
            if not m:
                return
            entry = {"time": t, "macro": m}
            scheduled.append(entry)
            lw.addItem(f"{t}, Makro: {m}")

        def _del():
            row = lw.currentRow()
            if 0 <= row < len(scheduled):
                scheduled.pop(row)
                lw.takeItem(row)

        add_btn.clicked.connect(_add)
        del_btn.clicked.connect(_del)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            try:
                self.settings_store.settings.scheduled_macros = scheduled
                self.settings_store.save()
                self.set_status("Geplante Makros gespeichert")
            except Exception as exc:
                self.set_status(f"Speichern fehlgeschlagen: {exc}")

    def on_menu_trigger_editor(self) -> None:
        s = self.settings_store.settings
        triggers = list(s.macro_triggers or [])
        macro_names = [m.get("name", "?") for m in (s.macros or [])]
        _EVENTS = ["user_join", "user_leave", "chat_message", "private_msg", "channel_join"]

        dlg = QDialog(self)
        dlg.setWindowTitle("Trigger-Regeln")
        layout = QVBoxLayout(dlg)
        layout.addWidget(QLabel("Makro automatisch ausführen wenn Ereignis eintritt:"))
        lw = QListWidget()
        for t in triggers:
            filt = t.get("filter", "") or ""
            filt_str = f" (Filter: {filt})" if filt else ""
            lw.addItem(f"{t.get('event','?')}{filt_str} → {t.get('macro','?')}")
        lw.setMinimumHeight(160)
        layout.addWidget(lw, 1)
        form = QFormLayout()
        event_combo = QComboBox()
        for ev in _EVENTS:
            event_combo.addItem(ev)
        form.addRow("Ereignis:", event_combo)
        filter_edit = QLineEdit()
        form.addRow("Filter (Name, leer=alle):", filter_edit)
        macro_combo = QComboBox()
        for name in macro_names:
            macro_combo.addItem(name)
        form.addRow("Makro:", macro_combo)
        layout.addLayout(form)
        btn_row = QHBoxLayout()
        add_btn = QPushButton("&Hinzufügen")
        del_btn = QPushButton("&Entfernen")
        btn_row.addWidget(add_btn)
        btn_row.addWidget(del_btn)
        layout.addLayout(btn_row)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        layout.addWidget(bb)

        def _add():
            ev = event_combo.currentText()
            filt = filter_edit.text().strip()
            m = macro_combo.currentText() if macro_names else ""
            if not m:
                return
            entry = {"event": ev, "macro": m}
            if filt:
                entry["filter"] = filt
            triggers.append(entry)
            filt_str = f" (Filter: {filt})" if filt else ""
            lw.addItem(f"{ev}{filt_str} → {m}")

        def _del():
            row = lw.currentRow()
            if 0 <= row < len(triggers):
                triggers.pop(row)
                lw.takeItem(row)

        add_btn.clicked.connect(_add)
        del_btn.clicked.connect(_del)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            try:
                self.settings_store.settings.macro_triggers = triggers
                self.settings_store.save()
                self.set_status("Trigger-Regeln gespeichert")
            except Exception as exc:
                self.set_status(f"Speichern fehlgeschlagen: {exc}")

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
                    self.setPalette(palette)
        except Exception:
            pass


def run_app() -> None:
    app = App()
    sys.exit(app.exec())
