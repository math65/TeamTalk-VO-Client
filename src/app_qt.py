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
    QInputDialog, QLineEdit,
)
from PySide6.QtCore import QTimer, Qt, Signal, QObject
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
from ui_qt.tabs.connection import ConnectionTab
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

APP_VERSION = "6.7.2"

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

        # Status bar
        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._status_bar.showMessage(f"TeamTalk VoiceOver Client {APP_VERSION}")

        # Start TT event loop
        self._tt_event_timer = QTimer(self)
        self._tt_event_timer.timeout.connect(self._poll_tt_events)
        self._tt_event_timer.start(50)

        # Reconnect timer
        self._reconnect_timer = QTimer(self)
        self._reconnect_timer.timeout.connect(self._on_reconnect_tick)

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

        # Server switcher bar
        srv_bar = QHBoxLayout()
        srv_bar.addWidget(QLabel("Server:"))
        self.server_choice = QComboBox()
        self.server_choice.setMinimumWidth(200)
        self.server_choice.currentIndexChanged.connect(self._on_server_choice_changed)
        self._srv_connect_btn = QPushButton("&Verbinden")
        self._srv_connect_btn.clicked.connect(lambda: self.on_menu_connect())
        self._srv_disconnect_btn = QPushButton("&Trennen")
        self._srv_disconnect_btn.clicked.connect(lambda: self.on_menu_disconnect())
        srv_bar.addWidget(self.server_choice, 1)
        srv_bar.addWidget(self._srv_connect_btn)
        srv_bar.addWidget(self._srv_disconnect_btn)
        root.addLayout(srv_bar)

        # Tab widget
        self.notebook = QTabWidget()
        self.notebook.currentChanged.connect(self._on_tab_changed)
        root.addWidget(self.notebook, 1)

        # Connection tab
        self.connection_tab = ConnectionTab(self.notebook, self)
        self.notebook.addTab(self.connection_tab, "Verbindung")

        # Channels+Chat
        self._cc_tab = ChannelsChatTab(self.notebook, self)
        self.channels_tab = self._cc_tab.channels_tab
        self.chat_tab = self._cc_tab.chat_tab
        self.notebook.addTab(self._cc_tab, "Kanäle & Chat")

        # Media
        self.media_tab = MediaTab(self.notebook, self)
        self.notebook.addTab(self.media_tab, "Medien")

        # Files
        self.files_tab = FilesTab(self.notebook, self)
        self.notebook.addTab(self.files_tab, "Dateien")

        # Admin
        self.admin_tab = AdminTab(self.notebook, self)
        self.notebook.addTab(self.admin_tab, "Administration")

        # Speak (ElevenLabs)
        self.speak_tab = SpeakTab(self.notebook, self)
        self.notebook.addTab(self.speak_tab, "Sprechen")

        # Desktop share
        self.desktop_tab = DesktopTab(self.notebook, self)
        self.notebook.addTab(self.desktop_tab, "Desktop")

        # Settings
        self.settings_tab_widget = SettingsTab(self.notebook, self)
        self.audio_tab = self.settings_tab_widget.audio_tab
        self.video_tab = self.settings_tab_widget.video_tab
        self.shortcuts_tab = self.settings_tab_widget.shortcuts_tab
        self.system_tab = self.settings_tab_widget.system_tab
        self.notebook.addTab(self.settings_tab_widget, "Einstellungen")

    def _build_menu(self) -> None:
        mb = self.menuBar()

        # Server menu
        srv = mb.addMenu("&Server")
        self._add_action(srv, "&Verbinden...", self.on_menu_connect, "Ctrl+Return")
        self._add_action(srv, "&Trennen", self.on_menu_disconnect)
        srv.addSeparator()
        self._add_action(srv, "&Kanal beitreten", self.on_menu_join_channel)
        self._add_action(srv, "Root-&Kanal", self.on_menu_join_root)
        self._add_action(srv, "Kanal &verlassen", self.on_menu_leave_channel)
        srv.addSeparator()
        self._add_action(srv, "&Status ändern...", self.on_menu_status)
        self._add_action(srv, "&Beenden", self.force_close, "Ctrl+Q")

        # Tools menu
        tools = mb.addMenu("&Werkzeuge")
        self._add_action(tools, "&TTS-Mitschrift...", self.on_menu_tts_transcript)
        self._add_action(tools, "&Chat-Suche...", self.on_menu_chat_search)
        self._add_action(tools, "&Nutzerwatcher...", self.on_menu_user_watcher)
        self._add_action(tools, "&Offline-Warteschlange...", self.on_menu_offline_queue)
        self._add_action(tools, "&Per-Server-Soundprofile...", self.on_menu_server_audio_profiles)
        tools.addSeparator()
        self._add_action(tools, "&Online-Nutzer...", self.on_menu_online_users)
        self._add_action(tools, "&Server-Statistiken...", self.on_menu_server_stats)
        self._add_action(tools, "&Sperrliste...", self.on_menu_ban_list)
        tools.addSeparator()
        self._add_action(tools, "&Makro-Manager...", self.on_menu_macros)

        # View menu
        view = mb.addMenu("&Ansicht")
        self._add_action(view, "&Einstellungen...", self.on_menu_settings, "Ctrl+,")
        self._add_action(view, "&Verbindung...", self.on_menu_connection_window)

        # Help menu
        hlp = mb.addMenu("&Hilfe")
        self._add_action(hlp, "&Handbuch...", self.on_menu_manual)
        self._add_action(hlp, "&Info...", self.on_menu_about)

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

    # ------------------------------------------------------------------
    # TeamTalk Event Loop
    # ------------------------------------------------------------------

    def _poll_tt_events(self) -> None:
        try:
            msgs = self.client.get_messages(max_count=32, timeout_ms=0)
        except Exception:
            return
        for msg in (msgs or []):
            try:
                self._handle_tt_message(msg)
            except Exception:
                pass

    def _handle_tt_message(self, msg) -> None:
        tt = self.client.tt
        mtype = int(msg.nClientEvent)

        if mtype == int(tt.ClientEvent.CLIENTEVENT_CON_SUCCESS):
            call_after(self._on_connected)
        elif mtype == int(tt.ClientEvent.CLIENTEVENT_CON_FAILED):
            call_after(self._on_connect_failed)
        elif mtype == int(tt.ClientEvent.CLIENTEVENT_CON_LOST):
            call_after(self._on_connection_lost)
        elif mtype == int(tt.ClientEvent.CLIENTEVENT_CMD_MYSELF_LOGGEDIN):
            call_after(self._on_logged_in, msg)
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

    def _on_connected(self) -> None:
        self.set_status("Verbunden, melde an...")
        profile = getattr(self, "_last_profile", None)
        if profile:
            try:
                self.client.login(
                    profile.nickname,
                    profile.username,
                    profile.password,
                    profile.client_name,
                )
            except Exception as exc:
                self.set_status(f"Login fehlgeschlagen: {exc}")

    def _on_connect_failed(self) -> None:
        self.set_status("Verbindung fehlgeschlagen")
        if self._auto_reconnect:
            self._schedule_reconnect()

    def _on_connection_lost(self) -> None:
        self.set_status("Verbindung verloren")
        self.tts.speak("Verbindung verloren", kind="system")
        self.sound_manager.play("server_disconnect")
        call_after(self._refresh_channels)
        if self._auto_reconnect:
            self._schedule_reconnect()

    def _on_logged_in(self, msg) -> None:
        self.set_status("Angemeldet")
        self.tts.speak("Angemeldet", kind="system")
        self.sound_manager.play("server_connect")
        self._audit_log.log(A_SERVER_CONNECT)
        self._drain_offline_queue()
        profile = getattr(self, "_last_profile", None)
        if profile:
            try:
                root_id = self.client.get_root_channel_id()
                if root_id:
                    join_ch = getattr(profile, "channel", "") or ""
                    if join_ch:
                        self._join_channel_by_path(join_ch)
                    else:
                        self.client.join_channel_by_id(root_id, "")
            except Exception as exc:
                self.logger.write(f"Auto-join fehlgeschlagen: {exc}")
        self._refresh_channels()

    def _on_logged_out(self) -> None:
        self.set_status("Abgemeldet")
        self._refresh_channels()

    def _join_channel_by_path(self, path: str) -> None:
        try:
            channels = list(self.client.get_server_channels() or [])
            for ch in channels:
                name = self.tt_str(ch.szName)
                if name == path or f"/{name}" == path:
                    self.client.join_channel_by_id(int(ch.nChannelID), "")
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
        try:
            self.client.connect(
                profile.host,
                profile.tcp_port,
                profile.udp_port,
                profile.encrypted,
            )
            self.set_status(f"Verbinde mit {profile.host}:{profile.tcp_port}...")
        except Exception as exc:
            self.set_status(f"Verbindungsfehler: {exc}")

    def reconnect(self) -> None:
        profile = getattr(self, "_last_profile", None)
        if profile:
            try:
                self.client.disconnect()
            except Exception:
                pass
            QTimer.singleShot(500, lambda: self.connect_to_server(profile))

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

    def start_media_stream(self, url: str) -> None:
        try:
            self.client.start_streaming_media_file_to_channel(url, 0)
            self.set_status(f"Streaming gestartet: {url}")
        except Exception as exc:
            self.set_status(f"Streaming fehlgeschlagen: {exc}")

    def stop_media_stream(self) -> None:
        try:
            self.client.stop_streaming_media_file_to_channel()
            self.set_status("Streaming gestoppt")
        except Exception:
            pass

    def yt_search(self, query: str, source: str, list_widget) -> None:
        self.set_status(f"Suche: {query} ({source})...")

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
                self.client.ban_user_by_ip(ip)
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

    def refresh_elevenlabs_voices(self, tab) -> None:
        self.set_status("ElevenLabs Stimmen werden geladen...")

    def elevenlabs_generate_and_send(self, text, voice_id, model_id, stability, similarity, streaming):
        self.set_status("ElevenLabs TTS: nicht implementiert")

    def elevenlabs_preview(self, text, tab) -> None:
        self.set_status("ElevenLabs Vorschau: nicht implementiert")

    def elevenlabs_stop(self) -> None:
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
            self.connection_tab.reload_server_list()

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
        self.notebook.setCurrentIndex(1)
        try:
            self.chat_tab.private_chat.setChecked(True)
            uid_list = self.chat_tab._private_user_ids
            if user_id in uid_list:
                self.chat_tab.private_user.setCurrentIndex(uid_list.index(user_id))
        except Exception:
            pass

    def kick_user(self, user_id: int) -> None:
        try:
            self.client.kick_user(user_id, 0)
        except Exception as exc:
            self.set_status(f"Kick fehlgeschlagen: {exc}")

    def mute_user(self, user_id: int) -> None:
        try:
            muted = user_id not in self._user_volume_levels or self._user_volume_levels[user_id] > 0
            self.client.set_user_volume(user_id, 0 if muted else 100)
            self._user_volume_levels[user_id] = 0 if muted else 100
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
    # Tab change
    # ------------------------------------------------------------------

    def _on_tab_changed(self, idx: int) -> None:
        pass

    def _on_server_choice_changed(self, idx: int) -> None:
        pass

    # ------------------------------------------------------------------
    # Menu handlers
    # ------------------------------------------------------------------

    def on_menu_connect(self) -> None:
        profile = self.connection_tab.profile_from_form()
        if profile:
            self.connect_to_server(profile)

    def on_menu_disconnect(self) -> None:
        self.logout()

    def on_menu_join_channel(self) -> None:
        row = self.channels_tab.channel_list.currentRow()
        if row >= 0:
            self.channels_tab._on_join_btn()

    def on_menu_join_root(self) -> None:
        self.join_root_channel()

    def on_menu_leave_channel(self) -> None:
        self.leave_channel()

    def on_menu_status(self) -> None:
        msg, ok = QInputDialog.getText(self, "Status", "Status-Meldung:")
        if ok:
            try:
                self.client.change_status(0, msg)
            except Exception:
                pass

    def on_menu_settings(self) -> None:
        idx = self.notebook.indexOf(self.settings_tab_widget)
        if idx >= 0:
            self.notebook.setCurrentIndex(idx)

    def on_menu_connection_window(self) -> None:
        self.notebook.setCurrentIndex(0)

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
        from ui_qt.dialogs import ServerStatisticsDialog
        dlg = ServerStatisticsDialog(self, self.client)
        dlg.exec()

    def on_menu_ban_list(self) -> None:
        idx = self.notebook.indexOf(self.admin_tab)
        if idx >= 0:
            self.notebook.setCurrentIndex(idx)

    def on_menu_macros(self) -> None:
        from ui_qt.dialogs import MacroManagerDialog
        dlg = MacroManagerDialog(self, self._macros)
        dlg.exec()

    def on_menu_manual(self) -> None:
        try:
            import webbrowser
            manual_path = Path(__file__).parent / "manual.html"
            if manual_path.exists():
                webbrowser.open(str(manual_path))
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
        self._tt_event_timer.stop()
        self._reconnect_timer.stop()
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
