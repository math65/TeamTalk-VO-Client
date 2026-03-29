from __future__ import annotations

import os
import sys
import threading
import time
import traceback
import json
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import wx
import wx.adv
import wx.dataview as dv

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
from ui.tray import TrayIcon
from ui.tt_file_parser import parse_teamtalk_file
from ui.tabs.connection import ConnectionTab
from ui.tabs.channels_chat import ChannelsChatTab
from ui.tabs.media import MediaTab
from ui.tabs.files import FilesTab
from ui.tabs.admin import AdminTab
from ui.tabs.speak import SpeakTab
from ui.tabs.settings import SettingsTab
from ui.tabs.desktop import DesktopTab
from ui.server_tools import BroadcastMessageDialog, OnlineUsersDialog, ServerStatisticsDialog, BanListDialog
from ui.user_status import ChangeStatusDialog
from ui.client_stats import ClientStatisticsDialog
from tts import TTSManager
from sound_manager import SoundManager
from platform_paths import log_dir as _log_dir # Moved this import up
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
from offline_queue import OfflineMessageQueue
from startup_profiler import StartupProfiler
from eq_presets import EqPresetsManager
from audit_log import AuditLog, A_SERVER_CONNECT, A_SERVER_DISCONNECT, A_API_KEY_SAVED, A_API_KEY_DELETED, A_SAVED_MSG_EXPIRED
from tls_verify import CertPinStore
from plugin_package import PluginPackage, read_package, install_package, PluginManifestError
from plugin_marketplace import PluginMarketplace
from companion_server import CompanionServer
from macos_integration import send_notification, set_dock_badge, DarkModeWatcher


APP_VERSION = "5.3.0"

def _upd_tok() -> str:
    import base64 as _b
    return bytes(x ^ 0x37 for x in _b.b64decode(
        b"UlYDU1VWVVFUBFRVVlFRAAAGUQQAU1NTAlUFUQQEVgNWAwMOUVFTDw=="
    )).decode()

TT_TRANSMITUSERS_MAX = 128
TT_TRANSMITUSERS_FREEFORALL = 0xFFF
TT_TRANSMITUSERS_USERID_INDEX = 0
TT_TRANSMITUSERS_STREAMTYPE_INDEX = 1


def _init_startup_logging() -> None:
    # `log_dir` is now imported at the top
    log_path = _log_dir()
    try:
        log_path.mkdir(parents=True, exist_ok=True)
    except Exception:
        if sys.platform == "win32":
            log_path = Path(os.environ.get("TEMP", "C:\\Temp")) / "TeamTalkVOClient"
        else:
            log_path = Path("/tmp") / "TeamTalkVOClient"
        log_path.mkdir(parents=True, exist_ok=True)

    log_file = log_path / "startup.log"
    # v4.1.0 – Strukturiertes JSON-Startup-Log parallel zum Text-Log
    json_log_file = log_path / "startup.jsonl"
    try:
        stream = log_file.open("a", encoding="utf-8")
        sys.stdout = stream
        sys.stderr = stream
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        print(f"\n=== Startup {ts} ===")
        print("sys.argv:", sys.argv)
        print("sys.frozen:", getattr(sys, "frozen", False))
        print("sys._MEIPASS:", getattr(sys, "_MEIPASS", None))
        # JSON-Eintrag schreiben
        try:
            entry = {
                "event": "startup",
                "timestamp": ts,
                "argv": sys.argv,
                "frozen": getattr(sys, "frozen", False),
                "meipass": str(getattr(sys, "_MEIPASS", "") or ""),
                "platform": sys.platform,
                "python": sys.version,
            }
            with json_log_file.open("a", encoding="utf-8") as jf:
                jf.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass
    except Exception:
        pass


_init_startup_logging()

# v4.6.0 – Startup-Profiler (globale Instanz, wird in MainFrame verwendet)
_startup_profiler: "StartupProfiler | None" = None


def _get_startup_profiler() -> "StartupProfiler":
    global _startup_profiler
    if _startup_profiler is None:
        from startup_profiler import StartupProfiler as _SP
        _startup_profiler = _SP()
    return _startup_profiler


# Ensure third_party is on sys.path for fvhai
_third_party = Path(__file__).resolve().parent.parent / "third_party"
if str(_third_party) not in sys.path:
    sys.path.insert(0, str(_third_party))


class ServerCheckDialog(wx.Dialog):
    def __init__(self, parent: wx.Window, rows: List[Tuple[str, str, str, str]]) -> None:
        super().__init__(parent, title="Server-Status", style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.SetMinSize((760, 420))

        panel = wx.Panel(self)
        root = wx.BoxSizer(wx.VERTICAL)

        accel = wx.AcceleratorTable([(wx.ACCEL_CMD, ord("W"), wx.ID_CLOSE)])
        self.SetAcceleratorTable(accel)
        self.Bind(wx.EVT_MENU, lambda e: self.EndModal(wx.ID_CANCEL), id=wx.ID_CLOSE)

        def _parse_online_count(result: str) -> int:
            text = (result or "").strip().lower()
            if text.endswith("online"):
                try:
                    return int(text.split()[0])
                except Exception:
                    return 0
            return 0

        total = len(rows)
        errors = sum(1 for _s, _t, result, _d in rows if (result or "").strip().lower() == "fehler")
        empty = sum(1 for _s, _t, result, _d in rows if (result or "").strip().lower() == "0 online")
        online_servers = total - errors - empty
        online_users = sum(_parse_online_count(result) for _s, _t, result, _d in rows)

        info = wx.StaticText(
            panel,
            label=(
                f"Geprüfte Server: {total}  |  Online-Server: {online_servers}  |  "
                f"Leere Server: {empty}  |  Fehler: {errors}  |  Nutzer online: {online_users}"
            ),
        )
        root.Add(info, 0, wx.ALL, 10)

        table = dv.DataViewListCtrl(panel, style=wx.BORDER_SUNKEN)
        table.SetName("Server-Status Tabelle")
        table.AppendTextColumn("Server", width=220)
        table.AppendTextColumn("TLS", width=110)
        table.AppendTextColumn("Ergebnis", width=120)
        table.AppendTextColumn("Nutzer / Details", width=560)
        def _sort_key(row: Tuple[str, str, str, str]) -> Tuple[int, int, str]:
            server, _tls, result, _details = row
            result_text = (result or "").strip().lower()
            if result_text == "fehler":
                priority = 0
            elif result_text == "0 online":
                priority = 2
            else:
                priority = 1
            online_count = _parse_online_count(result)
            return (priority, -online_count, server.lower())

        for server, tls, result, details in sorted(rows, key=_sort_key):
            table.AppendItem([server, tls, result, details])
        root.Add(table, 1, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 10)

        btn_sizer = wx.StdDialogButtonSizer()
        ok_btn = wx.Button(panel, wx.ID_OK)
        btn_sizer.AddButton(ok_btn)
        btn_sizer.Realize()
        root.Add(btn_sizer, 0, wx.ALL | wx.ALIGN_RIGHT, 10)

        panel.SetSizer(root)
        self.CentreOnParent()


class LazyTabPlaceholder(wx.Panel):
    def __init__(self, parent: wx.Window, label: str) -> None:
        super().__init__(parent)
        self.label = label
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(wx.StaticText(self, label="Wird geladen..."), 0, wx.ALL, 12)
        self.SetSizer(sizer)


class SettingsWindow(wx.Frame):
    def __init__(self, parent: wx.Window) -> None:
        super().__init__(parent, title="Einstellungen", size=(880, 820))
        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)
        self.settings_tab = SettingsTab(panel, parent)
        sizer.Add(self.settings_tab, 1, wx.ALL | wx.EXPAND, 8)
        panel.SetSizer(sizer)
        self.Bind(wx.EVT_CLOSE, self._on_close)
        self.Bind(wx.EVT_SHOW, self._on_show)
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)
        self._bind_shortcuts()

    def _on_close(self, event):
        # Hide instead of destroy to keep state.
        self.Hide()
        self.settings_tab.audio_tab.set_active(False)
        if event.CanVeto():
            event.Veto()

    def _on_show(self, event):
        if event.IsShown():
            self.settings_tab.audio_tab.set_active(True)
        else:
            self.settings_tab.audio_tab.set_active(False)
        event.Skip()

    def _bind_shortcuts(self) -> None:
        accel = wx.AcceleratorTable(
            [
                (wx.ACCEL_CMD, ord("W"), wx.ID_CLOSE),
            ]
        )
        self.SetAcceleratorTable(accel)
        self.Bind(wx.EVT_MENU, self._on_menu_close, id=wx.ID_CLOSE)

    def _on_menu_close(self, _event) -> None:
        self.Hide()
        self.settings_tab.audio_tab.set_active(False)

    def _on_char_hook(self, event) -> None:
        if event.CmdDown() and event.GetKeyCode() in (ord("W"), ord("w")):
            self._on_menu_close(None)
            return
        event.Skip()


class ConnectionWindow(wx.Frame):
    def __init__(self, parent: wx.Window) -> None:
        super().__init__(parent, title="Verbindung", size=(980, 900))
        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)
        self.connection_tab = ConnectionTab(panel, parent)
        sizer.Add(self.connection_tab, 1, wx.ALL | wx.EXPAND, 8)
        panel.SetSizer(sizer)
        self.Bind(wx.EVT_CLOSE, self._on_close)
        self._bind_shortcuts()

    def _on_close(self, event):
        # Hide instead of destroy to keep state.
        self.Hide()
        if event.CanVeto():
            event.Veto()

    def _bind_shortcuts(self) -> None:
        accel = wx.AcceleratorTable(
            [
                (wx.ACCEL_CMD, ord("W"), wx.ID_CLOSE),
            ]
        )
        self.SetAcceleratorTable(accel)
        self.Bind(wx.EVT_MENU, self._on_menu_close, id=wx.ID_CLOSE)

    def _on_menu_close(self, _event) -> None:
        self.Hide()


class MainFrame(wx.Frame):
    """Main window -- thin orchestrator that manages tab panels and dispatches events."""

    def __init__(self) -> None:
        super().__init__(None, title=f"TeamTalk VoiceOver Client {APP_VERSION}")
        self.client = TeamTalkClient()

        # Shared state
        self._closing = False
        self._auto_reconnect = False
        self._reconnect_attempts = 0
        self._ptt_enabled = False
        self._ptt_active = False
        self._message_buffers: Dict[Tuple[int, int, int, int], List] = {}
        self._pending_join: Optional[ParsedTeamTalkFile] = None
        self._window_focused = True
        self._capture_ptt_hotkey = False
        self._recording_active = False
        self._recording_path: Optional[str] = None
        self._user_recording_enabled = False
        self._user_recording_dir = ""
        self._user_recording_pattern = ""
        self._user_recording_format = int(self.client.tt.AudioFileFormat.AFF_WAVE_FORMAT)
        self._user_recording_include_self = True
        self._video_tx_enabled = False
        self._mute_all = False
        self._move_target_channel_id: Optional[int] = None
        self._last_private_sender_id: Optional[int] = None
        self._status_mode = 0
        self._status_message = ""
        self._capture_hotkey_target: Optional[str] = None
        self._user_volume_levels: Dict[int, int] = {}
        self._user_media_volume_levels: Dict[int, int] = {}
        self._channel_message_log: List[str] = []
        self._offline_event_log: List[Tuple[str, str, str]] = []  # (ts, text, kind)
        self._offline_buffering = False
        self._sound_input_menu: Optional[wx.Menu] = None
        self._sound_output_menu: Optional[wx.Menu] = None
        self._sound_menu_device_map: Dict[int, Tuple[str, int]] = {}
        self.speak_tab: Optional[SpeakTab] = None
        self._speak_tab_added = False
        self.media_tab: Optional[MediaTab] = None
        self.files_tab: Optional[FilesTab] = None
        self.admin_tab: Optional[AdminTab] = None
        self.desktop_tab: Optional[DesktopTab] = None
        self._lazy_pages: Dict[str, wx.Panel] = {}

        # Paths
        from platform_paths import app_data_dir
        app_dir = app_data_dir()
        app_dir.mkdir(parents=True, exist_ok=True)

        # v2.0.0: SQLite-Datenbank (migriert automatisch aus JSON)
        self._settings_db = SettingsDB(app_dir / "settings.db")
        migrated = migrate_from_json(
            self._settings_db,
            app_dir / "settings.json",
            app_dir / "servers.json",
        )
        if migrated:
            print("[v2.0.0] Einstellungen aus JSON nach SQLite migriert.")
        self.settings_store = SQLiteSettingsStore(self._settings_db)
        self.store = SQLiteServerStore(self._settings_db)
        # v3.6.0 – Sprache initialisieren
        _lang = getattr(self.settings_store.settings, "app_language", "de") or "de"
        set_language(_lang)

        # JSON-Stores als Fallback (werden nicht mehr aktiv beschrieben)
        self._json_settings_store = SettingsStore(app_dir / "settings.json")
        self._json_server_store = ServerStore(app_dir / "servers.json")

        self.logger = FileLogger(app_dir / "client.log")
        self._chat_history = ChatHistoryManager(app_dir)
        # v3.7.0 – Gespeicherte Nachrichten
        self._saved_messages = SavedMessageManager(app_dir)
        # v3.8.0 – Kanal-Notizen
        self._channel_notes = ChannelNotesManager(app_dir)
        # v3.9.0 – Übersetzer + Antwortvorschläge
        self._translator = ChatTranslatorManager(self.settings_store)
        self._ai_reply = AiReplyManager(self.settings_store)
        self._last_private_message_text: str = ""
        # v4.5.0 – Offline-Nachrichten-Warteschlange
        self._offline_queue = OfflineMessageQueue(app_dir)
        # v4.7.0 – EQ-Preset-Manager
        self._eq_presets = EqPresetsManager(app_dir)
        # v4.9.0 – Audit-Log, TLS-Pin-Store, gespeicherte Nachrichten ablaufen lassen
        self._audit_log = AuditLog(app_dir)
        self._cert_pins = CertPinStore(app_dir)
        # v4.10.0 – Plugin-Marktplatz
        self._marketplace = PluginMarketplace(plugins_dir=app_dir / "plugins")
        # v5.3.0 – macOS Desktop-Integration
        self._dark_mode_watcher = DarkModeWatcher(self._on_dark_mode_change)
        self._dark_mode_watcher.start()
        self._unread_count: int = 0
        # v5.1.0 – Companion-Server (Mobil-Companion)
        self._companion = CompanionServer(
            get_status_fn=self._companion_status,
            get_channels_fn=self._companion_channels,
            get_users_fn=self._companion_users,
            send_message_fn=self._companion_send,
        )
        _expired = self._saved_messages.expire()
        if _expired > 0:
            self._audit_log.log(A_SAVED_MSG_EXPIRED, detail=str(_expired))
        # v1.10.0 – Event-Bus + Plugin-Loader
        from event_bus import EventBus
        self.bus = EventBus()
        # v4.0.0 – Asyncio-Bridge (Bus-basiert, läuft dauerhaft)
        self._async_bridge = AsyncBusBridge(self.bus)
        self._async_bridge.start()
        from scheduled_recordings import ScheduledRecordingManager
        self._scheduled_rec_manager = ScheduledRecordingManager(app_dir)
        from plugin_api import PluginAPI
        from plugin_loader import PluginLoader
        self._plugin_api = PluginAPI(self)
        # v2.0.0 – Multi-Server, Braille, KI
        self.server_manager = ServerManager(self.bus)
        self._ai_summary: ChatSummaryManager | None = None  # wird nach TTS-Init gesetzt
        # Bus-Handler für Multi-Server
        self.bus.on("active_server_changed", self._on_active_server_changed)
        self.bus.on("server_state_changed", self._on_server_state_changed)
        # v3.5.0 – Makro-Trigger via Bus-Events
        self.bus.on("user_joined", lambda **kw: self._macros.fire_event("user_join", **kw))
        self.bus.on("user_left", lambda **kw: self._macros.fire_event("user_leave", **kw))
        self.bus.on("chat_message", lambda **kw: self._macros.fire_event("chat_message", **kw))
        self.bus.on("channel_joined", lambda **kw: self._macros.fire_event("channel_join", **kw))
        plugins_dir = Path(__file__).parent.parent / "plugins"
        self._plugin_loader = PluginLoader(self.bus, plugins_dir, api=self._plugin_api)
        n = self._plugin_loader.load_all()
        if n:
            self.logger.write(f"Plugins geladen: {n}")
        self._current_server_key = ""
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
        self.tts.settings.speak_who_speaks = _ts.tts_speak_who_speaks
        self.tts.settings.speak_channel_topic = _ts.tts_speak_channel_topic
        self.tts.settings.connect_announce = _ts.tts_connect_announce
        # v2.2.0 per-context TTS rates
        self.tts.settings.chat_rate = int(getattr(_ts, "tts_chat_rate", 0) or 0)
        self.tts.settings.system_rate = int(getattr(_ts, "tts_system_rate", 0) or 0)
        self.tts.settings.channel_rate = int(getattr(_ts, "tts_channel_rate", 0) or 0)
        self.tts.settings.chat_voice = str(getattr(_ts, "tts_chat_voice", "") or "")
        self.tts.settings.system_voice = str(getattr(_ts, "tts_system_voice", "") or "")
        self.sound_manager = SoundManager()
        self._ptt_hotkey = int(self.settings_store.settings.ptt_hotkey or 0) or wx.WXK_SPACE
        # v2.1.0 – Auto-Reconnect persistent
        self._auto_reconnect = bool(getattr(self.settings_store.settings, "auto_reconnect_enabled", True))
        # v2.2.0 – Aussprache, Lesezeichen
        self._pronunciation = PronunciationManager(dict(getattr(_ts, "pronunciation_dict", {}) or {}))
        self._bookmarks = BookmarkManager(self.settings_store)
        # v2.3.0 – Zeitgesteuerte Stille, Makros
        self._mute_scheduler = MuteScheduler(self)
        self._macros = MacroManager(self)
        # v2.5.0 – Auto-Antwort
        self._auto_reply = AutoReplyManager(self)
        # v2.7.0 – Webhook + HTTP-API
        self._webhook = WebhookManager(self)
        self._http_api = HttpApiServer(self)
        self._ping_last_ms: int = 0
        # v2.8.0 – PTT-Zeitlimit
        self._ptt_timeout_call: Optional[wx.CallLater] = None
        # v2.9.0 – VU-Pegel-Alarm, Aufnahme-Segmentierung
        self._vu_alert_count: int = 0
        self._recording_seg_start: float = 0.0
        self._recording_seg_timer: Optional[wx.Timer] = None
        # v3.0.0 – Wer-spricht-Protokoll
        self._speaking_log: List[Tuple[str, str, str]] = []
        self._user_speaking_start: Dict[int, float] = {}
        # v2.0.0 – Braille-Manager (nach TTS-Init)
        self.braille = BrailleOutputManager(self.tts)
        _braille_verbosity = getattr(self.settings_store.settings, "braille_verbosity", "normal")
        self.braille.verbosity = _braille_verbosity if _braille_verbosity in ("compact", "normal", "verbose") else "normal"
        # v2.0.2 – Gemini OAuth
        self._gemini_auth = GeminiAuthManager(app_dir)
        # v2.0.0 – KI-Zusammenfassung (mit Gemini-Auth)
        self._ai_summary = ChatSummaryManager(
            self.settings_store, self._chat_history, self._gemini_auth
        )
        # v2.0.0 – Sprachsteuerung (lazy init: wird erst bei Bedarf gestartet)
        self._voice_control = None
        # Global hotkeys (macOS)
        self._global_hotkey_mgr = None
        self._global_capture_target: Optional[str] = None
        if sys.platform == "darwin":
            try:
                from global_hotkeys import GlobalHotkeyManager
                self._global_hotkey_mgr = GlobalHotkeyManager()
            except Exception:
                pass

        # Tray
        self.tray = TrayIcon(self)

        # Menu
        self._build_menu()

        # --- Notebook ---
        panel = wx.Panel(self)
        panel.SetName("Hauptfenster")
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        # --- Multi-Server Switcher (v2.0.1) ---
        self.server_panel = wx.Panel(panel)
        self.server_panel.SetName("Server-Switcher")
        srv_sizer = wx.BoxSizer(wx.HORIZONTAL)
        srv_sizer.Add(wx.StaticText(self.server_panel, label="Server:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.server_choice = wx.Choice(self.server_panel)
        self.server_choice.SetName("Aktiver Server")
        self.server_choice.SetMinSize((200, -1))
        self.server_choice.Bind(wx.EVT_CHOICE, self._on_server_choice_changed)
        srv_sizer.Add(self.server_choice, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self._srv_connect_btn = wx.Button(self.server_panel, label="&Verbinden")
        self._srv_connect_btn.SetName("Server verbinden")
        self._srv_connect_btn.Bind(wx.EVT_BUTTON, lambda _e: self.on_menu_connect(None))
        srv_sizer.Add(self._srv_connect_btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        self._srv_disconnect_btn = wx.Button(self.server_panel, label="&Trennen")
        self._srv_disconnect_btn.SetName("Server trennen")
        self._srv_disconnect_btn.Bind(wx.EVT_BUTTON, lambda _e: self.on_menu_disconnect(None))
        srv_sizer.Add(self._srv_disconnect_btn, 0, wx.ALIGN_CENTER_VERTICAL)
        self.server_panel.SetSizer(srv_sizer)
        main_sizer.Add(self.server_panel, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)
        self._server_session_ids: List[str] = []  # parallel list to server_choice items

        nav_panel = wx.Panel(panel)
        nav_sizer = wx.BoxSizer(wx.HORIZONTAL)
        nav_label = wx.StaticText(nav_panel, label="Bereich:")
        self.tab_choice = wx.Choice(nav_panel)
        self.tab_choice.SetName("Bereich")
        self.tab_info = wx.StaticText(nav_panel, label="")
        self.tab_info.SetName("Bereichsinfo")
        nav_sizer.Add(nav_label, 0, wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 6)
        nav_sizer.Add(self.tab_choice, 0, wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 12)
        nav_sizer.Add(self.tab_info, 1, wx.ALIGN_CENTER_VERTICAL)
        nav_panel.SetSizer(nav_sizer)
        main_sizer.Add(nav_panel, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)

        # --- Quick-Actions Panel (toolbar equivalent, standardmaessig versteckt) ---
        self.qa_panel = wx.Panel(panel)
        self.qa_panel.SetName("Schnellaktionen")
        qa_panel = self.qa_panel  # lokaler Alias
        qa_sizer = wx.BoxSizer(wx.HORIZONTAL)

        self.tb_ptt = wx.CheckBox(qa_panel, label="&PTT")
        self.tb_ptt.SetName("Push-to-Talk")
        self.tb_va = wx.CheckBox(qa_panel, label="&Sprachaktivierung")
        self.tb_va.SetName("Sprachaktivierung")
        self.tb_video = wx.CheckBox(qa_panel, label="&Video")
        self.tb_video.SetName("Video senden")
        self.tb_desktop = wx.CheckBox(qa_panel, label="&Desktop")
        self.tb_desktop.SetName("Desktop freigeben")
        self.tb_mute = wx.CheckBox(qa_panel, label="S&tumm")
        self.tb_mute.SetName("Alles stummschalten")
        self.tb_record = wx.CheckBox(qa_panel, label="&Aufnahme")
        self.tb_record.SetName("Aufnahme")
        self.tb_question = wx.CheckBox(qa_panel, label="?-&Modus")
        self.tb_question.SetName("Frage-Modus")

        for btn in (self.tb_ptt, self.tb_va, self.tb_video, self.tb_desktop,
                    self.tb_mute, self.tb_record, self.tb_question):
            qa_sizer.Add(btn, 0, wx.RIGHT, 4)

        qa_sizer.AddSpacer(16)

        # Master volume spin (output)
        qa_sizer.Add(wx.StaticText(qa_panel, label="Ausgabe:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        self.master_volume_slider = wx.SpinCtrl(qa_panel, value="100", min=0, max=200)
        self.master_volume_slider.SetName("Ausgabelautstärke")
        self.master_volume_slider.SetMinSize((70, -1))
        qa_sizer.Add(self.master_volume_slider, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 12)

        # Mic gain spin
        qa_sizer.Add(wx.StaticText(qa_panel, label="Mikrofon:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        self.mic_gain_slider = wx.SpinCtrl(qa_panel, value="100", min=0, max=200)
        self.mic_gain_slider.SetName("Mikrofon-Gain")
        self.mic_gain_slider.SetMinSize((70, -1))
        qa_sizer.Add(self.mic_gain_slider, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 12)

        # VU meter
        qa_sizer.Add(wx.StaticText(qa_panel, label="Pegel:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        self.vu_meter = wx.Gauge(qa_panel, range=100, style=wx.GA_HORIZONTAL)
        self.vu_meter.SetName("Eingangspegel")
        self.vu_meter.SetMinSize((80, -1))
        qa_sizer.Add(self.vu_meter, 0, wx.ALIGN_CENTER_VERTICAL)

        qa_panel.SetSizer(qa_sizer)

        # --- Panel switcher (replaces wx.Notebook to avoid dual-navigation in VoiceOver) ---
        self.content_panel = wx.Panel(panel)
        self.content_panel.SetName("Hauptinhalt")
        self.content_sizer = wx.BoxSizer(wx.VERTICAL)

        self.connection_window = ConnectionWindow(self)
        self.connection_tab = self.connection_window.connection_tab
        self.channels_chat_tab = ChannelsChatTab(self.content_panel, self)
        self.channels_tab = self.channels_chat_tab.channels_tab
        self.chat_tab = self.channels_chat_tab.chat_tab
        self.settings_window = SettingsWindow(self)
        self.settings_tab = self.settings_window.settings_tab
        self.audio_tab = self.settings_tab.audio_tab
        self.video_tab = self.settings_tab.video_tab
        self.shortcuts_tab = self.settings_tab.shortcuts_tab
        self.system_tab = self.settings_tab.system_tab
        self.server_stats_dialog: Optional[ServerStatisticsDialog] = None
        self.online_users_dialog: Optional[OnlineUsersDialog] = None
        self.ban_dialog: Optional[BanListDialog] = None
        media_placeholder = LazyTabPlaceholder(self.content_panel, "Aufnahme & Medien")
        desktop_placeholder = LazyTabPlaceholder(self.content_panel, "Desktop")
        files_placeholder = LazyTabPlaceholder(self.content_panel, "Dateien")
        admin_placeholder = LazyTabPlaceholder(self.content_panel, "Administration")
        self._lazy_pages = {
            "media": media_placeholder,
            "desktop": desktop_placeholder,
            "files": files_placeholder,
            "admin": admin_placeholder,
        }

        self._tab_info_map = {
            "Kanäle und Chat": "Kanalliste, Nutzerliste, Chat und Privatnachrichten.",
            "Aufnahme & Medien": "Aufnahmen, Webradio/YouTube/Twitch-Streams.",
            "Desktop": "Desktopfreigabe senden/Status anzeigen.",
            "Dateien": "Kanaldateien hoch-/runterladen und verwalten.",
            "Administration": "Benutzerkonten, Sperren, Servereigenschaften.",
        }
        self._panels: Dict[str, wx.Panel] = {
            "Kanäle und Chat": self.channels_chat_tab,
            "Aufnahme & Medien": media_placeholder,
            "Desktop": desktop_placeholder,
            "Dateien": files_placeholder,
            "Administration": admin_placeholder,
        }
        self._panel_order: List[str] = list(self._panels.keys())

        for label, p in self._panels.items():
            self.content_sizer.Add(p, 1, wx.EXPAND)
            self.content_sizer.Show(p, label == "Kanäle und Chat")
        self.content_panel.SetSizer(self.content_sizer)

        self.tab_choice.SetItems(self._panel_order)
        self.tab_choice.SetSelection(0)
        self._update_tab_info(0)
        self.tab_choice.Bind(wx.EVT_CHOICE, self.on_tab_choice_changed)

        main_sizer.Add(self.content_panel, 1, wx.LEFT | wx.RIGHT | wx.EXPAND, 12)

        # --- Global status + log ---
        self.status = wx.StaticText(panel, label="Bereit")
        self.status.SetName("Status")
        self.status.SetHelpText("Zeigt den aktuellen Verbindungsstatus an")
        main_sizer.Add(self.status, 0, wx.LEFT | wx.RIGHT | wx.TOP, 12)

        self.log = wx.TextCtrl(panel, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2)
        self.log.SetName("Ereignisprotokoll")
        self.log.SetHelpText("Ausgaben und Servermeldungen")
        main_sizer.Add(self.log, 0, wx.ALL | wx.EXPAND, 12)
        self.log.SetMinSize((-1, 100))
        main_sizer.Add(qa_panel, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)

        panel.SetSizer(main_sizer)
        self.SetSize((980, 700))
        self.Centre()

        # Anzeigeeinstellungen sofort anwenden (Toolbar/Log standardmaessig versteckt).
        self.apply_display_settings()

        # Apply saved audio prefs (if enabled) after UI is ready.
        wx.CallLater(300, self._apply_saved_audio_prefs_on_startup)

        # Update-Checker beim Start
        if self.settings_store.settings.update_check_on_start:
            wx.CallLater(4000, self._check_for_update)

        # v2.3.0 – Zeitgesteuerte Stille starten
        if getattr(self.settings_store.settings, "mute_schedule", None):
            self._mute_scheduler.start()
        # v2.7.0 – HTTP-API starten
        if getattr(self.settings_store.settings, "http_api_enabled", False):
            port = int(getattr(self.settings_store.settings, "http_api_port", 8765) or 8765)
            self._http_api.start(port)

        # Tab order inside each tab is handled by the tab panels themselves.
        # Global keyboard hooks
        self.Bind(wx.EVT_CHAR_HOOK, self.on_key_hook)
        self.Bind(wx.EVT_KEY_DOWN, self.on_key_down)
        self.Bind(wx.EVT_KEY_UP, self.on_key_up)
        self.Bind(wx.EVT_CLOSE, self.on_close)
        self.Bind(wx.EVT_ACTIVATE, self._on_activate)

        # Ensure Cmd+, opens settings on macOS even if menu shortcuts are ignored.
        if sys.platform == "darwin":
            accel = wx.AcceleratorTable(
                [
                    (wx.ACCEL_CMD, ord(","), wx.ID_PREFERENCES),
                ]
            )
            self.SetAcceleratorTable(accel)
            self.Bind(wx.EVT_MENU, self.on_menu_settings, id=wx.ID_PREFERENCES)

        # Toolbar button bindings
        self.tb_ptt.Bind(wx.EVT_CHECKBOX, self._on_tb_ptt)
        self.tb_va.Bind(wx.EVT_CHECKBOX, self._on_tb_va)
        self.tb_video.Bind(wx.EVT_CHECKBOX, self._on_tb_video)
        self.tb_desktop.Bind(wx.EVT_CHECKBOX, self._on_tb_desktop)
        self.tb_mute.Bind(wx.EVT_CHECKBOX, self._on_tb_mute)
        self.tb_record.Bind(wx.EVT_CHECKBOX, self._on_tb_record)
        self.tb_question.Bind(wx.EVT_CHECKBOX, self._on_tb_question)
        self.master_volume_slider.Bind(wx.EVT_SPINCTRL, self._on_master_volume_slider)
        self.mic_gain_slider.Bind(wx.EVT_SPINCTRL, self._on_mic_gain_slider)
        # VU meter timer
        self._vu_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_vu_timer, self._vu_timer)
        self._vu_timer.Start(100)

        # Geplante Aufnahmen: alle 30 Sekunden prüfen
        self._scheduled_rec_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_scheduled_rec_timer, self._scheduled_rec_timer)
        self._scheduled_rec_timer.Start(30_000)

        # v2.9.0 – Aufnahme-Segmentierung: alle 30 Sekunden prüfen
        self._recording_seg_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_recording_seg_timer, self._recording_seg_timer)
        self._recording_seg_timer.Start(30_000)

        # v3.4.0 – Stille-Erkennung: alle 2 Sekunden prüfen
        self._silence_seconds: float = 0.0
        self._silence_check_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_silence_check_timer, self._silence_check_timer)
        self._silence_check_timer.Start(2_000)

        # v3.5.0 – Geplante Makros: jede Minute prüfen
        self._scheduled_macro_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_scheduled_macro_timer, self._scheduled_macro_timer)
        self._scheduled_macro_timer.Start(60_000)

        # Start global hotkeys if configured
        wx.CallLater(500, self.apply_global_hotkeys)
        # v2.0.0 – Sprachsteuerung starten wenn konfiguriert
        if getattr(self.settings_store.settings, "voice_control_enabled", False):
            wx.CallLater(3000, self._start_voice_control)
        # Plugin-Event: App vollständig initialisiert
        wx.CallLater(2000, lambda: self.bus.emit("app_startup"))

    # ------------------------------------------------------------------
    # Toolbar / Quick-Actions handlers
    # ------------------------------------------------------------------

    def _on_tb_ptt(self, event):
        val = event.GetEventObject().GetValue()
        self._ptt_enabled = val
        if not val and self._ptt_active:
            self._ptt_active = False
            self.client.enable_voice_transmission(False)
        try:
            self.audio_tab.ptt_toggle.SetValue(val)
        except Exception:
            pass
        self.set_status("PTT aktiv" if val else "PTT deaktiviert")

    def _on_tb_va(self, event):
        self.on_menu_audio_va(event)
        try:
            self.tb_va.SetValue(self.audio_tab.va_toggle.GetValue())
        except Exception:
            pass

    def _on_tb_video(self, event):
        val = event.GetEventObject().GetValue()
        self._video_tx_enabled = val
        self.video_tab.set_transmission_enabled(val)
        self.tb_video.SetValue(val)

    def _on_tb_desktop(self, event):
        self.on_menu_desktop_sharing(event)
        try:
            val = bool(self.client.is_desktop_sharing_active() if hasattr(self.client, 'is_desktop_sharing_active') else False)
            self.tb_desktop.SetValue(val)
        except Exception:
            pass

    def _on_tb_mute(self, event):
        val = event.GetEventObject().GetValue()
        self._mute_all = val
        self.client.set_sound_output_mute(val)
        self.set_status("Ausgabe stummgeschaltet" if val else "Ausgabe aktiv")

    def _on_tb_record(self, event):
        val = event.GetEventObject().GetValue()
        if val:
            self.on_menu_record_start(None)
        else:
            self.on_menu_record_stop(None)

    def _on_tb_question(self, event):
        val = event.GetEventObject().GetValue()
        self._status_mode = 1 if val else 0
        try:
            self.client.set_away_status(self._status_mode, self._status_message)
        except Exception:
            pass
        self.set_status("Frage-Modus aktiv" if val else "Frage-Modus deaktiviert")

    def _on_master_volume_slider(self, event):
        level = event.GetEventObject().GetValue()
        # 0-200 -> 0-32000 (SDK range); 100 = default 16000
        sdk_level = int(level * 160)
        try:
            self.client.set_sound_output_volume(sdk_level)
            self.audio_tab.output_volume.SetValue(sdk_level)
        except Exception:
            pass

    def _on_mic_gain_slider(self, event):
        level = event.GetEventObject().GetValue()
        sdk_level = int(level * 160)
        try:
            self.client.set_sound_input_gain(sdk_level)
            self.audio_tab.input_gain.SetValue(sdk_level)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # v2.0.0 – Multi-Server Bus-Handler
    # ------------------------------------------------------------------

    def _on_active_server_changed(self, session_id: str, session) -> None:
        """Wird aufgerufen wenn die aktive Session wechselt."""
        try:
            self.client = session.client
            label = session.profile.name
            wx.CallAfter(self.set_status, f"Server: {label}")
            wx.CallAfter(self._refresh_server_choice)
        except Exception as exc:
            print(f"[MultiServer] active_server_changed fehlgeschlagen: {exc}")

    def _on_server_state_changed(self, session_id: str, state: str, session) -> None:
        """Wird aufgerufen wenn sich der Verbindungsstatus einer Session ändert."""
        try:
            active = self.server_manager.get_active()
            if active and active.session_id == session_id:
                state_label = {"connected": "Verbunden", "connecting": "Verbinde...", "disconnected": "Getrennt"}.get(state, state)
                wx.CallAfter(self.set_status, f"{session.profile.name}: {state_label}")
            wx.CallAfter(self._refresh_server_choice)
        except Exception:
            pass

    def _refresh_server_choice(self) -> None:
        """Aktualisiert die Server-Choice mit allen aktiven Sessions."""
        try:
            sessions = self.server_manager.all_sessions()
            active = self.server_manager.get_active()
            self.server_choice.Clear()
            self._server_session_ids = []
            for s in sessions:
                self.server_choice.Append(s.display_label_ascii())
                self._server_session_ids.append(s.session_id)
            # Aktive Session markieren
            if active and active.session_id in self._server_session_ids:
                idx = self._server_session_ids.index(active.session_id)
                self.server_choice.SetSelection(idx)
            # Panel nur anzeigen wenn mehr als eine Session existiert
            self.server_panel.Show(len(sessions) > 1)
            self.server_panel.GetParent().Layout()
        except Exception as exc:
            print(f"[MultiServer] _refresh_server_choice fehlgeschlagen: {exc}")

    def add_server_session(self, profile) -> str:
        """Fügt eine neue Server-Session hinzu und aktualisiert die UI."""
        sid = self.server_manager.add_session(profile)
        wx.CallAfter(self._refresh_server_choice)
        return sid

    def _on_server_choice_changed(self, event) -> None:
        """Wechselt zur ausgewählten Server-Session."""
        idx = event.GetSelection()
        if 0 <= idx < len(self._server_session_ids):
            sid = self._server_session_ids[idx]
            try:
                self.server_manager.switch_to(sid)
            except Exception as exc:
                self.set_status(f"Server-Wechsel fehlgeschlagen: {exc}")

    # ------------------------------------------------------------------
    # v2.0.0 – Sprachsteuerung
    # ------------------------------------------------------------------

    def _start_voice_control(self) -> None:
        """Initialisiert und startet den VoiceCommandManager."""
        try:
            from voice_control import VoiceCommandManager
            self._voice_control = VoiceCommandManager(self)
            if self._voice_control.is_available():
                ok = self._voice_control.start()
                if ok:
                    self.logger.write("Sprachsteuerung gestartet.")
                    self.set_status("Sprachsteuerung aktiv")
                else:
                    self.logger.write("Sprachsteuerung konnte nicht gestartet werden.")
            else:
                self.logger.write("Sprachsteuerung nicht verfügbar (whisper/pyaudio fehlt).")
        except Exception as exc:
            self.logger.write(f"Sprachsteuerung Fehler: {exc}")

    def _stop_voice_control(self) -> None:
        if self._voice_control is not None:
            try:
                self._voice_control.stop()
            except Exception:
                pass
            self._voice_control = None

    # ------------------------------------------------------------------
    # v2.0.0 – KI-Zusammenfassung
    # ------------------------------------------------------------------

    def _show_ai_reply_suggestions(self) -> None:
        """Zeigt KI-generierte Antwortvorschläge auf die letzte Privatnachricht."""
        msg = getattr(self, "_last_private_message_text", "").strip()
        if not msg:
            self.tts.speak("Keine Privatnachricht zum Beantworten", kind="system")
            return
        self.set_status("KI-Antwortvorschläge werden generiert…")

        def _work():
            suggestions = self._ai_reply.suggest_replies(msg)
            wx.CallAfter(self._show_reply_dialog, suggestions, msg)

        threading.Thread(target=_work, daemon=True).start()

    def _show_reply_dialog(self, suggestions: list, original: str) -> None:
        if not suggestions:
            self.set_status("Keine Antwortvorschläge generiert")
            return
        dlg = wx.Dialog(self, title="KI-Antwortvorschläge", style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        dlg.SetMinSize((540, 300))
        accel = wx.AcceleratorTable([(wx.ACCEL_CMD, ord("W"), wx.ID_CLOSE)])
        dlg.SetAcceleratorTable(accel)
        dlg.Bind(wx.EVT_MENU, lambda e: dlg.EndModal(wx.ID_CANCEL), id=wx.ID_CLOSE)

        root = wx.BoxSizer(wx.VERTICAL)
        orig_trunc = original[:80] + "…" if len(original) > 80 else original
        lbl = wx.StaticText(dlg, label=f"Nachricht: {orig_trunc}")
        root.Add(lbl, 0, wx.ALL, 8)

        lb = wx.ListBox(dlg)
        lb.SetName("Antwortvorschläge")
        from ui.a11y import setup_list_accessible
        setup_list_accessible(lb)
        for s in suggestions:
            lb.Append(s)
        if suggestions:
            lb.SetSelection(0)
        lb.SetMinSize((-1, 120))
        root.Add(lb, 1, wx.LEFT | wx.RIGHT | wx.EXPAND, 8)

        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        use_btn = wx.Button(dlg, wx.ID_OK, "&Verwenden")
        use_btn.SetName("Antwort verwenden")
        cancel_btn = wx.Button(dlg, wx.ID_CANCEL, "Abbrechen")
        btn_row.Add(use_btn, 0, wx.RIGHT, 8)
        btn_row.Add(cancel_btn, 0)
        root.Add(btn_row, 0, wx.ALL | wx.ALIGN_RIGHT, 8)

        dlg.SetSizer(root)
        dlg.CentreOnParent()
        if dlg.ShowModal() == wx.ID_OK:
            idx = lb.GetSelection()
            if idx != wx.NOT_FOUND and idx < len(suggestions):
                text = suggestions[idx]
                # In Privat-Eingabefeld übernehmen
                try:
                    self.chat_tab.private_chat.SetValue(True)
                    self.chat_tab.update_chat_target()
                    self.chat_tab.chat_input.SetValue(text)
                    self.chat_tab.chat_input.SetFocus()
                except Exception:
                    pass
        dlg.Destroy()

    def _trigger_ai_summary(self) -> None:
        """Fasst verpasste Nachrichten zusammen und spricht sie via TTS an."""
        if self._ai_summary is None:
            return
        import time as _time
        import threading as _threading
        server_key = getattr(self, "_current_server_key", "")
        since = _time.time() - 3600  # letzte Stunde
        def _work():
            text = self._ai_summary.summarize_missed(server_key, since)
            import wx as _wx
            _wx.CallAfter(self.tts.speak, text, kind="system")
        _threading.Thread(target=_work, daemon=True).start()

    def _on_vu_timer(self, _event):
        if self._closing:
            return
        try:
            level = self.client.get_sound_input_level()
            if level is not None:
                pct = min(100, int(level * 100 / 32768))
                self.vu_meter.SetValue(pct)
                # v2.9.0 – VU-Alarm
                s = self.settings_store.settings
                if getattr(s, "vu_alert_enabled", False):
                    threshold = int(getattr(s, "vu_alert_threshold", 90) or 90)
                    if pct >= threshold:
                        self._vu_alert_count += 1
                        if self._vu_alert_count >= 3:
                            self._vu_alert_count = 0
                            self.tts.speak("Eingangspegel zu hoch", kind="system")
                    else:
                        self._vu_alert_count = 0
        except Exception:
            pass

    def _announce_vu_level(self) -> None:
        """Liest den aktuellen Eingangspegel via TTS vor."""
        try:
            level = self.client.get_sound_input_level()
            pct = min(100, int(level * 100 / 32768)) if level is not None else 0
            self.tts.speak(f"Eingangspegel {pct} Prozent", kind="system")
        except Exception:
            self.tts.speak("Pegel nicht verfügbar", kind="system")

    def _cycle_sound_profile(self) -> None:
        """Schaltet zum nächsten Sound-Profil und sagt es via TTS an."""
        s = self.settings_store.settings
        builtin = ["Standard", "Minimal", "Stumm"]
        user_profiles = [p.get("name", "") for p in (s.sound_profiles or []) if p.get("name")]
        all_profiles = builtin + user_profiles
        current = s.active_sound_profile or "Standard"
        try:
            idx = all_profiles.index(current)
        except ValueError:
            idx = 0
        next_idx = (idx + 1) % len(all_profiles)
        next_profile = all_profiles[next_idx]
        s.active_sound_profile = next_profile
        self.settings_store.save()
        self.tts.speak(f"Sound-Profil: {next_profile}", kind="system")

    def _reply_last_sender(self) -> None:
        """Öffnet Privat-Chat mit dem zuletzt sprechenden Absender."""
        uid = self._last_private_sender_id
        if not uid:
            self.tts.speak("Kein letzter Absender", kind="system")
            return
        if self.chat_tab:
            self.chat_tab.select_private_recipient(uid)
            self.tts.speak("Privatantwort bereit", kind="system")

    def _announce_user_info(self) -> None:
        """Liest Infos über den aktuell ausgewählten Nutzer via TTS vor."""
        try:
            self.channels_tab.announce_selected_user_info()
        except Exception:
            self.tts.speak("Nutzerinfo nicht verfügbar", kind="system")

    def _announce_ping(self) -> None:
        """Liest den aktuellen Ping via TTS vor."""
        try:
            text = self.connection_tab.get_ping_text()
            self.tts.speak(text, kind="system")
        except Exception:
            self.tts.speak("Ping nicht verfügbar", kind="system")

    def _announce_braille_status(self) -> None:
        """v3.3.0 – Liest konfigurierbaren Braille-Status via TTS vor."""
        s = self.settings_store.settings
        parts = []
        # Kanal
        if getattr(s, "braille_status_show_channel", True):
            try:
                ch = self.client.get_my_channel()
                name = ch.szName.decode() if ch and hasattr(ch.szName, "decode") else (str(ch.szName) if ch else "")
                if name:
                    parts.append(f"Kanal: {name}")
            except Exception:
                pass
        # Nutzeranzahl im Kanal
        if getattr(s, "braille_status_show_users", True):
            try:
                users = self.client.get_channel_users(self.client.get_my_channel_id())
                parts.append(f"Nutzer: {len(users)}")
            except Exception:
                pass
        # Ping
        if getattr(s, "braille_status_show_ping", True):
            try:
                ping_text = self.connection_tab.get_ping_text()
                parts.append(ping_text)
            except Exception:
                pass
        # Stummgeschaltet
        if getattr(s, "braille_status_show_mute", False):
            parts.append("Stummgeschaltet" if self._mute_all else "Ton aktiv")
        # Verbindungsstatus
        if getattr(s, "braille_status_show_connection", True):
            connected = self.client.is_connected()
            parts.append("Verbunden" if connected else "Getrennt")
        text = ", ".join(parts) if parts else "Kein Status konfiguriert"
        self.tts.speak(text, kind="system")

    def _on_scheduled_rec_timer(self, _event) -> None:
        """Prüft ob eine geplante Aufnahme jetzt starten soll."""
        if getattr(self, '_closing', False):
            return
        try:
            rec = self._scheduled_rec_manager.check_due()
            if rec:
                if not self._recording_active:
                    self.on_menu_record_start(None)
                    self.set_status(f"Geplante Aufnahme gestartet: {rec.label}")
                    if rec.duration_min > 0:
                        wx.CallLater(rec.duration_min * 60_000, self._stop_scheduled_recording, rec.label)
        except Exception:
            pass

    def _stop_scheduled_recording(self, label: str) -> None:
        if self._recording_active:
            self.on_menu_record_stop(None)
            self.set_status(f"Geplante Aufnahme beendet: {label}")

    # v2.9.0 – Aufnahme-Segmentierung
    def _on_recording_seg_timer(self, _event) -> None:
        if self._closing or not self._recording_active:
            return
        s = self.settings_store.settings
        max_mb = int(getattr(s, "recording_max_size_mb", 0) or 0)
        max_min = int(getattr(s, "recording_max_minutes", 0) or 0)
        if not max_mb and not max_min:
            return
        try:
            if max_mb and self._recording_path:
                import os as _os
                size_mb = _os.path.getsize(self._recording_path) / (1024 * 1024)
                if size_mb >= max_mb:
                    self.on_menu_record_stop(None)
                    self.on_menu_record_start(None)
                    self._recording_seg_start = time.time()
                    return
            if max_min and self._recording_seg_start:
                elapsed_min = (time.time() - self._recording_seg_start) / 60
                if elapsed_min >= max_min:
                    self.on_menu_record_stop(None)
                    self.on_menu_record_start(None)
                    self._recording_seg_start = time.time()
        except Exception:
            pass

    # v3.5.0 – Geplante Makros
    def _on_scheduled_macro_timer(self, _event) -> None:
        if self._closing:
            return
        try:
            self._macros.check_scheduled()
        except Exception:
            pass

    # v3.4.0 – Stille-Erkennung während Aufnahme
    def _on_silence_check_timer(self, _event) -> None:
        if self._closing or not self._recording_active:
            self._silence_seconds = 0.0
            return
        s = self.settings_store.settings
        silence_enabled = bool(getattr(s, "silence_detection_enabled", False))
        if not silence_enabled:
            return
        silence_timeout = int(getattr(s, "silence_detection_timeout_sec", 30) or 30)
        silence_threshold = int(getattr(s, "silence_detection_threshold_pct", 2) or 2)
        try:
            level = self.client.get_sound_input_level()
            pct = min(100, int(level * 100 / 32768)) if level is not None else 0
            if pct <= silence_threshold:
                self._silence_seconds += 2.0
                if self._silence_seconds >= silence_timeout:
                    self._silence_seconds = 0.0
                    self.on_menu_record_stop(None)
                    self.set_status(f"Aufnahme durch Stille-Erkennung gestoppt ({silence_timeout}s Stille)")
            else:
                self._silence_seconds = 0.0
        except Exception:
            pass

    # v2.8.0 – Nutzer-Notizen
    def _get_user_note(self, username: str) -> str:
        notes = getattr(self.settings_store.settings, "user_notes", {}) or {}
        return notes.get(username, "")

    def _set_user_note(self, username: str, note: str) -> None:
        if not hasattr(self.settings_store.settings, "user_notes") or \
                not isinstance(self.settings_store.settings.user_notes, dict):
            self.settings_store.settings.user_notes = {}
        if note:
            self.settings_store.settings.user_notes[username] = note
        else:
            self.settings_store.settings.user_notes.pop(username, None)
        self.settings_store.save()

    def on_menu_user_note(self, _event) -> None:
        user = self._get_selected_user()
        if not user:
            self.set_status("Kein Benutzer ausgewählt")
            return
        name = self.tt_str(getattr(user, "szNickname", "")) or self.tt_str(getattr(user, "szUsername", "")) or "Benutzer"
        current_note = self._get_user_note(name)
        with wx.TextEntryDialog(self, f"Notiz für {name}:", "Nutzer-Notiz", current_note) as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                note = dlg.GetValue().strip()
                self._set_user_note(name, note)
                self.set_status(f"Notiz für {name} gespeichert")

    # v2.8.0 – Letzte Kanäle
    def _add_to_recent_channels(self, channel_id: int, channel_name: str) -> None:
        s = self.settings_store.settings
        if not hasattr(s, "recent_channels") or not isinstance(s.recent_channels, list):
            s.recent_channels = []
        server_key = self._get_server_key() or ""
        entry = {"id": channel_id, "name": channel_name, "server_key": server_key}
        # Dedup
        s.recent_channels = [r for r in s.recent_channels
                             if not (r.get("id") == channel_id and r.get("server_key") == server_key)]
        s.recent_channels.insert(0, entry)
        s.recent_channels = s.recent_channels[:8]
        self.settings_store.save()
        self._refresh_recent_channels_menu()

    def _refresh_recent_channels_menu(self) -> None:
        try:
            menu = self._recent_channels_menu
            for item in menu.GetMenuItems():
                menu.Delete(item)
            s = self.settings_store.settings
            channels = getattr(s, "recent_channels", []) or []
            if not channels:
                menu.Append(wx.ID_ANY, "(Keine letzten Kanäle)").Enable(False)
                return
            for ch in channels:
                ch_id = int(ch.get("id", 0))
                ch_name = str(ch.get("name", "?"))
                ch_key = str(ch.get("server_key", ""))
                item = menu.Append(wx.ID_ANY, f"{ch_name}")
                self.Bind(wx.EVT_MENU,
                          lambda _e, cid=ch_id, ckey=ch_key: self.on_menu_recent_channels_submenu(cid, ckey),
                          item)
        except Exception:
            pass

    def on_menu_recent_channels_submenu(self, channel_id: int, server_key: str) -> None:
        s_key = self._get_server_key() or ""
        if s_key and s_key != server_key:
            self.set_status("Falscher Server für diesen Kanal")
            return
        self.join_channel(channel_id)

    # v2.8.0 – Stichwort-Alarm
    def _check_keyword_alert(self, text: str, from_user: str) -> None:
        s = self.settings_store.settings
        keywords = getattr(s, "alert_keywords", []) or []
        if not keywords:
            return
        text_lower = text.lower()
        for kw in keywords:
            if kw.lower() in text_lower:
                self.sound_manager.play("msg_private_rx", s.sound_events.get("msg_private_rx"))
                if getattr(s, "alert_keywords_tts", True):
                    self.tts.speak(f"Stichwort: {kw}", kind="system")
                return

    # v3.0.0 – Wer-spricht-Protokoll
    def _track_speaking_log(self, user_id: int, username: str, is_talking: bool) -> None:
        if is_talking:
            if user_id not in self._user_speaking_start:
                self._user_speaking_start[user_id] = time.time()
        else:
            start = self._user_speaking_start.pop(user_id, None)
            if start is not None:
                duration_s = time.time() - start
                ts = time.strftime("%H:%M:%S")
                dur_str = f"{duration_s:.1f}s"
                self._speaking_log.append((ts, username, dur_str))
                if len(self._speaking_log) > 100:
                    self._speaking_log = self._speaking_log[-100:]

    def on_menu_speaking_log(self, _event) -> None:
        dlg = wx.Dialog(self, title="Wer-spricht-Protokoll", style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        dlg.SetMinSize((500, 400))
        panel = wx.Panel(dlg)
        sizer = wx.BoxSizer(wx.VERTICAL)
        lb = wx.ListBox(panel, style=wx.LB_SINGLE)
        lb.SetName("Wer-spricht-Protokoll")
        for ts, username, duration in self._speaking_log:
            lb.Append(f"{ts}, {username}, {duration}")
        sizer.Add(lb, 1, wx.ALL | wx.EXPAND, 8)
        btn_sizer = wx.StdDialogButtonSizer()
        ok_btn = wx.Button(panel, wx.ID_OK)
        btn_sizer.AddButton(ok_btn)
        btn_sizer.Realize()
        sizer.Add(btn_sizer, 0, wx.ALL | wx.ALIGN_RIGHT, 8)
        panel.SetSizer(sizer)
        dlg.ShowModal()
        dlg.Destroy()

    # v2.9.0 – Audio-Datei streamen
    def on_menu_stream_audio_file(self, _event) -> None:
        if not self._require_connected("Audio-Datei streamen"):
            return
        with wx.FileDialog(self, "Audio-Datei auswählen",
                           wildcard="Audio-Dateien (*.wav;*.mp3)|*.wav;*.mp3|Alle Dateien|*.*",
                           style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            path = dlg.GetPath()
        try:
            fn = getattr(self.client, "start_media_file_stream", None)
            if fn:
                fn(path)
                self.set_status(f"Streaming: {path}")
            else:
                self.set_status("Audio-Streaming nicht verfügbar (SDK)")
        except Exception as exc:
            self.set_status(f"Stream-Fehler: {exc}")

    def on_menu_scheduled_recordings(self, _event) -> None:
        """Öffnet den Dialog für geplante Aufnahmen."""
        from ui.scheduled_recordings_dialog import ScheduledRecordingsDialog
        dlg = ScheduledRecordingsDialog(self, self._scheduled_rec_manager)
        dlg.ShowModal()
        dlg.Destroy()

    def apply_display_settings(self) -> None:
        """Wendet Anzeigeeinstellungen auf das Hauptfenster an (Toolbar, Log, Immer-vorne)."""
        s = self.settings_store.settings
        self.qa_panel.Show(bool(s.show_toolbar))
        self.log.Show(bool(s.show_event_log))
        self.vu_meter.Show(bool(s.show_vu_meter))
        if bool(s.always_on_top):
            self.SetWindowStyle(self.GetWindowStyle() | wx.STAY_ON_TOP)
        else:
            self.SetWindowStyle(self.GetWindowStyle() & ~wx.STAY_ON_TOP)
        self.Layout()

    def apply_general_settings(self) -> None:
        """Wendet allgemeine Einstellungen an (Chat-Verlauf, Auto-Kanal, Braillemodus)."""
        s = self.settings_store.settings
        if s.braille_compact_mode:
            self._apply_braille_compact_labels()

    def _apply_braille_compact_labels(self) -> None:
        """Kürzt ausgewählte VoiceOver-Beschriftungen für Braillezeilen."""
        _map = {
            "Eingabegerät": "Eingang",
            "Ausgabegerät": "Ausgang",
            "Mikrofonverstärkung (0–32000)": "Mikrofon",
            "Ausgabe-Lautstärke (0–32000)": "Lautstärke",
            "Aktivierungspegel (0–100)": "VA-Pegel",
            "Nachlauf (ms, 0–5000)": "VA-Nachlauf",
        }
        try:
            for win in self.GetChildren():
                name = win.GetName()
                short = _map.get(name)
                if short:
                    win.SetName(short)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Chat history
    # ------------------------------------------------------------------

    def _get_server_key(self) -> str:
        try:
            lc = self.client._last_connect
            if lc:
                return f"{lc[0]}:{lc[1]}"
        except Exception:
            pass
        return self._current_server_key

    # ------------------------------------------------------------------
    # v5.1.0 – Companion-Server Callbacks
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # v5.3.0 – macOS-Integration Callbacks
    # ------------------------------------------------------------------

    def _on_dark_mode_change(self, is_dark: bool) -> None:
        """Wird aufgerufen wenn Dark-Mode wechselt."""
        import wx
        wx.CallAfter(lambda: self.bus.emit("dark_mode_changed", is_dark=is_dark))

    def _send_native_notification(self, title: str, body: str) -> None:
        send_notification(title, body)

    def _update_unread_badge(self, delta: int = 1) -> None:
        self._unread_count = max(0, self._unread_count + delta)
        set_dock_badge(self._unread_count)

    def _clear_unread_badge(self) -> None:
        self._unread_count = 0
        set_dock_badge(0)

    def _companion_status(self) -> dict:
        active = self.server_manager.get_active() if hasattr(self, "server_manager") else None
        return {
            "app_version": APP_VERSION,
            "connected": self.client.is_connected() if hasattr(self, "client") else False,
            "server": active.profile.name if active else "",
            "session_count": self.server_manager.session_count() if hasattr(self, "server_manager") else 0,
        }

    def _companion_channels(self) -> list:
        try:
            return [
                {"id": ch.channelid, "name": ch.name, "users": ch.nusers}
                for ch in (self.client.get_channels() or [])
            ]
        except Exception:
            return []

    def _companion_users(self) -> list:
        try:
            return [
                {"id": u.userid, "name": u.nickname}
                for u in (self.client.get_users() or [])
            ]
        except Exception:
            return []

    def _companion_send(self, text: str, channel_id: int) -> bool:
        try:
            return self.client.send_channel_message(text, channel_id)
        except Exception:
            return False

    def save_chat_message(self, text: str, kind: str) -> None:
        key = self._get_server_key()
        if key:
            self._chat_history.append(key, text, kind)

    def _load_chat_history_to_ui(self) -> None:
        """Lädt den gespeicherten Chat-Verlauf in den Chat-Tab."""
        key = self._get_server_key()
        if not key:
            return
        entries = self._chat_history.load(key)
        if not entries:
            return
        self.chat_tab.append_chat("--- Gespeicherter Verlauf ---", kind="system", speak=False)
        for entry in entries:
            ts = entry.get("ts", "")
            text = entry.get("text", "")
            kind = entry.get("kind", "chat")
            line = f"[{ts}] {text}" if ts else text
            self.chat_tab.append_chat(line, kind=kind, speak=False)
        self.chat_tab.append_chat("--- Ende Verlauf ---", kind="system", speak=False)

    # ------------------------------------------------------------------
    # Global hotkeys
    # ------------------------------------------------------------------

    def apply_global_hotkeys(self) -> None:
        """Startet oder stoppt den GlobalHotkeyManager entsprechend den Einstellungen."""
        if self._global_hotkey_mgr is None:
            return
        s = self.settings_store.settings
        self._global_hotkey_mgr.stop()
        if s.global_hotkeys_enabled and (s.global_hotkey_ptt or s.global_hotkey_mute):
            self._global_hotkey_mgr.start(
                ptt_vk=int(s.global_hotkey_ptt or 0),
                mute_vk=int(s.global_hotkey_mute or 0),
                on_ptt_down=self._on_global_ptt_down,
                on_ptt_up=self._on_global_ptt_up,
                on_mute=self._on_global_mute,
            )

    def _on_global_ptt_down(self) -> None:
        if not self.client.is_connected():
            return
        if not self._ptt_active:
            self._ptt_active = True
            self.client.enable_voice_transmission(True)
            self.set_status("Sprechen an (global)")

    def _on_global_ptt_up(self) -> None:
        if self._ptt_active:
            self._ptt_active = False
            self.client.enable_voice_transmission(False)
            self.set_status("Sprechen aus")

    def _on_global_mute(self) -> None:
        self._mute_all = not self._mute_all
        self.client.mute_all(self._mute_all)
        self.set_status("Stummgeschaltet" if self._mute_all else "Stummschaltung aufgehoben")

    def start_global_hotkey_capture(self, target: str) -> None:
        if self._global_hotkey_mgr is None:
            self.set_status("Globale Hotkeys nur auf macOS verfügbar")
            return
        self._global_capture_target = target
        try:
            self.shortcuts_tab.set_global_capture_label(target, True)
        except Exception:
            pass
        self.set_status("Globaler Hotkey: Taste drücken (ESC = Abbruch)")
        self._global_hotkey_mgr.capture_key_vk(self._on_global_key_captured)

    def _on_global_key_captured(self, vk: int) -> None:
        target = self._global_capture_target
        self._global_capture_target = None
        if not target:
            return
        if vk == 53:  # ESC virtual key code
            try:
                self.shortcuts_tab.set_global_capture_label(target, False)
            except Exception:
                pass
            self.set_status("Globale Hotkey-Aufnahme abgebrochen")
            return
        s = self.settings_store.settings
        if target == "global_hotkey_ptt":
            s.global_hotkey_ptt = vk
        elif target == "global_hotkey_mute":
            s.global_hotkey_mute = vk
        self.settings_store.save()
        try:
            self.shortcuts_tab.set_global_capture_label(target, False)
        except Exception:
            pass
        try:
            from global_hotkeys import vk_to_name
            name = vk_to_name(vk)
        except Exception:
            name = str(vk)
        self.set_status(f"Globaler Hotkey gespeichert: {name}")
        self.apply_global_hotkeys()

    # ------------------------------------------------------------------
    # Menu
    # ------------------------------------------------------------------

    def _build_menu(self):
        menubar = wx.MenuBar()
        file_menu = wx.Menu()
        open_tt = file_menu.Append(wx.ID_ANY, "TeamTalk-Datei öffnen...\tCtrl+O")
        new_client = file_menu.Append(wx.ID_ANY, "Neuen Client starten\tCtrl+N")
        sound_menu = wx.Menu()
        self._sound_input_menu = wx.Menu()
        self._sound_output_menu = wx.Menu()
        sound_menu.AppendSubMenu(self._sound_input_menu, "Eingabegeräte")
        sound_menu.AppendSubMenu(self._sound_output_menu, "Ausgabegeräte")
        sound_menu.AppendSeparator()
        sound_settings = sound_menu.Append(wx.ID_ANY, "Audio-Einstellungen...")
        sound_apply = sound_menu.Append(wx.ID_ANY, "Audio anwenden")
        sound_refresh = sound_menu.Append(wx.ID_ANY, "Geräte aktualisieren")
        sound_menu.AppendSeparator()
        sound_effects = sound_menu.Append(wx.ID_ANY, "Effekte anwenden")
        file_menu.AppendSubMenu(sound_menu, "Sound-Konfiguration")
        record_convo = file_menu.Append(wx.ID_ANY, "Konversationen aufzeichnen...")
        prefs_item = file_menu.Append(wx.ID_PREFERENCES, "Einstellungen...\tF4")
        file_menu.AppendSeparator()
        con_connect = file_menu.Append(wx.ID_ANY, "Verbinden")
        con_disconnect = file_menu.Append(wx.ID_ANY, "Trennen")
        con_reconnect = file_menu.Append(wx.ID_ANY, "Neu verbinden")
        file_menu.AppendSeparator()
        con_autoreconnect = file_menu.AppendCheckItem(wx.ID_ANY, "Automatisch neu verbinden")
        file_menu.AppendSeparator()
        con_join_root = file_menu.Append(wx.ID_ANY, "Root-Kanal beitreten")
        con_leave = file_menu.Append(wx.ID_ANY, "Kanal verlassen")
        file_menu.AppendSeparator()
        # Server-Favoriten Kurzwahl Cmd+1..9
        favorites_menu = wx.Menu()
        self._favorites_menu_items = []
        for i in range(1, 10):
            fav_item = favorites_menu.Append(wx.ID_ANY, f"Server {i}\tCtrl+{i}")
            self._favorites_menu_items.append(fav_item)
            self.Bind(wx.EVT_MENU, lambda e, idx=i - 1: self._connect_favorite(idx), fav_item)
        self._favorites_menu = favorites_menu
        file_menu.AppendSubMenu(favorites_menu, "Schnellverbindung (Cmd+1–9)")
        self.Bind(wx.EVT_MENU_OPEN, self._on_favorites_menu_open)
        file_menu.AppendSeparator()
        con_server_check = file_menu.Append(wx.ID_ANY, "Server prüfen")
        file_menu.AppendSeparator()
        import_servers = file_menu.Append(wx.ID_ANY, "Serverliste importieren...")
        export_servers = file_menu.Append(wx.ID_ANY, "Serverliste exportieren...")
        file_menu.AppendSeparator()
        settings_backup = file_menu.Append(wx.ID_ANY, "Einstellungen sichern (Backup)...")
        settings_restore = file_menu.Append(wx.ID_ANY, "Einstellungen wiederherstellen...")
        file_menu.AppendSeparator()
        quit_item = file_menu.Append(wx.ID_EXIT, _("Beenden") + "\tCtrl+Q")

        menubar.Append(file_menu, _("Datei"))

        

        # Kanal
        chan_menu = wx.Menu()
        chan_create = chan_menu.Append(wx.ID_ANY, "Kanal erstellen...\tF7")
        chan_edit = chan_menu.Append(wx.ID_ANY, "Kanal bearbeiten...")
        chan_delete = chan_menu.Append(wx.ID_ANY, "Kanal löschen...")
        chan_menu.AppendSeparator()
        chan_join = chan_menu.Append(wx.ID_ANY, "Kanal beitreten...")
        chan_leave = chan_menu.Append(wx.ID_ANY, "Kanal verlassen")
        chan_menu.AppendSeparator()
        chan_info = chan_menu.Append(wx.ID_ANY, "Kanalinfo...")
        chan_info_speak = chan_menu.Append(wx.ID_ANY, "Kanalinfo vorlesen")
        chan_stats_speak = chan_menu.Append(wx.ID_ANY, "Kanalstatistik vorlesen")
        chan_state_speak = chan_menu.Append(wx.ID_ANY, "Kanalzustand vorlesen")
        chan_tt_url = chan_menu.Append(wx.ID_ANY, "TT-URL für Kanal kopieren")
        chan_bans = chan_menu.Append(wx.ID_ANY, "Sperren im Kanal anzeigen...")
        chan_note = chan_menu.Append(wx.ID_ANY, "Kanal-Notiz bearbeiten...")
        chan_msg = chan_menu.Append(wx.ID_ANY, "Kanalnachricht senden...")
        chan_view_msgs = chan_menu.Append(wx.ID_ANY, "Kanalnachrichten anzeigen...")
        chan_menu.AppendSeparator()
        chan_files_menu = wx.Menu()
        chan_file_upload = chan_files_menu.Append(wx.ID_ANY, "Datei hochladen...")
        chan_file_download = chan_files_menu.Append(wx.ID_ANY, "Datei herunterladen...")
        chan_file_delete = chan_files_menu.Append(wx.ID_ANY, "Datei löschen...")
        chan_file_refresh = chan_files_menu.Append(wx.ID_ANY, "Dateiliste aktualisieren")
        chan_menu.AppendSubMenu(chan_files_menu, "Dateien")
        chan_stream_menu = wx.Menu()
        chan_stream_file = chan_stream_menu.Append(wx.ID_ANY, "Mediendatei streamen...")
        chan_stream_yt = chan_stream_menu.Append(wx.ID_ANY, "YouTube streamen...")
        chan_stream_sc = chan_stream_menu.Append(wx.ID_ANY, "SoundCloud streamen...")
        chan_stream_twitch = chan_stream_menu.Append(wx.ID_ANY, "Twitch streamen...")
        chan_stream_bandcamp = chan_stream_menu.Append(wx.ID_ANY, "Bandcamp streamen...")
        chan_stream_vimeo = chan_stream_menu.Append(wx.ID_ANY, "Vimeo streamen...")
        chan_stream_mixcloud = chan_stream_menu.Append(wx.ID_ANY, "Mixcloud streamen...")
        chan_stream_radio = chan_stream_menu.Append(wx.ID_ANY, "Webradio streamen...")
        chan_stream_podcast = chan_stream_menu.Append(wx.ID_ANY, "Podcast streamen...")
        chan_stream_playlist = chan_stream_menu.Append(wx.ID_ANY, "Playlist streamen...")
        chan_menu.AppendSubMenu(chan_stream_menu, "Streaming")
        chan_menu.AppendSeparator()
        self._recent_channels_menu = wx.Menu()
        chan_menu.AppendSubMenu(self._recent_channels_menu, "Letzte Kanäle")
        chan_recent_dialog = chan_menu.Append(wx.ID_ANY, "Kanalverlauf...")
        chan_stream_audio = chan_menu.Append(wx.ID_ANY, "Audio-Datei in Kanal streamen...")
        menubar.Append(chan_menu, _("Kanal"))

        # Benutzer
        user_menu = wx.Menu()
        user_info = user_menu.Append(wx.ID_ANY, "Benutzerinfo...")
        user_info_speak = user_menu.Append(wx.ID_ANY, "Benutzerinfo vorlesen")
        user_message = user_menu.Append(wx.ID_ANY, "Private Nachricht...")
        user_mute_menu = wx.Menu()
        user_mute_voice = user_mute_menu.Append(wx.ID_ANY, "Sprache stummschalten")
        user_mute_media = user_mute_menu.Append(wx.ID_ANY, "Mediendatei stummschalten")
        user_menu.AppendSubMenu(user_mute_menu, "Stummschalten")
        user_volume = user_menu.Append(wx.ID_ANY, "Benutzerlautstärke...")
        user_note = user_menu.Append(wx.ID_ANY, "Notiz &bearbeiten...")
        user_adv = wx.Menu()
        user_vol_up = user_adv.Append(wx.ID_ANY, "Lauter\tCtrl+Right")
        user_vol_down = user_adv.Append(wx.ID_ANY, "Leiser\tCtrl+Left")
        user_relay_voice = user_adv.Append(wx.ID_ANY, "Sprachstream weiterleiten")
        user_relay_media = user_adv.Append(wx.ID_ANY, "Medienstream weiterleiten")
        user_position = user_adv.Append(wx.ID_ANY, "Benutzer positionieren...")
        user_allow_menu = wx.Menu()
        user_allow_voice = user_allow_menu.Append(wx.ID_ANY, "Sprache erlauben")
        user_allow_video = user_allow_menu.Append(wx.ID_ANY, "Video erlauben")
        user_allow_desktop = user_allow_menu.Append(wx.ID_ANY, "Desktop erlauben")
        user_allow_media = user_allow_menu.Append(wx.ID_ANY, "Mediendatei erlauben")
        user_allow_text = user_allow_menu.Append(wx.ID_ANY, "Kanalnachricht erlauben")
        user_allow_menu.AppendSeparator()
        user_allow_all_voice = user_allow_menu.Append(wx.ID_ANY, "Alle Sprache erlauben")
        user_allow_all_video = user_allow_menu.Append(wx.ID_ANY, "Alle Video erlauben")
        user_allow_all_desktop = user_allow_menu.Append(wx.ID_ANY, "Alle Desktop erlauben")
        user_allow_all_media = user_allow_menu.Append(wx.ID_ANY, "Alle Mediendatei erlauben")
        user_allow_all_text = user_allow_menu.Append(wx.ID_ANY, "Alle Kanalnachrichten erlauben")
        user_adv.AppendSubMenu(user_allow_menu, "Uebertragung erlauben")
        user_menu.AppendSubMenu(user_adv, "Erweitert")
        user_menu.AppendSeparator()
        user_op = user_menu.Append(wx.ID_ANY, "Operator geben/nehmen")
        user_kick_menu = wx.Menu()
        user_kick = user_kick_menu.Append(wx.ID_ANY, "Aus Kanal kicken...")
        user_kick_ban = user_kick_menu.Append(wx.ID_ANY, "Aus Kanal kicken + Bannen...")
        user_kick_server = user_kick_menu.Append(wx.ID_ANY, "Vom Server kicken...")
        user_kick_ban_server = user_kick_menu.Append(wx.ID_ANY, "Vom Server kicken + Bannen...")
        user_kick_menu.AppendSeparator()
        user_ban = user_kick_menu.Append(wx.ID_ANY, "Bannen...")
        user_menu.AppendSubMenu(user_kick_menu, "Kicken / Sperren")
        user_tx_menu = wx.Menu()
        user_tx_voice = user_tx_menu.AppendCheckItem(wx.ID_ANY, "Sprache senden")
        user_tx_video = user_tx_menu.AppendCheckItem(wx.ID_ANY, "Video senden")
        user_tx_desktop = user_tx_menu.AppendCheckItem(wx.ID_ANY, "Desktop senden")
        user_tx_media = user_tx_menu.AppendCheckItem(wx.ID_ANY, "Mediendatei senden")
        user_tx_msg = user_tx_menu.AppendCheckItem(wx.ID_ANY, "Kanalnachricht senden")
        user_tx_desktop_access = user_tx_menu.AppendCheckItem(wx.ID_ANY, "Desktopzugriff erlauben")
        user_menu.AppendSubMenu(user_tx_menu, "Sendekontrolle")
        user_menu.AppendSeparator()
        user_subs = user_menu.Append(wx.ID_ANY, "Abonnements...")
        user_move = user_menu.Append(wx.ID_ANY, "Benutzer verschieben...")
        user_store_move = user_menu.Append(wx.ID_ANY, "Zielkanal merken")
        user_move_stored = user_menu.Append(wx.ID_ANY, "In Zielkanal verschieben")
        user_menu.AppendSeparator()
        user_mute_all = user_menu.AppendCheckItem(wx.ID_ANY, "Alles stummschalten")
        menubar.Append(user_menu, _("Benutzer"))

        # Server
        server_menu = wx.Menu()
        server_online = server_menu.Append(wx.ID_ANY, "Online-Benutzer...")
        server_broadcast = server_menu.Append(wx.ID_ANY, "Servernachricht senden...")
        server_stats = server_menu.Append(wx.ID_ANY, "Serverstatistiken...")
        server_bans = server_menu.Append(wx.ID_ANY, "Sperren (Server) anzeigen...")
        server_admin = server_menu.Append(wx.ID_ANY, "Administration öffnen")
        server_props = server_menu.Append(wx.ID_ANY, "Servereigenschaften...")
        server_save_config = server_menu.Append(wx.ID_ANY, "Konfiguration speichern")
        server_menu.AppendSeparator()
        server_speaking_log = server_menu.Append(wx.ID_ANY, "Wer-spricht-Protokoll...")
        menubar.Append(server_menu, _("Server"))

        # Profil
        profile_menu = wx.Menu()
        profile_nick = profile_menu.Append(wx.ID_ANY, "Nickname ändern...")
        profile_status = profile_menu.Append(wx.ID_ANY, "Status setzen...")
        profile_question = profile_menu.AppendCheckItem(wx.ID_ANY, "Frage-Modus")
        profile_hear = profile_menu.AppendCheckItem(wx.ID_ANY, "Mich selbst hören")
        profile_tts = profile_menu.AppendCheckItem(wx.ID_ANY, "TTS aktiv")
        profile_desktop = profile_menu.AppendCheckItem(wx.ID_ANY, "Desktop senden")
        profile_menu.AppendSeparator()
        notif_menu = wx.Menu()
        notif_chat = notif_menu.AppendCheckItem(wx.ID_ANY, "Chat vorlesen")
        notif_private = notif_menu.AppendCheckItem(wx.ID_ANY, "Privat vorlesen")
        notif_system = notif_menu.AppendCheckItem(wx.ID_ANY, "System vorlesen")
        notif_own = notif_menu.AppendCheckItem(wx.ID_ANY, "Eigene Nachrichten vorlesen")
        profile_menu.AppendSubMenu(notif_menu, "Benachrichtigungen")
        menubar.Append(profile_menu, _("Profil"))

        # Audio
        audio_menu = wx.Menu()
        audio_ptt = audio_menu.AppendCheckItem(wx.ID_ANY, "Push-to-Talk")
        audio_va = audio_menu.AppendCheckItem(wx.ID_ANY, "Sprachaktivierung")
        audio_menu.AppendSeparator()
        audio_settings = audio_menu.Append(wx.ID_ANY, "Audio-Einstellungen...")
        audio_menu.AppendSeparator()
        audio_agc = audio_menu.AppendCheckItem(wx.ID_ANY, "AGC")
        audio_denoise = audio_menu.AppendCheckItem(wx.ID_ANY, "Rauschunterdrückung")
        audio_echo = audio_menu.AppendCheckItem(wx.ID_ANY, "Echounterdrückung")
        audio_apply_effects = audio_menu.Append(wx.ID_ANY, "Effekte anwenden")
        audio_menu.AppendSeparator()
        audio_apply = audio_menu.Append(wx.ID_ANY, "Audio anwenden")
        audio_refresh = audio_menu.Append(wx.ID_ANY, "Geräte aktualisieren")
        audio_menu.AppendSeparator()
        audio_loopback = audio_menu.AppendCheckItem(wx.ID_ANY, "Mikrofontest")
        audio_menu.AppendSeparator()
        audio_mute_all = audio_menu.AppendCheckItem(wx.ID_ANY, "Alles stummschalten")
        audio_menu.AppendSeparator()
        audio_eq_presets = audio_menu.Append(wx.ID_ANY, _("Equalizer-Voreinstellungen..."))
        menubar.Append(audio_menu, _("Audio"))

        # Video
        video_menu = wx.Menu()
        video_tx = video_menu.AppendCheckItem(wx.ID_ANY, "Video senden")
        video_menu.AppendSeparator()
        video_settings = video_menu.Append(wx.ID_ANY, "Video-Einstellungen...")
        video_refresh = video_menu.Append(wx.ID_ANY, "Video-Geräte aktualisieren")
        menubar.Append(video_menu, _("Video"))

        # Aufnahmen
        rec_menu = wx.Menu()
        rec_convo = rec_menu.Append(wx.ID_ANY, "Konversationen aufzeichnen...")
        rec_menu.AppendSeparator()
        rec_start = rec_menu.Append(wx.ID_ANY, "Aufnahme starten...")
        rec_stop = rec_menu.Append(wx.ID_ANY, "Aufnahme stoppen")
        rec_menu.AppendSeparator()
        rec_scheduled = rec_menu.Append(wx.ID_ANY, "Geplante Aufnahmen...")
        rec_browser = rec_menu.Append(wx.ID_ANY, _("Aufnahmen durchsuchen..."))
        menubar.Append(rec_menu, _("Aufnahmen"))

        # Automation
        auto_menu = wx.Menu()
        auto_macro_editor = auto_menu.Append(wx.ID_ANY, "Makro-Editor...")
        auto_scheduled_macros = auto_menu.Append(wx.ID_ANY, "Geplante Makros...")
        auto_menu.AppendSeparator()
        auto_trigger_editor = auto_menu.Append(wx.ID_ANY, _("Trigger-Regeln..."))
        auto_menu.AppendSeparator()
        auto_translate = auto_menu.AppendCheckItem(wx.ID_ANY, "Chat-Übersetzung aktivieren")
        auto_menu.AppendSeparator()
        auto_plugin_manager = auto_menu.Append(wx.ID_ANY, "Plugin-Manager...")
        menubar.Append(auto_menu, _("Automation"))

        # Hilfe
        help_menu = wx.Menu()
        help_settings = help_menu.Append(wx.ID_PREFERENCES, "Einstellungen...\tCmd+,")
        help_logs = help_menu.Append(wx.ID_ANY, "Logs exportieren...")
        help_stats = help_menu.Append(wx.ID_ANY, "Verbindungsstatistiken...")
        help_stats_speak = help_menu.Append(wx.ID_ANY, "Statistiken vorlesen")
        help_menu.AppendSeparator()
        help_saved_msgs = help_menu.Append(wx.ID_ANY, "Gespeicherte Nachrichten...")
        help_menu.AppendSeparator()
        help_manual = help_menu.Append(wx.ID_ANY, "Handbuch")
        help_hotkeys = help_menu.Append(wx.ID_ANY, "Tastenkürzel-Referenz...")
        help_menu.AppendSeparator()
        help_changelog = help_menu.Append(wx.ID_ANY, "Changelog")
        help_about = help_menu.Append(wx.ID_ANY, _("Über"))
        menubar.Append(help_menu, _("Hilfe"))

        self.SetMenuBar(menubar)

        self.Bind(wx.EVT_MENU, self.on_open_tt_file, open_tt)
        self.Bind(wx.EVT_MENU, self.on_menu_new_client, new_client)
        self.Bind(wx.EVT_MENU, self.on_menu_audio_settings, sound_settings)
        self.Bind(wx.EVT_MENU, self.on_menu_audio_apply, sound_apply)
        self.Bind(wx.EVT_MENU, self.on_menu_audio_refresh, sound_refresh)
        self.Bind(wx.EVT_MENU, self.on_menu_audio_apply_effects, sound_effects)
        self.Bind(wx.EVT_MENU, self.on_menu_record_conversations, record_convo)
        self.Bind(wx.EVT_MENU, self.on_menu_settings, prefs_item)
        self.Bind(wx.EVT_MENU_OPEN, self.on_sound_menu_open)
        self.Bind(wx.EVT_MENU, self.on_import_servers, import_servers)
        self.Bind(wx.EVT_MENU, self.on_export_servers, export_servers)
        self.Bind(wx.EVT_MENU, self.on_menu_settings_backup, settings_backup)
        self.Bind(wx.EVT_MENU, self.on_menu_settings_restore, settings_restore)
        self.Bind(wx.EVT_MENU, self.on_menu_quit, quit_item)

        self.Bind(wx.EVT_MENU, self.on_menu_connect, con_connect)
        self.Bind(wx.EVT_MENU, self.on_menu_disconnect, con_disconnect)
        self.Bind(wx.EVT_MENU, self.on_menu_reconnect, con_reconnect)
        self.Bind(wx.EVT_MENU, self.on_menu_auto_reconnect, con_autoreconnect)
        self.Bind(wx.EVT_MENU, self.on_menu_join_root, con_join_root)
        self.Bind(wx.EVT_MENU, self.on_menu_leave_channel, con_leave)
        self.Bind(wx.EVT_MENU, self.on_menu_server_check, con_server_check)

        self.Bind(wx.EVT_MENU, self.on_menu_channel_create, chan_create)
        self.Bind(wx.EVT_MENU, self.on_menu_channel_edit, chan_edit)
        self.Bind(wx.EVT_MENU, self.on_menu_channel_delete, chan_delete)
        self.Bind(wx.EVT_MENU, self.on_menu_channel_join, chan_join)
        self.Bind(wx.EVT_MENU, self.on_menu_channel_leave, chan_leave)
        self.Bind(wx.EVT_MENU, self.on_menu_channel_info, chan_info)
        self.Bind(wx.EVT_MENU, self.on_menu_channel_info_speak, chan_info_speak)
        self.Bind(wx.EVT_MENU, self.on_menu_channel_stats_speak, chan_stats_speak)
        self.Bind(wx.EVT_MENU, self.on_menu_channel_state_speak, chan_state_speak)
        self.Bind(wx.EVT_MENU, self.on_menu_channel_tt_url, chan_tt_url)
        self.Bind(wx.EVT_MENU, self.on_menu_channel_bans, chan_bans)
        self.Bind(wx.EVT_MENU, self.on_menu_channel_note, chan_note)
        self.Bind(wx.EVT_MENU, self.on_menu_channel_message, chan_msg)
        self.Bind(wx.EVT_MENU, self.on_menu_channel_file_upload, chan_file_upload)
        self.Bind(wx.EVT_MENU, self.on_menu_channel_file_download, chan_file_download)
        self.Bind(wx.EVT_MENU, self.on_menu_channel_file_delete, chan_file_delete)
        self.Bind(wx.EVT_MENU, self.on_menu_channel_file_refresh, chan_file_refresh)
        self.Bind(wx.EVT_MENU, lambda e: self.on_menu_channel_stream_mode(0, e), chan_stream_file)
        self.Bind(wx.EVT_MENU, lambda e: self.on_menu_channel_stream_mode(1, e), chan_stream_yt)
        self.Bind(wx.EVT_MENU, lambda e: self.on_menu_channel_stream_mode(2, e), chan_stream_sc)
        self.Bind(wx.EVT_MENU, lambda e: self.on_menu_channel_stream_mode(3, e), chan_stream_twitch)
        self.Bind(wx.EVT_MENU, lambda e: self.on_menu_channel_stream_mode(4, e), chan_stream_bandcamp)
        self.Bind(wx.EVT_MENU, lambda e: self.on_menu_channel_stream_mode(5, e), chan_stream_vimeo)
        self.Bind(wx.EVT_MENU, lambda e: self.on_menu_channel_stream_mode(6, e), chan_stream_mixcloud)
        self.Bind(wx.EVT_MENU, lambda e: self.on_menu_channel_stream_mode(7, e), chan_stream_radio)
        self.Bind(wx.EVT_MENU, lambda e: self.on_menu_channel_stream_mode(8, e), chan_stream_podcast)
        self.Bind(wx.EVT_MENU, lambda e: self.on_menu_channel_stream_mode(9, e), chan_stream_playlist)
        self.Bind(wx.EVT_MENU, self.on_menu_channel_view_messages, chan_view_msgs)
        self.Bind(wx.EVT_MENU, self.on_menu_channel_recent_dialog, chan_recent_dialog)
        self.Bind(wx.EVT_MENU, self.on_menu_stream_audio_file, chan_stream_audio)

        self.Bind(wx.EVT_MENU, self.on_menu_user_info, user_info)
        self.Bind(wx.EVT_MENU, self.on_menu_user_info_speak, user_info_speak)
        self.Bind(wx.EVT_MENU, self.on_menu_user_message, user_message)
        self.Bind(wx.EVT_MENU, self.on_menu_user_mute_voice, user_mute_voice)
        self.Bind(wx.EVT_MENU, self.on_menu_user_mute_media, user_mute_media)
        self.Bind(wx.EVT_MENU, self.on_menu_user_volume, user_volume)
        self.Bind(wx.EVT_MENU, self.on_menu_user_note, user_note)
        self.Bind(wx.EVT_MENU, self.on_menu_user_volume_up, user_vol_up)
        self.Bind(wx.EVT_MENU, self.on_menu_user_volume_down, user_vol_down)
        self.Bind(wx.EVT_MENU, self.on_menu_user_relay_voice, user_relay_voice)
        self.Bind(wx.EVT_MENU, self.on_menu_user_relay_media, user_relay_media)
        self.Bind(wx.EVT_MENU, self.on_menu_user_position, user_position)
        self.Bind(wx.EVT_MENU, self.on_menu_user_allow_voice, user_allow_voice)
        self.Bind(wx.EVT_MENU, self.on_menu_user_allow_video, user_allow_video)
        self.Bind(wx.EVT_MENU, self.on_menu_user_allow_desktop, user_allow_desktop)
        self.Bind(wx.EVT_MENU, self.on_menu_user_allow_media, user_allow_media)
        self.Bind(wx.EVT_MENU, self.on_menu_user_allow_text, user_allow_text)
        self.Bind(wx.EVT_MENU, self.on_menu_user_allow_all_voice, user_allow_all_voice)
        self.Bind(wx.EVT_MENU, self.on_menu_user_allow_all_video, user_allow_all_video)
        self.Bind(wx.EVT_MENU, self.on_menu_user_allow_all_desktop, user_allow_all_desktop)
        self.Bind(wx.EVT_MENU, self.on_menu_user_allow_all_media, user_allow_all_media)
        self.Bind(wx.EVT_MENU, self.on_menu_user_allow_all_text, user_allow_all_text)
        self.Bind(wx.EVT_MENU, self.on_menu_user_operator, user_op)
        self.Bind(wx.EVT_MENU, self.on_menu_user_kick, user_kick)
        self.Bind(wx.EVT_MENU, self.on_menu_user_kick_ban, user_kick_ban)
        self.Bind(wx.EVT_MENU, self.on_menu_user_kick_server, user_kick_server)
        self.Bind(wx.EVT_MENU, self.on_menu_user_kick_ban_server, user_kick_ban_server)
        self.Bind(wx.EVT_MENU, self.on_menu_user_ban, user_ban)
        self.Bind(wx.EVT_MENU, lambda e: self.on_menu_user_tx_toggle("voice", e), user_tx_voice)
        self.Bind(wx.EVT_MENU, lambda e: self.on_menu_user_tx_toggle("video", e), user_tx_video)
        self.Bind(wx.EVT_MENU, lambda e: self.on_menu_user_tx_toggle("desktop", e), user_tx_desktop)
        self.Bind(wx.EVT_MENU, lambda e: self.on_menu_user_tx_toggle("media", e), user_tx_media)
        self.Bind(wx.EVT_MENU, lambda e: self.on_menu_user_tx_toggle("msg", e), user_tx_msg)
        self.Bind(wx.EVT_MENU, self.on_menu_user_allow_desktop_access, user_tx_desktop_access)
        self.Bind(wx.EVT_MENU, self.on_menu_user_subscriptions, user_subs)
        self.Bind(wx.EVT_MENU, self.on_menu_user_move, user_move)
        self.Bind(wx.EVT_MENU, self.on_menu_store_move_target, user_store_move)
        self.Bind(wx.EVT_MENU, self.on_menu_move_to_target, user_move_stored)
        self.Bind(wx.EVT_MENU, self.on_menu_user_mute_all, user_mute_all)

        self.Bind(wx.EVT_MENU, self.on_menu_online_users, server_online)
        self.Bind(wx.EVT_MENU, self.on_menu_server_broadcast, server_broadcast)
        self.Bind(wx.EVT_MENU, self.on_menu_server_stats, server_stats)
        self.Bind(wx.EVT_MENU, self.on_menu_server_bans, server_bans)
        self.Bind(wx.EVT_MENU, self.on_menu_open_admin, server_admin)
        self.Bind(wx.EVT_MENU, self.on_menu_server_properties, server_props)
        self.Bind(wx.EVT_MENU, self.on_menu_server_save_config, server_save_config)
        self.Bind(wx.EVT_MENU, self.on_menu_speaking_log, server_speaking_log)

        self.Bind(wx.EVT_MENU, self.on_menu_change_nickname, profile_nick)
        self.Bind(wx.EVT_MENU, self.on_menu_change_status, profile_status)
        self.Bind(wx.EVT_MENU, self.on_menu_question_mode, profile_question)
        self.Bind(wx.EVT_MENU, self.on_menu_hear_myself, profile_hear)
        self.Bind(wx.EVT_MENU, self.on_menu_toggle_tts, profile_tts)
        self.Bind(wx.EVT_MENU, self.on_menu_desktop_sharing, profile_desktop)
        self.Bind(wx.EVT_MENU, lambda e: self.on_menu_toggle_tts_flag("chat", e), notif_chat)
        self.Bind(wx.EVT_MENU, lambda e: self.on_menu_toggle_tts_flag("private", e), notif_private)
        self.Bind(wx.EVT_MENU, lambda e: self.on_menu_toggle_tts_flag("system", e), notif_system)
        self.Bind(wx.EVT_MENU, lambda e: self.on_menu_toggle_tts_flag("own", e), notif_own)

        self.Bind(wx.EVT_MENU, self.on_menu_audio_ptt, audio_ptt)
        self.Bind(wx.EVT_MENU, self.on_menu_audio_va, audio_va)
        self.Bind(wx.EVT_MENU, self.on_menu_audio_settings, audio_settings)
        self.Bind(wx.EVT_MENU, lambda e: self.on_menu_audio_effect_toggle("agc", e), audio_agc)
        self.Bind(wx.EVT_MENU, lambda e: self.on_menu_audio_effect_toggle("denoise", e), audio_denoise)
        self.Bind(wx.EVT_MENU, lambda e: self.on_menu_audio_effect_toggle("echo", e), audio_echo)
        self.Bind(wx.EVT_MENU, self.on_menu_audio_apply_effects, audio_apply_effects)
        self.Bind(wx.EVT_MENU, self.on_menu_audio_apply, audio_apply)
        self.Bind(wx.EVT_MENU, self.on_menu_audio_refresh, audio_refresh)
        self.Bind(wx.EVT_MENU, self.on_menu_audio_loopback, audio_loopback)
        self.Bind(wx.EVT_MENU, self.on_menu_audio_mute_all, audio_mute_all)
        self.Bind(wx.EVT_MENU, self.on_menu_eq_presets, audio_eq_presets)

        self.Bind(wx.EVT_MENU, self.on_menu_video_toggle, video_tx)
        self.Bind(wx.EVT_MENU, self.on_menu_video_settings, video_settings)
        self.Bind(wx.EVT_MENU, self.on_menu_video_refresh, video_refresh)

        self.Bind(wx.EVT_MENU, self.on_menu_record_start, rec_start)
        self.Bind(wx.EVT_MENU, self.on_menu_record_stop, rec_stop)
        self.Bind(wx.EVT_MENU, self.on_menu_record_conversations, rec_convo)
        self.Bind(wx.EVT_MENU, self.on_menu_scheduled_recordings, rec_scheduled)
        self.Bind(wx.EVT_MENU, self.on_menu_recording_browser, rec_browser)
        self.Bind(wx.EVT_MENU, self.on_menu_macro_editor, auto_macro_editor)
        self.Bind(wx.EVT_MENU, self.on_menu_scheduled_macros, auto_scheduled_macros)
        self.Bind(wx.EVT_MENU, self.on_menu_trigger_editor, auto_trigger_editor)
        self._auto_translate_menu_item = auto_translate
        auto_translate.Check(bool(getattr(self.settings_store.settings, "translate_chat_enabled", False)))
        self.Bind(wx.EVT_MENU, self._on_menu_toggle_translation, auto_translate)
        self.Bind(wx.EVT_MENU, self.on_menu_plugin_manager, auto_plugin_manager)

        self.Bind(wx.EVT_MENU, self.on_menu_settings, help_settings)
        self.Bind(wx.EVT_MENU, self.on_menu_export_logs, help_logs)
        self.Bind(wx.EVT_MENU, self.on_menu_client_stats, help_stats)
        self.Bind(wx.EVT_MENU, self.on_menu_client_stats_speak, help_stats_speak)
        self.Bind(wx.EVT_MENU, self.on_menu_saved_messages, help_saved_msgs)
        self.Bind(wx.EVT_MENU, self.on_menu_manual, help_manual)
        self.Bind(wx.EVT_MENU, self.on_menu_hotkey_reference, help_hotkeys)
        self.Bind(wx.EVT_MENU, self.on_menu_changelog, help_changelog)
        self.Bind(wx.EVT_MENU, self.on_menu_about, help_about)

    # ------------------------------------------------------------------
    # Shared helpers (called from tabs)
    # ------------------------------------------------------------------

    def set_status(self, text: str) -> None:
        self.status.SetLabel(text)
        self.log.AppendText(text + "\n")
        self.logger.write(text)

    def _apply_saved_audio_prefs_on_startup(self) -> None:
        try:
            settings = self.settings_store.settings
            if settings.auto_apply_audio and settings.audio_prefs:
                self.audio_tab.apply_audio_prefs(settings.audio_prefs, announce=False)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Menu helpers
    # ------------------------------------------------------------------

    def _get_selected_channel_id(self) -> Optional[int]:
        chan_id = self.channels_tab._selected_channel_id
        if chan_id:
            return int(chan_id)
        my_ch = self.client.get_my_channel_id()
        if my_ch:
            return int(my_ch)
        return None

    def _get_selected_user(self):
        uid = self.channels_tab._selected_user_id
        if uid is None:
            return None
        for user in self.channels_tab._current_users:
            if int(user.nUserID) == int(uid):
                return user
        try:
            return self.client.get_user(int(uid))
        except Exception:
            return None

    def _select_tab_by_label(self, label: str) -> bool:
        if label not in self._panels:
            return False
        self._switch_to_panel(label)
        try:
            idx = self._panel_order.index(label)
            self._update_tab_info(idx)
        except ValueError:
            pass
        return True

    def _open_files_tab(self) -> Optional[FilesTab]:
        if not self._select_tab_by_label("Dateien"):
            self._replace_lazy_tab("files", FilesTab)
            self._select_tab_by_label("Dateien")
        return self.files_tab

    def _open_media_tab(self, mode_idx: Optional[int] = None):
        if not self._select_tab_by_label("Aufnahme & Medien"):
            self._replace_lazy_tab("media", MediaTab)
            self._select_tab_by_label("Aufnahme & Medien")
        if self.media_tab is None:
            return None
        if mode_idx is not None:
            self.media_tab.stream_mode.SetSelection(int(mode_idx))
            self.media_tab._update_stream_mode()
        return self.media_tab

    def _ask_text(self, title: str, label: str, value: str = "", password: bool = False) -> Optional[str]:
        style = wx.OK | wx.CANCEL
        if password:
            style |= wx.TE_PASSWORD
        dlg = wx.TextEntryDialog(self, label, title, value, style=style)
        accel = wx.AcceleratorTable([(wx.ACCEL_CMD, ord("W"), wx.ID_CLOSE)])
        dlg.SetAcceleratorTable(accel)
        dlg.Bind(wx.EVT_MENU, lambda e: dlg.EndModal(wx.ID_CANCEL), id=wx.ID_CLOSE)
        if dlg.ShowModal() != wx.ID_OK:
            dlg.Destroy()
            return None
        text = dlg.GetValue()
        dlg.Destroy()
        return text

    def _require_connected(self, action_label: str = "Aktion") -> bool:
        if not self.client.is_connected():
            self.set_status(f"Nicht verbunden: {action_label}")
            return False
        return True

    def _ask_ban_types(self, user) -> Optional[int]:
        tt = self.client.tt
        in_channel = int(getattr(user, "nChannelID", 0) or 0) > 0
        choices = []
        types = []
        if in_channel:
            choices.extend(
                [
                    "IP-Adresse (Kanal)",
                    "Benutzername (Kanal)",
                    "IP-Adresse (Server)",
                    "Benutzername (Server)",
                ]
            )
            types.extend(
                [
                    int(tt.BanType.BANTYPE_CHANNEL | tt.BanType.BANTYPE_IPADDR),
                    int(tt.BanType.BANTYPE_CHANNEL | tt.BanType.BANTYPE_USERNAME),
                    int(tt.BanType.BANTYPE_IPADDR),
                    int(tt.BanType.BANTYPE_USERNAME),
                ]
            )
        else:
            choices.extend(["IP-Adresse (Server)", "Benutzername (Server)"])
            types.extend(
                [
                    int(tt.BanType.BANTYPE_IPADDR),
                    int(tt.BanType.BANTYPE_USERNAME),
                ]
            )
        dlg = wx.SingleChoiceDialog(self, "Ban-Art auswählen", "Bannen", choices)
        if dlg.ShowModal() != wx.ID_OK:
            dlg.Destroy()
            return None
        idx = dlg.GetSelection()
        dlg.Destroy()
        if idx == wx.NOT_FOUND:
            return None
        return types[idx]

    def _get_user_volume_level(self, user_id: int) -> int:
        return int(self._user_volume_levels.get(int(user_id), 1000))

    def _set_user_volume_level(self, user_id: int, level: int) -> int:
        volume = max(0, min(32000, int(level)))
        self._user_volume_levels[int(user_id)] = volume
        self.client.set_user_volume(int(user_id), int(self.client.tt.StreamType.STREAMTYPE_VOICE), volume)
        # v2.4.0 – persist volume preset by username
        try:
            user = self.client.get_user(int(user_id))
            if user is not None:
                username = self.tt_str(getattr(user, "szUsername", "")) or ""
                if username:
                    presets = getattr(self.settings_store.settings, "user_volume_presets", {}) or {}
                    presets[username] = volume
                    self.settings_store.settings.user_volume_presets = presets
                    self.settings_store.save()
        except Exception:
            pass
        return volume

    def _apply_saved_user_volume(self, user_id: int) -> None:
        """v2.4.0 – Applies a persisted volume preset for a user who just joined."""
        try:
            user = self.client.get_user(int(user_id))
            if user is None:
                return
            username = self.tt_str(getattr(user, "szUsername", "")) or ""
            if not username:
                return
            presets = getattr(self.settings_store.settings, "user_volume_presets", {}) or {}
            if username in presets:
                vol = int(presets[username])
                self._user_volume_levels[int(user_id)] = vol
                self.client.set_user_volume(int(user_id), int(self.client.tt.StreamType.STREAMTYPE_VOICE), vol)
        except Exception:
            pass

    def _apply_noise_gate(self) -> None:
        """v2.4.0 – Applies noise gate / denoiser settings from settings store."""
        try:
            enabled = bool(getattr(self.settings_store.settings, "noise_gate_enabled", False))
            fn = getattr(self.client, "enable_denoiser", None)
            if fn is not None:
                fn(enabled)
        except Exception:
            pass

    def _apply_status_template(self, idx: int) -> None:
        """v2.5.0 – Applies a status template by index (0-based)."""
        try:
            templates = list(getattr(self.settings_store.settings, "status_templates", []) or [])
            if idx < 0 or idx >= len(templates):
                self.tts.speak(f"Keine Status-Vorlage {idx + 1}", kind="system")
                return
            text = str(templates[idx])
            self.client.change_status(self._status_mode, text)
            self._status_message = text
            self.tts.speak(f"Status: {text}", kind="system")
        except Exception as exc:
            self.tts.speak(f"Status-Vorlage Fehler: {exc}", kind="system")

    def _http_api_toggle_ptt(self) -> None:
        """Atomically toggles PTT state on the main thread (called via wx.CallAfter)."""
        new = not self._ptt_active
        self.client.enable_voice_transmission(new)

    def _http_api_toggle_mute(self) -> None:
        """Atomically toggles mute state on the main thread (called via wx.CallAfter)."""
        new = not self._mute_all
        self._mute_all = new
        self.client.set_sound_output_mute(new)

    def _http_api_join_channel(self, name: str) -> None:
        """v2.7.0 – Finds a channel by name and joins it (for HTTP API use)."""
        try:
            channels = list(self.client.get_channels() or [])
            name_l = name.strip().lower()
            for ch in channels:
                ch_name = (self.tt_str(getattr(ch, "szName", "")) or "").lower()
                if name_l == ch_name or name_l in ch_name:
                    wx.CallAfter(self.join_channel, int(getattr(ch, "nChannelID", 0)))
                    return
        except Exception as exc:
            self.logger.write(f"http_api_join_channel error: {exc}")

    def _check_connection_quality(self) -> None:
        """v2.6.0 – Announces poor connection quality via TTS (once per bad event)."""
        try:
            if not self.client.is_connected():
                return
            threshold = int(getattr(self.settings_store.settings, "connection_quality_threshold_ms", 200) or 200)
            ping = int(self._ping_last_ms or 0)
            if ping <= 0:
                # Try reading from connection tab
                try:
                    ping_text = self.connection_tab.get_ping_text()
                    import re as _re
                    m = _re.search(r"(\d+)", ping_text)
                    if m:
                        ping = int(m.group(1))
                except Exception:
                    pass
            if ping > threshold:
                if not getattr(self, "_quality_bad_announced", False):
                    self._quality_bad_announced = True
                    self.tts.speak(f"Verbindungsqualität schlecht, Ping {ping} ms", kind="system")
            else:
                self._quality_bad_announced = False
        except Exception:
            pass

    def _on_quality_timer(self, _event) -> None:
        """v2.6.0 – Timer callback for connection quality monitoring and titlebar update."""
        if getattr(self, "_closing", False):
            return
        try:
            if getattr(self.settings_store.settings, "connection_quality_announce", False):
                self._check_connection_quality()
        except Exception:
            pass
        self._update_titlebar()

    def _update_titlebar(self) -> None:
        """v2.6.0 – Updates window title with user count and ping if enabled."""
        try:
            if not getattr(self.settings_store.settings, "server_info_in_titlebar", False):
                self.SetTitle(f"TeamTalk VoiceOver Client {APP_VERSION}")
                return
            if not self.client.is_connected():
                self.SetTitle(f"TeamTalk VoiceOver Client {APP_VERSION}")
                return
            ping = int(self._ping_last_ms or 0)
            user_count = 0
            try:
                users = list(self.client.get_server_users() or [])
                user_count = len(users)
            except Exception:
                pass
            title = f"TeamTalk VoiceOver Client {APP_VERSION}"
            info_parts = []
            if user_count:
                info_parts.append(f"{user_count} Nutzer")
            if ping:
                info_parts.append(f"Ping {ping} ms")
            if info_parts:
                title += " — " + ", ".join(info_parts)
            self.SetTitle(title)
        except Exception:
            pass

    def _channel_details_dialog(
        self,
        title: str,
        name: str = "",
        topic: str = "",
        permanent: bool = False,
        allow_password: bool = True,
        channel_type: int = 0,
        disk_quota_mb: int = 0,
        max_users: int = 0,
        op_password: str = "",
        audio_codec_mode: str = "inherit",
        audio_codec_locked: bool = False,
    ) -> Optional[dict]:
        dlg = wx.Dialog(self, title=title)
        accel = wx.AcceleratorTable([(wx.ACCEL_CMD, ord("W"), wx.ID_CLOSE)])
        dlg.SetAcceleratorTable(accel)
        dlg.Bind(wx.EVT_MENU, lambda e: dlg.EndModal(wx.ID_CANCEL), id=wx.ID_CLOSE)
        root = wx.BoxSizer(wx.VERTICAL)

        form_box = wx.StaticBoxSizer(wx.StaticBox(dlg, label="Grunddaten"), wx.VERTICAL)
        form = wx.FlexGridSizer(cols=2, vgap=6, hgap=12)
        form.AddGrowableCol(1)

        lbl_name = wx.StaticText(dlg, label="Name")
        name_ctrl = wx.TextCtrl(dlg, value=name)
        lbl_topic = wx.StaticText(dlg, label="Thema")
        topic_ctrl = wx.TextCtrl(dlg, value=topic)

        form.Add(lbl_name, 0, wx.ALIGN_CENTER_VERTICAL)
        form.Add(name_ctrl, 1, wx.EXPAND)
        form.Add(lbl_topic, 0, wx.ALIGN_CENTER_VERTICAL)
        form.Add(topic_ctrl, 1, wx.EXPAND)

        pw_ctrl = None
        pw_check = None
        if allow_password:
            pw_check = wx.CheckBox(dlg, label="Passwort setzen")
            pw_ctrl = wx.TextCtrl(dlg, value="", style=wx.TE_PASSWORD)
            form.Add(pw_check, 0, wx.ALIGN_CENTER_VERTICAL)
            form.Add(pw_ctrl, 1, wx.EXPAND)

        perm_check = wx.CheckBox(dlg, label="Permanent")
        perm_check.SetValue(permanent)
        form.AddSpacer(0)
        form.Add(perm_check, 0)

        form_box.Add(form, 0, wx.ALL | wx.EXPAND, 10)
        root.Add(form_box, 0, wx.ALL | wx.EXPAND, 10)

        limits_box = wx.StaticBoxSizer(wx.StaticBox(dlg, label="Limits"), wx.VERTICAL)
        limits = wx.FlexGridSizer(cols=2, vgap=6, hgap=12)
        limits.AddGrowableCol(1)
        lbl_quota = wx.StaticText(dlg, label="Datei-Quota (MB, 0=aus)")
        quota_ctrl = wx.SpinCtrl(dlg, min=0, max=1024 * 1024, initial=int(disk_quota_mb))
        lbl_max = wx.StaticText(dlg, label="Max. Benutzer (0=Server)")
        max_ctrl = wx.SpinCtrl(dlg, min=0, max=10000, initial=int(max_users))
        lbl_op = wx.StaticText(dlg, label="Operator-Passwort")
        op_ctrl = wx.TextCtrl(dlg, value=op_password)
        limits.Add(lbl_quota, 0, wx.ALIGN_CENTER_VERTICAL)
        limits.Add(quota_ctrl, 1, wx.EXPAND)
        limits.Add(lbl_max, 0, wx.ALIGN_CENTER_VERTICAL)
        limits.Add(max_ctrl, 1, wx.EXPAND)
        limits.Add(lbl_op, 0, wx.ALIGN_CENTER_VERTICAL)
        limits.Add(op_ctrl, 1, wx.EXPAND)
        limits_box.Add(limits, 0, wx.ALL | wx.EXPAND, 10)
        root.Add(limits_box, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 10)

        type_box = wx.StaticBoxSizer(wx.StaticBox(dlg, label="Kanaltyp"), wx.VERTICAL)
        tt = self.client.tt
        flags = []
        def _flag(label: str, flag_value: int) -> wx.CheckBox:
            cb = wx.CheckBox(dlg, label=label)
            cb.SetValue(bool(channel_type & int(flag_value)))
            flags.append((cb, int(flag_value)))
            type_box.Add(cb, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
            return cb

        _flag("Nur ein Sprecher gleichzeitig (Solo)", tt.ChannelType.CHANNEL_SOLO_TRANSMIT)
        _flag("Unterrichtsmodus (Operator steuert Sprecher)", tt.ChannelType.CHANNEL_CLASSROOM)
        _flag("Operator nur Empfang", tt.ChannelType.CHANNEL_OPERATOR_RECVONLY)
        _flag("Keine Sprachaktivierung", tt.ChannelType.CHANNEL_NO_VOICEACTIVATION)
        _flag("Keine Aufnahmen", tt.ChannelType.CHANNEL_NO_RECORDING)
        _flag("Versteckter Kanal", tt.ChannelType.CHANNEL_HIDDEN)
        root.Add(type_box, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 10)

        audio_box = wx.StaticBoxSizer(wx.StaticBox(dlg, label="Audio-Codec"), wx.VERTICAL)
        codec_choices = [
            ("Vom Elternkanal übernehmen", "inherit"),
            ("Opus (Standard)", "opus"),
            ("Speex (Standard)", "speex"),
            ("Speex VBR (Standard)", "speex_vbr"),
            ("Kein Audio", "none"),
        ]
        if audio_codec_mode == "keep":
            codec_choices.insert(0, ("Aktueller Codec beibehalten", "keep"))
        codec_choice = wx.Choice(dlg, choices=[c[0] for c in codec_choices])
        codec_choice.SetSelection(0)
        for idx, _ in enumerate(codec_choices):
            if codec_choices[idx][1] == audio_codec_mode:
                codec_choice.SetSelection(idx)
                break
        codec_choice.Enable(not audio_codec_locked)
        audio_box.Add(codec_choice, 0, wx.ALL | wx.EXPAND, 8)
        if audio_codec_locked:
            audio_box.Add(wx.StaticText(dlg, label="Audio-Codec kann nicht geändert werden, wenn Nutzer im Kanal sind."), 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        root.Add(audio_box, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 10)

        # OPUS settings panel
        opus_box = wx.StaticBoxSizer(wx.StaticBox(dlg, label="OPUS Einstellungen"), wx.VERTICAL)
        opus_form = wx.FlexGridSizer(cols=2, vgap=6, hgap=12)
        opus_form.AddGrowableCol(1)

        lbl_opus_app = wx.StaticText(dlg, label="Anwendung")
        opus_app = wx.Choice(dlg, choices=["VoIP", "Musik"])
        opus_app.SetSelection(0)
        lbl_opus_sr = wx.StaticText(dlg, label="Samplerate (Hz)")
        opus_sr = wx.Choice(dlg, choices=["8000", "12000", "16000", "24000", "48000"])
        opus_sr.SetStringSelection("48000")
        lbl_opus_ch = wx.StaticText(dlg, label="Kanäle")
        opus_ch = wx.Choice(dlg, choices=["Mono", "Stereo"])
        opus_ch.SetSelection(0)
        lbl_opus_br = wx.StaticText(dlg, label="Bitrate (kbps)")
        opus_br = wx.SpinCtrl(dlg, min=6, max=510, initial=64)
        opus_vbr = wx.CheckBox(dlg, label="Variable Bitrate (VBR)")
        opus_dtx = wx.CheckBox(dlg, label="Silence ignorieren (DTX)")
        lbl_opus_tx = wx.StaticText(dlg, label="Intervall (ms)")
        opus_tx = wx.SpinCtrl(dlg, min=20, max=1000, initial=40)
        lbl_opus_frame = wx.StaticText(dlg, label="Framegröße (ms)")
        opus_frame = wx.SpinCtrl(dlg, min=2, max=60, initial=20)

        for lbl, ctrl in [(lbl_opus_app, opus_app), (lbl_opus_sr, opus_sr),
                          (lbl_opus_ch, opus_ch), (lbl_opus_br, opus_br),
                          (lbl_opus_tx, opus_tx), (lbl_opus_frame, opus_frame)]:
            opus_form.Add(lbl, 0, wx.ALIGN_CENTER_VERTICAL)
            opus_form.Add(ctrl, 1, wx.EXPAND)
        opus_form.AddSpacer(0)
        opus_form.Add(opus_vbr, 0)
        opus_form.AddSpacer(0)
        opus_form.Add(opus_dtx, 0)
        opus_box.Add(opus_form, 0, wx.ALL | wx.EXPAND, 8)
        root.Add(opus_box, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 10)

        # Speex settings panel
        speex_box = wx.StaticBoxSizer(wx.StaticBox(dlg, label="Speex Einstellungen"), wx.VERTICAL)
        speex_form = wx.FlexGridSizer(cols=2, vgap=6, hgap=12)
        speex_form.AddGrowableCol(1)
        lbl_spx_sr = wx.StaticText(dlg, label="Samplerate (Hz)")
        spx_sr = wx.Choice(dlg, choices=["8000", "16000", "32000"])
        spx_sr.SetStringSelection("16000")
        lbl_spx_q = wx.StaticText(dlg, label="Qualität (0–10)")
        spx_q = wx.SpinCtrl(dlg, min=0, max=10, initial=4)
        lbl_spx_tx = wx.StaticText(dlg, label="Intervall (ms)")
        spx_tx = wx.SpinCtrl(dlg, min=20, max=1000, initial=40)
        spx_vbr = wx.CheckBox(dlg, label="Variable Bitrate (VBR)")
        lbl_spx_maxbr = wx.StaticText(dlg, label="Max. Bitrate (bps, 0=aus)")
        spx_maxbr = wx.SpinCtrl(dlg, min=0, max=128000, initial=0)
        spx_dtx = wx.CheckBox(dlg, label="Stille ignorieren (DTX)")
        for lbl, ctrl in [(lbl_spx_sr, spx_sr), (lbl_spx_q, spx_q),
                          (lbl_spx_tx, spx_tx), (lbl_spx_maxbr, spx_maxbr)]:
            speex_form.Add(lbl, 0, wx.ALIGN_CENTER_VERTICAL)
            speex_form.Add(ctrl, 1, wx.EXPAND)
        speex_form.AddSpacer(0)
        speex_form.Add(spx_vbr, 0)
        speex_form.AddSpacer(0)
        speex_form.Add(spx_dtx, 0)
        speex_box.Add(speex_form, 0, wx.ALL | wx.EXPAND, 8)
        root.Add(speex_box, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 10)

        # Fixed audio volume + stream timeouts
        audio_adv_box = wx.StaticBoxSizer(wx.StaticBox(dlg, label="Audio-Optionen"), wx.VERTICAL)
        audio_adv_form = wx.FlexGridSizer(cols=2, vgap=6, hgap=12)
        audio_adv_form.AddGrowableCol(1)
        fixed_vol_check = wx.CheckBox(dlg, label="Feste Lautstärke für alle Nutzer")
        fixed_vol_spin = wx.SpinCtrl(dlg, min=0, max=32000, initial=0)
        lbl_voice_timeout = wx.StaticText(dlg, label="Max. Sprachdauer (Sek., 0=aus)")
        voice_timeout = wx.SpinCtrl(dlg, min=0, max=3600, initial=0)
        lbl_media_timeout = wx.StaticText(dlg, label="Max. Mediendauer (Sek., 0=aus)")
        media_timeout = wx.SpinCtrl(dlg, min=0, max=3600, initial=0)
        audio_adv_form.AddSpacer(0)
        audio_adv_form.Add(fixed_vol_check, 0)
        audio_adv_form.Add(wx.StaticText(dlg, label="Lautstärke"), 0, wx.ALIGN_CENTER_VERTICAL)
        audio_adv_form.Add(fixed_vol_spin, 1, wx.EXPAND)
        audio_adv_form.Add(lbl_voice_timeout, 0, wx.ALIGN_CENTER_VERTICAL)
        audio_adv_form.Add(voice_timeout, 1, wx.EXPAND)
        audio_adv_form.Add(lbl_media_timeout, 0, wx.ALIGN_CENTER_VERTICAL)
        audio_adv_form.Add(media_timeout, 1, wx.EXPAND)
        audio_adv_box.Add(audio_adv_form, 0, wx.ALL | wx.EXPAND, 8)
        root.Add(audio_adv_box, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 10)

        def _update_codec_panels():
            sel = codec_choices[codec_choice.GetSelection()][1]
            opus_box.GetStaticBox().Show(sel in ("opus",))
            speex_box.GetStaticBox().Show(sel in ("speex", "speex_vbr"))
            for child in opus_box.GetChildren():
                try:
                    child.GetWindow().Show(sel == "opus")
                except Exception:
                    pass
            for child in speex_box.GetChildren():
                try:
                    child.GetWindow().Show(sel in ("speex", "speex_vbr"))
                except Exception:
                    pass
            dlg.Layout()

        codec_choice.Bind(wx.EVT_CHOICE, lambda e: _update_codec_panels())
        _update_codec_panels()

        rights_note = None
        try:
            rights = int(self.client.get_my_user_rights() or 0)
        except Exception:
            rights = 0
        can_modify = bool(rights & int(tt.UserRight.USERRIGHT_MODIFY_CHANNELS))
        if not can_modify:
            perm_check.Disable()
            quota_ctrl.Disable()
            max_ctrl.Disable()
            op_ctrl.Disable()
            for cb, _flag in flags:
                cb.Disable()
            if not audio_codec_locked:
                codec_choice.Disable()
            rights_note = wx.StaticText(dlg, label="Hinweis: Einige Optionen erfordern Serverrechte (Kanaleigenschaften).")
            root.Add(rights_note, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        btns = dlg.CreateButtonSizer(wx.OK | wx.CANCEL)
        root.Add(btns, 0, wx.ALL | wx.ALIGN_RIGHT, 10)
        dlg.SetSizerAndFit(root)

        if dlg.ShowModal() != wx.ID_OK:
            dlg.Destroy()
            return None

        result_flags = 0
        for cb, flag_value in flags:
            if cb.GetValue():
                result_flags |= int(flag_value)

        result = {
            "name": name_ctrl.GetValue().strip(),
            "topic": topic_ctrl.GetValue().strip(),
            "permanent": bool(perm_check.GetValue()),
            "channel_type": result_flags,
            "disk_quota_mb": int(quota_ctrl.GetValue()),
            "max_users": int(max_ctrl.GetValue()),
            "op_password": op_ctrl.GetValue().strip(),
            "audio_codec_mode": codec_choices[codec_choice.GetSelection()][1],
            "opus_app": opus_app.GetSelection(),
            "opus_samplerate": int(opus_sr.GetStringSelection()),
            "opus_channels": opus_ch.GetSelection() + 1,
            "opus_bitrate": int(opus_br.GetValue()),
            "opus_vbr": bool(opus_vbr.GetValue()),
            "opus_dtx": bool(opus_dtx.GetValue()),
            "opus_tx_interval": int(opus_tx.GetValue()),
            "opus_frame_size": int(opus_frame.GetValue()),
            "speex_samplerate": int(spx_sr.GetStringSelection()),
            "speex_quality": int(spx_q.GetValue()),
            "speex_tx_interval": int(spx_tx.GetValue()),
            "speex_vbr": bool(spx_vbr.GetValue()),
            "speex_max_bitrate": int(spx_maxbr.GetValue()),
            "speex_dtx": bool(spx_dtx.GetValue()),
            "fixed_volume": int(fixed_vol_spin.GetValue()) if fixed_vol_check.GetValue() else 0,
            "voice_timeout_sec": int(voice_timeout.GetValue()),
            "media_timeout_sec": int(media_timeout.GetValue()),
        }
        if allow_password and pw_check and pw_ctrl:
            result["set_password"] = bool(pw_check.GetValue())
            result["password"] = pw_ctrl.GetValue()
        dlg.Destroy()
        return result

    def _record_format_dialog(self) -> Optional[tuple]:
        formats = [
            ("WAV (PCM)", self.client.tt.AudioFileFormat.AFF_WAVE_FORMAT),
            ("MP3 128k", self.client.tt.AudioFileFormat.AFF_MP3_128KBIT_FORMAT),
            ("MP3 256k", self.client.tt.AudioFileFormat.AFF_MP3_256KBIT_FORMAT),
            ("Channel-Codec", self.client.tt.AudioFileFormat.AFF_CHANNELCODEC_FORMAT),
        ]
        dlg = wx.SingleChoiceDialog(self, "Aufnahmeformat wählen", "Aufnahme", [f[0] for f in formats])
        if dlg.ShowModal() != wx.ID_OK:
            dlg.Destroy()
            return None
        idx = dlg.GetSelection()
        dlg.Destroy()
        return formats[idx]

    def tt_str(self, value) -> str:
        out = self.client.tt.ttstr(value)
        if isinstance(out, bytes):
            return out.decode("utf-8", errors="replace")
        return str(out)

    # ------------------------------------------------------------------
    # Menu actions
    # ------------------------------------------------------------------

    def on_menu_connect(self, _event):
        if not self.connection_window.IsShown():
            self.connection_window.Show()
        self.connection_window.Raise()
        wx.CallAfter(self.connection_window.connection_tab.server_list.SetFocus)

    def on_menu_disconnect(self, _event):
        if not self.client.is_connected():
            self.set_status("Nicht verbunden")
            return
        try:
            self.client.stop_event_loop_and_wait()
        except Exception:
            pass
        self.sound_manager.play("server_disconnect", self.settings_store.settings.sound_events.get("server_disconnect"))
        self.client.disconnect_transport()
        # v2.6.0 – Verbindungsqualitäts-Timer stoppen
        try:
            if hasattr(self, "_quality_timer") and self._quality_timer.IsRunning():
                self._quality_timer.Stop()
        except Exception:
            pass
        # v2.7.0 – Webhook: Verbindung getrennt
        try:
            self._webhook.emit("disconnect", {"server": getattr(self, "_current_server_key", "")})
        except Exception:
            pass
        self.set_status("Verbindung getrennt")

    def on_menu_reconnect(self, _event):
        self.connection_tab.on_reconnect(None)

    def on_menu_auto_reconnect(self, event):
        enabled = event.IsChecked()
        self._auto_reconnect = enabled
        self.connection_tab.auto_reconnect.SetValue(enabled)
        self.settings_store.settings.auto_reconnect_enabled = enabled
        self.settings_store.save()

    def on_menu_join_root(self, _event):
        if not self._require_connected("Root-Kanal beitreten"):
            return
        self.connection_tab.on_join_root(None)

    def on_menu_leave_channel(self, _event):
        if not self._require_connected("Kanal verlassen"):
            return
        self.connection_tab.on_leave_channel(None)

    def on_menu_new_client(self, _event):
        try:
            if getattr(sys, "frozen", False):
                cmd = [sys.executable]
                cwd = None
            else:
                cmd = [sys.executable, os.path.abspath(__file__)]
                cwd = os.path.dirname(os.path.abspath(__file__))
            subprocess.Popen(cmd, cwd=cwd)
            self.set_status("Neuer Client gestartet")
        except Exception as exc:
            self.set_status(f"Neuer Client konnte nicht gestartet werden: {exc}")

    def on_menu_server_check(self, _event):
        self.connection_tab.on_server_check(None)

    def on_menu_online_users(self, _event):
        if not self.client.is_connected():
            self.set_status("Nicht verbunden")
            return
        dlg = OnlineUsersDialog(self, self)
        self.online_users_dialog = dlg
        dlg.refresh()
        dlg.ShowModal()
        dlg.Destroy()
        self.online_users_dialog = None

    def on_menu_server_broadcast(self, _event):
        if not self.client.is_connected():
            self.set_status("Nicht verbunden")
            return
        dlg = BroadcastMessageDialog(self)
        if dlg.ShowModal() == wx.ID_OK:
            msg = dlg.get_message()
            if msg:
                ok = self.client.send_broadcast_message(msg)
                if ok:
                    self.set_status("Servernachricht gesendet")
                else:
                    self.set_status("Servernachricht konnte nicht gesendet werden")
            else:
                self.set_status("Nachricht ist leer")
        dlg.Destroy()

    def on_menu_server_stats(self, _event):
        if not self.client.is_connected():
            self.set_status("Nicht verbunden")
            return
        dlg = ServerStatisticsDialog(self, self)
        self.server_stats_dialog = dlg
        dlg.refresh()
        dlg.ShowModal()
        dlg.Destroy()
        self.server_stats_dialog = None

    def on_menu_server_bans(self, _event):
        if not self._require_connected("Sperren (Server) anzeigen"):
            return
        dlg = BanListDialog(self, self, "Sperren (Server)")
        self.ban_dialog = dlg
        dlg.clear()

        def worker():
            try:
                self.client.do_list_bans(0)
            except Exception as exc:
                wx.CallAfter(self.set_status, f"Sperren laden fehlgeschlagen: {exc}")

        threading.Thread(target=worker, daemon=True).start()
        dlg.ShowModal()
        dlg.Destroy()
        self.ban_dialog = None

    def on_menu_open_admin(self, _event):
        if not self._require_connected("Administration öffnen"):
            return
        if not self._select_tab_by_label("Administration"):
            self._replace_lazy_tab("admin", AdminTab)
            self._select_tab_by_label("Administration")

    def on_menu_server_properties(self, _event):
        if not self._require_connected("Servereigenschaften öffnen"):
            return
        if not self._select_tab_by_label("Administration"):
            self._replace_lazy_tab("admin", AdminTab)
            self._select_tab_by_label("Administration")
        if self.admin_tab is not None:
            wx.CallAfter(self.admin_tab.srv_name.SetFocus)

    def on_menu_server_save_config(self, _event):
        if not self._require_connected("Konfiguration speichern"):
            return
        try:
            result = self.client.do_save_config()
        except Exception as exc:
            self.set_status(f"Konfiguration speichern fehlgeschlagen: {exc}")
            return
        if int(result or 0) >= 0:
            self.set_status("Konfiguration gespeichert")
        else:
            self.set_status("Konfiguration konnte nicht gespeichert werden")

    def on_menu_client_stats(self, _event):
        dlg = ClientStatisticsDialog(self, self)
        dlg.ShowModal()
        dlg.Destroy()

    def on_menu_client_stats_speak(self, _event):
        if not self.client.is_connected():
            self.set_status("Nicht verbunden")
            return
        stats = self.client.get_client_statistics()
        if stats is None:
            self.set_status("Keine Statistik verfügbar")
            return
        udp = int(getattr(stats, "nUdpPingTimeMs", 0) or 0)
        tcp = int(getattr(stats, "nTcpPingTimeMs", 0) or 0)
        text = f"UDP Ping {udp} Millisekunden, TCP Ping {tcp} Millisekunden."
        self.tts.speak(text, kind="system")

    def on_menu_change_nickname(self, _event):
        if not self._require_connected("Nickname ändern"):
            return
        current = ""
        try:
            user = self.client.get_user(self.client.get_my_user_id())
            current = self.tt_str(getattr(user, "szNickname", "")) or ""
        except Exception:
            current = ""
        value = self._ask_text("Nickname ändern", "Neuer Nickname", current)
        if value is None:
            return
        value = value.strip()
        if not value:
            self.set_status("Nickname darf nicht leer sein")
            return
        cmdid = self.client.change_nickname(value)
        if cmdid < 0:
            self.set_status("Nickname ändern fehlgeschlagen")
        else:
            self.set_status("Nickname wird geändert")

    def on_menu_change_status(self, _event):
        if not self._require_connected("Status setzen"):
            return
        dlg = ChangeStatusDialog(self)
        if dlg.ShowModal() == wx.ID_OK:
            idx, message = dlg.get_values()
            tt = self.client.tt
            mode_map = {
                0: int(tt.UserStatusMode.STATUSMODE_AVAILABLE),
                1: int(tt.UserStatusMode.STATUSMODE_AWAY),
                2: int(tt.UserStatusMode.STATUSMODE_QUESTION),
            }
            mode = mode_map.get(idx, int(tt.UserStatusMode.STATUSMODE_AVAILABLE))
            self._status_mode = mode
            self._status_message = message
            cmdid = self.client.change_status(mode, message)
            if cmdid < 0:
                self.set_status("Status konnte nicht gesetzt werden")
            else:
                self.set_status("Status wird gesetzt")
        dlg.Destroy()

    def on_menu_question_mode(self, event):
        if not self._require_connected("Frage-Modus"):
            return
        tt = self.client.tt
        enabled = event.IsChecked()
        if enabled:
            mode = int(tt.UserStatusMode.STATUSMODE_QUESTION)
        else:
            mode = int(tt.UserStatusMode.STATUSMODE_AVAILABLE)
        self._status_mode = mode
        cmdid = self.client.change_status(mode, self._status_message)
        if cmdid < 0:
            self.set_status("Status konnte nicht gesetzt werden")
        else:
            self.set_status("Frage-Modus aktiv" if enabled else "Frage-Modus aus")

    def on_menu_hear_myself(self, event):
        enabled = event.IsChecked()
        try:
            self.audio_tab.loopback_toggle.SetValue(enabled)
            self.audio_tab.on_loopback_toggle(None)
        except Exception:
            self.set_status("Mikrofontest konnte nicht umgestellt werden")

    def on_menu_toggle_tts(self, event):
        enabled = event.IsChecked()
        try:
            self.system_tab.tts_enabled.SetValue(enabled)
            self.system_tab._on_enable_changed(None)
            self.set_status("TTS aktiviert" if enabled else "TTS deaktiviert")
        except Exception:
            self.set_status("TTS konnte nicht umgestellt werden")

    def on_menu_toggle_tts_flag(self, flag: str, event) -> None:
        enabled = event.IsChecked()
        try:
            if flag == "chat":
                self.system_tab.tts_chat.SetValue(enabled)
            elif flag == "private":
                self.system_tab.tts_private.SetValue(enabled)
            elif flag == "system":
                self.system_tab.tts_system.SetValue(enabled)
            elif flag == "own":
                self.system_tab.tts_own.SetValue(enabled)
            self.system_tab._apply_settings(None)
            self.set_status("Benachrichtigung gespeichert")
        except Exception:
            self.set_status("Benachrichtigung konnte nicht umgestellt werden")

    def _ensure_desktop_tab(self) -> Optional[DesktopTab]:
        if self.desktop_tab is not None:
            return self.desktop_tab
        placeholder = self._lazy_pages.get("desktop")
        if placeholder is None:
            return self.desktop_tab
        self._replace_lazy_tab("desktop", DesktopTab)
        return self.desktop_tab

    def on_menu_desktop_sharing(self, event):
        enabled = event.IsChecked()
        tab = self._ensure_desktop_tab()
        if tab is None:
            self.set_status("Desktop-Tab nicht verfügbar")
            return
        tab.share_toggle.SetValue(enabled)
        tab.on_share_toggle(wx.CommandEvent())

    def on_menu_channel_create(self, _event):
        if not self._require_connected("Kanal erstellen"):
            return
        parent_id = self._get_selected_channel_id() or self.client.get_root_channel_id()
        parent_channel = self.client.get_channel(parent_id) if parent_id else None
        default_codec_mode = "opus"
        if parent_channel is not None:
            default_codec_mode = "inherit"
        data = self._channel_details_dialog(
            "Kanal erstellen",
            allow_password=True,
            permanent=bool(parent_channel.uChannelType & self.client.tt.ChannelType.CHANNEL_PERMANENT) if parent_channel else False,
            channel_type=int(getattr(parent_channel, "uChannelType", 0) or 0) if parent_channel else 0,
            disk_quota_mb=int(getattr(parent_channel, "nDiskQuota", 0) or 0) // (1024 * 1024) if parent_channel else 0,
            max_users=int(getattr(parent_channel, "nMaxUsers", 0) or 0) if parent_channel else 0,
            audio_codec_mode=default_codec_mode,
        )
        if not data or not data["name"]:
            self.set_status("Kanalname fehlt")
            return
        try:
            rights = int(self.client.get_my_user_rights() or 0)
        except Exception:
            rights = 0
        can_modify = bool(rights & int(self.client.tt.UserRight.USERRIGHT_MODIFY_CHANNELS))
        channel_type = int(data.get("channel_type", 0) or 0)
        if data.get("permanent") and can_modify:
            channel_type |= int(self.client.tt.ChannelType.CHANNEL_PERMANENT)
        audio_codec = None
        codec_mode = data.get("audio_codec_mode")
        if codec_mode == "inherit" and parent_channel is not None:
            audio_codec = parent_channel.audiocodec
        elif codec_mode == "opus":
            audio_codec = self.client.build_default_opus_codec()
            try:
                tt_mod = self.client.tt
                audio_codec.opus.nSampleRate = int(data.get("opus_samplerate", 48000))
                audio_codec.opus.nChannels = int(data.get("opus_channels", 1))
                audio_codec.opus.nBitRate = int(data.get("opus_bitrate", 64)) * 1000
                audio_codec.opus.bVBR = bool(data.get("opus_vbr", True))
                audio_codec.opus.bDTX = bool(data.get("opus_dtx", False))
                audio_codec.opus.nTxIntervalMSec = int(data.get("opus_tx_interval", 40))
                audio_codec.opus.nFrameSizeMSec = int(data.get("opus_frame_size", 0))
                opus_app_idx = int(data.get("opus_app", 0))
                audio_codec.opus.nApplication = int(
                    tt_mod.OPUS_APPLICATION_VOIP if opus_app_idx == 0 else tt_mod.OPUS_APPLICATION_MUSIC
                )
            except Exception:
                pass
        elif codec_mode == "speex":
            audio_codec = self.client.build_default_speex_codec()
            try:
                sr = int(data.get("speex_samplerate", 16000))
                audio_codec.speex.nBandmode = {8000: 0, 16000: 1, 32000: 2}.get(sr, 1)
                audio_codec.speex.nQuality = int(data.get("speex_quality", 4))
                audio_codec.speex.nTxIntervalMSec = int(data.get("speex_tx_interval", 40))
            except Exception:
                pass
        elif codec_mode == "speex_vbr":
            audio_codec = self.client.build_default_speex_vbr_codec()
            try:
                sr = int(data.get("speex_samplerate", 16000))
                audio_codec.speex_vbr.nBandmode = {8000: 0, 16000: 1, 32000: 2}.get(sr, 1)
                audio_codec.speex_vbr.nQuality = int(data.get("speex_quality", 4))
                audio_codec.speex_vbr.nTxIntervalMSec = int(data.get("speex_tx_interval", 40))
                audio_codec.speex_vbr.nMaxBitRate = int(data.get("speex_max_bitrate", 0))
                audio_codec.speex_vbr.bDTX = bool(data.get("speex_dtx", True))
            except Exception:
                pass
        elif codec_mode == "none":
            audio_codec = self.client.build_no_audio_codec()
        if can_modify:
            result = self.client.make_channel(
                name=data["name"],
                parent_id=parent_id,
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
                name=data["name"],
                parent_id=parent_id,
                topic=data.get("topic", ""),
                password=data.get("password", "") if data.get("set_password") else "",
                channel_type=channel_type,
                audio_codec=audio_codec,
            )
        self.set_status(result.message)
        if result.ok:
            self.channels_tab.refresh_channels_and_users()

    def on_menu_channel_edit(self, _event):
        if not self._require_connected("Kanal bearbeiten"):
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
        except Exception:
            rights = 0
        can_modify = bool(rights & int(self.client.tt.UserRight.USERRIGHT_MODIFY_CHANNELS))
        users_in_channel = []
        try:
            users_in_channel = self.client.get_channel_users(chan_id)
        except Exception:
            users_in_channel = []
        data = self._channel_details_dialog(
            "Kanal bearbeiten",
            name=self.tt_str(channel.szName),
            topic=self.tt_str(channel.szTopic),
            permanent=bool(channel.uChannelType & self.client.tt.ChannelType.CHANNEL_PERMANENT),
            allow_password=True,
            channel_type=int(channel.uChannelType or 0),
            disk_quota_mb=int(getattr(channel, "nDiskQuota", 0) or 0) // (1024 * 1024),
            max_users=int(getattr(channel, "nMaxUsers", 0) or 0),
            op_password=self.tt_str(getattr(channel, "szOpPassword", "")),
            audio_codec_mode="keep",
            audio_codec_locked=bool(users_in_channel),
        )
        if not data or not data["name"]:
            self.set_status("Kanalname fehlt")
            return
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
            op_password = str(data.get("op_password", "")).strip()
            if op_password:
                channel.szOpPassword = self.client.tt.ttstr(op_password)
            codec_mode = data.get("audio_codec_mode")
            if not users_in_channel and codec_mode:
                if codec_mode == "opus":
                    channel.audiocodec = self.client.build_default_opus_codec()
                elif codec_mode == "speex":
                    channel.audiocodec = self.client.build_default_speex_codec()
                elif codec_mode == "speex_vbr":
                    channel.audiocodec = self.client.build_default_speex_vbr_codec()
                elif codec_mode == "none":
                    channel.audiocodec = self.client.build_no_audio_codec()
        result = self.client.update_channel(channel)
        self.set_status(result.message)
        if result.ok:
            self.channels_tab.refresh_channels_and_users()

    def on_menu_channel_delete(self, _event):
        if not self._require_connected("Kanal löschen"):
            return
        chan_id = self._get_selected_channel_id()
        if not chan_id:
            self.set_status("Kein Kanal ausgewählt")
            return
        dlg = wx.MessageDialog(self, "Kanal wirklich löschen?", "Kanal löschen", wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION)
        dlg.SetYesNoLabels("Ja", "Nein")
        if dlg.ShowModal() != wx.ID_YES:
            dlg.Destroy()
            return
        dlg.Destroy()
        result = self.client.remove_channel(chan_id)
        self.set_status(result.message)
        if result.ok:
            self.channels_tab.refresh_channels_and_users()

    def on_menu_channel_join(self, _event):
        if not self._require_connected("Kanal beitreten"):
            return
        chan_id = self._get_selected_channel_id()
        if chan_id:
            self.join_channel(int(chan_id))
            return
        path = self._ask_text("Kanal beitreten", "Kanalpfad (z. B. /Lobby):", "/")
        if not path:
            return
        self.set_status("Trete Kanal bei...")

        def worker():
            self.client.stop_event_loop_and_wait()
            result = self.client.join_channel_by_path(path, timeout_ms=6000)
            self.client.start_event_loop(self.handle_tt_message)
            wx.CallAfter(self.set_status, result.message)
            if result.ok:
                self.sound_manager.play("channel_join", self.settings_store.settings.sound_events.get("channel_join"))
                wx.CallAfter(self.channels_tab.refresh_channels_and_users)

        threading.Thread(target=worker, daemon=True).start()

    def on_menu_channel_leave(self, _event):
        if not self._require_connected("Kanal verlassen"):
            return
        self.connection_tab.on_leave_channel(None)

    def on_menu_channel_info(self, _event):
        if not self._require_connected("Kanalinfo"):
            return
        channel_id = self._get_selected_channel_id()
        if not channel_id:
            self.set_status("Kein Kanal ausgewählt")
            return
        channel = self.client.get_channel(int(channel_id))
        if channel is None:
            self.set_status("Kanal nicht gefunden")
            return
        tt_str = self.tt_str
        details = [
            f"Name: {tt_str(channel.szName)}",
            f"ID: {int(channel.nChannelID)}",
            f"Pfad: {tt_str(self.client.get_channel_path(int(channel_id)))}",
            f"Topic: {tt_str(getattr(channel, 'szTopic', ''))}",
            f"Max. Benutzer: {int(getattr(channel, 'nMaxUsers', 0) or 0)}",
            f"Disk-Quota: {int(getattr(channel, 'nDiskQuota', 0) or 0) // (1024 * 1024)} MB",
        ]
        dlg = wx.MessageDialog(self, "\n".join(details), "Kanalinfo", wx.OK | wx.ICON_INFORMATION)
        dlg.ShowModal()
        dlg.Destroy()

    def on_menu_channel_info_speak(self, _event):
        if not self._require_connected("Kanalinfo vorlesen"):
            return
        channel_id = self._get_selected_channel_id()
        if not channel_id:
            self.set_status("Kein Kanal ausgewählt")
            return
        channel = self.client.get_channel(int(channel_id))
        if channel is None:
            self.set_status("Kanal nicht gefunden")
            return
        tt_str = self.tt_str
        text = (
            f"Kanal {tt_str(channel.szName)}, "
            f"Maximal {int(getattr(channel, 'nMaxUsers', 0) or 0)} Benutzer, "
            f"Diskquota {int(getattr(channel, 'nDiskQuota', 0) or 0) // (1024 * 1024)} MB."
        )
        self.tts.speak(text, kind="system")

    def on_menu_channel_stats_speak(self, _event):
        if not self._require_connected("Kanalstatistik vorlesen"):
            return
        channel_id = self._get_selected_channel_id()
        if not channel_id:
            self.set_status("Kein Kanal ausgewählt")
            return
        users = list(self.client.get_channel_users(int(channel_id)))
        count = len(users)
        self.tts.speak(f"{count} Benutzer im Kanal.", kind="system")

    def on_menu_channel_state_speak(self, _event):
        if not self._require_connected("Kanalzustand vorlesen"):
            return
        channel_id = self._get_selected_channel_id() or self.client.get_my_channel_id()
        if not channel_id:
            self.set_status("Kein Kanal ausgewählt")
            return
        tt = self.client.tt
        users = list(self.client.get_channel_users(int(channel_id)))
        transmitting = []
        for u in users:
            state = int(getattr(u, "uUserState", 0) or 0)
            voice_active = bool(state & tt.UserState.USERSTATE_VOICE)
            media_active = bool(state & tt.UserState.USERSTATE_MEDIAFILE_AUDIO) if hasattr(tt.UserState, "USERSTATE_MEDIAFILE_AUDIO") else False
            if voice_active or media_active:
                nick = self.tt_str(getattr(u, "szNickname", "")) or self.tt_str(getattr(u, "szUsername", "")) or f"Benutzer {u.nUserID}"
                suffix = ""
                if voice_active and media_active:
                    suffix = " (Sprache + Medien)"
                elif media_active:
                    suffix = " (Medien)"
                transmitting.append(nick + suffix)
        if transmitting:
            text = "Sendet gerade: " + ", ".join(transmitting) + "."
        else:
            text = "Niemand sendet gerade."
        self.tts.speak(text, kind="system")
        self.set_status(text)

    def on_menu_channel_tt_url(self, _event):
        if not self._require_connected("TT-URL für Kanal"):
            return
        profile = self.connection_tab.profile_from_form()
        if not profile:
            return
        channel_id = self._get_selected_channel_id()
        channel_path = None
        if channel_id:
            try:
                channel_path = self.tt_str(self.client.get_channel_path(int(channel_id)))
            except Exception:
                channel_path = None
        from ui.tt_file_parser import build_teamtalk_url
        url = build_teamtalk_url(profile, channel_path=channel_path or None)
        if wx.TheClipboard.Open():
            wx.TheClipboard.SetData(wx.TextDataObject(url))
            wx.TheClipboard.Close()
            self.set_status("TT-URL kopiert")
        else:
            self.set_status("Zwischenablage konnte nicht geöffnet werden")

    def on_menu_channel_note(self, _event) -> None:
        """Öffnet einen Dialog zum Bearbeiten der lokalen Notiz für den aktuellen Kanal."""
        channel_id = self._get_selected_channel_id()
        if not channel_id:
            self.set_status("Kein Kanal ausgewählt")
            return
        server_key = self._current_server_key or ""
        # Kanalname für Titel
        ch_name = ""
        try:
            ch = self.client.get_channel(int(channel_id))
            if ch:
                ch_name = self.tt_str(ch.szName)
        except Exception:
            pass
        title = f"Notiz: {ch_name}" if ch_name else "Kanal-Notiz"
        current_note = self._channel_notes.get(server_key, int(channel_id))

        dlg = wx.Dialog(self, title=title, style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        dlg.SetMinSize((520, 320))
        accel = wx.AcceleratorTable([(wx.ACCEL_CMD, ord("W"), wx.ID_CLOSE)])
        dlg.SetAcceleratorTable(accel)
        dlg.Bind(wx.EVT_MENU, lambda e: dlg.EndModal(wx.ID_CANCEL), id=wx.ID_CLOSE)

        root = wx.BoxSizer(wx.VERTICAL)
        lbl = wx.StaticText(dlg, label="Notiz (lokal, nur auf diesem Gerät gespeichert):")
        root.Add(lbl, 0, wx.ALL, 8)
        text_ctrl = wx.TextCtrl(dlg, value=current_note, style=wx.TE_MULTILINE)
        text_ctrl.SetName("Kanal-Notiz")
        text_ctrl.SetMinSize((-1, 160))
        root.Add(text_ctrl, 1, wx.LEFT | wx.RIGHT | wx.EXPAND, 8)

        btn_sizer = wx.StdDialogButtonSizer()
        ok_btn = wx.Button(dlg, wx.ID_OK, "Speichern")
        cancel_btn = wx.Button(dlg, wx.ID_CANCEL, "Abbrechen")
        btn_sizer.AddButton(ok_btn)
        btn_sizer.AddButton(cancel_btn)
        btn_sizer.Realize()
        root.Add(btn_sizer, 0, wx.ALL | wx.ALIGN_RIGHT, 8)

        dlg.SetSizer(root)
        dlg.CentreOnParent()
        if dlg.ShowModal() == wx.ID_OK:
            self._channel_notes.set(server_key, int(channel_id), text_ctrl.GetValue())
            self.set_status("Kanal-Notiz gespeichert")
        dlg.Destroy()

    def on_menu_channel_bans(self, _event):
        if not self._require_connected("Sperren im Kanal anzeigen"):
            return
        channel_id = self._get_selected_channel_id()
        if not channel_id:
            self.set_status("Kein Kanal ausgewählt")
            return
        dlg = BanListDialog(self, self, "Sperren im Kanal")
        self.ban_dialog = dlg
        dlg.clear()

        def worker():
            try:
                self.client.do_list_bans(int(channel_id))
            except Exception as exc:
                wx.CallAfter(self.set_status, f"Sperren laden fehlgeschlagen: {exc}")

        threading.Thread(target=worker, daemon=True).start()
        dlg.ShowModal()
        dlg.Destroy()
        self.ban_dialog = None

    def on_menu_channel_message(self, _event):
        if not self._require_connected("Kanalnachricht senden"):
            return
        chan_id = self.client.get_my_channel_id() or self._get_selected_channel_id()
        if not chan_id:
            self.set_status("Kein Kanal ausgewählt")
            return
        msg = self._ask_text("Kanalnachricht", "Nachricht:")
        if not msg:
            return
        if self.client.send_channel_message(int(chan_id), msg):
            self.chat_tab.append_chat(f"Ich: {msg}", kind="own")
        else:
            self.set_status("Senden fehlgeschlagen")

    def on_menu_channel_recent_dialog(self, _event) -> None:
        """Zeigt den Kanalverlauf (zuletzt besuchte Kanäle) als Dialog."""
        s = self.settings_store.settings
        channels = list(getattr(s, "recent_channels", []) or [])
        dlg = wx.Dialog(self, title="Kanalverlauf", style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        dlg.SetMinSize((560, 380))
        accel = wx.AcceleratorTable([(wx.ACCEL_CMD, ord("W"), wx.ID_CLOSE)])
        dlg.SetAcceleratorTable(accel)
        dlg.Bind(wx.EVT_MENU, lambda e: dlg.EndModal(wx.ID_CANCEL), id=wx.ID_CLOSE)

        root = wx.BoxSizer(wx.VERTICAL)
        if not channels:
            root.Add(wx.StaticText(dlg, label="Noch keine Kanäle besucht."), 0, wx.ALL, 16)
        else:
            lbl = wx.StaticText(dlg, label=f"{len(channels)} zuletzt besuchte Kanal/Kanäle:")
            root.Add(lbl, 0, wx.ALL, 8)
            lb = wx.ListBox(dlg)
            lb.SetName("Kanalverlauf Liste")
            from ui.a11y import setup_list_accessible
            setup_list_accessible(lb)
            for entry in channels:
                name = entry.get("name", "") or str(entry.get("channel_id", "?"))
                server = entry.get("server_key", "")
                label = f"{name}  [{server}]" if server else name
                lb.Append(label)
            lb.SetMinSize((-1, 240))
            root.Add(lb, 1, wx.LEFT | wx.RIGHT | wx.EXPAND, 8)

            btn_row = wx.BoxSizer(wx.HORIZONTAL)
            join_btn = wx.Button(dlg, label="&Beitreten")
            join_btn.SetName("Kanal aus Verlauf beitreten")
            clear_btn = wx.Button(dlg, label="&Verlauf leeren")
            clear_btn.SetName("Kanalverlauf leeren")
            btn_row.Add(join_btn, 0, wx.RIGHT, 8)
            btn_row.Add(clear_btn, 0)
            root.Add(btn_row, 0, wx.ALL, 8)

            def _on_join(_e):
                idx = lb.GetSelection()
                if idx == wx.NOT_FOUND or idx >= len(channels):
                    return
                entry = channels[idx]
                ch_id = entry.get("channel_id")
                if ch_id and self.client.is_connected():
                    dlg.EndModal(wx.ID_OK)
                    self.join_channel(int(ch_id))
                else:
                    self.set_status("Nicht verbunden oder keine Kanal-ID")

            def _on_clear(_e):
                confirm = wx.MessageDialog(
                    dlg, "Kanalverlauf wirklich leeren?",
                    "Verlauf leeren", wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION,
                )
                if confirm.ShowModal() == wx.ID_YES:
                    self.settings_store.settings.recent_channels = []
                    self.settings_store.save()
                    lb.Clear()
                    channels.clear()
                confirm.Destroy()

            join_btn.Bind(wx.EVT_BUTTON, _on_join)
            clear_btn.Bind(wx.EVT_BUTTON, _on_clear)
            lb.Bind(wx.EVT_LISTBOX_DCLICK, _on_join)

        btn_sizer = wx.StdDialogButtonSizer()
        ok_btn = wx.Button(dlg, wx.ID_OK)
        btn_sizer.AddButton(ok_btn)
        btn_sizer.Realize()
        root.Add(btn_sizer, 0, wx.ALL | wx.ALIGN_RIGHT, 8)

        dlg.SetSizer(root)
        dlg.CentreOnParent()
        dlg.ShowModal()
        dlg.Destroy()

    def on_menu_channel_view_messages(self, _event):
        if not self._channel_message_log:
            dlg = wx.MessageDialog(self, "Keine Kanalnachrichten gespeichert.", "Kanalnachrichten", wx.OK | wx.ICON_INFORMATION)
            dlg.ShowModal()
            dlg.Destroy()
            return
        dlg = wx.Dialog(self, title="Kanalnachrichten", style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        dlg.SetMinSize((640, 420))
        accel = wx.AcceleratorTable([(wx.ACCEL_CMD, ord("W"), wx.ID_CLOSE)])
        dlg.SetAcceleratorTable(accel)
        dlg.Bind(wx.EVT_MENU, lambda e: dlg.EndModal(wx.ID_CANCEL), id=wx.ID_CLOSE)
        root = wx.BoxSizer(wx.VERTICAL)
        text = wx.TextCtrl(dlg, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2)
        text.SetValue("\n".join(self._channel_message_log))
        root.Add(text, 1, wx.ALL | wx.EXPAND, 10)
        btns = wx.BoxSizer(wx.HORIZONTAL)
        clear_btn = wx.Button(dlg, label="Leeren")
        ok_btn = wx.Button(dlg, id=wx.ID_OK, label="OK")
        btns.Add(clear_btn, 0, wx.RIGHT, 8)
        btns.Add(ok_btn, 0)
        root.Add(btns, 0, wx.ALL | wx.ALIGN_RIGHT, 8)

        def on_clear(_evt):
            self._channel_message_log.clear()
            text.SetValue("")

        clear_btn.Bind(wx.EVT_BUTTON, on_clear)
        dlg.SetSizerAndFit(root)
        dlg.ShowModal()
        dlg.Destroy()

    def on_menu_channel_file_upload(self, _event):
        if not self._require_connected("Datei hochladen"):
            return
        tab = self._open_files_tab()
        if tab is None:
            return
        tab.on_upload(None)

    def on_menu_channel_file_download(self, _event):
        if not self._require_connected("Datei herunterladen"):
            return
        tab = self._open_files_tab()
        if tab is None:
            return
        tab.on_download(None)

    def on_menu_channel_file_delete(self, _event):
        if not self._require_connected("Datei löschen"):
            return
        tab = self._open_files_tab()
        if tab is None:
            return
        tab.on_delete(None)

    def on_menu_channel_file_refresh(self, _event):
        if not self._require_connected("Dateiliste aktualisieren"):
            return
        tab = self._open_files_tab()
        if tab is None:
            return
        tab.on_refresh(None)

    def on_menu_channel_stream_mode(self, mode_idx: int, _event):
        if not self._require_connected("Streaming"):
            return
        self._open_media_tab(mode_idx)

    def on_menu_user_info(self, _event):
        if not self._require_connected("Benutzerinfo"):
            return
        user = self._get_selected_user()
        if not user:
            self.set_status("Kein Benutzer ausgewählt")
            return
        details = [
            f"Nickname: {self.tt_str(user.szNickname)}",
            f"Benutzername: {self.tt_str(user.szUsername)}",
            f"ID: {int(user.nUserID)}",
            f"Kanal: {int(user.nChannelID)}",
            f"Status: {int(user.nStatusMode)}",
        ]
        dlg = wx.MessageDialog(self, "\n".join(details), "Benutzerinfo", wx.OK | wx.ICON_INFORMATION)
        dlg.ShowModal()
        dlg.Destroy()

    def on_menu_user_message(self, _event):
        if not self._require_connected("Private Nachricht"):
            return
        user = self._get_selected_user()
        if not user:
            self.set_status("Kein Benutzer ausgewählt")
            return
        nick = self.tt_str(getattr(user, "szNickname", "")) or self.tt_str(getattr(user, "szUsername", "")) or "Benutzer"
        msg = self._ask_text("Private Nachricht", f"Nachricht an {nick}:")
        if not msg:
            return
        if self.client.send_user_message(int(user.nUserID), msg):
            self.chat_tab.append_chat(f"An {nick}: {msg}", kind="own")
        else:
            self.set_status("Nachricht konnte nicht gesendet werden")

    def on_menu_store_move_target(self, _event):
        if not self._require_connected("Zielkanal merken"):
            return
        channel_id = self._get_selected_channel_id()
        if not channel_id:
            self.set_status("Kein Kanal ausgewählt")
            return
        self._move_target_channel_id = int(channel_id)
        channel = self.client.get_channel(int(channel_id))
        name = self.tt_str(getattr(channel, "szName", "")) if channel else str(channel_id)
        self.set_status(f"Zielkanal gespeichert: {name}")

    def on_menu_move_to_target(self, _event):
        if not self._require_connected("In Zielkanal verschieben"):
            return
        user = self._get_selected_user()
        if not user:
            self.set_status("Kein Benutzer ausgewählt")
            return
        if not self._move_target_channel_id:
            self.set_status("Kein Zielkanal gespeichert")
            return
        cmdid = self.client.do_move_user(int(user.nUserID), int(self._move_target_channel_id))
        if cmdid < 0:
            self.set_status("Benutzer verschieben fehlgeschlagen")
        else:
            self.set_status("Benutzer verschoben")
    def on_menu_user_info_speak(self, _event):
        if not self._require_connected("Benutzerinfo vorlesen"):
            return
        user = self._get_selected_user()
        if not user:
            self.set_status("Kein Benutzer ausgewählt")
            return
        nickname = self.tt_str(user.szNickname) or self.tt_str(user.szUsername) or "Benutzer"
        channel_id = int(getattr(user, "nChannelID", 0) or 0)
        channel_name = ""
        if channel_id:
            channel = self.client.get_channel(channel_id)
            if channel is not None:
                channel_name = self.tt_str(channel.szName)
        text = f"{nickname} in Kanal {channel_name or channel_id}."
        self.tts.speak(text, kind="system")

    def on_menu_user_mute(self, _event):
        # Compat-Wrapper: stummschaltet Sprache (wird noch von altem Code genutzt)
        self.on_menu_user_mute_voice(_event)

    def on_menu_user_mute_voice(self, _event):
        if not self._require_connected("Sprache stummschalten"):
            return
        user = self._get_selected_user()
        if not user:
            self.set_status("Kein Benutzer ausgewählt")
            return
        tt = self.client.tt
        muted = bool(user.uUserState & tt.UserState.USERSTATE_MUTE_VOICE)
        self.client.set_user_mute(int(user.nUserID), int(tt.StreamType.STREAMTYPE_VOICE), not muted)
        self.set_status("Sprache stummgeschaltet" if not muted else "Sprache entstummt")

    def on_menu_user_mute_media(self, _event):
        if not self._require_connected("Mediendatei stummschalten"):
            return
        user = self._get_selected_user()
        if not user:
            self.set_status("Kein Benutzer ausgewählt")
            return
        tt = self.client.tt
        muted = bool(user.uUserState & tt.UserState.USERSTATE_MUTE_MEDIAFILE)
        self.client.set_user_mute(int(user.nUserID), int(tt.StreamType.STREAMTYPE_MEDIAFILE_AUDIO), not muted)
        self.set_status("Mediendatei stummgeschaltet" if not muted else "Mediendatei entstummt")

    def on_menu_user_mute_all(self, _event):
        self._mute_all = not self._mute_all
        self.client.set_sound_output_mute(self._mute_all)
        self.set_status("Ausgabe stummgeschaltet" if self._mute_all else "Ausgabe aktiv")

    def on_menu_user_relay_voice(self, _event):
        if not self._require_connected("Sprachstream weiterleiten"):
            return
        user = self._get_selected_user()
        if not user:
            self.set_status("Kein Benutzer ausgewählt")
            return
        tt = self.client.tt
        # Intercept-Abonnement toggeln: weiterleiten = SUBSCRIBE_INTERCEPT_VOICE aktivieren
        current = int(getattr(user, "uLocalSubscriptions", 0) or 0)
        flag = int(tt.Subscription.SUBSCRIBE_INTERCEPT_VOICE)
        if current & flag:
            self.client.do_unsubscribe(int(user.nUserID), flag)
            self.set_status("Sprachstream-Weiterleitung deaktiviert")
        else:
            self.client.do_subscribe(int(user.nUserID), flag)
            self.set_status("Sprachstream wird weitergeleitet")

    def on_menu_user_relay_media(self, _event):
        if not self._require_connected("Medienstream weiterleiten"):
            return
        user = self._get_selected_user()
        if not user:
            self.set_status("Kein Benutzer ausgewählt")
            return
        tt = self.client.tt
        current = int(getattr(user, "uLocalSubscriptions", 0) or 0)
        flag = int(tt.Subscription.SUBSCRIBE_INTERCEPT_MEDIAFILE)
        if current & flag:
            self.client.do_unsubscribe(int(user.nUserID), flag)
            self.set_status("Medienstream-Weiterleitung deaktiviert")
        else:
            self.client.do_subscribe(int(user.nUserID), flag)
            self.set_status("Medienstream wird weitergeleitet")

    def on_menu_user_volume(self, _event):
        if not self._require_connected("Benutzerlautstärke"):
            return
        user = self._get_selected_user()
        if not user:
            self.set_status("Kein Benutzer ausgewählt")
            return
        current = self._get_user_volume_level(int(user.nUserID))
        dlg = wx.NumberEntryDialog(self, "Lautstärke (0–32000)", "Lautstärke:", "Benutzerlautstärke", current, 0, 32000)
        accel = wx.AcceleratorTable([(wx.ACCEL_CMD, ord("W"), wx.ID_CLOSE)])
        dlg.SetAcceleratorTable(accel)
        dlg.Bind(wx.EVT_MENU, lambda e: dlg.EndModal(wx.ID_CANCEL), id=wx.ID_CLOSE)
        if dlg.ShowModal() == wx.ID_OK:
            vol = dlg.GetValue()
            vol = self._set_user_volume_level(int(user.nUserID), int(vol))
            self.set_status(f"Lautstärke auf {vol} gesetzt")
        dlg.Destroy()

    def on_menu_user_volume_up(self, _event):
        if not self._require_connected("Benutzer lauter"):
            return
        user = self._get_selected_user()
        if not user:
            self.set_status("Kein Benutzer ausgewählt")
            return
        current = self._get_user_volume_level(int(user.nUserID))
        new_level = self._set_user_volume_level(int(user.nUserID), current + 1000)
        self.set_status(f"Lautstärke: {new_level}")

    def on_menu_user_volume_down(self, _event):
        if not self._require_connected("Benutzer leiser"):
            return
        user = self._get_selected_user()
        if not user:
            self.set_status("Kein Benutzer ausgewählt")
            return
        current = self._get_user_volume_level(int(user.nUserID))
        new_level = self._set_user_volume_level(int(user.nUserID), current - 1000)
        self.set_status(f"Lautstärke: {new_level}")

    def on_menu_user_operator(self, _event):
        if not self._require_connected("Operator geben/nehmen"):
            return
        user = self._get_selected_user()
        if not user:
            self.set_status("Kein Benutzer ausgewählt")
            return
        my_ch = self.client.get_my_channel_id()
        if not my_ch:
            self.set_status("Kein eigener Kanal")
            return
        is_op = self.client.is_channel_operator(int(my_ch), int(user.nUserID))
        self.client.do_channel_op(int(my_ch), int(user.nUserID), not is_op)
        self.set_status("Operator gesetzt" if not is_op else "Operator entzogen")

    def on_menu_user_kick(self, _event):
        if not self._require_connected("Benutzer kicken"):
            return
        user = self._get_selected_user()
        if not user:
            self.set_status("Kein Benutzer ausgewählt")
            return
        my_ch = self.client.get_my_channel_id()
        if not my_ch:
            self.set_status("Kein eigener Kanal")
            return
        dlg = wx.MessageDialog(self, "Benutzer wirklich kicken?", "Kicken", wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION)
        dlg.SetYesNoLabels("Ja", "Nein")
        if dlg.ShowModal() != wx.ID_YES:
            dlg.Destroy()
            return
        dlg.Destroy()
        self.client.do_kick_user(int(user.nUserID), int(my_ch))
        self.set_status("Benutzer gekickt")

    def on_menu_user_ban(self, _event):
        if not self._require_connected("Benutzer bannen"):
            return
        user = self._get_selected_user()
        if not user:
            self.set_status("Kein Benutzer ausgewählt")
            return
        ban_types = self._ask_ban_types(user)
        if ban_types is None:
            return
        self.client.do_ban_user_ex(int(user.nUserID), int(ban_types))
        self.set_status("Benutzer gebannt")

    def on_menu_user_kick_ban(self, _event):
        if not self._require_connected("Kicken + Bannen (Kanal)"):
            return
        user = self._get_selected_user()
        if not user:
            self.set_status("Kein Benutzer ausgewählt")
            return
        ban_types = self._ask_ban_types(user)
        if ban_types is None:
            return
        dlg = wx.MessageDialog(self, "Benutzer wirklich kicken und bannen?", "Kicken + Bannen", wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION)
        dlg.SetYesNoLabels("Ja", "Nein")
        if dlg.ShowModal() != wx.ID_YES:
            dlg.Destroy()
            return
        dlg.Destroy()
        self.client.do_ban_user_ex(int(user.nUserID), int(ban_types))
        channel_id = int(getattr(user, "nChannelID", 0) or 0)
        if channel_id:
            self.client.do_kick_user(int(user.nUserID), channel_id)
        self.set_status("Benutzer gekickt und gebannt")

    def on_menu_user_kick_server(self, _event):
        if not self._require_connected("Vom Server kicken"):
            return
        user = self._get_selected_user()
        if not user:
            self.set_status("Kein Benutzer ausgewählt")
            return
        dlg = wx.MessageDialog(self, "Benutzer wirklich vom Server kicken?", "Vom Server kicken", wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION)
        dlg.SetYesNoLabels("Ja", "Nein")
        if dlg.ShowModal() != wx.ID_YES:
            dlg.Destroy()
            return
        dlg.Destroy()
        # channel_id=0 bedeutet Server-Kick laut TeamTalk SDK
        self.client.do_kick_user(int(user.nUserID), 0)
        self.set_status("Benutzer vom Server gekickt")

    def on_menu_user_kick_ban_server(self, _event):
        if not self._require_connected("Vom Server kicken + Bannen"):
            return
        user = self._get_selected_user()
        if not user:
            self.set_status("Kein Benutzer ausgewählt")
            return
        ban_types = self._ask_ban_types(user)
        if ban_types is None:
            return
        dlg = wx.MessageDialog(self, "Benutzer wirklich vom Server kicken und bannen?", "Kicken + Bannen (Server)", wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION)
        dlg.SetYesNoLabels("Ja", "Nein")
        if dlg.ShowModal() != wx.ID_YES:
            dlg.Destroy()
            return
        dlg.Destroy()
        self.client.do_ban_user_ex(int(user.nUserID), int(ban_types))
        self.client.do_kick_user(int(user.nUserID), 0)
        self.set_status("Benutzer vom Server gekickt und gebannt")

    def on_menu_user_tx_toggle(self, kind: str, _event):
        if not self._require_connected("Sendekontrolle"):
            return
        user = self._get_selected_user()
        if not user:
            self.set_status("Kein Benutzer ausgewählt")
            return
        my_ch = self.client.get_my_channel_id()
        if not my_ch:
            self.set_status("Nicht in einem Kanal")
            return
        tt = self.client.tt
        stream_map = {
            "voice":   int(tt.StreamType.STREAMTYPE_VOICE),
            "video":   int(tt.StreamType.STREAMTYPE_VIDEOCAPTURE),
            "desktop": int(tt.StreamType.STREAMTYPE_DESKTOP),
            "media":   int(tt.StreamType.STREAMTYPE_MEDIAFILE_AUDIO),
            "msg":     int(tt.StreamType.STREAMTYPE_CHANNELMSG) if hasattr(tt.StreamType, "STREAMTYPE_CHANNELMSG") else 0,
        }
        stream_type = stream_map.get(kind, 0)
        if not stream_type:
            self.set_status("Unbekannter Stream-Typ")
            return
        self.client.do_channel_user_transmit(int(user.nUserID), int(my_ch), stream_type)
        self.set_status(f"Sendekontrolle ({kind}) umgeschaltet")

    def on_menu_user_position(self, _event):
        if not self._require_connected("Benutzer positionieren"):
            return
        user = self._get_selected_user()
        if not user:
            self.set_status("Kein Benutzer ausgewählt")
            return
        tt = self.client.tt
        choices = [
            ("Sprache", int(tt.StreamType.STREAMTYPE_VOICE)),
        ]
        media_st = getattr(tt.StreamType, "STREAMTYPE_MEDIAFILE", None)
        if media_st is None:
            media_st = getattr(tt.StreamType, "STREAMTYPE_MEDIAFILE_AUDIO", None)
        if media_st is not None:
            choices.append(("Mediendatei", int(media_st)))
        choices.append(("Sprache + Medien", 0))
        dlg = wx.Dialog(self, title="Benutzer positionieren", style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        accel = wx.AcceleratorTable([(wx.ACCEL_CMD, ord("W"), wx.ID_CLOSE)])
        dlg.SetAcceleratorTable(accel)
        dlg.Bind(wx.EVT_MENU, lambda e: dlg.EndModal(wx.ID_CANCEL), id=wx.ID_CLOSE)
        root = wx.BoxSizer(wx.VERTICAL)
        root.Add(wx.StaticText(dlg, label="Stream-Typ:"), 0, wx.ALL, 6)
        choice = wx.Choice(dlg, choices=[label for label, _ in choices])
        choice.SetSelection(0)
        root.Add(choice, 0, wx.ALL | wx.EXPAND, 6)
        grid = wx.FlexGridSizer(3, 2, 8, 12)
        grid.AddGrowableCol(1, 1)
        x_ctrl = wx.SpinCtrlDouble(dlg, min=-1000.0, max=1000.0, inc=0.1, initial=0.0)
        y_ctrl = wx.SpinCtrlDouble(dlg, min=-1000.0, max=1000.0, inc=0.1, initial=0.0)
        z_ctrl = wx.SpinCtrlDouble(dlg, min=-1000.0, max=1000.0, inc=0.1, initial=0.0)
        grid.Add(wx.StaticText(dlg, label="X:"), 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(x_ctrl, 1, wx.EXPAND)
        grid.Add(wx.StaticText(dlg, label="Y:"), 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(y_ctrl, 1, wx.EXPAND)
        grid.Add(wx.StaticText(dlg, label="Z:"), 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(z_ctrl, 1, wx.EXPAND)
        root.Add(grid, 0, wx.ALL | wx.EXPAND, 6)
        btns = dlg.CreateButtonSizer(wx.OK | wx.CANCEL)
        root.Add(btns, 0, wx.ALL | wx.ALIGN_RIGHT, 8)
        dlg.SetSizerAndFit(root)
        if dlg.ShowModal() == wx.ID_OK:
            idx = choice.GetSelection()
            stream_type = choices[idx][1] if 0 <= idx < len(choices) else 0
            x = float(x_ctrl.GetValue())
            y = float(y_ctrl.GetValue())
            z = float(z_ctrl.GetValue())
            success = True
            if stream_type == 0:
                success = self.client.set_user_position(int(user.nUserID), int(tt.StreamType.STREAMTYPE_VOICE), x, y, z)
                if media_st is not None:
                    success = self.client.set_user_position(int(user.nUserID), int(media_st), x, y, z) and success
            else:
                success = self.client.set_user_position(int(user.nUserID), int(stream_type), x, y, z)
            if success:
                self.set_status("Position aktualisiert")
            else:
                self.set_status("Position setzen fehlgeschlagen")
        dlg.Destroy()

    def on_menu_user_allow_voice(self, _event):
        self._toggle_allow_stream_for_user("Sprache", self._stream_type_voice())

    def on_menu_user_allow_video(self, _event):
        self._toggle_allow_stream_for_user("Video", self._stream_type_video())

    def on_menu_user_allow_desktop(self, _event):
        self._toggle_allow_stream_for_user("Desktop", self._stream_type_desktop())

    def on_menu_user_allow_media(self, _event):
        self._toggle_allow_stream_for_user("Mediendatei", self._stream_type_media())

    def on_menu_user_allow_text(self, _event):
        self._toggle_allow_stream_for_user("Kanalnachricht", self._stream_type_channel_msg())

    def on_menu_user_allow_all_voice(self, _event):
        self._toggle_allow_stream_for_all("Alle Sprache", self._stream_type_voice())

    def on_menu_user_allow_all_video(self, _event):
        self._toggle_allow_stream_for_all("Alle Video", self._stream_type_video())

    def on_menu_user_allow_all_desktop(self, _event):
        self._toggle_allow_stream_for_all("Alle Desktop", self._stream_type_desktop())

    def on_menu_user_allow_all_media(self, _event):
        self._toggle_allow_stream_for_all("Alle Mediendatei", self._stream_type_media())

    def on_menu_user_allow_all_text(self, _event):
        self._toggle_allow_stream_for_all("Alle Kanalnachrichten", self._stream_type_channel_msg())

    def on_menu_user_subscriptions(self, _event):
        if not self._require_connected("Abonnements"):
            return
        user = self._get_selected_user()
        if not user:
            self.set_status("Kein Benutzer ausgewählt")
            return
        tt = self.client.tt
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
            ("Benutzerdefiniert abfangen", tt.Subscription.SUBSCRIBE_INTERCEPT_CUSTOM_MSG),
        ]
        dlg = wx.Dialog(self, title="Abonnements")
        accel = wx.AcceleratorTable([(wx.ACCEL_CMD, ord("W"), wx.ID_CLOSE)])
        dlg.SetAcceleratorTable(accel)
        dlg.Bind(wx.EVT_MENU, lambda e: dlg.EndModal(wx.ID_CANCEL), id=wx.ID_CLOSE)
        root = wx.BoxSizer(wx.VERTICAL)
        checks = []
        current = int(getattr(user, "uLocalSubscriptions", 0) or 0)
        for label, flag in flags:
            cb = wx.CheckBox(dlg, label=label)
            cb.SetValue(bool(current & int(flag)))
            checks.append((cb, int(flag)))
            root.Add(cb, 0, wx.ALL, 4)
        btns = dlg.CreateButtonSizer(wx.OK | wx.CANCEL)
        root.Add(btns, 0, wx.ALL | wx.ALIGN_RIGHT, 8)
        dlg.SetSizerAndFit(root)
        if dlg.ShowModal() == wx.ID_OK:
            for cb, flag in checks:
                want = cb.GetValue()
                have = bool(current & flag)
                if want and not have:
                    self.client.do_subscribe(int(user.nUserID), flag)
                if not want and have:
                    self.client.do_unsubscribe(int(user.nUserID), flag)
            self.set_status("Abonnements geändert")
        dlg.Destroy()

    def on_menu_user_move(self, _event):
        if not self._require_connected("Benutzer verschieben"):
            return
        user = self._get_selected_user()
        if not user:
            self.set_status("Kein Benutzer ausgewählt")
            return
        channels = list(self.client.get_server_channels())
        if not channels:
            self.set_status("Keine Kanäle gefunden")
            return
        options = []
        ids = []
        for ch in channels:
            cid = int(ch.nChannelID)
            path = ""
            try:
                path = self.tt_str(self.client.get_channel_path(cid))
            except Exception:
                path = ""
            label = path or self.tt_str(ch.szName) or f"Kanal {cid}"
            options.append(label)
            ids.append(cid)
        dlg = wx.SingleChoiceDialog(self, "Zielkanal wählen", "Benutzer verschieben", options)
        if dlg.ShowModal() != wx.ID_OK:
            dlg.Destroy()
            return
        idx = dlg.GetSelection()
        dlg.Destroy()
        if idx == wx.NOT_FOUND:
            return
        target_id = ids[idx]
        self.client.do_move_user(int(user.nUserID), int(target_id))
        self.set_status("Benutzer verschoben")

    def on_menu_user_allow_desktop_access(self, _event):
        if not self._require_connected("Desktop-Zugriff"):
            return
        user = self._get_selected_user()
        if not user:
            self.set_status("Kein Benutzer ausgewählt")
            return
        tt = self.client.tt
        current = int(getattr(user, "uLocalSubscriptions", 0) or 0)
        flag = int(tt.Subscription.SUBSCRIBE_DESKTOPINPUT)
        if current & flag:
            self.client.do_unsubscribe(int(user.nUserID), flag)
            self.set_status("Desktop-Zugriff entzogen")
        else:
            self.client.do_subscribe(int(user.nUserID), flag)
            self.set_status("Desktop-Zugriff erlaubt")

    def _stream_type_voice(self) -> int:
        return int(self.client.tt.StreamType.STREAMTYPE_VOICE)

    def _stream_type_video(self) -> int:
        return int(self.client.tt.StreamType.STREAMTYPE_VIDEOCAPTURE)

    def _stream_type_desktop(self) -> int:
        return int(self.client.tt.StreamType.STREAMTYPE_DESKTOP)

    def _stream_type_media(self) -> int:
        tt = self.client.tt
        st = getattr(tt.StreamType, "STREAMTYPE_MEDIAFILE", None)
        if st is None:
            st = getattr(tt.StreamType, "STREAMTYPE_MEDIAFILE_AUDIO", None)
        return int(st or 0)

    def _stream_type_channel_msg(self) -> int:
        tt = self.client.tt
        st = getattr(tt.StreamType, "STREAMTYPE_CHANNELMSG", None)
        return int(st or 0)

    def _is_classroom_channel(self, channel) -> bool:
        try:
            return bool(int(channel.uChannelType or 0) & int(self.client.tt.ChannelType.CHANNEL_CLASSROOM))
        except Exception:
            return False

    def _can_modify_channel(self, channel_id: int) -> bool:
        try:
            rights = int(self.client.get_my_user_rights() or 0)
        except Exception:
            rights = 0
        if rights & int(self.client.tt.UserRight.USERRIGHT_MODIFY_CHANNELS):
            return True
        my_id = int(self.client.get_my_user_id() or 0)
        if my_id and self.client.is_channel_operator(int(channel_id), int(my_id)):
            return True
        return False

    def _get_transmit_users_map(self, channel) -> Dict[int, int]:
        transmit: Dict[int, int] = {}
        arr = getattr(channel, "transmitUsers", None)
        if arr is None:
            return transmit
        for i in range(TT_TRANSMITUSERS_MAX):
            try:
                uid = int(arr[i][TT_TRANSMITUSERS_USERID_INDEX])
                st = int(arr[i][TT_TRANSMITUSERS_STREAMTYPE_INDEX])
            except Exception:
                try:
                    base = i * 2
                    uid = int(arr[base])
                    st = int(arr[base + 1])
                except Exception:
                    break
            if uid == 0:
                break
            transmit[uid] = st
        return transmit

    def _set_transmit_user_entry(self, channel, idx: int, user_id: int, stream_type: int) -> bool:
        try:
            channel.transmitUsers[idx][TT_TRANSMITUSERS_USERID_INDEX] = int(user_id)
            channel.transmitUsers[idx][TT_TRANSMITUSERS_STREAMTYPE_INDEX] = int(stream_type)
            return True
        except Exception:
            try:
                base = idx * 2
                channel.transmitUsers[base] = int(user_id)
                channel.transmitUsers[base + 1] = int(stream_type)
                return True
            except Exception:
                return False

    def _set_transmit_users_from_map(self, channel, transmit: Dict[int, int]) -> bool:
        items = sorted(transmit.items(), key=lambda kv: kv[0])
        if len(items) > TT_TRANSMITUSERS_MAX:
            self.set_status(f"Max. {TT_TRANSMITUSERS_MAX} Benutzer erlauben")
            return False
        for i in range(TT_TRANSMITUSERS_MAX):
            if i < len(items):
                uid, st = items[i]
                if not self._set_transmit_user_entry(channel, i, uid, st):
                    return False
            else:
                if not self._set_transmit_user_entry(channel, i, 0, 0):
                    return False
        return True

    def _toggle_allow_stream(self, label: str, user_id: int, stream_type: int, require_user: bool = True) -> None:
        if not self._require_connected("Uebertragung erlauben"):
            return
        if stream_type == 0:
            self.set_status("Stream-Typ nicht verfügbar")
            return
        user = self._get_selected_user() if require_user else None
        if require_user and not user:
            self.set_status("Kein Benutzer ausgewählt")
            return
        channel_id = 0
        if user is not None:
            channel_id = int(getattr(user, "nChannelID", 0) or 0)
        if not channel_id:
            channel_id = int(self.client.get_my_channel_id() or 0) or int(self._get_selected_channel_id() or 0)
        if not channel_id:
            self.set_status("Kein Kanal ausgewählt")
            return
        channel = self.client.get_channel(int(channel_id))
        if not channel:
            self.set_status("Kanal nicht gefunden")
            return
        if not self._is_classroom_channel(channel):
            self.set_status("Nur in Klassenzimmer-Kanälen verfügbar")
            return
        if not self._can_modify_channel(int(channel_id)):
            self.set_status("Keine Rechte für Uebertragung erlauben")
            return
        transmit = self._get_transmit_users_map(channel)
        current = int(transmit.get(user_id, 0))
        allowed = bool(current & stream_type)
        if allowed:
            new_val = current & ~stream_type
        else:
            new_val = current | stream_type
        if new_val:
            transmit[user_id] = new_val
        else:
            transmit.pop(user_id, None)
        if not self._set_transmit_users_from_map(channel, transmit):
            return
        result = self.client.update_channel(channel)
        if result.ok:
            state = "erlaubt" if not allowed else "entzogen"
            self.set_status(f"{label} {state}")
        else:
            self.set_status(result.message)

    def _toggle_allow_stream_for_user(self, label: str, stream_type: int) -> None:
        user = self._get_selected_user()
        if not user:
            self.set_status("Kein Benutzer ausgewählt")
            return
        self._toggle_allow_stream(label, int(user.nUserID), stream_type, require_user=True)

    def _toggle_allow_stream_for_all(self, label: str, stream_type: int) -> None:
        self._toggle_allow_stream(label, TT_TRANSMITUSERS_FREEFORALL, stream_type, require_user=False)

    def on_menu_audio_settings(self, _event):
        if not self.settings_window.IsShown():
            self.settings_window.Show()
        self.settings_window.Raise()
        self.settings_tab.show_section("Audio & Aufnahme")
        wx.CallAfter(self.settings_tab.section_choice.SetFocus)

    def on_sound_menu_open(self, event):
        menu = event.GetMenu()
        if menu is self._sound_input_menu:
            self._populate_sound_device_menu(menu, kind="input")
        elif menu is self._sound_output_menu:
            self._populate_sound_device_menu(menu, kind="output")
        event.Skip()

    def _populate_sound_device_menu(self, menu: wx.Menu, kind: str) -> None:
        while menu.GetMenuItemCount() > 0:
            menu.DestroyItem(menu.FindItemByPosition(0))
        self._sound_menu_device_map.clear()
        try:
            self.audio_tab.refresh_audio_devices(
                announce=False, prefer_previous=True, auto_apply=False, restart_sound=False
            )
        except Exception:
            pass
        devices = self.audio_tab._input_devices if kind == "input" else self.audio_tab._output_devices
        choice = self.audio_tab.input_device if kind == "input" else self.audio_tab.output_device
        current_idx = choice.GetSelection()
        current_id = None
        if 0 <= current_idx < len(devices):
            current_id = int(devices[current_idx].nDeviceID)
        if not devices:
            item = menu.Append(wx.ID_ANY, "Keine Geräte")
            item.Enable(False)
            return
        for dev in devices:
            name = self.tt_str(getattr(dev, "szDeviceName", "")) or "Unbekannt"
            item = menu.AppendRadioItem(wx.ID_ANY, name)
            dev_id = int(dev.nDeviceID)
            if current_id is not None and dev_id == current_id:
                item.Check(True)
            self._sound_menu_device_map[item.GetId()] = (kind, dev_id)
            self.Bind(wx.EVT_MENU, self.on_sound_device_select, item)

    def on_sound_device_select(self, event):
        info = self._sound_menu_device_map.get(event.GetId())
        if not info:
            return
        kind, dev_id = info
        devices = self.audio_tab._input_devices if kind == "input" else self.audio_tab._output_devices
        choice = self.audio_tab.input_device if kind == "input" else self.audio_tab.output_device
        target_idx = None
        for idx, dev in enumerate(devices):
            if int(dev.nDeviceID) == int(dev_id):
                target_idx = idx
                break
        if target_idx is None:
            self.set_status("Gerät nicht gefunden")
            return
        choice.SetSelection(target_idx)
        self.audio_tab.on_apply_audio(None)
        label = "Eingabegerät" if kind == "input" else "Ausgabegerät"
        self.set_status(f"{label} gesetzt")

    def on_menu_audio_effect_toggle(self, flag: str, event):
        enabled = event.IsChecked()
        if flag == "agc":
            self.audio_tab.agc_check.SetValue(enabled)
            label = "AGC"
        elif flag == "denoise":
            self.audio_tab.denoise_check.SetValue(enabled)
            label = "Rauschunterdrückung"
        elif flag == "echo":
            self.audio_tab.echo_check.SetValue(enabled)
            label = "Echounterdrückung"
        else:
            return
        self.audio_tab.on_apply_effects(None)
        self.set_status(f"{label} {'an' if enabled else 'aus'}")

    def on_menu_audio_apply_effects(self, _event):
        self.audio_tab.on_apply_effects(None)

    def on_menu_audio_ptt(self, _event):
        at = self.audio_tab
        at.ptt_toggle.SetValue(not at.ptt_toggle.GetValue())
        at.on_ptt_toggle(None)

    def on_menu_audio_va(self, _event):
        enabled = not self.audio_tab.voice_activation.GetValue()
        self.audio_tab.voice_activation.SetValue(enabled)
        self.client.enable_voice_activation(enabled)
        if enabled and not self._ptt_enabled:
            self.client.enable_voice_transmission(True)
        if not enabled and not self._ptt_enabled:
            self.client.enable_voice_transmission(False)
        self.set_status("Sprachaktivierung an" if enabled else "Sprachaktivierung aus")

    def on_menu_audio_apply(self, _event):
        self.audio_tab.on_apply_audio(None)

    def on_menu_audio_refresh(self, _event):
        self.audio_tab.on_refresh_audio(None)

    def on_menu_video_settings(self, _event):
        if not self.settings_window.IsShown():
            self.settings_window.Show()
        self.settings_window.Raise()
        self.settings_tab.show_section("Video")
        wx.CallAfter(self.settings_tab.section_choice.SetFocus)

    def on_menu_video_refresh(self, _event):
        self.video_tab.refresh_devices()
        self.set_status("Video-Geräte aktualisiert")

    def on_menu_video_toggle(self, event):
        enabled = event.IsChecked()
        self._video_tx_enabled = bool(enabled)
        self.video_tab.set_transmission_enabled(enabled)

    def on_menu_audio_loopback(self, _event):
        at = self.audio_tab
        at.loopback_toggle.SetValue(not at.loopback_toggle.GetValue())
        at.on_loopback_toggle(None)

    def on_menu_audio_mute_all(self, event):
        enabled = event.IsChecked()
        self._mute_all = bool(enabled)
        self.client.set_sound_output_mute(enabled)
        self.set_status("Ausgabe stummgeschaltet" if enabled else "Ausgabe aktiv")

    def on_menu_eq_presets(self, _event):
        """v4.7.0 – Equalizer-Voreinstellungen mit Import/Export/Speichern."""
        s = self.settings_store.settings
        current_preset = getattr(s, "eq_active_preset", "Standard")
        eq_mgr = self._eq_presets
        all_presets = eq_mgr.all_presets

        dlg = wx.Dialog(self, title="Equalizer-Voreinstellungen",
                        style=wx.DEFAULT_DIALOG_STYLE)
        root = wx.BoxSizer(wx.VERTICAL)

        root.Add(wx.StaticText(dlg, label="Voreinstellung wählen:"), 0, wx.ALL, 8)
        preset_names = [p["name"] for p in all_presets]
        preset_choice = wx.Choice(dlg, choices=preset_names)
        preset_choice.SetName("Equalizer-Voreinstellung")
        if current_preset in preset_names:
            preset_choice.SetSelection(preset_names.index(current_preset))
        else:
            preset_choice.SetSelection(0)
        root.Add(preset_choice, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)

        # Custom adjustment sliders
        custom_box = wx.StaticBox(dlg, label="Manuelle Anpassung")
        custom_sizer = wx.StaticBoxSizer(custom_box, wx.VERTICAL)

        mic_row = wx.BoxSizer(wx.HORIZONTAL)
        mic_row.Add(wx.StaticText(dlg, label="Mikrofon-Gain (%):"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        mic_spin = wx.SpinCtrl(dlg, min=0, max=200, initial=int(getattr(s, "eq_mic_gain_pct", 50) or 50))
        mic_spin.SetName("Mikrofon-Gain Prozent")
        mic_row.Add(mic_spin, 0)
        custom_sizer.Add(mic_row, 0, wx.ALL, 8)

        out_row = wx.BoxSizer(wx.HORIZONTAL)
        out_row.Add(wx.StaticText(dlg, label="Ausgabe-Lautstärke (%):"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        out_spin = wx.SpinCtrl(dlg, min=0, max=200, initial=int(getattr(s, "eq_out_volume_pct", 100) or 100))
        out_spin.SetName("Ausgabe-Lautstärke Prozent")
        out_row.Add(out_spin, 0)
        custom_sizer.Add(out_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        root.Add(custom_sizer, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)

        def _on_preset_changed(_evt):
            idx = preset_choice.GetSelection()
            if 0 <= idx < len(all_presets):
                p = all_presets[idx]
                mic_spin.SetValue(p["mic_gain_pct"])
                out_spin.SetValue(p["out_volume_pct"])
        preset_choice.Bind(wx.EVT_CHOICE, _on_preset_changed)

        # v4.7.0 – Import/Export/Speichern-Buttons
        io_row = wx.BoxSizer(wx.HORIZONTAL)
        save_btn = wx.Button(dlg, label="&Speichern als…")
        save_btn.SetName("Preset speichern")
        import_btn = wx.Button(dlg, label="&Importieren…")
        import_btn.SetName("Presets importieren")
        export_btn = wx.Button(dlg, label="&Exportieren…")
        export_btn.SetName("Presets exportieren")
        io_row.Add(save_btn, 0, wx.RIGHT, 8)
        io_row.Add(import_btn, 0, wx.RIGHT, 8)
        io_row.Add(export_btn, 0)
        root.Add(io_row, 0, wx.LEFT | wx.BOTTOM, 8)

        def _save_preset(_evt):
            name = wx.GetTextFromUser("Preset-Name:", "Preset speichern", "Mein Preset", dlg)
            if name.strip():
                eq_mgr.add_or_update(name.strip(), mic_spin.GetValue(), out_spin.GetValue())
                self.set_status(f"EQ-Preset '{name}' gespeichert")
                # Auswahl aktualisieren
                new_presets = eq_mgr.all_presets
                preset_choice.Set([p["name"] for p in new_presets])
                all_presets.clear()
                all_presets.extend(new_presets)
                names2 = [p["name"] for p in new_presets]
                if name.strip() in names2:
                    preset_choice.SetSelection(names2.index(name.strip()))

        def _import_presets(_evt):
            with wx.FileDialog(dlg, "EQ-Presets importieren",
                               wildcard="JSON (*.json)|*.json|Alle|*.*",
                               style=wx.FD_OPEN) as fd:
                if fd.ShowModal() != wx.ID_OK:
                    return
                try:
                    count = eq_mgr.import_from_file(Path(fd.GetPath()))
                    self.set_status(f"{count} EQ-Preset(s) importiert")
                    new_presets = eq_mgr.all_presets
                    preset_choice.Set([p["name"] for p in new_presets])
                    all_presets.clear()
                    all_presets.extend(new_presets)
                except Exception as exc:
                    wx.MessageBox(f"Import fehlgeschlagen: {exc}", "Fehler", wx.OK | wx.ICON_ERROR, dlg)

        def _export_presets(_evt):
            with wx.FileDialog(dlg, "EQ-Presets exportieren",
                               wildcard="JSON (*.json)|*.json|Alle|*.*",
                               style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
                               defaultFile="eq_presets.json") as fd:
                if fd.ShowModal() != wx.ID_OK:
                    return
                try:
                    eq_mgr.export_to_file(Path(fd.GetPath()))
                    self.set_status("EQ-Presets exportiert")
                except Exception as exc:
                    wx.MessageBox(f"Export fehlgeschlagen: {exc}", "Fehler", wx.OK | wx.ICON_ERROR, dlg)

        save_btn.Bind(wx.EVT_BUTTON, _save_preset)
        import_btn.Bind(wx.EVT_BUTTON, _import_presets)
        export_btn.Bind(wx.EVT_BUTTON, _export_presets)

        btns = dlg.CreateButtonSizer(wx.OK | wx.CANCEL)
        root.Add(btns, 0, wx.ALL | wx.ALIGN_RIGHT, 8)
        dlg.SetSizerAndFit(root)
        dlg.CentreOnParent()

        if dlg.ShowModal() == wx.ID_OK:
            mic_pct = mic_spin.GetValue()
            out_pct = out_spin.GetValue()
            preset_name = preset_choice.GetString(preset_choice.GetSelection())
            s.eq_active_preset = preset_name
            s.eq_mic_gain_pct = mic_pct
            s.eq_out_volume_pct = out_pct
            self.settings_store.save()
            try:
                sdk_mic = min(32768, int(mic_pct * 32768 / 100))
                self.client.set_sound_input_gain(sdk_mic)
            except Exception:
                pass
            try:
                sdk_out = min(32768, int(out_pct * 32768 / 100))
                self.client.set_sound_output_volume(sdk_out)
            except Exception:
                pass
            self.set_status(f"Equalizer: {preset_name} angewendet (Mikrofon {mic_pct}%, Ausgabe {out_pct}%)")
        dlg.Destroy()

    # ------------------------------------------------------------------
    # v3.5.0 – Automation: Makro-Editor, Geplante Makros, Trigger-Regeln
    # ------------------------------------------------------------------

    def on_menu_macro_editor(self, _event):
        """Grafischer Makro-Editor: Erstellen, bearbeiten und löschen von Makros."""
        import json as _json
        s = self.settings_store.settings
        macros = list(s.macros or [])

        dlg = wx.Dialog(self, title="Makro-Editor",
                        style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        accel = wx.AcceleratorTable([(wx.ACCEL_CMD, ord("W"), wx.ID_CLOSE)])
        dlg.SetAcceleratorTable(accel)
        dlg.Bind(wx.EVT_MENU, lambda e: dlg.EndModal(wx.ID_CANCEL), id=wx.ID_CLOSE)
        root = wx.BoxSizer(wx.HORIZONTAL)

        # Left: Makro list
        left = wx.BoxSizer(wx.VERTICAL)
        left.Add(wx.StaticText(dlg, label="Makros:"), 0, wx.ALL, 4)
        macro_lb = wx.ListBox(dlg, style=wx.LB_SINGLE)
        macro_lb.SetName("Makroliste")
        for m in macros:
            macro_lb.Append(m.get("name", "?"))
        macro_lb.SetMinSize((200, 300))
        left.Add(macro_lb, 1, wx.EXPAND | wx.BOTTOM, 4)

        lb_btns = wx.BoxSizer(wx.HORIZONTAL)
        new_btn = wx.Button(dlg, label="&Neu")
        new_btn.SetName("Makro neu")
        del_btn = wx.Button(dlg, label="&Löschen")
        del_btn.SetName("Makro löschen")
        lb_btns.Add(new_btn, 1, wx.RIGHT, 4)
        lb_btns.Add(del_btn, 1)
        left.Add(lb_btns, 0, wx.EXPAND)
        root.Add(left, 0, wx.ALL | wx.EXPAND, 8)

        # Right: Makro detail editor
        right = wx.BoxSizer(wx.VERTICAL)

        name_row = wx.BoxSizer(wx.HORIZONTAL)
        name_row.Add(wx.StaticText(dlg, label="Name:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        name_field = wx.TextCtrl(dlg, size=(200, -1))
        name_field.SetName("Makro Name")
        name_row.Add(name_field, 1)
        right.Add(name_row, 0, wx.BOTTOM | wx.EXPAND, 8)

        right.Add(wx.StaticText(dlg, label="Aktionen (eine pro Zeile, Format: type=value):"), 0, wx.BOTTOM, 4)
        right.Add(wx.StaticText(dlg, label="  speak=Text | channel=Kanalname | status=Status"), 0, wx.BOTTOM, 2)
        right.Add(wx.StaticText(dlg, label="  ptt_on | ptt_off | mute_toggle | wait=Sekunden"), 0, wx.BOTTOM, 8)
        actions_field = wx.TextCtrl(dlg, style=wx.TE_MULTILINE, size=(350, 200))
        actions_field.SetName("Makro Aktionen")
        right.Add(actions_field, 1, wx.EXPAND | wx.BOTTOM, 8)

        save_macro_btn = wx.Button(dlg, label="Makro &speichern")
        save_macro_btn.SetName("Makro speichern")
        right.Add(save_macro_btn, 0, wx.BOTTOM, 8)

        close_btn = wx.Button(dlg, wx.ID_CLOSE, label="&Schließen")
        right.Add(close_btn, 0)
        root.Add(right, 1, wx.TOP | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)

        dlg.SetSizer(root)
        dlg.Fit()
        dlg.CentreOnParent()

        _current_idx = [None]

        def _load_macro(idx):
            if 0 <= idx < len(macros):
                m = macros[idx]
                name_field.SetValue(m.get("name", ""))
                lines = []
                for a in m.get("actions", []):
                    atype = a.get("type", "")
                    aval = a.get("value", "")
                    lines.append(f"{atype}={aval}" if aval else atype)
                actions_field.SetValue("\n".join(lines))
                _current_idx[0] = idx

        def _on_select(evt):
            idx = macro_lb.GetSelection()
            if idx != wx.NOT_FOUND:
                _load_macro(idx)

        def _on_new(_evt):
            new_name = f"Makro {len(macros) + 1}"
            macros.append({"name": new_name, "hotkey": 0, "actions": []})
            macro_lb.Append(new_name)
            macro_lb.SetSelection(len(macros) - 1)
            _load_macro(len(macros) - 1)

        def _on_delete(_evt):
            idx = macro_lb.GetSelection()
            if idx == wx.NOT_FOUND:
                return
            macros.pop(idx)
            macro_lb.Delete(idx)
            _current_idx[0] = None
            name_field.SetValue("")
            actions_field.SetValue("")

        def _on_save_macro(_evt):
            idx = _current_idx[0]
            if idx is None:
                return
            name = name_field.GetValue().strip()
            if not name:
                return
            actions = []
            for line in actions_field.GetValue().splitlines():
                line = line.strip()
                if not line:
                    continue
                if "=" in line:
                    atype, _, aval = line.partition("=")
                    actions.append({"type": atype.strip(), "value": aval.strip()})
                else:
                    actions.append({"type": line})
            macros[idx]["name"] = name
            macros[idx]["actions"] = actions
            macro_lb.SetString(idx, name)
            # Persist immediately
            s.macros = list(macros)
            self.settings_store.save()
            self.set_status(f"Makro '{name}' gespeichert")

        macro_lb.Bind(wx.EVT_LISTBOX, _on_select)
        new_btn.Bind(wx.EVT_BUTTON, _on_new)
        del_btn.Bind(wx.EVT_BUTTON, _on_delete)
        save_macro_btn.Bind(wx.EVT_BUTTON, _on_save_macro)
        close_btn.Bind(wx.EVT_BUTTON, lambda e: dlg.EndModal(wx.ID_CLOSE))

        dlg.ShowModal()
        # Final save on close
        s.macros = list(macros)
        self.settings_store.save()
        dlg.Destroy()

    def on_menu_scheduled_macros(self, _event):
        """v3.5.0 – Geplante Makros: Makros zu bestimmten Uhrzeiten ausführen."""
        s = self.settings_store.settings
        scheduled = list(s.scheduled_macros or [])
        macro_names = [m.get("name", "?") for m in (s.macros or [])]

        dlg = wx.Dialog(self, title="Geplante Makros",
                        style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        root = wx.BoxSizer(wx.VERTICAL)

        root.Add(wx.StaticText(dlg, label="Format HH:MM – täglich ausführen"), 0, wx.ALL, 8)

        lb = wx.ListBox(dlg, style=wx.LB_SINGLE)
        lb.SetName("Geplante Makros Liste")
        for e in scheduled:
            lb.Append(f"{e.get('time','?')}, Makro: {e.get('macro','?')}")
        lb.SetMinSize((400, 200))
        root.Add(lb, 1, wx.LEFT | wx.RIGHT | wx.EXPAND, 8)

        form = wx.BoxSizer(wx.HORIZONTAL)
        form.Add(wx.StaticText(dlg, label="Zeit (HH:MM):"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        time_field = wx.TextCtrl(dlg, value="08:00", size=(80, -1))
        time_field.SetName("Geplante Zeit")
        form.Add(time_field, 0, wx.RIGHT, 16)
        form.Add(wx.StaticText(dlg, label="Makro:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        macro_choice = wx.Choice(dlg, choices=macro_names)
        macro_choice.SetName("Makro auswählen")
        if macro_names:
            macro_choice.SetSelection(0)
        form.Add(macro_choice, 1)
        root.Add(form, 0, wx.ALL | wx.EXPAND, 8)

        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        add_btn = wx.Button(dlg, label="&Hinzufügen")
        add_btn.SetName("Geplantes Makro hinzufügen")
        del_btn = wx.Button(dlg, label="&Entfernen")
        del_btn.SetName("Geplantes Makro entfernen")
        close_btn = wx.Button(dlg, wx.ID_CLOSE, label="&Schließen")
        btn_row.Add(add_btn, 0, wx.RIGHT, 8)
        btn_row.Add(del_btn, 0, wx.RIGHT, 8)
        btn_row.Add(close_btn, 0)
        root.Add(btn_row, 0, wx.ALL, 8)
        dlg.SetSizerAndFit(root)
        dlg.CentreOnParent()

        def _on_add(_evt):
            t = time_field.GetValue().strip()
            if len(t) != 5 or t[2] != ":":
                wx.MessageBox("Ungültiges Zeitformat. Bitte HH:MM eingeben.", "Fehler", wx.OK)
                return
            idx = macro_choice.GetSelection()
            mname = macro_names[idx] if 0 <= idx < len(macro_names) else ""
            if not mname:
                return
            entry = {"time": t, "macro": mname}
            scheduled.append(entry)
            lb.Append(f"{t}, Makro: {mname}")
            s.scheduled_macros = list(scheduled)
            self.settings_store.save()

        def _on_del(_evt):
            idx = lb.GetSelection()
            if idx == wx.NOT_FOUND:
                return
            scheduled.pop(idx)
            lb.Delete(idx)
            s.scheduled_macros = list(scheduled)
            self.settings_store.save()

        add_btn.Bind(wx.EVT_BUTTON, _on_add)
        del_btn.Bind(wx.EVT_BUTTON, _on_del)
        close_btn.Bind(wx.EVT_BUTTON, lambda e: dlg.EndModal(wx.ID_CLOSE))
        dlg.ShowModal()
        dlg.Destroy()

    def on_menu_plugin_manager(self, _event) -> None:
        """v4.0.0 – Plugin-Manager Dialog."""
        from ui.plugin_manager import PluginManagerDialog
        dlg = PluginManagerDialog(self)
        dlg.ShowModal()
        dlg.Destroy()

    def _on_menu_toggle_translation(self, _event) -> None:
        """Aktiviert/deaktiviert die Echtzeit-Chat-Übersetzung."""
        enabled = self._auto_translate_menu_item.IsChecked()
        self.settings_store.settings.translate_chat_enabled = enabled
        self.settings_store.save()
        self._translator = __import__("chat_translator").ChatTranslatorManager(self.settings_store)
        status = "aktiviert" if enabled else "deaktiviert"
        self.set_status(f"Chat-Übersetzung {status}")
        if enabled:
            self.tts.speak(f"Chat-Übersetzung aktiviert, Zielsprache: {self._translator.target_language()}", kind="system")

    def on_menu_trigger_editor(self, _event):
        """v3.5.0 – Trigger-Regeln: Makros automatisch bei Ereignissen ausführen."""
        s = self.settings_store.settings
        triggers = list(s.macro_triggers or [])
        macro_names = [m.get("name", "?") for m in (s.macros or [])]
        _EVENTS = ["user_join", "user_leave", "chat_message", "private_msg", "channel_join"]

        dlg = wx.Dialog(self, title="Trigger-Regeln",
                        style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        root = wx.BoxSizer(wx.VERTICAL)
        root.Add(wx.StaticText(dlg, label="Makro automatisch ausführen wenn Ereignis eintritt:"), 0, wx.ALL, 8)

        lb = wx.ListBox(dlg, style=wx.LB_SINGLE)
        lb.SetName("Trigger-Regeln Liste")
        for t in triggers:
            filt = t.get("filter", "") or ""
            filt_str = f" (Filter: {filt})" if filt else ""
            lb.Append(f"{t.get('event','?')}{filt_str} → {t.get('macro','?')}")
        lb.SetMinSize((500, 200))
        root.Add(lb, 1, wx.LEFT | wx.RIGHT | wx.EXPAND, 8)

        form = wx.FlexGridSizer(3, 2, 6, 8)
        form.AddGrowableCol(1)
        form.Add(wx.StaticText(dlg, label="Ereignis:"), 0, wx.ALIGN_CENTER_VERTICAL)
        event_choice = wx.Choice(dlg, choices=_EVENTS)
        event_choice.SetName("Trigger-Ereignis")
        event_choice.SetSelection(0)
        form.Add(event_choice, 1, wx.EXPAND)
        form.Add(wx.StaticText(dlg, label="Filter (Name, leer=alle):"), 0, wx.ALIGN_CENTER_VERTICAL)
        filter_field = wx.TextCtrl(dlg)
        filter_field.SetName("Trigger-Filter")
        form.Add(filter_field, 1, wx.EXPAND)
        form.Add(wx.StaticText(dlg, label="Makro:"), 0, wx.ALIGN_CENTER_VERTICAL)
        macro_choice = wx.Choice(dlg, choices=macro_names)
        macro_choice.SetName("Trigger-Makro")
        if macro_names:
            macro_choice.SetSelection(0)
        form.Add(macro_choice, 1, wx.EXPAND)
        root.Add(form, 0, wx.ALL | wx.EXPAND, 8)

        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        add_btn = wx.Button(dlg, label="&Hinzufügen")
        del_btn = wx.Button(dlg, label="&Entfernen")
        close_btn = wx.Button(dlg, wx.ID_CLOSE, label="&Schließen")
        btn_row.Add(add_btn, 0, wx.RIGHT, 8)
        btn_row.Add(del_btn, 0, wx.RIGHT, 8)
        btn_row.Add(close_btn, 0)
        root.Add(btn_row, 0, wx.ALL, 8)
        dlg.SetSizerAndFit(root)
        dlg.CentreOnParent()

        def _on_add(_evt):
            ev = _EVENTS[event_choice.GetSelection()]
            filt = filter_field.GetValue().strip()
            idx = macro_choice.GetSelection()
            mname = macro_names[idx] if 0 <= idx < len(macro_names) else ""
            if not mname:
                return
            rule = {"event": ev, "filter": filt, "macro": mname}
            triggers.append(rule)
            fstr = f" (Filter: {filt})" if filt else ""
            lb.Append(f"{ev}{fstr} → {mname}")
            s.macro_triggers = list(triggers)
            self.settings_store.save()

        def _on_del(_evt):
            idx = lb.GetSelection()
            if idx == wx.NOT_FOUND:
                return
            triggers.pop(idx)
            lb.Delete(idx)
            s.macro_triggers = list(triggers)
            self.settings_store.save()

        add_btn.Bind(wx.EVT_BUTTON, _on_add)
        del_btn.Bind(wx.EVT_BUTTON, _on_del)
        close_btn.Bind(wx.EVT_BUTTON, lambda e: dlg.EndModal(wx.ID_CLOSE))
        dlg.ShowModal()
        dlg.Destroy()

    def on_menu_record_conversations(self, _event):
        if not self._select_tab_by_label("Aufnahme & Medien"):
            self._replace_lazy_tab("media", MediaTab)
            self._select_tab_by_label("Aufnahme & Medien")
        if self.media_tab is not None:
            wx.CallAfter(self.media_tab.user_rec_enable.SetFocus)

    def on_menu_record_start(self, _event):
        if not self._require_connected("Aufnahme starten"):
            return
        if self._recording_active:
            self.set_status("Aufnahme läuft bereits")
            return
        fmt = self._record_format_dialog()
        if not fmt:
            return
        label, audio_format = fmt
        with wx.FileDialog(self, "Aufnahme speichern", wildcard="Audio (*.wav;*.mp3)|*.wav;*.mp3|Alle Dateien|*.*", style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            path = dlg.GetPath()
        ok = self.client.start_recording_muxed(path, int(audio_format))
        if ok:
            self._recording_active = True
            self._recording_path = path
            self._recording_seg_start = time.time()
            self.set_status(f"Aufnahme gestartet ({label})")
        else:
            self.set_status("Aufnahme konnte nicht gestartet werden")

    def on_menu_record_stop(self, _event):
        if not self._require_connected("Aufnahme stoppen"):
            return
        if not self._recording_active:
            self.set_status("Keine laufende Aufnahme")
            return
        ok = self.client.stop_recording_muxed()
        self._recording_active = False
        if ok:
            self.set_status("Aufnahme beendet")
        else:
            self.set_status("Aufnahme beenden fehlgeschlagen")

    def on_menu_recording_browser(self, _event):
        """v3.4.0 – Aufnahmen-Browser: durchsuche und spiele vergangene Aufnahmen ab."""
        import os, glob as _glob
        s = self.settings_store.settings
        # Determine search directories
        dirs_to_scan = []
        user_dir = getattr(s, "_last_recording_dir", "")
        if user_dir and os.path.isdir(user_dir):
            dirs_to_scan.append(user_dir)
        from platform_paths import app_data_dir
        default_dir = str(app_data_dir() / "Aufnahmen")
        if os.path.isdir(default_dir):
            dirs_to_scan.append(default_dir)
        # Collect .wav and .mp3 files
        files = []
        for d in dirs_to_scan:
            for ext in ("*.wav", "*.mp3"):
                files.extend(_glob.glob(os.path.join(d, ext)))
        # Also search home Downloads
        dl = os.path.join(os.path.expanduser("~"), "Downloads")
        if os.path.isdir(dl):
            for ext in ("*.wav", "*.mp3"):
                files.extend(_glob.glob(os.path.join(dl, ext)))
        files = sorted(set(files), key=os.path.getmtime, reverse=True)[:200]

        dlg = wx.Dialog(self, title="Aufnahmen-Browser",
                        style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        accel = wx.AcceleratorTable([(wx.ACCEL_CMD, ord("W"), wx.ID_CLOSE)])
        dlg.SetAcceleratorTable(accel)
        dlg.Bind(wx.EVT_MENU, lambda e: dlg.EndModal(wx.ID_CANCEL), id=wx.ID_CLOSE)
        root = wx.BoxSizer(wx.VERTICAL)

        info_lbl = wx.StaticText(dlg, label=f"{len(files)} Aufnahme(n) gefunden")
        info_lbl.SetName("Aufnahmen Anzahl")
        root.Add(info_lbl, 0, wx.ALL, 8)

        lb = wx.ListBox(dlg, style=wx.LB_SINGLE)
        lb.SetName("Aufnahmeliste")
        for f in files:
            size_kb = os.path.getsize(f) // 1024
            mtime = os.path.getmtime(f)
            import datetime as _dt
            dt_str = _dt.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
            lb.Append(f"{os.path.basename(f)}, {dt_str}, {size_kb} KB")
        lb.SetMinSize((600, 320))
        root.Add(lb, 1, wx.LEFT | wx.RIGHT | wx.EXPAND, 8)

        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        play_btn = wx.Button(dlg, label="&Abspielen")
        play_btn.SetName("Aufnahme abspielen")
        delete_btn = wx.Button(dlg, label="&Löschen")
        delete_btn.SetName("Aufnahme löschen")
        open_btn = wx.Button(dlg, label="Im &Finder öffnen")
        open_btn.SetName("Aufnahme im Finder öffnen")
        close_btn = wx.Button(dlg, wx.ID_CANCEL, label="&Schließen")
        btn_row.Add(play_btn, 0, wx.RIGHT, 8)
        btn_row.Add(delete_btn, 0, wx.RIGHT, 8)
        btn_row.Add(open_btn, 0, wx.RIGHT, 8)
        btn_row.Add(close_btn, 0)
        root.Add(btn_row, 0, wx.ALL, 8)
        dlg.SetSizer(root)
        dlg.Fit()
        dlg.CentreOnParent()

        def _get_selected_file():
            idx = lb.GetSelection()
            if idx == wx.NOT_FOUND or idx >= len(files):
                return None
            return files[idx]

        def _on_play(_evt):
            f = _get_selected_file()
            if not f:
                return
            import subprocess
            try:
                if sys.platform == "darwin":
                    subprocess.Popen(["afplay", f])
                elif sys.platform == "win32":
                    import winsound
                    winsound.PlaySound(f, winsound.SND_FILENAME | winsound.SND_ASYNC)
                else:
                    subprocess.Popen(["xdg-open", f])
            except Exception as exc:
                wx.MessageBox(f"Abspielen fehlgeschlagen: {exc}", "Fehler", wx.OK | wx.ICON_ERROR)

        def _on_delete(_evt):
            f = _get_selected_file()
            if not f:
                return
            if wx.MessageBox(
                f"'{os.path.basename(f)}' wirklich löschen?",
                "Löschen bestätigen",
                wx.YES_NO | wx.ICON_WARNING
            ) != wx.YES:
                return
            try:
                os.remove(f)
                idx = lb.GetSelection()
                files.pop(idx)
                lb.Delete(idx)
                info_lbl.SetLabel(f"{len(files)} Aufnahme(n) gefunden")
            except Exception as exc:
                wx.MessageBox(f"Löschen fehlgeschlagen: {exc}", "Fehler", wx.OK | wx.ICON_ERROR)

        def _on_open(_evt):
            f = _get_selected_file()
            if not f:
                return
            import subprocess
            try:
                if sys.platform == "darwin":
                    subprocess.Popen(["open", "-R", f])
                elif sys.platform == "win32":
                    subprocess.Popen(["explorer", "/select,", f])
                else:
                    subprocess.Popen(["xdg-open", os.path.dirname(f)])
            except Exception:
                pass

        play_btn.Bind(wx.EVT_BUTTON, _on_play)
        delete_btn.Bind(wx.EVT_BUTTON, _on_delete)
        open_btn.Bind(wx.EVT_BUTTON, _on_open)
        dlg.ShowModal()
        dlg.Destroy()

    def on_menu_export_logs(self, _event):
        try:
            self.settings_tab._export_logs_zip()
        except Exception:
            self.set_status("Log-Export fehlgeschlagen")

    def on_menu_settings(self, _event):
        if not self.settings_window.IsShown():
            self.settings_window.Show()
        self.settings_window.Raise()
        wx.CallAfter(self.settings_window.settings_tab.section_choice.SetFocus)

    def _get_manual_text_de(self) -> str:
        """Deutsches Benutzerhandbuch."""
        return (
            f"TeamTalk VoiceOver Client – Benutzerhandbuch  (Version {APP_VERSION})\n"
            "=======================================================================\n"
            "\n"
            "Hinweis: Dieses Handbuch wird mit jeder Version aktualisiert und kann sich\n"
            "jederzeit ändern. Aktuelle Informationen stehen immer im Handbuch der\n"
            "jeweils installierten Version.\n"
            "\n"
            "Inhaltsverzeichnis\n"
            "------------------\n"
            " 1. Überblick\n"
            " 2. Programmstart und Bedienkonzept\n"
            " 3. Tab Verbindung\n"
            " 4. Tab Kanäle\n"
            " 5. Tab Chat\n"
            " 6. Tab Audio\n"
            " 7. Tab Aufnahme & Medien\n"
            " 8. Tab Dateien\n"
            " 9. Tab Administration\n"
            "10. Tab ElevenLabs TTS (Sprechen)\n"
            "11. Tab Desktop\n"
            "12. Tab Einstellungen\n"
            "13. Tab Tastenkürzel\n"
            "14. Tab System-Log\n"
            "15. Tab Video\n"
            "16. Menüleiste\n"
            "17. Tastaturkürzel\n"
            "18. Push-to-Talk und Sprachaktivierung\n"
            "19. Text-to-Speech (espeak-ng)\n"
            "20. Plattformunterschiede (macOS / Windows / Linux)\n"
            "21. Automation (Makros und Trigger)\n"
            "22. Globale Hotkeys (macOS)\n"
            "23. Braillezeilen-Ausgabe\n"
            "24. KI-Funktionen (Claude / Gemini)\n"
            "25. HTTP-Steuer-API\n"
            "26. Webhook-Integration\n"
            "27. Sprache der Benutzeroberfläche\n"
            "28. Plugin-Manager\n"
            "\n"
            "\n"
            "1. Überblick\n"
            "============\n"
            "Der TeamTalk VoiceOver Client ist ein barrierefreier Client für TeamTalk-5-Server,\n"
            "optimiert für VoiceOver (macOS), NVDA/JAWS (Windows) und andere Screenreader.\n"
            "Er ermöglicht Sprach- und Textkommunikation, Dateiübertragung, Medien-Streaming\n"
            "und Desktop-Freigabe.\n"
            "\n"
            "\n"
            "2. Programmstart und Bedienkonzept\n"
            "===================================\n"
            "Das Hauptfenster ist in Tabs gegliedert. Mit Ctrl+Tab / Shift+Ctrl+Tab wechseln\n"
            "Sie zwischen den Tabs. Auf macOS sprechen VoiceOver-Gesten Elemente direkt an.\n"
            "\n"
            "Listen: Alle Listen im Programm sind als einfache ListBox aufgebaut.\n"
            "Einträge sind durch Komma getrennt, damit Screenreader sie flüssig vorlesen.\n"
            "\n"
            "Statuszeile: Am unteren Fensterrand wird laufend Feedback angezeigt\n"
            "(Verbindungsstatus, Aktionen, Fehler).\n"
            "\n"
            "\n"
            "3. Tab Verbindung\n"
            "=================\n"
            "Hier verwalten Sie Serverprofile und stellen die Verbindung her.\n"
            "\n"
            "Bereich 'Serverprofil'\n"
            "  Profil-Liste:    Liste gespeicherter Profile. Auswahl übernimmt die Daten.\n"
            "  Neu:             Leeres Profil anlegen.\n"
            "  Duplizieren:     Ausgewähltes Profil kopieren.\n"
            "  Löschen:         Ausgewähltes Profil entfernen.\n"
            "  Speichern:       Aktuelle Eingaben im Profil speichern.\n"
            "\n"
            "Bereich 'Verbindungsdaten'\n"
            "  Profilname:      Anzeigename des Profils (nur lokal).\n"
            "  Server-Host:     Hostname oder IP-Adresse des TeamTalk-Servers.\n"
            "  TCP-Port:        TCP-Port (Standard: 10333).\n"
            "  UDP-Port:        UDP-Port (Standard: 10333).\n"
            "  Benutzername:    Anmeldename. Für Gastanmeldung leer lassen.\n"
            "  Passwort:        Passwort (leer = kein Passwort).\n"
            "  Nickname:        Angezeigter Name im Kanal.\n"
            "  Kanal:           Kanal, dem nach Anmeldung automatisch beigetreten wird.\n"
            "  Kanalpasswort:   Passwort des Zielkanals (falls nötig).\n"
            "  Serverpasswort:  Server-Beitrittspasswort.\n"
            "\n"
            "Bereich 'Aktionen'\n"
            "  Verbinden:       Verbindung mit den eingegebenen Daten herstellen.\n"
            "  Trennen:         Verbindung zum Server trennen.\n"
            "  Wiederverbinden: Erneut mit dem zuletzt verwendeten Server verbinden.\n"
            "\n"
            "Bereich 'Verbindungsstatus'\n"
            "  Zeigt den aktuellen Verbindungsstatus (Getrennt / Verbunden / Angemeldet).\n"
            "\n"
            "Optionen\n"
            "  Auto-Wiederverbinden: Ist diese Option aktiv, verbindet sich das Programm\n"
            "  nach einem Verbindungsverlust automatisch erneut.\n"
            "\n"
            "\n"
            "4. Bereich Kanäle und Chat\n"
            "==========================\n"
            "Zeigt die Kanalstruktur des Servers, Benutzer und den Chat.\n"
            "\n"
            "Bereich 'Kanalliste'\n"
            "  Flache Liste aller Kanäle und Nutzer auf dem Server.\n"
            "  Einrückung zeigt die Kanaltiefe (Leerzeichen = Unterebene).\n"
            "  Enter oder Doppelklick: Kanal beitreten.\n"
            "\n"
            "Bereich 'Benutzer im Kanal'\n"
            "  Benutzer erscheinen als Einträge unter ihrem Kanal.\n"
            "  Eintragsformat: Nickname, Status, Eigenschaften\n"
            "\n"
            "Kontextmenü auf Benutzer (Rechtsklick oder Anwendungstaste):\n"
            "  Benutzerinfo:           Detailinformationen anzeigen.\n"
            "  Benutzerinfo vorlesen:  Info per TTS ausgeben.\n"
            "  Nachricht senden:       Privatnachricht senden.\n"
            "  Lautstärke anpassen:    Individuelle Lautstärke für diesen Nutzer setzen.\n"
            "  Lauter / Leiser:        Lautstärke um 10 % erhöhen / verringern.\n"
            "  Stimme stummschalten:   Stimme dieses Benutzers stummschalten.\n"
            "  Medienstrom stummschalten: Medienstrom stummschalten.\n"
            "  Stimme weiterleiten:    Stimme an anderen Kanal weiterleiten.\n"
            "  Medienstrom weiterleiten: Medienstrom weiterleiten.\n"
            "  Operator:               Benutzer zum Kanaloperator machen / zurückstufen.\n"
            "  Rauswerfen:             Benutzer aus dem Kanal werfen.\n"
            "  Rauswerfen + Sperren:   Benutzer aus dem Kanal werfen und sperren.\n"
            "  Vom Server rauswerfen:  Benutzer vom gesamten Server entfernen.\n"
            "  Vom Server + Sperren:   Vom Server entfernen und IP-Sperre setzen.\n"
            "  Auf Server sperren:     IP-Adresse auf Serverliste sperren.\n"
            "  Übertragungsrechte:     Abonnements (Stimme, Video, Desktop, Medien, Nachrichten)\n"
            "                          für diesen Nutzer verwalten.\n"
            "  Abonnements:            Eigene Abonnements für diesen Nutzer verwalten.\n"
            "  Zu Kanal bewegen:       Benutzer in einen anderen Kanal verschieben.\n"
            "  Zielkanal speichern:    Aktuellen Kanal als Ziel für Verschieben speichern.\n"
            "  Zu gespeichertem Kanal: Benutzer in den gespeicherten Zielkanal verschieben.\n"
            "  Alle stummschalten:     Alle Benutzer im Kanal stummschalten.\n"
            "\n"
            "\n"
            "5. Tab Chat\n"
            "===========\n"
            "Senden und Empfangen von Textnachrichten.\n"
            "\n"
            "Bereich 'Chat-Ziel'\n"
            "  Zeigt an, wohin Nachrichten gesendet werden.\n"
            "  Privat (Checkbox): Aktiviert den privaten Chat.\n"
            "  Privat an (Auswahlliste): Empfänger für private Nachrichten.\n"
            "\n"
            "Chatverlauf:\n"
            "  Mehrzeiliges Textfeld, nicht bearbeitbar. Farbkodierung:\n"
            "    Schwarz  = Kanalnachricht\n"
            "    Blau     = Privatnachricht\n"
            "    Grün     = Eigene Nachricht\n"
            "    Grau     = Systemnachricht\n"
            "\n"
            "Nachricht eingeben: Eingabefeld + Senden-Schaltfläche (oder Enter).\n"
            "\n"
            "Chat-Verlauf:\n"
            "  Verlauf exportieren: Aktuellen Chat als TXT-Datei speichern.\n"
            "  Verlauf leeren: Chatverlauf löschen (optional inkl. gespeicherter Datei).\n"
            "  Chat-Verlauf speichern (Einstellungen): Speichert pro Server bis zu 200 Einträge.\n"
            "\n"
            "\n"
            "6. Tab Audio\n"
            "============\n"
            "Konfiguration der Audiogeräte und Übertragungsoptionen.\n"
            "\n"
            "Erststart – Audio einrichten\n"
            "  Beim ersten Programmstart sind Mikrofon und Lautsprecher noch nicht aktiv.\n"
            "  Vorgehen:\n"
            "  1. Tab 'Audio' öffnen.\n"
            "  2. Unter 'Geräte' das gewünschte Eingabegerät (Mikrofon) wählen.\n"
            "  3. Das gewünschte Ausgabegerät (Lautsprecher / Kopfhörer) wählen.\n"
            "  4. 'Audio anwenden' drücken – die Geräte werden jetzt aktiviert.\n"
            "  Ohne diesen Schritt kann weder Sprache gesendet noch empfangen werden.\n"
            "  Hinweis: Die Sprachaktivierung ist standardmäßig deaktiviert. Nach dem\n"
            "  Anwenden der Geräte kann sie hier aktiviert werden (Checkbox\n"
            "  'Sprachaktivierung') oder über Push-to-Talk gesendet werden.\n"
            "\n"
            "Bereich 'Geräte'\n"
            "  Eingabegerät:  Mikrofon für die Übertragung (Auswahlmenü).\n"
            "  Ausgabegerät:  Lautsprecher / Kopfhörer (Auswahlmenü).\n"
            "\n"
            "Bereich 'Sprachaktivierung'\n"
            "  Sprachaktivierung (Checkbox): Mikrofon automatisch bei Sprache aktivieren.\n"
            "  Aktivierungspegel (0–100):    Schwellwert für die Sprachaktivierung.\n"
            "  Nachlauf (ms, 0–5000):        Wie lange nach Sprache noch gesendet wird.\n"
            "\n"
            "Bereich 'Pegel und Lautstärke'\n"
            "  Mikrofonverstärkung (0–32000): Empfindlichkeit des Mikrofons.\n"
            "  Ausgabe-Lautstärke (0–32000):  Lautstärke der Ausgabe.\n"
            "\n"
            "Bereich 'Aussteuerungsanzeige'\n"
            "  Zeigt den aktuellen Mikrofonpegel als Fortschrittsbalken (nur im Audio-Tab).\n"
            "\n"
            "Bereich 'Ausgabe'\n"
            "  Ausgabe stummschalten (Checkbox): Gesamte Ausgabe stummschalten.\n"
            "\n"
            "Bereich 'Geräteeffekte'\n"
            "  AGC (Checkbox):              Automatische Lautstärkeregelung.\n"
            "  Rauschunterdrückung:         Hintergrundrauschen reduzieren.\n"
            "  Echounterdrückung:           Echos des eigenen Mikrofons unterdrücken.\n"
            "  Effekte anwenden (Schalt.):  Ausgewählte Effekte aktivieren.\n"
            "\n"
            "Bereich 'Vorverarbeitung'\n"
            "  Auswahl: Keine / SpeexDSP / WebRTC. Sofortige Wirkung bei Änderung.\n"
            "\n"
            "Bereich 'Aktionen'\n"
            "  Duplex-Modus (Checkbox):  Eingang und Ausgang gekoppelt betreiben.\n"
            "  Geräte aktualisieren:     Geräteliste neu einlesen.\n"
            "  Audio anwenden:           Ausgewählte Geräte und Einstellungen aktivieren.\n"
            "  Push-to-Talk (Checkbox):  PTT-Modus aktivieren (Leertaste halten zum Sprechen).\n"
            "  Mikrofontest (Checkbox):  Eigene Stimme zur Kontrolle direkt hören.\n"
            "\n"
            "Bereich 'PTT-Hotkey'\n"
            "  Hotkey aufnehmen: Eine Taste als PTT-Hotkey innerhalb der App festlegen.\n"
            "  Hinweis: Der Hotkey funktioniert nur, wenn das Programmfenster aktiv ist.\n"
            "\n"
            "Bereich 'Audioeinstellungen speichern'\n"
            "  Audioeinstellungen beim Start anwenden (Checkbox):\n"
            "    Gespeicherte Einstellungen beim Programmstart automatisch laden.\n"
            "  Bei Gerätewechsel automatisch anwenden (Checkbox):\n"
            "    Wenn ein Gerät angeschlossen/getrennt wird, automatisch anwenden.\n"
            "  Aktuelle Audioeinstellungen speichern: Alle Einstellungen speichern.\n"
            "  Gespeicherte Audioeinstellungen anwenden: Gespeicherte Werte laden.\n"
            "  Gespeicherte Audioeinstellungen löschen: Gespeicherte Werte entfernen.\n"
            "\n"
            "Bereich 'Lokale Wiedergabe'\n"
            "  Spielt eine Audiodatei lokal ab – nur Sie selbst hören die Wiedergabe,\n"
            "  nichts wird in den Kanal gestreamt. Für alle Benutzer verfügbar.\n"
            "  Datei:        Pfad zur Audiodatei (Durchsuchen-Schaltfläche öffnet Dateidialog).\n"
            "  Abspielen:    Wiedergabe starten (unterstützte Formate: MP3, WAV, OGG, FLAC, M4A).\n"
            "  Pause /\n"
            "  Fortsetzen:   Wiedergabe anhalten und wieder aufnehmen.\n"
            "  Stopp:        Wiedergabe beenden.\n"
            "\n"
            "\n"
            "7. Tab Aufnahme & Medien\n"
            "========================\n"
            "\n"
            "Bereich 'Aufnahme'\n"
            "  Format (Auswahlmenü): WAV, MP3 (16/32/64/128/256/320 kbit).\n"
            "  Aufnahme starten: Speicherort auswählen, dann Aufnahme starten.\n"
            "  Aufnahme stoppen: Laufende Aufnahme beenden.\n"
            "\n"
            "Bereich 'Konversationen aufzeichnen'\n"
            "  Automatisch aufzeichnen (Checkbox): Gespräche aller Benutzer aufzeichnen.\n"
            "  Zielordner: Ordner, in dem die Dateien gespeichert werden.\n"
            "  Dateiname: Namensmuster mit Platzhaltern (%Y%m%d-%H%M%S #%userid% %username%).\n"
            "  Format: WAV, MP3 128k oder 256k.\n"
            "  Eigene Stimme mit aufnehmen (Checkbox).\n"
            "  Anwenden: Einstellungen übernehmen.\n"
            "\n"
            "Bereich 'Medien-Streaming'\n"
            "  Streaming-Quelle (Auswahlmenü):\n"
            "    Datei:       Lokale Audio-/Videodatei streamen (WAV, MP3, OGG, MP4, AVI...).\n"
            "    YouTube:     YouTube-Video per URL oder Suche streamen (yt-dlp).\n"
            "    SoundCloud:  SoundCloud-Track per URL oder Suche streamen (yt-dlp).\n"
            "    Twitch:      Twitch-Kanal per URL streamen (yt-dlp, kein Suchen).\n"
            "    Bandcamp:    Bandcamp-Track per URL streamen (yt-dlp, kein Suchen).\n"
            "    Vimeo:       Vimeo-Video per URL streamen (yt-dlp, kein Suchen).\n"
            "    Mixcloud:    Mixcloud-Mix per URL streamen (yt-dlp, kein Suchen).\n"
            "    Webradio:    Live-Stream aus eingebetteter Senderliste oder eigener URL.\n"
            "    Podcasts:    Podcast-Suche (iTunes-API) oder RSS-Feed direkt laden.\n"
            "    Playlist:    Mehrere lokale Dateien als Playlist streamen (siehe unten).\n"
            "\n"
            "  Datei-Streaming:\n"
            "    Durchsuchen: Datei auswählen.\n"
            "    Abspielen / Pause / Stopp.\n"
            "    Position (0–1000): Springen in der Datei.\n"
            "    Streaming-Lautstärke (25–400): Lautstärke des gestreamten Signals.\n"
            "\n"
            "  YouTube/SoundCloud (yt-dlp mit Suche):\n"
            "    Suche: Begriff eingeben, Suchen drücken, Ergebnis aus Liste wählen.\n"
            "    Link: URL direkt eingeben, Streamen drücken.\n"
            "    Pause / Stopp.\n"
            "\n"
            "  Webradio:\n"
            "    Senderliste: Voreingestellte Sender (90s90s, 80s80s, TechnoBase u.v.m.).\n"
            "    Webradio Suche: Online-Suche via Radio Browser API.\n"
            "    Stream-URL: Eigene URL eingeben und streamen.\n"
            "\n"
            "  Podcasts:\n"
            "    Podcast Suche: Suche via iTunes API.\n"
            "    Feed URL: RSS-Feed direkt eingeben und laden.\n"
            "    Episodenliste: Episode auswählen und streamen.\n"
            "\n"
            "  Playlist:\n"
            "    Playlist-Liste:  Zeigt alle Titel der aktuellen Playlist (nur Dateiname).\n"
            "    Hinzufügen...:   Mehrfachauswahl lokaler Audiodateien (MP3, WAV, OGG,\n"
            "                     FLAC, M4A, Opus, MP4, AVI, MKV).\n"
            "    M3U laden...:    Vorhandene M3U- oder M3U8-Datei importieren.\n"
            "                     Relative Pfade werden relativ zur M3U-Datei aufgelöst.\n"
            "    Entfernen:       Ausgewählten Titel aus der Playlist löschen.\n"
            "    Nach oben /\n"
            "    Nach unten:      Reihenfolge der Titel ändern.\n"
            "    Als M3U exportieren...: Aktuelle Playlist als .m3u-Datei speichern.\n"
            "    Leeren:          Alle Titel aus der Playlist entfernen.\n"
            "    Automatisch weiter (Checkbox): Nach Ende jedes Titels automatisch\n"
            "                     den nächsten abspielen.\n"
            "    Abspielen:       Streaming ab dem markierten Titel starten.\n"
            "    Pause / Stopp:   Wiedergabe anhalten / beenden.\n"
            "    Streaming-Lautstärke: Lautstärke des gestreamten Signals (25–400).\n"
            "\n"
            "\n"
            "8. Tab Dateien\n"
            "==============\n"
            "Dateiübertragung im aktuellen Kanal.\n"
            "\n"
            "Dateiliste: Zeigt alle Dateien im Kanal.\n"
            "  Eintragsformat: Dateiname, Größe, Hochgeladen von, Datum\n"
            "\n"
            "Hochladen:     Datei vom lokalen Rechner in den Kanal hochladen.\n"
            "Herunterladen: Ausgewählte Datei herunterladen (Speicherort wählen).\n"
            "Löschen:       Ausgewählte Datei aus dem Kanal löschen (Bestätigungsdialog).\n"
            "Aktualisieren: Dateiliste neu laden.\n"
            "\n"
            "Übertragungsfortschritt: Fortschrittsbalken während Up-/Download.\n"
            "\n"
            "\n"
            "9. Tab Administration\n"
            "=====================\n"
            "Nur für Benutzer mit Administrator-Rechten verfügbar.\n"
            "\n"
            "Bereich 'Benutzerkonten'\n"
            "  Spalten: Benutzername, Typ (Standard/Administrator), Notiz.\n"
            "  Konten laden: Liste der Konten vom Server laden.\n"
            "  Konto hinzufügen: Neues Konto anlegen (Benutzername, Passwort, Notiz, Typ).\n"
            "  Konto löschen: Ausgewähltes Konto entfernen (Bestätigungsdialog).\n"
            "\n"
            "Bereich 'Sperren'\n"
            "  Spalten: IP-Adresse, Benutzername, Zeitpunkt.\n"
            "  Sperren laden:         Sperrliste vom Server laden.\n"
            "  Entsperren:            Ausgewählte Sperre aufheben.\n"
            "  IP-Adresse bannen...:  IP-Adresse direkt sperren ohne dass der Benutzer\n"
            "                         gerade verbunden sein muss. Texteingabedialog.\n"
            "\n"
            "Bereich 'Servereigenschaften'\n"
            "  Servername, MOTD (Willkommensnachricht), Max. Benutzer.\n"
            "  Laden: Aktuelle Serverwerte lesen.\n"
            "  Speichern: Geänderte Werte auf den Server schreiben.\n"
            "  Konfiguration speichern: Server-Konfigurationsdatei speichern.\n"
            "\n"
            "\n"
            "10. Tab ElevenLabs TTS (Sprechen)\n"
            "==================================\n"
            "Eigene KI-Sprachausgabe über ElevenLabs in den Kanal sprechen lassen.\n"
            "\n"
            "Voraussetzung: ElevenLabs-API-Schlüssel.\n"
            "Den API-Schlüssel tragen Sie in den Einstellungen ein:\n"
            "  Einstellungen → Bereich 'ElevenLabs' → Feld 'API-Schlüssel'\n"
            "  → Speichern drücken.\n"
            "Der Schlüssel gilt global für alle Serverprofile. Er wird beim\n"
            "nächsten Verbinden automatisch an den Sprechen-Tab übergeben.\n"
            "\n"
            "Bedienung:\n"
            "  Stimme / Modell: Aus den per API geladenen Listen wählen.\n"
            "  Aktualisieren:   Stimmen und Modelle neu von der API laden.\n"
            "  Stabilität (0–100):   Stimmstabilität.\n"
            "  Ähnlichkeit (0–100):  Ähnlichkeit zur Originalstimme.\n"
            "  Stil (0–100):         Stil-Übertreibung.\n"
            "  Sprecher-Boost:       Sprecherklarheit verstärken (nicht bei v3-Modellen).\n"
            "  Text:                 Zu sprechenden Text eingeben.\n"
            "  Sprechen:             Audio generieren und in den Kanal streamen.\n"
            "  Stopp:                Streaming stoppen.\n"
            "\n"
            "\n"
            "11. Tab Desktop\n"
            "===============\n"
            "Desktopfreigabe: Den eigenen Bildschirm in den Kanal übertragen.\n"
            "\n"
            "Bereich 'Desktop senden'\n"
            "  Desktop senden (Checkbox): Fortlaufende Übertragung starten/stoppen.\n"
            "  FPS: Bildrate (1, 2, 5 oder 10 Bilder/Sekunde).\n"
            "  Skalierung: Bildgröße reduzieren (25%, 50%, 75%, 100%).\n"
            "  Einmal senden: Einzelnes Bild senden.\n"
            "  Freigabe beenden: Übertragung stoppen.\n"
            "\n"
            "Bereich 'Desktop-Steuerung (Remote)'\n"
            "  Linksklick / Rechtsklick / Mittelklick:\n"
            "  Mausklick an den Desktop-Empfänger senden.\n"
            "\n"
            "Bereich 'Status'\n"
            "  Zeigt den aktuellen Freigabe-Status.\n"
            "\n"
            "\n"
            "12. Tab Einstellungen\n"
            "=====================\n"
            "\n"
            "Suchfeld: Bereichsnamen tippen, um direkt dorthin zu springen.\n"
            "\n"
            "Bereich 'Allgemein'\n"
            "  Sprache:             Oberflächensprache (Deutsch / Englisch). Neustart erforderlich.\n"
            "  Geschlecht:          Wird dem Server gemeldet (Männlich/Weiblich/Neutral).\n"
            "  Abwesenheits-Timer:  Nach X Minuten Inaktivität automatisch 'Abwesend' setzen.\n"
            "  BearWare-Konto:      BearWare-ID und Token für registrierte Nutzer.\n"
            "  Chat-Verlauf speichern: Verlauf pro Server sichern und beim nächsten Verbinden laden.\n"
            "  Letzten Kanal automatisch beitreten: Nach dem Verbinden automatisch in den letzten Kanal.\n"
            "  Zeitstempel im Chat: [HH:MM:SS]-Prefix vor Chatnachrichten anzeigen.\n"
            "\n"
            "Bereich 'Anzeige'\n"
            "  Tray-Icon:          Programm im System-Tray minimieren.\n"
            "  Immer im Vordergrund: Fenster immer oben halten.\n"
            "  Chat-Format:        Zeitstempel und Format für Chatnachrichten.\n"
            "  VU-Meter:           Aussteuerungsanzeige im Hauptfenster (oben).\n"
            "  Fenstertitel:       Kanalname und Benutzeranzahl im Titel anzeigen.\n"
            "  Werkzeugleiste:     Schaltflächenleiste anzeigen.\n"
            "  Ereignisprotokoll:  System-Ereignisse protokollieren.\n"
            "\n"
            "Bereich 'Verbindung'\n"
            "  Abonnements:        Standard-Abonnements für neue Benutzer.\n"
            "  Port-Bindung:       Lokalen UDP/TCP-Port vorgeben.\n"
            "\n"
            "Bereich 'Sound-Ereignisse'\n"
            "  18 Ereignisse können mit Sounds belegt werden:\n"
            "    Benutzer beigetreten, verlassen, Kanal gewechselt, Verbunden, Getrennt,\n"
            "    Nachricht empfangen, Privat empfangen, Übertragung gestartet/gestoppt,\n"
            "    Frage-Modus, Video-Start, Desktop-Start, Datei-Start, Aufnahme-Start,\n"
            "    Hotkey gedrückt, Fehler.\n"
            "  Lautstärke: Lautstärke der Ereignisklänge.\n"
            "  Abspielgerät: Ausgabegerät für Klänge.\n"
            "\n"
            "Bereich 'Audio'\n"
            "  Siehe Tab Audio (Audioeinstellungen werden hier gespiegelt).\n"
            "\n"
            "Bereich 'Video'\n"
            "  Videokamera konfigurieren.\n"
            "\n"
            "Bereich 'Tastenkürzel'\n"
            "  Siehe Tab Tastenkürzel.\n"
            "\n"
            "Bereich 'System & TTS'\n"
            "  Sprachausgabe (TTS) aktivieren (Checkbox).\n"
            "  Chat vorlesen / Private vorlesen / System vorlesen / Eigene vorlesen.\n"
            "  Unterbrechen: Laufende Ausgabe stoppen, wenn neue Nachricht kommt.\n"
            "  Sprache: ISO-Sprachcode (z. B. 'de', 'en').\n"
            "  Stimme: espeak-ng-Stimme (z. B. 'de', 'en', 'Linda', 'Max').\n"
            "  Geschwindigkeit (80–450): Sprechrate in Wörtern pro Minute.\n"
            "  Lautstärke (0–200): Lautstärke der TTS-Ausgabe.\n"
            "  espeak-ng Pfad: Manueller Pfad zum espeak-ng-Binary.\n"
            "  Stimme auswählen: Dialog zum Durchsuchen verfügbarer Stimmen.\n"
            "  Einstellungen speichern.\n"
            "\n"
            "\n"
            "13. Tab Tastenkürzel\n"
            "====================\n"
            "App-interne Hotkeys (nur bei aktivem Programmfenster):\n"
            "  Alles stummschalten:          Alle Benutzer stummschalten/reaktivieren.\n"
            "  Sprachaktivierung umschalten: VA ein-/ausschalten.\n"
            "  Video senden umschalten:      Video-Übertragung starten/stoppen.\n"
            "  Eingangspegel ansagen:        Aktuellen Mikrofonpegel per TTS vorlesen.\n"
            "  Nutzerinfo ansagen:           Info über ausgewählten Benutzer per TTS.\n"
            "  Ping ansagen:                 Aktuellen Ping per TTS vorlesen.\n"
            "  Braille-Status ansagen:       Konfigurierte Statusfelder vorlesen.\n"
            "  Privatantwort:                Antwort auf die letzte Privatnachricht.\n"
            "  Sound-Profil wechseln:        Zwischen Sound-Profilen wechseln.\n"
            "  Braille-Verbosität wechseln:  Braille-Ausführlichkeitsstufe umschalten.\n"
            "  KI-Zusammenfassung:           Letzte Chat-Nachrichten per KI zusammenfassen.\n"
            "  Lesezeichen 1/2/3:            Gespeicherte Lesezeichen-Kanäle beitreten.\n"
            "  Aufnahme umschalten:          Aufnahme starten/stoppen.\n"
            "  Status-Vorlage 1/2/3:         Vordefinierte Statusnachrichten setzen.\n"
            "  Mikrofon-Boost hoch/runter:   Mikrofonverstärkung erhöhen/verringern.\n"
            "  TTS abbrechen:                Laufende TTS-Ausgabe stoppen + Warteschlange leeren.\n"
            "\n"
            "Globale Hotkeys (macOS, systemweit):\n"
            "  PTT und Stummschalten funktionieren auch im Hintergrund.\n"
            "  'Globale Hotkeys aktivieren' → Taste aufnehmen.\n"
            "  Hinweis: Berechtigungen in Systemeinstellungen → Datenschutz &\n"
            "  Sicherheit → Bedienungshilfen erteilen.\n"
            "\n"
            "Hotkey aufnehmen: Schaltfläche drücken, dann gewünschte Taste betätigen.\n"
            "ESC = Aufnahme abbrechen.\n"
            "\n"
            "\n"
            "14. Tab System-Log\n"
            "==================\n"
            "Protokoll interner Ereignisse (Verbindung, Fehler, TTS-Meldungen).\n"
            "Log kopieren: Inhalt in die Zwischenablage kopieren.\n"
            "Log leeren: Protokoll zurücksetzen.\n"
            "\n"
            "\n"
            "15. Tab Video\n"
            "=============\n"
            "Videokamera-Übertragung.\n"
            "Videokamera auswählen und Übertragung starten.\n"
            "\n"
            "\n"
            "16. Menüleiste\n"
            "==============\n"
            "\n"
            "Menü 'Datei'\n"
            "  Neues Fenster:    Weitere Client-Instanz öffnen.\n"
            "  Einstellungen:    Einstellungen-Tab öffnen (Cmd+,).\n"
            "  Beenden:          Programm schließen.\n"
            "\n"
            "Menü 'Verbindung'\n"
            "  Verbinden:               Mit dem gewählten Profil verbinden.\n"
            "  Trennen:                 Verbindung beenden.\n"
            "  Wiederverbinden:         Letzte Verbindung erneut herstellen.\n"
            "  Auto-Wiederverbinden:    Automatisch wiederverbinden (Umschalter).\n"
            "  Stammkanal beitreten:    Dem Stammkanal (/) beitreten.\n"
            "  Kanal verlassen:         Aktuellen Kanal verlassen.\n"
            "  Server-Check:            Server-Erreichbarkeit prüfen.\n"
            "\n"
            "Menü 'Kanal'\n"
            "  Erstellen:               Neuen Kanal anlegen.\n"
            "  Bearbeiten:              Kanal-Einstellungen ändern.\n"
            "  Löschen:                 Kanal entfernen (Admin).\n"
            "  Beitreten:               Dem ausgewählten Kanal beitreten.\n"
            "  Verlassen:               Aktuellen Kanal verlassen.\n"
            "  Info vorlesen:           Kanalinfo per TTS ausgeben.\n"
            "  Kanalstatistik vorlesen: Statistiken vorlesen.\n"
            "  Kanalstatus vorlesen:    Status vorlesen.\n"
            "  TT-URL kopieren:         TeamTalk-URL in die Zwischenablage kopieren.\n"
            "  Kanalsperren:            Sperrliste des Kanals anzeigen.\n"
            "  Kanalnachricht:          Nachricht an alle im Kanal senden.\n"
            "  Datei hochladen:         Datei in den Kanal laden.\n"
            "  Datei herunterladen:     Datei aus dem Kanal laden.\n"
            "  Datei löschen:           Datei aus dem Kanal entfernen.\n"
            "  Dateiliste aktualisieren: Dateiliste neu laden.\n"
            "  Streaming (Datei/YouTube/SoundCloud/Twitch/Bandcamp/Vimeo/Mixcloud/Webradio/Podcast/Playlist): Medien-Streaming starten.\n"
            "\n"
            "Menü 'Benutzer'\n"
            "  Alle Aktionen wie im Kontextmenü (Tab Kanäle, Abschnitt 4).\n"
            "\n"
            "Menü 'Server'\n"
            "  Online-Benutzer:       Liste aller verbundenen Benutzer.\n"
            "                         Enthält ein Suchfeld: Benutzernamen eingeben und\n"
            "                         Enter drücken oder 'Suchen' klicken – der Eintrag\n"
            "                         wird in der Liste markiert und angesprungen.\n"
            "  Broadcast-Nachricht:   Nachricht an alle Benutzer senden (Admin).\n"
            "  Serverstatistiken:     Server-Kennzahlen anzeigen.\n"
            "  Serversperren:         IP-Sperrliste des Servers anzeigen.\n"
            "  Administration:        Admin-Tab öffnen.\n"
            "  Servereigenschaften:   Name, MOTD, Max. Benutzer bearbeiten.\n"
            "  Konfiguration speichern: Konfiguration auf dem Server speichern.\n"
            "\n"
            "Menü 'Profil'\n"
            "  Nickname ändern:       Anzeigenamen ändern.\n"
            "  Status ändern:         Statusnachricht setzen.\n"
            "  Fragemodus:            Hand heben / senken (Umschalter).\n"
            "  Sich selbst hören:     Eigene Stimme über Ausgabe hören (Loopback).\n"
            "  TTS umschalten:        Text-to-Speech global ein-/ausschalten.\n"
            "  Desktopfreigabe:       Desktopfreigabe starten/stoppen.\n"
            "\n"
            "Menü 'Benachrichtigungen'\n"
            "  Chat-TTS:     TTS für Kanalnachrichten ein-/ausschalten.\n"
            "  Private-TTS:  TTS für Privatnachrichten ein-/ausschalten.\n"
            "  System-TTS:   TTS für Systemnachrichten ein-/ausschalten.\n"
            "  Eigene-TTS:   TTS für eigene Nachrichten ein-/ausschalten.\n"
            "\n"
            "Menü 'Audio'\n"
            "  Push-to-Talk:             PTT-Modus umschalten.\n"
            "  Sprachaktivierung:        VA umschalten.\n"
            "  Audioeinstellungen:       Audio-Tab öffnen.\n"
            "  AGC / Rauschunterdrückung / Echounterdrückung: Effekte umschalten.\n"
            "  Effekte anwenden:         Ausgewählte Effekte aktivieren.\n"
            "  Audio anwenden:           Gerätekonfiguration anwenden.\n"
            "  Geräte aktualisieren:     Geräteliste neu einlesen.\n"
            "  Mikrofontest:             Eigentest-Schleife starten/stoppen.\n"
            "  Alles stummschalten:      Alle Benutzer stummschalten.\n"
            "\n"
            "Menü 'Video'\n"
            "  Video senden:             Video-Übertragung starten/stoppen.\n"
            "  Videoeinstellungen:       Video-Tab öffnen.\n"
            "  Geräte aktualisieren:     Kameraliste aktualisieren.\n"
            "\n"
            "Menü 'Aufnahme'\n"
            "  Aufnahme starten:         Kanalaudio aufnehmen.\n"
            "  Aufnahme stoppen:         Aufnahme beenden.\n"
            "  Gespräche aufzeichnen:    Konversationsaufnahme konfigurieren.\n"
            "\n"
            "Menü 'Hilfe'\n"
            "  Einstellungen:               Einstellungen öffnen (Cmd+,).\n"
            "  Logs exportieren:            System-Log in Datei speichern.\n"
            "  Verbindungsstatistiken:      Client-Netzwerkstatistiken anzeigen.\n"
            "  Statistiken vorlesen:        Statistiken per TTS ausgeben.\n"
            "  Handbuch:                    Dieses Handbuch anzeigen.\n"
            "  Changelog:                   Versionsänderungen anzeigen.\n"
            "  Über:                        Programminfo, Danksagungen, Lizenzen.\n"
            "\n"
            "\n"
            "17. Tastaturkürzel\n"
            "==================\n"
            "  Cmd+,          Einstellungen öffnen (macOS)\n"
            "  Cmd+W          Dialog/Fenster schließen\n"
            "  Leertaste      Push-to-Talk (halten) – wenn PTT aktiv\n"
            "  Ctrl+Tab       Nächster Tab\n"
            "  Shift+Ctrl+Tab Vorheriger Tab\n"
            "\n"
            "Konfigurierbare Hotkeys (Tab Tastenkürzel):\n"
            "  Alles stummschalten\n"
            "  Sprachaktivierung umschalten\n"
            "  Video senden umschalten\n"
            "\n"
            "\n"
            "18. Push-to-Talk und Sprachaktivierung\n"
            "======================================\n"
            "Push-to-Talk (PTT):\n"
            "  Im Audio-Tab 'Push-to-Talk' aktivieren.\n"
            "  Leertaste gedrückt halten = Mikrofon aktiv.\n"
            "  Alternativer Hotkey: Im Audio-Tab unter 'PTT-Hotkey' aufnehmen.\n"
            "  Hinweis: Funktioniert nur bei aktivem Programmfenster.\n"
            "\n"
            "Sprachaktivierung (VA):\n"
            "  Im Audio-Tab 'Sprachaktivierung' aktivieren.\n"
            "  Pegel einstellen: Wie laut muss es sein, damit das Mikrofon aktiviert wird.\n"
            "  Nachlauf: Wie lange sendet das Mikrofon nach der Stille noch weiter.\n"
            "  PTT und VA schließen sich gegenseitig aus: Wer PTT nutzt, sendet nicht via VA.\n"
            "\n"
            "\n"
            "19. Text-to-Speech (espeak-ng)\n"
            "==============================\n"
            "Der Client enthält espeak-ng für Sprachausgabe.\n"
            "Konfiguration im Tab Einstellungen, Bereich 'System & TTS':\n"
            "  Sprache: z. B. 'de' für Deutsch, 'en' für Englisch.\n"
            "  Stimme:  espeak-ng-Stimme (leer = Sprache wird direkt verwendet).\n"
            "           Stimmenliste über 'Stimme auswählen' durchsuchen.\n"
            "  Geschwindigkeit (80–450): Höherer Wert = schnellere Ausgabe.\n"
            "  Lautstärke (0–200): Standard = 100.\n"
            "  Unterbrechen: Laufende Ausgabe sofort stoppen, wenn neue kommt.\n"
            "\n"
            "Was wird vorgelesen?\n"
            "  - Chat-Nachrichten (wenn 'Chat vorlesen' aktiv)\n"
            "  - Privatnachrichten (wenn 'Private vorlesen' aktiv)\n"
            "  - Systemnachrichten (wenn 'System vorlesen' aktiv)\n"
            "  - Eigene Nachrichten (wenn 'Eigene vorlesen' aktiv)\n"
            "\n"
            "\n"
            "20. Plattformunterschiede\n"
            "=========================\n"
            "\n"
            "macOS\n"
            "  Primärplattform des Clients. Vollständige VoiceOver-Unterstützung.\n"
            "  Alle Steuerelemente haben korrekte Rollen (Taste, Auswahlmenü, Liste usw.).\n"
            "  Audioausgabe: afplay.\n"
            "  TTS: espeak-ng (gebündelt) mit afplay.\n"
            "  PTT-Hotkey nur bei aktivem Fenster (kein systemweiter Hotkey auf macOS).\n"
            "\n"
            "Windows\n"
            "  NVDA und JAWS werden unterstützt.\n"
            "  Audioausgabe: winsound.\n"
            "  TTS: espeak-ng (gebündelt) mit winsound.\n"
            "  PTT-Hotkey: Leertaste und konfigurierter Hotkey funktionieren.\n"
            "\n"
            "Linux\n"
            "  Grundlegende Unterstützung vorhanden.\n"
            "  Audioausgabe über espeak-ng direkt (kein afplay/winsound).\n"
            "  Screenreader-Unterstützung von wxGTK abhängig.\n"
            "\n"
            "\n"
            "21. Automation (Makros und Trigger)\n"
            "====================================\n"
            "Über Menü 'Automation' stehen drei Werkzeuge zur Verfügung:\n"
            "\n"
            "Makro-Editor (Automation → Makro-Editor...)\n"
            "  Erstellen, bearbeiten und löschen von Makros.\n"
            "  Jedes Makro hat einen Namen und eine Aktionsliste.\n"
            "  Aktionstypen:\n"
            "    speak  – Text per TTS vorlesen.\n"
            "    channel – Kanal nach Name wechseln.\n"
            "    status  – Statusnachricht setzen.\n"
            "    ptt     – PTT-Schaltung (on/off/toggle).\n"
            "    wait    – Pause in Millisekunden.\n"
            "  Makros können manuell ausgeführt oder durch Zeitplan/Trigger gestartet werden.\n"
            "\n"
            "Geplante Makros (Automation → Geplante Makros...)\n"
            "  Makro täglich zu einer konfigurierten Uhrzeit (HH:MM) automatisch ausführen.\n"
            "  Mehrere Zeitpläne möglich.\n"
            "\n"
            "Trigger-Regeln (Automation → Trigger-Regeln...)\n"
            "  Makros automatisch bei Ereignissen ausführen.\n"
            "  Unterstützte Ereignisse:\n"
            "    user_join      – Benutzer betritt einen Kanal.\n"
            "    user_leave     – Benutzer verlässt einen Kanal.\n"
            "    chat_message   – Kanalnachricht empfangen.\n"
            "    private_msg    – Privatnachricht empfangen.\n"
            "    channel_join   – Ich trete einem Kanal bei.\n"
            "  Optionaler Namensfilter: Nur auslösen, wenn der Benutzername den\n"
            "  eingegebenen Text enthält.\n"
            "\n"
            "\n"
            "22. Globale Hotkeys (macOS)\n"
            "===========================\n"
            "Auf macOS können PTT und Stummschalten systemweit funktionieren,\n"
            "also auch wenn das Programmfenster im Hintergrund ist.\n"
            "\n"
            "Aktivieren: Tab Tastenkürzel → 'Globale Hotkeys aktivieren' (Checkbox).\n"
            "Hinweis: macOS fragt nach Berechtigungen für Tastaturzugriff –\n"
            "diese müssen einmalig in Systemeinstellungen → Datenschutz &\n"
            "Sicherheit → Bedienungshilfen erteilt werden.\n"
            "\n"
            "Konfigurierbare globale Hotkeys:\n"
            "  PTT (Sprechtaste): Mikrofon bei Gedrückthalten aktivieren.\n"
            "  Alles stummschalten: Gesamtausgabe stummschalten/reaktivieren.\n"
            "\n"
            "Hinweis: App-interne Hotkeys (Tab 13) funktionieren nur wenn das\n"
            "Programmfenster den Fokus hat.\n"
            "\n"
            "\n"
            "23. Braillezeilen-Ausgabe\n"
            "=========================\n"
            "Der Client kann strukturierte Statusinformationen über eine konfigurierbare\n"
            "Braille-Ausgabe bereitstellen.\n"
            "\n"
            "Konfiguration: Einstellungen → KI & Integration → Braillezeilen-Ausgabe.\n"
            "Felder: Kanal, Nutzeranzahl, Ping, Stummschaltstatus, Verbindungsstatus.\n"
            "\n"
            "Hotkey 'Braille-Status ansagen': Liest den aktuellen Status per TTS vor.\n"
            "Konfigurierbar in Tab Tastenkürzel.\n"
            "\n"
            "\n"
            "24. KI-Funktionen (Claude / Gemini)\n"
            "=====================================\n"
            "Der Client unterstützt KI-gestützte Chat-Zusammenfassungen.\n"
            "\n"
            "Voraussetzung: API-Schlüssel in Einstellungen → KI & Integration.\n"
            "  Claude API-Schlüssel: Für Anthropic Claude.\n"
            "  Gemini API-Schlüssel: Für Google Gemini.\n"
            "  KI-Anbieter: Auswahl welcher Dienst verwendet wird.\n"
            "\n"
            "Hotkey 'KI-Zusammenfassung': Fasst die letzten Chat-Nachrichten zusammen.\n"
            "Ergebnis wird per TTS vorgelesen.\n"
            "\n"
            "\n"
            "25. HTTP-Steuer-API\n"
            "====================\n"
            "Die eingebaute HTTP-API erlaubt die Fernsteuerung des Clients von jedem\n"
            "Programm aus, das HTTP-Anfragen senden kann – z. B. Streamdeck,\n"
            "Home Assistant, Shell-Skripte, Automator (macOS), n8n, Node-RED u. v. m.\n"
            "\n"
            "Aktivieren\n"
            "----------\n"
            "Einstellungen → KI & Integration → 'HTTP-API aktivieren' (Checkbox).\n"
            "Standard-Port: 8765. Änderbar im Feld 'HTTP-API Port'.\n"
            "Tritt sofort in Kraft; kein Neustart erforderlich.\n"
            "\n"
            "Sicherheitshinweis\n"
            "------------------\n"
            "Der Server hört ausschließlich auf 127.0.0.1 (localhost) – kein Zugriff\n"
            "aus dem Netzwerk. Keine Authentifizierung: Jeder lokale Prozess desselben\n"
            "Nutzers kann die API aufrufen.\n"
            "\n"
            "Antwortformat\n"
            "-------------\n"
            "Alle Endpunkte antworten mit JSON:\n"
            "\n"
            "  Erfolg:  {\"ok\": true,  \"result\": <Wert oder Text>}\n"
            "  Fehler:  {\"ok\": false, \"error\": \"Fehlerbeschreibung\"}\n"
            "\n"
            "HTTP-Statuscode: 200 bei Erfolg, 500 bei Fehler.\n"
            "\n"
            "Endpunkte\n"
            "---------\n"
            "Alle Anfragen sind HTTP GET.\n"
            "\n"
            "PTT-Steuerung:\n"
            "  GET /ptt/on\n"
            "    Aktiviert Push-to-Talk (Mikrofon einschalten).\n"
            "    Antwort: {\"ok\": true, \"result\": \"PTT on\"}\n"
            "\n"
            "  GET /ptt/off\n"
            "    Deaktiviert Push-to-Talk.\n"
            "    Antwort: {\"ok\": true, \"result\": \"PTT off\"}\n"
            "\n"
            "  GET /ptt/toggle\n"
            "    Schaltet PTT um (an → aus → an …).\n"
            "    Antwort: {\"ok\": true, \"result\": \"PTT toggled\"}\n"
            "\n"
            "Stummschaltung:\n"
            "  GET /mute/on\n"
            "    Schaltet die gesamte Audioausgabe stumm.\n"
            "    Antwort: {\"ok\": true, \"result\": \"muted\"}\n"
            "\n"
            "  GET /mute/off\n"
            "    Hebt die Stummschaltung auf.\n"
            "    Antwort: {\"ok\": true, \"result\": \"unmuted\"}\n"
            "\n"
            "  GET /mute/toggle\n"
            "    Schaltet Stummschaltung um.\n"
            "    Antwort: {\"ok\": true, \"result\": \"mute toggled\"}\n"
            "\n"
            "Kanal:\n"
            "  GET /channel/<name>\n"
            "    Wechselt in den Kanal dessen Name <name> enthält (Teilstring).\n"
            "    Beispiel: /channel/Lobby\n"
            "    Antwort: {\"ok\": true, \"result\": \"joining Lobby\"}\n"
            "    Hinweis: Kanaltrennung erfolgt asynchron.\n"
            "\n"
            "Status:\n"
            "  GET /status/<text>\n"
            "    Setzt die Statusnachricht des eigenen Nutzers.\n"
            "    Leerzeichen als %20 oder + kodieren.\n"
            "    Beispiel: /status/Im%20Meeting\n"
            "    Antwort: {\"ok\": true, \"result\": \"status set: Im Meeting\"}\n"
            "\n"
            "TTS:\n"
            "  GET /speak/<text>\n"
            "    Liest <text> per TTS vor (URL-kodiert).\n"
            "    Beispiel: /speak/Hallo%20Welt\n"
            "    Antwort: {\"ok\": true, \"result\": \"speaking: Hallo Welt\"}\n"
            "\n"
            "Statusabfrage:\n"
            "  GET /info\n"
            "    Gibt den aktuellen App-Status als JSON zurück.\n"
            "    Antwort:\n"
            "      {\n"
            "        \"ok\": true,\n"
            "        \"result\": {\n"
            "          \"connected\": true,\n"
            "          \"channel\": \"Serverprofil-Schlüssel\"\n"
            "        }\n"
            "      }\n"
            "\n"
            "Praxisbeispiele\n"
            "---------------\n"
            "\n"
            "Shell / Terminal:\n"
            "  curl http://127.0.0.1:8765/ptt/on\n"
            "  curl http://127.0.0.1:8765/mute/toggle\n"
            "  curl http://127.0.0.1:8765/speak/Hallo%20Welt\n"
            "  curl http://127.0.0.1:8765/info\n"
            "\n"
            "Python:\n"
            "  import urllib.request\n"
            "  urllib.request.urlopen('http://127.0.0.1:8765/ptt/on')\n"
            "\n"
            "AppleScript (macOS):\n"
            "  do shell script \"curl -s http://127.0.0.1:8765/mute/toggle\"\n"
            "\n"
            "Streamdeck-Plugin (HTTP-Request-Aktion):\n"
            "  URL: http://127.0.0.1:8765/ptt/toggle\n"
            "  Methode: GET\n"
            "\n"
            "Home Assistant:\n"
            "  service: rest_command.teamtalk_ptt_toggle\n"
            "  Konfiguration in configuration.yaml:\n"
            "    rest_command:\n"
            "      teamtalk_ptt_toggle:\n"
            "        url: 'http://127.0.0.1:8765/ptt/toggle'\n"
            "\n"
            "Fehlerbehandlung\n"
            "----------------\n"
            "  Unbekannter Pfad:  HTTP 500, {\"ok\": false, \"error\": \"Unknown path: /xyz\"}\n"
            "  App nicht bereit:  HTTP 500, {\"ok\": false, \"error\": \"App not ready\"}\n"
            "\n"
            "\n"
            "26. Webhook-Integration\n"
            "========================\n"
            "Der Client sendet automatisch JSON-Payloads (HTTP POST) an eine konfigurierte\n"
            "URL, wenn bestimmte Ereignisse eintreten. So können externe Dienste wie\n"
            "n8n, Zapier, Home Assistant oder eigene Server auf App-Ereignisse reagieren.\n"
            "\n"
            "Konfiguration\n"
            "-------------\n"
            "Einstellungen → KI & Integration:\n"
            "  Webhook-URL:       Ziel-URL (muss mit http:// oder https:// beginnen).\n"
            "  Webhook-Ereignisse: Kommagetrennte Liste von Ereignissen, auf die\n"
            "                      reagiert werden soll. Leer = alle Ereignisse.\n"
            "\n"
            "Erlaubte URL-Schemata: http:// und https:// (andere werden abgewiesen).\n"
            "\n"
            "Payload-Format\n"
            "--------------\n"
            "Jeder POST enthält einen JSON-Body:\n"
            "\n"
            "  {\n"
            "    \"event\":   \"<Ereignisname>\",\n"
            "    \"ts\":      \"2026-03-29T14:23:01\",\n"
            "    \"app\":     \"TeamTalk VO Client\",\n"
            "    <ereignisspezifische Felder>\n"
            "  }\n"
            "\n"
            "HTTP-Header:\n"
            "  Content-Type: application/json\n"
            "  User-Agent: TeamTalkVOClient/2.7\n"
            "\n"
            "Timeout: 5 Sekunden. Fehlgeschlagene Anfragen werden im System-Log\n"
            "protokolliert, aber nicht erneut versucht.\n"
            "\n"
            "Unterstützte Ereignisse\n"
            "-----------------------\n"
            "\n"
            "private_msg – Privatnachricht empfangen\n"
            "  Felder: from_user (str), text (str)\n"
            "  Beispiel:\n"
            "  {\n"
            "    \"event\": \"private_msg\",\n"
            "    \"ts\": \"2026-03-29T14:23:01\",\n"
            "    \"app\": \"TeamTalk VO Client\",\n"
            "    \"from_user\": \"Alice\",\n"
            "    \"text\": \"Bist du da?\"\n"
            "  }\n"
            "\n"
            "channel_msg – Kanalnachricht empfangen\n"
            "  Felder: from_user (str), text (str)\n"
            "\n"
            "user_join – Benutzer hat Kanal betreten\n"
            "  Felder: user (str), channel (str)\n"
            "\n"
            "user_leave – Benutzer hat Kanal verlassen\n"
            "  Felder: user (str), channel (str)\n"
            "\n"
            "connect – Mit Server verbunden\n"
            "  Felder: server (str)\n"
            "\n"
            "disconnect – Verbindung getrennt\n"
            "  Felder: server (str)\n"
            "\n"
            "recording_start – Aufnahme gestartet\n"
            "  Felder: path (str)\n"
            "\n"
            "Praxisbeispiele\n"
            "---------------\n"
            "\n"
            "n8n-Webhook:\n"
            "  1. Neuer Workflow → Trigger: 'Webhook'\n"
            "  2. URL aus n8n kopieren und in den Client-Einstellungen eintragen.\n"
            "  3. Ereignisse filtern, z. B. nur private_msg.\n"
            "\n"
            "Eigener Python-Server:\n"
            "  from http.server import HTTPServer, BaseHTTPRequestHandler\n"
            "  import json\n"
            "  class Handler(BaseHTTPRequestHandler):\n"
            "      def do_POST(self):\n"
            "          length = int(self.headers['Content-Length'])\n"
            "          data = json.loads(self.rfile.read(length))\n"
            "          print('Ereignis:', data['event'])\n"
            "          self.send_response(200); self.end_headers()\n"
            "  HTTPServer(('', 9999), Handler).serve_forever()\n"
            "\n"
            "\n"
            "27. Sprache der Benutzeroberfläche\n"
            "====================================\n"
            "Der Client unterstützt Deutsch und Englisch.\n"
            "\n"
            "Umschalten: Einstellungen → Allgemein → Sprache.\n"
            "Hinweis: Ein Neustart ist erforderlich, damit die Sprache vollständig\n"
            "übernommen wird. Menüs, Dialoge und das Handbuch erscheinen dann\n"
            "in der gewählten Sprache.\n"
            "\n"
            "\n"
            "28. Plugin-Manager\n"
            "==================\n"
            "Plugins sind Python-Skripte, die den Client erweitern oder automatisieren\n"
            "ohne den Quellcode zu verändern. Sie reagieren auf App-Ereignisse und\n"
            "können aktiv in die App eingreifen (TTS, Nachrichten senden, Kanal wechseln).\n"
            "\n"
            "Plugin-Verzeichnis\n"
            "------------------\n"
            "Im App-Bundle:\n"
            "  TeamTalk VO Client.app/Contents/Resources/plugins/\n"
            "\n"
            "Im Entwicklungsmodus (Quellcode):\n"
            "  TeamTalk-VO-Client-macOS/plugins/\n"
            "\n"
            "Das Verzeichnis muss ggf. manuell angelegt werden.\n"
            "Alle *.py-Dateien darin werden beim App-Start automatisch geladen.\n"
            "Dateien die mit _ beginnen werden übersprungen.\n"
            "\n"
            "Plugin-Struktur\n"
            "---------------\n"
            "Ein Plugin ist eine einzelne Python-Datei:\n"
            "\n"
            "  # plugins/mein_plugin.py\n"
            "\n"
            "  metadata = {\n"
            "      \"name\":        \"Mein Plugin\",\n"
            "      \"version\":     \"1.0\",\n"
            "      \"description\": \"Tut etwas Nützliches\",\n"
            "      \"author\":      \"Dein Name\",\n"
            "  }\n"
            "\n"
            "  def register(bus, api):\n"
            "      \"\"\"Wird einmalig beim App-Start aufgerufen.\"\"\"\n"
            "      bus.on(\"connection_state_changed\", on_verbindung)\n"
            "\n"
            "  def on_verbindung(connected, reason):\n"
            "      if connected:\n"
            "          api.speak(\"Verbunden!\")\n"
            "\n"
            "Pflichtbestandteile:\n"
            "  register(bus, api)  – Einstiegspunkt; wird einmalig aufgerufen.\n"
            "\n"
            "Optional:\n"
            "  metadata            – Dict mit name, version, description, author.\n"
            "                        Wird im Einstellungs-Tab 'Plugins' angezeigt.\n"
            "\n"
            "EventBus (bus)\n"
            "--------------\n"
            "Der EventBus verbindet Plugins mit App-Ereignissen.\n"
            "\n"
            "  bus.on(event, handler)   – Handler für ein Ereignis registrieren.\n"
            "  bus.off(event, handler)  – Handler wieder entfernen.\n"
            "  bus.emit(event, **kw)    – Eigenes Ereignis auslösen.\n"
            "\n"
            "Verfügbare Ereignisse:\n"
            "\n"
            "  app_startup\n"
            "    Ausgelöst ca. 2 Sekunden nach vollständiger App-Initialisierung.\n"
            "    Parameter: (keine)\n"
            "\n"
            "  connection_state_changed\n"
            "    Verbindung hergestellt oder getrennt.\n"
            "    Parameter: connected (bool), reason (str)\n"
            "    reason: 'login' | 'failed' | 'lost'\n"
            "\n"
            "  user_joined\n"
            "    Benutzer hat einen Kanal betreten.\n"
            "    Parameter: user (str), user_id (int), channel_id (int), channel_name (str)\n"
            "\n"
            "  user_left\n"
            "    Benutzer hat einen Kanal verlassen.\n"
            "    Parameter: user (str), user_id (int), channel_id (int), channel_name (str)\n"
            "\n"
            "  chat_message\n"
            "    Nachricht empfangen oder gesendet.\n"
            "    Parameter: text (str), kind (str), from_user (str), from_id (int)\n"
            "    kind: 'chat' | 'private' | 'broadcast'\n"
            "\n"
            "  channel_joined\n"
            "    Ich bin einem Kanal beigetreten.\n"
            "    Parameter: channel_id (int)\n"
            "\n"
            "  file_transfer_complete\n"
            "    Dateiübertragung abgeschlossen.\n"
            "    Parameter: filename (str)\n"
            "\n"
            "PluginAPI (api)\n"
            "---------------\n"
            "Ermöglicht aktive Steuerung der App aus dem Plugin.\n"
            "\n"
            "TTS:\n"
            "  api.speak(text, kind='system')\n"
            "    Text per TTS vorlesen. Sicher aus jedem Thread aufrufbar.\n"
            "    kind: 'system' | 'chat' | 'private'\n"
            "\n"
            "Verbindungsstatus:\n"
            "  api.is_connected() → bool\n"
            "    True wenn mit Server verbunden.\n"
            "  api.get_server_name() → str\n"
            "    Konfigurierter Server-Name (leer = nicht verbunden).\n"
            "\n"
            "Nutzer & Kanal:\n"
            "  api.get_my_user_id() → int\n"
            "    Eigene User-ID (0 = nicht verbunden).\n"
            "  api.get_my_channel_id() → int\n"
            "    ID des eigenen Kanals (0 = kein Kanal).\n"
            "  api.get_channel_users(channel_id) → list\n"
            "    Nutzer im Kanal als Liste von dicts:\n"
            "    [{\"id\": 42, \"name\": \"Alice\", \"is_admin\": False}, ...]\n"
            "\n"
            "Nachrichten senden (immer aus Hintergrundthread aufrufen!):\n"
            "  api.send_channel_message(text, channel_id=0) → bool\n"
            "    Nachricht in eigenen Kanal (oder channel_id) senden.\n"
            "  api.send_private_message(user_id, text) → bool\n"
            "    Privatnachricht an Nutzer senden.\n"
            "\n"
            "Kanal:\n"
            "  api.join_channel(channel_id, password='')\n"
            "    In einen Kanal wechseln (asynchron via wx.CallAfter).\n"
            "\n"
            "Plugin-Konfiguration:\n"
            "  api.get_config(plugin_name) → PluginConfig\n"
            "    Persistenter Key-Value-Store pro Plugin.\n"
            "    Gespeichert in:\n"
            "    ~/Library/Application Support/TeamTalkVOClient/plugin_configs/\n"
            "\n"
            "    cfg = api.get_config('mein_plugin')\n"
            "    cfg.set('schluessel', 'wert')   # sofort gespeichert\n"
            "    cfg.get('schluessel', 'default') # lesen\n"
            "    cfg.delete('schluessel')          # löschen\n"
            "    cfg.all()                         # alle Einträge\n"
            "\n"
            "Threading-Regeln\n"
            "----------------\n"
            "Handler werden im GUI-Thread aufgerufen (EventBus ist synchron).\n"
            "\n"
            "  RICHTIG – blockierende Ops im Hintergrundthread:\n"
            "    import threading\n"
            "    def on_event(**kw):\n"
            "        threading.Thread(target=_mach_was, daemon=True).start()\n"
            "\n"
            "  FALSCH – blockiert den GUI-Thread:\n"
            "    def on_event(**kw):\n"
            "        time.sleep(5)  # friert die App ein!\n"
            "\n"
            "  api.speak() ist immer sicher (intern wx.CallAfter).\n"
            "  api.send_channel_message() muss aus Hintergrundthread aufgerufen werden.\n"
            "\n"
            "Beispiel-Plugins\n"
            "----------------\n"
            "\n"
            "1. Begrüßung bei Kanalzutritt:\n"
            "\n"
            "  metadata = {\"name\": \"Begrüßung\", \"version\": \"1.0\"}\n"
            "\n"
            "  def register(bus, api):\n"
            "      def on_join(user, channel_id, **kw):\n"
            "          if channel_id == api.get_my_channel_id():\n"
            "              api.speak(f\"Willkommen, {user}!\")\n"
            "      bus.on(\"user_joined\", on_join)\n"
            "\n"
            "2. Chat-Befehle (!ping, !nutzer):\n"
            "\n"
            "  import threading\n"
            "  metadata = {\"name\": \"Chat-Befehle\", \"version\": \"1.0\"}\n"
            "\n"
            "  def register(bus, api):\n"
            "      def on_chat(text, kind, from_user, from_id, **kw):\n"
            "          if kind != \"chat\" or not text.startswith(\"!\"):\n"
            "              return\n"
            "          if text.strip() == \"!ping\":\n"
            "              threading.Thread(\n"
            "                  target=lambda: api.send_channel_message(\n"
            "                      f\"{from_user}: pong!\"),\n"
            "                  daemon=True).start()\n"
            "      bus.on(\"chat_message\", on_chat)\n"
            "\n"
            "3. Verbindungsprotokoll in Datei schreiben:\n"
            "\n"
            "  import datetime, pathlib\n"
            "  metadata = {\"name\": \"Verbindungslog\", \"version\": \"1.0\"}\n"
            "  LOG = pathlib.Path.home() / \"teamtalk_verbindungen.log\"\n"
            "\n"
            "  def register(bus, api=None):\n"
            "      bus.on(\"connection_state_changed\", _log)\n"
            "\n"
            "  def _log(connected, reason):\n"
            "      ts = datetime.datetime.now().strftime(\"%Y-%m-%d %H:%M:%S\")\n"
            "      status = \"VERBUNDEN\" if connected else f\"GETRENNT ({reason})\"\n"
            "      with LOG.open(\"a\", encoding=\"utf-8\") as f:\n"
            "          f.write(f\"[{ts}] {status}\\n\")\n"
            "\n"
            "4. macOS-Desktop-Benachrichtigung bei Verbindungsverlust:\n"
            "\n"
            "  import subprocess\n"
            "  metadata = {\"name\": \"Verbindungsalarm\", \"version\": \"1.0\"}\n"
            "\n"
            "  def register(bus, api=None):\n"
            "      bus.on(\"connection_state_changed\", _alarm)\n"
            "\n"
            "  def _alarm(connected, reason):\n"
            "      if not connected:\n"
            "          subprocess.run([\"osascript\", \"-e\",\n"
            "              'display notification \"Verbindung verloren\" '\n"
            "              'with title \"TeamTalk VO Client\"'], check=False)\n"
            "\n"
            "Debugging\n"
            "---------\n"
            "Plugins können print() nutzen. Ausgaben erscheinen im Terminal wenn die\n"
            "App aus dem Quellcode gestartet wird:\n"
            "\n"
            "  cd TeamTalk-VO-Client-macOS\n"
            "  .venv/bin/python src/app.py\n"
            "\n"
            "Fehler beim Laden:\n"
            "  [PluginLoader] Fehler beim Laden von mein_plugin.py: <Ursache>\n"
            "Handler-Fehler:\n"
            "  [EventBus] Handler <fn> für '<event>' fehlgeschlagen: <Ursache>\n"
            "\n"
            "Häufige Probleme:\n"
            "  Plugin wird nicht geladen  – Dateiname beginnt mit '_'\n"
            "  Handler wird nicht aufgerufen – Falscher Event-Name (case-sensitiv)\n"
            "  App friert ein             – Blockierender Code im Handler\n"
            "  api ist None               – Altes Plugin mit register(bus) statt\n"
            "                               register(bus, api=None)\n"
        )

    def _get_manual_text_en(self) -> str:
        """English user manual."""
        return (
            f"TeamTalk VoiceOver Client – User Manual  (Version {APP_VERSION})\n"
            "=======================================================================\n"
            "\n"
            "Note: This manual is updated with each release.\n"
            "Current information is always available in the manual of the\n"
            "installed version.\n"
            "\n"
            "Table of Contents\n"
            "-----------------\n"
            " 1. Overview\n"
            " 2. Getting started\n"
            " 3. Tab: Connection\n"
            " 4. Tab: Channels & Chat\n"
            " 5. Tab: Chat\n"
            " 6. Tab: Audio\n"
            " 7. Tab: Recordings & Media\n"
            " 8. Tab: Files\n"
            " 9. Tab: Administration\n"
            "10. Tab: ElevenLabs TTS (Speak)\n"
            "11. Tab: Desktop\n"
            "12. Tab: Settings\n"
            "13. Tab: Shortcuts\n"
            "14. Tab: System log\n"
            "15. Tab: Video\n"
            "16. Menu bar\n"
            "17. Keyboard shortcuts\n"
            "18. Push-to-Talk and voice activation\n"
            "19. Text-to-Speech (espeak-ng)\n"
            "20. Platform differences (macOS / Windows / Linux)\n"
            "21. Automation (macros and triggers)\n"
            "22. Global hotkeys (macOS)\n"
            "23. Braille output\n"
            "24. AI features (Claude / Gemini)\n"
            "25. HTTP control API\n"
            "26. Webhook integration\n"
            "27. Interface language\n"
            "28. Plugin manager\n"
            "\n"
            "\n"
            "1. Overview\n"
            "===========\n"
            "TeamTalk VoiceOver Client is an accessible client for TeamTalk 5 servers,\n"
            "optimised for VoiceOver (macOS), NVDA/JAWS (Windows) and other screen readers.\n"
            "It enables voice and text communication, file transfer, media streaming\n"
            "and desktop sharing.\n"
            "\n"
            "\n"
            "2. Getting started\n"
            "==================\n"
            "The main window is divided into tabs. Use Ctrl+Tab / Shift+Ctrl+Tab to switch\n"
            "between tabs. On macOS, VoiceOver gestures address elements directly.\n"
            "\n"
            "Lists: All lists in the programme are built as simple ListBoxes.\n"
            "Entries are separated by commas so that screen readers can read them fluently.\n"
            "\n"
            "Status bar: Continuous feedback is displayed at the bottom of the window\n"
            "(connection status, actions, errors).\n"
            "\n"
            "\n"
            "3. Tab: Connection\n"
            "==================\n"
            "Manage server profiles and establish connections here.\n"
            "\n"
            "Section 'Server profile'\n"
            "  Profile list:    List of saved profiles. Selecting one loads its data.\n"
            "  New:             Create an empty profile.\n"
            "  Duplicate:       Copy the selected profile.\n"
            "  Delete:          Remove the selected profile.\n"
            "  Save:            Save current input to the profile.\n"
            "\n"
            "Section 'Connection data'\n"
            "  Profile name:    Display name for the profile (local only).\n"
            "  Server host:     Hostname or IP address of the TeamTalk server.\n"
            "  TCP port:        TCP port (default: 10333).\n"
            "  UDP port:        UDP port (default: 10333).\n"
            "  Username:        Login name. Leave empty for guest login.\n"
            "  Password:        Password (empty = no password).\n"
            "  Nickname:        Display name shown in the channel.\n"
            "  Channel:         Channel to join automatically after login.\n"
            "  Channel password: Password for the target channel (if required).\n"
            "  Server password: Server entry password.\n"
            "\n"
            "Section 'Actions'\n"
            "  Connect:         Connect with the entered data.\n"
            "  Disconnect:      Disconnect from the server.\n"
            "  Reconnect:       Reconnect to the last used server.\n"
            "\n"
            "Section 'Connection status'\n"
            "  Shows the current connection status (Disconnected / Connected / Logged in).\n"
            "\n"
            "Options\n"
            "  Auto-reconnect: When active, the programme reconnects automatically\n"
            "  after a connection loss.\n"
            "\n"
            "Import (.tt file): Import a server directly from a .tt file.\n"
            "Export (.tt file): Save the selected server as a .tt file.\n"
            "Check status: Test TCP reachability of all servers (✓ / ✗).\n"
            "Ping history: Shows average/min/max of the last 10 measurements.\n"
            "\n"
            "\n"
            "4. Tab: Channels & Chat\n"
            "=======================\n"
            "Shows the channel structure of the server, users and chat.\n"
            "\n"
            "Section 'Channel list'\n"
            "  Flat list of all channels and users on the server.\n"
            "  Indentation shows channel depth (spaces = sub-level).\n"
            "  Enter or double-click: Join channel.\n"
            "\n"
            "Section 'Users in channel'\n"
            "  Users appear as entries below their channel.\n"
            "  Entry format: Nickname, status, properties\n"
            "\n"
            "Context menu on user (right-click or application key):\n"
            "  User info:              Show detailed information.\n"
            "  Announce user info:     Output info via TTS.\n"
            "  Send message:           Send a private message.\n"
            "  Adjust volume:          Set individual volume for this user.\n"
            "  Louder / Quieter:       Increase / decrease volume by 10%.\n"
            "  Mute voice:             Mute this user's voice.\n"
            "  Mute media stream:      Mute this user's media stream.\n"
            "  Forward voice:          Forward voice to another channel.\n"
            "  Forward media stream:   Forward media stream.\n"
            "  Operator:               Make / demote user as channel operator.\n"
            "  Kick:                   Remove user from channel.\n"
            "  Kick + ban:             Kick and ban user from channel.\n"
            "  Kick from server:       Remove user from the entire server.\n"
            "  Kick from server + ban: Remove from server and set IP ban.\n"
            "  Ban on server:          Add IP address to server ban list.\n"
            "  Transmission rights:    Manage subscriptions (voice, video, desktop,\n"
            "                          media, messages) for this user.\n"
            "  Subscriptions:          Manage own subscriptions for this user.\n"
            "  Move to channel:        Move user to another channel.\n"
            "  Save target channel:    Save current channel as move target.\n"
            "  To saved channel:       Move user to the saved target channel.\n"
            "  Mute all:               Mute all users in the channel.\n"
            "\n"
            "\n"
            "5. Tab: Chat\n"
            "============\n"
            "Send and receive text messages.\n"
            "\n"
            "Section 'Chat target'\n"
            "  Shows where messages will be sent.\n"
            "  Private (checkbox): Enables private chat.\n"
            "  Private to (dropdown): Recipient for private messages.\n"
            "\n"
            "Chat history:\n"
            "  Multi-line text field, read-only. Colour coding:\n"
            "    Black = Channel message\n"
            "    Blue  = Private message\n"
            "    Green = Own message\n"
            "    Grey  = System message\n"
            "\n"
            "Enter message: Input field + Send button (or Enter).\n"
            "\n"
            "Chat history management:\n"
            "  Export history: Save current chat as a TXT file.\n"
            "  Clear history:  Delete chat history (optionally including saved file).\n"
            "  Save chat history (Settings): Saves up to 200 entries per server.\n"
            "\n"
            "\n"
            "6. Tab: Audio\n"
            "=============\n"
            "Configure audio devices and transmission options.\n"
            "\n"
            "First start – setting up audio\n"
            "  On first start, microphone and speakers are not yet active.\n"
            "  Steps:\n"
            "  1. Open the 'Audio' tab.\n"
            "  2. Under 'Devices', select the desired input device (microphone).\n"
            "  3. Select the desired output device (speakers / headphones).\n"
            "  4. Press 'Apply audio' – the devices are now activated.\n"
            "  Without this step, voice can neither be sent nor received.\n"
            "  Note: Voice activation is disabled by default. After applying the\n"
            "  devices it can be enabled here (checkbox 'Voice activation') or\n"
            "  you can use Push-to-Talk.\n"
            "\n"
            "Section 'Devices'\n"
            "  Input device:  Microphone for transmission (dropdown).\n"
            "  Output device: Speakers / headphones (dropdown).\n"
            "\n"
            "Section 'Voice activation'\n"
            "  Voice activation (checkbox): Activate microphone automatically on speech.\n"
            "  Activation level (0–100):    Threshold for voice activation.\n"
            "  Hold time (ms, 0–5000):      How long to keep sending after speech ends.\n"
            "\n"
            "Section 'Levels and volume'\n"
            "  Microphone gain (0–32000): Microphone sensitivity.\n"
            "  Output volume (0–32000):   Output volume.\n"
            "\n"
            "Section 'VU meter'\n"
            "  Shows the current microphone level as a progress bar (Audio tab only).\n"
            "\n"
            "Section 'Output'\n"
            "  Mute output (checkbox): Mute entire output.\n"
            "\n"
            "Section 'Device effects'\n"
            "  AGC (checkbox):              Automatic gain control.\n"
            "  Noise suppression:           Reduce background noise.\n"
            "  Echo cancellation:           Suppress echoes from the microphone.\n"
            "  Apply effects (button):      Activate selected effects.\n"
            "\n"
            "Section 'Preprocessing'\n"
            "  Selection: None / SpeexDSP / WebRTC. Takes effect immediately.\n"
            "\n"
            "Section 'Actions'\n"
            "  Duplex mode (checkbox):   Run input and output together.\n"
            "  Refresh devices:          Re-read device list.\n"
            "  Apply audio:              Activate selected devices and settings.\n"
            "  Push-to-Talk (checkbox):  Enable PTT mode (hold Space to speak).\n"
            "  Microphone test (checkbox): Hear your own voice as a check.\n"
            "\n"
            "Section 'PTT hotkey'\n"
            "  Record hotkey: Record a key as PTT hotkey within the app.\n"
            "  Note: Hotkey only works when the programme window is active.\n"
            "\n"
            "Section 'Save audio settings'\n"
            "  Apply audio settings on start (checkbox):\n"
            "    Automatically load saved settings at programme start.\n"
            "  Auto-apply on device change (checkbox):\n"
            "    Apply automatically when a device is connected/disconnected.\n"
            "  Save current audio settings: Save all settings.\n"
            "  Apply saved audio settings:  Load saved values.\n"
            "  Delete saved audio settings: Remove saved values.\n"
            "\n"
            "Section 'Local playback'\n"
            "  Plays an audio file locally – only you hear the playback,\n"
            "  nothing is streamed to the channel. Available to all users.\n"
            "  File:     Path to audio file (Browse button opens file dialog).\n"
            "  Play:     Start playback (supported: MP3, WAV, OGG, FLAC, M4A).\n"
            "  Pause /\n"
            "  Resume:   Pause and resume playback.\n"
            "  Stop:     End playback.\n"
            "\n"
            "\n"
            "7. Tab: Recordings & Media\n"
            "==========================\n"
            "\n"
            "Section 'Recording'\n"
            "  Format (dropdown): WAV, MP3 (16/32/64/128/256/320 kbit).\n"
            "  Start recording: Select save location, then start recording.\n"
            "  Stop recording: End the running recording.\n"
            "\n"
            "Section 'Record conversations'\n"
            "  Auto-record (checkbox): Record all users' conversations.\n"
            "  Target folder: Folder where files are saved.\n"
            "  Filename: Name pattern with placeholders (%Y%m%d-%H%M%S #%userid% %username%).\n"
            "  Format: WAV, MP3 128k or 256k.\n"
            "  Include own voice (checkbox).\n"
            "  Apply: Apply settings.\n"
            "\n"
            "Section 'Media streaming'\n"
            "  Streaming source (dropdown):\n"
            "    File:       Stream a local audio/video file (WAV, MP3, OGG, MP4, AVI...).\n"
            "    YouTube:    Stream a YouTube video via URL or search (yt-dlp).\n"
            "    SoundCloud: Stream a SoundCloud track via URL or search (yt-dlp).\n"
            "    Twitch:     Stream a Twitch channel via URL (yt-dlp, no search).\n"
            "    Bandcamp:   Stream a Bandcamp track via URL (yt-dlp, no search).\n"
            "    Vimeo:      Stream a Vimeo video via URL (yt-dlp, no search).\n"
            "    Mixcloud:   Stream a Mixcloud mix via URL (yt-dlp, no search).\n"
            "    Web radio:  Live stream from built-in station list or custom URL.\n"
            "    Podcasts:   Podcast search (iTunes API) or load RSS feed directly.\n"
            "    Playlist:   Stream multiple local files as a playlist (see below).\n"
            "\n"
            "  File streaming:\n"
            "    Browse: Select file.\n"
            "    Play / Pause / Stop.\n"
            "    Position (0–1000): Seek within the file.\n"
            "    Streaming volume (25–400): Volume of the streamed signal.\n"
            "\n"
            "  YouTube/SoundCloud (yt-dlp with search):\n"
            "    Search: Enter a term, press Search, select result from list.\n"
            "    Link: Enter URL directly, press Stream.\n"
            "    Pause / Stop.\n"
            "\n"
            "  Web radio:\n"
            "    Station list: Preset stations (90s90s, 80s80s, TechnoBase, etc.).\n"
            "    Web radio search: Online search via Radio Browser API.\n"
            "    Stream URL: Enter a custom URL and stream it.\n"
            "\n"
            "  Podcasts:\n"
            "    Podcast search: Search via iTunes API.\n"
            "    Feed URL: Enter an RSS feed URL directly and load it.\n"
            "    Episode list: Select an episode and stream it.\n"
            "\n"
            "  Playlist:\n"
            "    Playlist list:   Shows all tracks (filename only).\n"
            "    Add...:          Multi-select local audio files (MP3, WAV, OGG,\n"
            "                     FLAC, M4A, Opus, MP4, AVI, MKV).\n"
            "    Load M3U...:     Import an existing M3U or M3U8 file.\n"
            "                     Relative paths are resolved relative to the M3U file.\n"
            "    Remove:          Delete selected track from playlist.\n"
            "    Move up /\n"
            "    Move down:       Change track order.\n"
            "    Export as M3U...: Save current playlist as .m3u file.\n"
            "    Clear:           Remove all tracks.\n"
            "    Auto-advance (checkbox): Automatically play next track when current ends.\n"
            "    Play:            Start streaming from the selected track.\n"
            "    Pause / Stop:    Pause / end playback.\n"
            "    Streaming volume: Volume of the streamed signal (25–400).\n"
            "\n"
            "\n"
            "8. Tab: Files\n"
            "=============\n"
            "File transfer in the current channel.\n"
            "\n"
            "File list: Shows all files in the channel.\n"
            "  Entry format: Filename, size, uploaded by, date\n"
            "\n"
            "Upload:   Upload a file from the local computer to the channel.\n"
            "Download: Download the selected file (choose save location).\n"
            "Delete:   Delete the selected file from the channel (confirmation dialog).\n"
            "Refresh:  Reload the file list.\n"
            "\n"
            "Transfer progress: Progress bar during upload/download.\n"
            "\n"
            "\n"
            "9. Tab: Administration\n"
            "======================\n"
            "Only available to users with administrator rights.\n"
            "\n"
            "Section 'User accounts'\n"
            "  Columns: Username, type (Standard/Administrator), note.\n"
            "  Load accounts: Load the account list from the server.\n"
            "  Add account: Create a new account (username, password, note, type).\n"
            "  Delete account: Remove the selected account (confirmation dialog).\n"
            "\n"
            "Section 'Bans'\n"
            "  Columns: IP address, username, timestamp.\n"
            "  Load bans:        Load ban list from server.\n"
            "  Unban:            Remove the selected ban.\n"
            "  Ban IP address...: Directly ban an IP address without the user\n"
            "                     needing to be connected. Text input dialog.\n"
            "\n"
            "Section 'Server properties'\n"
            "  Server name, MOTD (welcome message), max. users.\n"
            "  Load:               Read current server values.\n"
            "  Save:               Write changed values to the server.\n"
            "  Save configuration: Save the server configuration file.\n"
            "\n"
            "\n"
            "10. Tab: ElevenLabs TTS (Speak)\n"
            "================================\n"
            "Have your own AI voice speak into the channel via ElevenLabs.\n"
            "\n"
            "Prerequisite: ElevenLabs API key.\n"
            "Enter the API key in Settings:\n"
            "  Settings → Section 'ElevenLabs' → Field 'API key'\n"
            "  → Press Save.\n"
            "The key applies globally to all server profiles. It is automatically\n"
            "passed to the Speak tab on the next connection.\n"
            "\n"
            "Operation:\n"
            "  Voice / Model: Select from lists loaded via the API.\n"
            "  Refresh:       Reload voices and models from the API.\n"
            "  Stability (0–100):    Voice stability.\n"
            "  Similarity (0–100):   Similarity to the original voice.\n"
            "  Style (0–100):        Style exaggeration.\n"
            "  Speaker boost:        Enhance speaker clarity (not for v3 models).\n"
            "  Text:                 Enter the text to be spoken.\n"
            "  Speak:                Generate audio and stream it to the channel.\n"
            "  Stop:                 Stop streaming.\n"
            "\n"
            "\n"
            "11. Tab: Desktop\n"
            "================\n"
            "Desktop sharing: Transmit your own screen to the channel.\n"
            "\n"
            "Section 'Send desktop'\n"
            "  Send desktop (checkbox): Start/stop continuous transmission.\n"
            "  FPS: Frame rate (1, 2, 5 or 10 frames/second).\n"
            "  Scale: Reduce image size (25%, 50%, 75%, 100%).\n"
            "  Send once: Send a single frame.\n"
            "  End sharing: Stop transmission.\n"
            "\n"
            "Section 'Desktop control (remote)'\n"
            "  Left click / Right click / Middle click:\n"
            "  Send a mouse click to the desktop receiver.\n"
            "\n"
            "Section 'Status'\n"
            "  Shows the current sharing status.\n"
            "\n"
            "\n"
            "12. Tab: Settings\n"
            "=================\n"
            "\n"
            "Use the search field at the top to jump directly to a section.\n"
            "\n"
            "Section 'General'\n"
            "  Language:            Interface language (German / English). Restart required.\n"
            "  Gender:              Reported to the server (Male/Female/Neutral).\n"
            "  Away timer:          Automatically set 'Away' after X minutes of inactivity.\n"
            "  BearWare account:    BearWare ID and token for registered users.\n"
            "  Save chat history:   Save history per server and reload on next connection.\n"
            "  Auto-join last channel: Automatically join the last channel after connecting.\n"
            "  Show timestamps:     Add [HH:MM:SS] prefix to chat messages.\n"
            "\n"
            "Section 'Display'\n"
            "  Tray icon:           Minimise programme to system tray.\n"
            "  Always on top:       Keep window always in front.\n"
            "  Channel name in title: Show channel and user count in title bar.\n"
            "  Show toolbar:        Display button toolbar.\n"
            "  Event log:           Log system events.\n"
            "  VU meter:            Show input level meter.\n"
            "\n"
            "Section 'Connection'\n"
            "  Default subscriptions: Default subscriptions for new users.\n"
            "  Bind local port:     Specify local UDP/TCP port.\n"
            "\n"
            "Section 'Sound events'\n"
            "  18 events can be assigned sounds:\n"
            "    User joined, left, channel changed, connected, disconnected,\n"
            "    message received, private received, transmission started/stopped,\n"
            "    question mode, video start, desktop start, file start, recording start,\n"
            "    hotkey pressed, error.\n"
            "  Volume: Volume of event sounds.\n"
            "  Playback device: Output device for sounds.\n"
            "\n"
            "Section 'Audio'\n"
            "  See Tab Audio (audio settings are mirrored here).\n"
            "\n"
            "Section 'Video'\n"
            "  Configure video camera.\n"
            "\n"
            "Section 'Shortcuts'\n"
            "  See Tab Shortcuts.\n"
            "\n"
            "Section 'System & TTS'\n"
            "  Enable TTS (checkbox).\n"
            "  Read chat / Read private / Read system / Read own.\n"
            "  Interrupt: Stop running output when a new message arrives.\n"
            "  Language: ISO language code (e.g. 'de', 'en').\n"
            "  Voice: espeak-ng voice (e.g. 'de', 'en', 'Linda', 'Max').\n"
            "  Speed (80–450): Speaking rate in words per minute.\n"
            "  Volume (0–200): TTS output volume.\n"
            "  espeak-ng path: Manual path to the espeak-ng binary.\n"
            "  Select voice: Dialog to browse available voices.\n"
            "  Save settings.\n"
            "\n"
            "\n"
            "13. Tab: Shortcuts\n"
            "==================\n"
            "In-app hotkeys (active window only):\n"
            "  Mute all:                  Mute/unmute all users.\n"
            "  Toggle voice activation:   Enable/disable VA.\n"
            "  Toggle video:              Start/stop video transmission.\n"
            "  Announce input level:      Read current microphone level via TTS.\n"
            "  Announce user info:        Read info about selected user via TTS.\n"
            "  Announce ping:             Read current ping via TTS.\n"
            "  Announce braille status:   Read configured status fields via TTS.\n"
            "  Reply to last sender:      Open reply to the last private message sender.\n"
            "  Cycle sound profile:       Switch between sound profiles.\n"
            "  Cycle braille verbosity:   Toggle braille verbosity level.\n"
            "  AI summary:                Summarise recent chat messages with AI.\n"
            "  Bookmark 1/2/3:            Join saved bookmark channels.\n"
            "  Toggle recording:          Start/stop recording.\n"
            "  Status template 1/2/3:     Set predefined status messages.\n"
            "  Mic boost up/down:         Increase/decrease microphone gain.\n"
            "  Cancel TTS:                Stop running TTS and clear queue.\n"
            "\n"
            "Global hotkeys (macOS, system-wide):\n"
            "  PTT and mute work even in the background.\n"
            "  Enable and then record keys.\n"
            "\n"
            "Record hotkey: Press button, then press the desired key.\n"
            "ESC = cancel recording.\n"
            "\n"
            "\n"
            "14. Tab: System log\n"
            "===================\n"
            "Log of internal events (connection, errors, TTS messages).\n"
            "Copy log: Copy contents to clipboard.\n"
            "Clear log: Reset the log.\n"
            "\n"
            "\n"
            "15. Tab: Video\n"
            "==============\n"
            "Video camera transmission.\n"
            "Select video camera and start transmission.\n"
            "\n"
            "\n"
            "16. Menu bar\n"
            "============\n"
            "\n"
            "Menu 'File'\n"
            "  New window:   Open a further client instance.\n"
            "  Settings:     Open Settings tab (Cmd+,).\n"
            "  Quit:         Close the programme.\n"
            "\n"
            "Menu 'Channel'\n"
            "  Create:               Create a new channel.\n"
            "  Edit:                 Change channel settings.\n"
            "  Delete:               Remove channel (admin).\n"
            "  Join:                 Join the selected channel.\n"
            "  Leave:                Leave the current channel.\n"
            "  Announce info:        Output channel info via TTS.\n"
            "  Announce statistics:  Read channel statistics via TTS.\n"
            "  Announce status:      Read channel status via TTS.\n"
            "  Copy TT URL:          Copy TeamTalk URL to clipboard.\n"
            "  Channel bans:         Show channel ban list.\n"
            "  Channel message:      Send message to everyone in the channel.\n"
            "  Upload file:          Upload file to channel.\n"
            "  Download file:        Download file from channel.\n"
            "  Delete file:          Remove file from channel.\n"
            "  Refresh file list:    Reload file list.\n"
            "  Streaming (File/YouTube/SoundCloud/...): Start media streaming.\n"
            "\n"
            "Menu 'User'\n"
            "  All actions as in the context menu (Tab Channels, Section 4).\n"
            "\n"
            "Menu 'Server'\n"
            "  Users online:         List of all connected users.\n"
            "                        Contains a search field: enter username and\n"
            "                        press Enter or click 'Search' to highlight the entry.\n"
            "  Broadcast message:    Send message to all users (admin).\n"
            "  Server statistics:    Show server metrics.\n"
            "  Server bans:          Show server IP ban list.\n"
            "  Administration:       Open Admin tab.\n"
            "  Server properties:    Edit name, MOTD, max users.\n"
            "  Save configuration:   Save configuration on the server.\n"
            "\n"
            "Menu 'Profile'\n"
            "  Change nickname:      Change display name.\n"
            "  Change status:        Set status message.\n"
            "  Question mode:        Raise / lower hand (toggle).\n"
            "  Hear yourself:        Hear your own voice via output (loopback).\n"
            "  Toggle TTS:           Enable/disable Text-to-Speech globally.\n"
            "  Desktop sharing:      Start/stop desktop sharing.\n"
            "\n"
            "Menu 'Notifications'\n"
            "  Chat TTS:    Enable/disable TTS for channel messages.\n"
            "  Private TTS: Enable/disable TTS for private messages.\n"
            "  System TTS:  Enable/disable TTS for system messages.\n"
            "  Own TTS:     Enable/disable TTS for own messages.\n"
            "\n"
            "Menu 'Audio'\n"
            "  Push-to-Talk:          Toggle PTT mode.\n"
            "  Voice activation:      Toggle VA.\n"
            "  Audio settings:        Open Audio tab.\n"
            "  AGC / Noise suppression / Echo cancellation: Toggle effects.\n"
            "  Apply effects:         Activate selected effects.\n"
            "  Apply audio:           Apply device configuration.\n"
            "  Refresh devices:       Re-read device list.\n"
            "  Microphone test:       Start/stop self-test loop.\n"
            "  Mute all:              Mute all users.\n"
            "\n"
            "Menu 'Video'\n"
            "  Send video:            Start/stop video transmission.\n"
            "  Video settings:        Open Video tab.\n"
            "  Refresh devices:       Update camera list.\n"
            "\n"
            "Menu 'Recordings'\n"
            "  Start recording:       Record channel audio.\n"
            "  Stop recording:        End recording.\n"
            "  Record conversations:  Configure conversation recording.\n"
            "  Browse recordings:     Open the recording browser.\n"
            "\n"
            "Menu 'Automation'\n"
            "  Macro editor...:       Create and manage macros.\n"
            "  Scheduled macros...:   Schedule macros to run at specific times.\n"
            "  Trigger rules...:      Define event-based macro triggers.\n"
            "\n"
            "Menu 'Help'\n"
            "  Settings:              Open settings (Cmd+,).\n"
            "  Export logs:           Save system log to file.\n"
            "  Connection statistics: Show client network statistics.\n"
            "  Announce statistics:   Read statistics via TTS.\n"
            "  Manual:                Show this manual.\n"
            "  Shortcut reference:    Show configured hotkeys.\n"
            "  Changelog:             Show version changes.\n"
            "  About:                 Programme info, credits, licences.\n"
            "\n"
            "\n"
            "17. Keyboard shortcuts\n"
            "======================\n"
            "  Cmd+,          Open Settings (macOS)\n"
            "  Cmd+W          Close dialog/window\n"
            "  Space          Push-to-Talk (hold) – when PTT is active\n"
            "  Ctrl+Tab       Next tab\n"
            "  Shift+Ctrl+Tab Previous tab\n"
            "\n"
            "Configurable hotkeys (Tab Shortcuts):\n"
            "  Mute all\n"
            "  Toggle voice activation\n"
            "  Toggle video\n"
            "  ... (see Tab Shortcuts for full list)\n"
            "\n"
            "\n"
            "18. Push-to-Talk and voice activation\n"
            "======================================\n"
            "Push-to-Talk (PTT):\n"
            "  Enable 'Push-to-Talk' in the Audio tab.\n"
            "  Hold Space = microphone active.\n"
            "  Alternative hotkey: Record under 'PTT hotkey' in the Audio tab.\n"
            "  Note: Only works when the programme window is active.\n"
            "  On macOS: Activate global PTT in Tab Shortcuts for background operation.\n"
            "\n"
            "Voice activation (VA):\n"
            "  Enable 'Voice activation' in the Audio tab.\n"
            "  Set level: How loud it must be for the microphone to activate.\n"
            "  Hold time: How long the microphone keeps transmitting after silence.\n"
            "  PTT and VA are mutually exclusive: using PTT does not send via VA.\n"
            "\n"
            "\n"
            "19. Text-to-Speech (espeak-ng)\n"
            "==============================\n"
            "The client includes espeak-ng for speech output.\n"
            "Configuration in Tab Settings, Section 'System & TTS':\n"
            "  Language: e.g. 'de' for German, 'en' for English.\n"
            "  Voice:    espeak-ng voice (empty = language used directly).\n"
            "            Browse voice list via 'Select voice'.\n"
            "  Speed (80–450): Higher value = faster output.\n"
            "  Volume (0–200): Default = 100.\n"
            "  Interrupt: Immediately stop running output when a new message arrives.\n"
            "\n"
            "What is read aloud?\n"
            "  - Chat messages (when 'Read chat' is active)\n"
            "  - Private messages (when 'Read private' is active)\n"
            "  - System messages (when 'Read system' is active)\n"
            "  - Own messages (when 'Read own' is active)\n"
            "\n"
            "\n"
            "20. Platform differences\n"
            "========================\n"
            "\n"
            "macOS\n"
            "  Primary platform. Full VoiceOver support.\n"
            "  All controls have correct roles (button, dropdown, list, etc.).\n"
            "  Audio output: afplay.\n"
            "  TTS: espeak-ng (bundled) with afplay.\n"
            "  PTT hotkey only with active window unless global hotkeys are enabled.\n"
            "\n"
            "Windows\n"
            "  NVDA and JAWS are supported.\n"
            "  Audio output: winsound.\n"
            "  TTS: espeak-ng (bundled) with winsound.\n"
            "  PTT hotkey: Space and configured hotkey work.\n"
            "\n"
            "Linux\n"
            "  Basic support available.\n"
            "  Audio output via espeak-ng directly (no afplay/winsound).\n"
            "  Screen reader support depends on wxGTK.\n"
            "\n"
            "\n"
            "21. Automation (macros and triggers)\n"
            "=====================================\n"
            "Three tools are available via the 'Automation' menu:\n"
            "\n"
            "Macro editor (Automation → Macro editor...)\n"
            "  Create, edit and delete macros.\n"
            "  Each macro has a name and an action list.\n"
            "  Action types:\n"
            "    speak   – Read text via TTS.\n"
            "    channel – Switch to a channel by name.\n"
            "    status  – Set status message.\n"
            "    ptt     – PTT control (on/off/toggle).\n"
            "    wait    – Pause in milliseconds.\n"
            "  Macros can be run manually or started by schedule/trigger.\n"
            "\n"
            "Scheduled macros (Automation → Scheduled macros...)\n"
            "  Run a macro daily at a configured time (HH:MM).\n"
            "  Multiple schedules are possible.\n"
            "\n"
            "Trigger rules (Automation → Trigger rules...)\n"
            "  Run macros automatically on events.\n"
            "  Supported events:\n"
            "    user_join    – A user enters a channel.\n"
            "    user_leave   – A user leaves a channel.\n"
            "    chat_message – Channel message received.\n"
            "    private_msg  – Private message received.\n"
            "    channel_join – I join a channel.\n"
            "  Optional name filter: Only trigger if the username contains the entered text.\n"
            "\n"
            "\n"
            "22. Global hotkeys (macOS)\n"
            "==========================\n"
            "On macOS, PTT and mute can work system-wide,\n"
            "even when the programme window is in the background.\n"
            "\n"
            "Enable: Tab Shortcuts → 'Enable global hotkeys' (checkbox).\n"
            "Note: macOS will ask for keyboard access permissions –\n"
            "these must be granted once in System Settings → Privacy &\n"
            "Security → Accessibility.\n"
            "\n"
            "Configurable global hotkeys:\n"
            "  PTT (push-to-talk): Activate microphone while held.\n"
            "  Mute all:           Mute/unmute total output.\n"
            "\n"
            "Note: In-app hotkeys (Tab 13) only work when the programme\n"
            "window has focus.\n"
            "\n"
            "\n"
            "23. Braille output\n"
            "==================\n"
            "The client can provide structured status information via a\n"
            "configurable braille output.\n"
            "\n"
            "Configuration: Settings → AI & Integration → Braille output.\n"
            "Fields: Channel, user count, ping, mute status, connection status.\n"
            "\n"
            "Hotkey 'Announce braille status': Reads the current status via TTS.\n"
            "Configurable in Tab Shortcuts.\n"
            "\n"
            "\n"
            "24. AI features (Claude / Gemini)\n"
            "==================================\n"
            "The client supports AI-powered chat summaries.\n"
            "\n"
            "Prerequisite: API key in Settings → AI & Integration.\n"
            "  Claude API key:  For Anthropic Claude.\n"
            "  Gemini API key:  For Google Gemini.\n"
            "  AI provider:     Select which service to use.\n"
            "\n"
            "Hotkey 'AI summary': Summarises recent chat messages.\n"
            "Result is read aloud via TTS.\n"
            "\n"
            "\n"
            "25. HTTP control API\n"
            "====================\n"
            "The built-in HTTP API allows remote control of the client from any\n"
            "programme that can send HTTP requests – e.g. Streamdeck, Home Assistant,\n"
            "shell scripts, Automator (macOS), n8n, Node-RED, and more.\n"
            "\n"
            "Enabling\n"
            "--------\n"
            "Settings → AI & Integration → 'Enable HTTP API' (checkbox).\n"
            "Default port: 8765. Changeable in the 'HTTP API port' field.\n"
            "Takes effect immediately; no restart required.\n"
            "\n"
            "Security note\n"
            "-------------\n"
            "The server listens exclusively on 127.0.0.1 (localhost) – no network\n"
            "access. No authentication: any local process of the same user can call\n"
            "the API.\n"
            "\n"
            "Response format\n"
            "---------------\n"
            "All endpoints respond with JSON:\n"
            "\n"
            "  Success: {\"ok\": true,  \"result\": <value or text>}\n"
            "  Error:   {\"ok\": false, \"error\": \"description\"}\n"
            "\n"
            "HTTP status code: 200 on success, 500 on error.\n"
            "\n"
            "Endpoints\n"
            "---------\n"
            "All requests are HTTP GET.\n"
            "\n"
            "PTT control:\n"
            "  GET /ptt/on\n"
            "    Enable Push-to-Talk (turn on microphone).\n"
            "    Response: {\"ok\": true, \"result\": \"PTT on\"}\n"
            "\n"
            "  GET /ptt/off\n"
            "    Disable Push-to-Talk.\n"
            "    Response: {\"ok\": true, \"result\": \"PTT off\"}\n"
            "\n"
            "  GET /ptt/toggle\n"
            "    Toggle PTT (on → off → on …).\n"
            "    Response: {\"ok\": true, \"result\": \"PTT toggled\"}\n"
            "\n"
            "Mute control:\n"
            "  GET /mute/on\n"
            "    Mute the entire audio output.\n"
            "    Response: {\"ok\": true, \"result\": \"muted\"}\n"
            "\n"
            "  GET /mute/off\n"
            "    Unmute audio output.\n"
            "    Response: {\"ok\": true, \"result\": \"unmuted\"}\n"
            "\n"
            "  GET /mute/toggle\n"
            "    Toggle mute.\n"
            "    Response: {\"ok\": true, \"result\": \"mute toggled\"}\n"
            "\n"
            "Channel:\n"
            "  GET /channel/<name>\n"
            "    Join the channel whose name contains <name> (substring match).\n"
            "    Example: /channel/Lobby\n"
            "    Response: {\"ok\": true, \"result\": \"joining Lobby\"}\n"
            "    Note: Channel joining is asynchronous.\n"
            "\n"
            "Status:\n"
            "  GET /status/<text>\n"
            "    Set the status message of your user.\n"
            "    Encode spaces as %20 or +.\n"
            "    Example: /status/In%20a%20meeting\n"
            "    Response: {\"ok\": true, \"result\": \"status set: In a meeting\"}\n"
            "\n"
            "TTS:\n"
            "  GET /speak/<text>\n"
            "    Read <text> aloud via TTS (URL-encoded).\n"
            "    Example: /speak/Hello%20World\n"
            "    Response: {\"ok\": true, \"result\": \"speaking: Hello World\"}\n"
            "\n"
            "Status query:\n"
            "  GET /info\n"
            "    Returns the current app status as JSON.\n"
            "    Response:\n"
            "      {\n"
            "        \"ok\": true,\n"
            "        \"result\": {\n"
            "          \"connected\": true,\n"
            "          \"channel\": \"server-profile-key\"\n"
            "        }\n"
            "      }\n"
            "\n"
            "Practical examples\n"
            "------------------\n"
            "\n"
            "Shell / Terminal:\n"
            "  curl http://127.0.0.1:8765/ptt/on\n"
            "  curl http://127.0.0.1:8765/mute/toggle\n"
            "  curl http://127.0.0.1:8765/speak/Hello%20World\n"
            "  curl http://127.0.0.1:8765/info\n"
            "\n"
            "Python:\n"
            "  import urllib.request\n"
            "  urllib.request.urlopen('http://127.0.0.1:8765/ptt/on')\n"
            "\n"
            "AppleScript (macOS):\n"
            "  do shell script \"curl -s http://127.0.0.1:8765/mute/toggle\"\n"
            "\n"
            "Streamdeck plugin (HTTP Request action):\n"
            "  URL: http://127.0.0.1:8765/ptt/toggle\n"
            "  Method: GET\n"
            "\n"
            "Home Assistant:\n"
            "  service: rest_command.teamtalk_ptt_toggle\n"
            "  Configure in configuration.yaml:\n"
            "    rest_command:\n"
            "      teamtalk_ptt_toggle:\n"
            "        url: 'http://127.0.0.1:8765/ptt/toggle'\n"
            "\n"
            "Error handling\n"
            "--------------\n"
            "  Unknown path:    HTTP 500, {\"ok\": false, \"error\": \"Unknown path: /xyz\"}\n"
            "  App not ready:   HTTP 500, {\"ok\": false, \"error\": \"App not ready\"}\n"
            "\n"
            "\n"
            "26. Webhook integration\n"
            "=======================\n"
            "The client automatically sends JSON payloads (HTTP POST) to a configured\n"
            "URL when certain events occur. External services like n8n, Zapier,\n"
            "Home Assistant or custom servers can react to these events.\n"
            "\n"
            "Configuration\n"
            "-------------\n"
            "Settings → AI & Integration:\n"
            "  Webhook URL:     Target URL (must start with http:// or https://).\n"
            "  Webhook events:  Comma-separated list of events to react to.\n"
            "                   Empty = all events.\n"
            "\n"
            "Allowed URL schemes: http:// and https:// (others are rejected).\n"
            "\n"
            "Payload format\n"
            "--------------\n"
            "Each POST contains a JSON body:\n"
            "\n"
            "  {\n"
            "    \"event\":  \"<event name>\",\n"
            "    \"ts\":     \"2026-03-29T14:23:01\",\n"
            "    \"app\":    \"TeamTalk VO Client\",\n"
            "    <event-specific fields>\n"
            "  }\n"
            "\n"
            "HTTP headers:\n"
            "  Content-Type: application/json\n"
            "  User-Agent: TeamTalkVOClient/2.7\n"
            "\n"
            "Timeout: 5 seconds. Failed requests are logged in the system log\n"
            "but not retried.\n"
            "\n"
            "Supported events\n"
            "----------------\n"
            "\n"
            "private_msg – Private message received\n"
            "  Fields: from_user (str), text (str)\n"
            "  Example:\n"
            "  {\n"
            "    \"event\": \"private_msg\",\n"
            "    \"ts\": \"2026-03-29T14:23:01\",\n"
            "    \"app\": \"TeamTalk VO Client\",\n"
            "    \"from_user\": \"Alice\",\n"
            "    \"text\": \"Are you there?\"\n"
            "  }\n"
            "\n"
            "channel_msg – Channel message received\n"
            "  Fields: from_user (str), text (str)\n"
            "\n"
            "user_join – User has entered a channel\n"
            "  Fields: user (str), channel (str)\n"
            "\n"
            "user_leave – User has left a channel\n"
            "  Fields: user (str), channel (str)\n"
            "\n"
            "connect – Connected to server\n"
            "  Fields: server (str)\n"
            "\n"
            "disconnect – Connection lost\n"
            "  Fields: server (str)\n"
            "\n"
            "recording_start – Recording started\n"
            "  Fields: path (str)\n"
            "\n"
            "Practical examples\n"
            "------------------\n"
            "\n"
            "n8n webhook:\n"
            "  1. New workflow → Trigger: 'Webhook'\n"
            "  2. Copy URL from n8n and enter it in the client settings.\n"
            "  3. Filter events, e.g. only private_msg.\n"
            "\n"
            "Custom Python server:\n"
            "  from http.server import HTTPServer, BaseHTTPRequestHandler\n"
            "  import json\n"
            "  class Handler(BaseHTTPRequestHandler):\n"
            "      def do_POST(self):\n"
            "          length = int(self.headers['Content-Length'])\n"
            "          data = json.loads(self.rfile.read(length))\n"
            "          print('Event:', data['event'])\n"
            "          self.send_response(200); self.end_headers()\n"
            "  HTTPServer(('', 9999), Handler).serve_forever()\n"
            "\n"
            "\n"
            "27. Interface language\n"
            "======================\n"
            "The client supports German and English.\n"
            "\n"
            "Switch: Settings → General → Language.\n"
            "Note: A restart is required for the language to take full effect.\n"
            "Menus, dialogs and the manual will then appear in the selected language.\n"
            "\n"
            "\n"
            "28. Plugin manager\n"
            "==================\n"
            "Plugins are Python scripts that extend or automate the client without\n"
            "modifying its source code. They react to app events and can actively\n"
            "control the app (TTS, send messages, join channels).\n"
            "\n"
            "Plugin directory\n"
            "----------------\n"
            "In the app bundle:\n"
            "  TeamTalk VO Client.app/Contents/Resources/plugins/\n"
            "\n"
            "In development mode (source code):\n"
            "  TeamTalk-VO-Client-macOS/plugins/\n"
            "\n"
            "The directory may need to be created manually.\n"
            "All *.py files in it are loaded automatically at app start.\n"
            "Files starting with _ are skipped.\n"
            "\n"
            "Plugin structure\n"
            "----------------\n"
            "A plugin is a single Python file:\n"
            "\n"
            "  # plugins/my_plugin.py\n"
            "\n"
            "  metadata = {\n"
            "      \"name\":        \"My Plugin\",\n"
            "      \"version\":     \"1.0\",\n"
            "      \"description\": \"Does something useful\",\n"
            "      \"author\":      \"Your Name\",\n"
            "  }\n"
            "\n"
            "  def register(bus, api):\n"
            "      \"\"\"Called once at app start.\"\"\"\n"
            "      bus.on(\"connection_state_changed\", on_connection)\n"
            "\n"
            "  def on_connection(connected, reason):\n"
            "      if connected:\n"
            "          api.speak(\"Connected!\")\n"
            "\n"
            "Required:\n"
            "  register(bus, api)  – Entry point; called once at startup.\n"
            "\n"
            "Optional:\n"
            "  metadata            – Dict with name, version, description, author.\n"
            "                        Shown in the Settings tab 'Plugins'.\n"
            "\n"
            "EventBus (bus)\n"
            "--------------\n"
            "The EventBus connects plugins to app events.\n"
            "\n"
            "  bus.on(event, handler)   – Register a handler for an event.\n"
            "  bus.off(event, handler)  – Remove a handler.\n"
            "  bus.emit(event, **kw)    – Fire a custom event.\n"
            "\n"
            "Available events:\n"
            "\n"
            "  app_startup\n"
            "    Fired ~2 seconds after the app has fully initialised.\n"
            "    Parameters: (none)\n"
            "\n"
            "  connection_state_changed\n"
            "    Connection established or lost.\n"
            "    Parameters: connected (bool), reason (str)\n"
            "    reason: 'login' | 'failed' | 'lost'\n"
            "\n"
            "  user_joined\n"
            "    A user has entered a channel.\n"
            "    Parameters: user (str), user_id (int), channel_id (int),\n"
            "                 channel_name (str)\n"
            "\n"
            "  user_left\n"
            "    A user has left a channel.\n"
            "    Parameters: user (str), user_id (int), channel_id (int),\n"
            "                 channel_name (str)\n"
            "\n"
            "  chat_message\n"
            "    Message received or sent.\n"
            "    Parameters: text (str), kind (str), from_user (str), from_id (int)\n"
            "    kind: 'chat' | 'private' | 'broadcast'\n"
            "\n"
            "  channel_joined\n"
            "    You have joined a channel.\n"
            "    Parameters: channel_id (int)\n"
            "\n"
            "  file_transfer_complete\n"
            "    File transfer completed.\n"
            "    Parameters: filename (str)\n"
            "\n"
            "PluginAPI (api)\n"
            "---------------\n"
            "Enables active control of the app from within the plugin.\n"
            "\n"
            "TTS:\n"
            "  api.speak(text, kind='system')\n"
            "    Read text aloud via TTS. Safe to call from any thread.\n"
            "    kind: 'system' | 'chat' | 'private'\n"
            "\n"
            "Connection status:\n"
            "  api.is_connected() → bool\n"
            "    True if connected to a server.\n"
            "  api.get_server_name() → str\n"
            "    Configured server name (empty = not connected).\n"
            "\n"
            "Users & channels:\n"
            "  api.get_my_user_id() → int\n"
            "    Own user ID (0 = not connected).\n"
            "  api.get_my_channel_id() → int\n"
            "    ID of current channel (0 = no channel).\n"
            "  api.get_channel_users(channel_id) → list\n"
            "    Users in channel as a list of dicts:\n"
            "    [{\"id\": 42, \"name\": \"Alice\", \"is_admin\": False}, ...]\n"
            "\n"
            "Sending messages (always call from a background thread!):\n"
            "  api.send_channel_message(text, channel_id=0) → bool\n"
            "    Send message to own channel (or channel_id).\n"
            "  api.send_private_message(user_id, text) → bool\n"
            "    Send a private message to a user.\n"
            "\n"
            "Channel:\n"
            "  api.join_channel(channel_id, password='')\n"
            "    Join a channel (asynchronous via wx.CallAfter).\n"
            "\n"
            "Plugin configuration:\n"
            "  api.get_config(plugin_name) → PluginConfig\n"
            "    Persistent key-value store per plugin.\n"
            "    Stored in:\n"
            "    ~/Library/Application Support/TeamTalkVOClient/plugin_configs/\n"
            "\n"
            "    cfg = api.get_config('my_plugin')\n"
            "    cfg.set('key', 'value')       # saved immediately\n"
            "    cfg.get('key', 'default')     # read\n"
            "    cfg.delete('key')             # remove\n"
            "    cfg.all()                     # all entries\n"
            "\n"
            "Threading rules\n"
            "---------------\n"
            "Handlers are called in the GUI thread (EventBus is synchronous).\n"
            "\n"
            "  CORRECT – blocking ops in background thread:\n"
            "    import threading\n"
            "    def on_event(**kw):\n"
            "        threading.Thread(target=_do_work, daemon=True).start()\n"
            "\n"
            "  WRONG – blocks the GUI thread:\n"
            "    def on_event(**kw):\n"
            "        time.sleep(5)  # freezes the app!\n"
            "\n"
            "  api.speak() is always safe (uses wx.CallAfter internally).\n"
            "  api.send_channel_message() must be called from a background thread.\n"
            "\n"
            "Example plugins\n"
            "---------------\n"
            "\n"
            "1. Greet users on channel join:\n"
            "\n"
            "  metadata = {\"name\": \"Greeter\", \"version\": \"1.0\"}\n"
            "\n"
            "  def register(bus, api):\n"
            "      def on_join(user, channel_id, **kw):\n"
            "          if channel_id == api.get_my_channel_id():\n"
            "              api.speak(f\"Welcome, {user}!\")\n"
            "      bus.on(\"user_joined\", on_join)\n"
            "\n"
            "2. Chat commands (!ping, !users):\n"
            "\n"
            "  import threading\n"
            "  metadata = {\"name\": \"Chat commands\", \"version\": \"1.0\"}\n"
            "\n"
            "  def register(bus, api):\n"
            "      def on_chat(text, kind, from_user, from_id, **kw):\n"
            "          if kind != \"chat\" or not text.startswith(\"!\"):\n"
            "              return\n"
            "          if text.strip() == \"!ping\":\n"
            "              threading.Thread(\n"
            "                  target=lambda: api.send_channel_message(\n"
            "                      f\"{from_user}: pong!\"),\n"
            "                  daemon=True).start()\n"
            "      bus.on(\"chat_message\", on_chat)\n"
            "\n"
            "3. Log connections to file:\n"
            "\n"
            "  import datetime, pathlib\n"
            "  metadata = {\"name\": \"Connection log\", \"version\": \"1.0\"}\n"
            "  LOG = pathlib.Path.home() / \"teamtalk_connections.log\"\n"
            "\n"
            "  def register(bus, api=None):\n"
            "      bus.on(\"connection_state_changed\", _log)\n"
            "\n"
            "  def _log(connected, reason):\n"
            "      ts = datetime.datetime.now().strftime(\"%Y-%m-%d %H:%M:%S\")\n"
            "      status = \"CONNECTED\" if connected else f\"DISCONNECTED ({reason})\"\n"
            "      with LOG.open(\"a\", encoding=\"utf-8\") as f:\n"
            "          f.write(f\"[{ts}] {status}\\n\")\n"
            "\n"
            "4. macOS desktop notification on connection loss:\n"
            "\n"
            "  import subprocess\n"
            "  metadata = {\"name\": \"Connection alert\", \"version\": \"1.0\"}\n"
            "\n"
            "  def register(bus, api=None):\n"
            "      bus.on(\"connection_state_changed\", _alert)\n"
            "\n"
            "  def _alert(connected, reason):\n"
            "      if not connected:\n"
            "          subprocess.run([\"osascript\", \"-e\",\n"
            "              'display notification \"Connection lost\" '\n"
            "              'with title \"TeamTalk VO Client\"'], check=False)\n"
            "\n"
            "Debugging\n"
            "---------\n"
            "Plugins can use print(). Output appears in the terminal when the app\n"
            "is started from source code:\n"
            "\n"
            "  cd TeamTalk-VO-Client-macOS\n"
            "  .venv/bin/python src/app.py\n"
            "\n"
            "Load errors:\n"
            "  [PluginLoader] Error loading my_plugin.py: <cause>\n"
            "Handler errors:\n"
            "  [EventBus] Handler <fn> for '<event>' failed: <cause>\n"
            "\n"
            "Common problems:\n"
            "  Plugin not loaded       – Filename starts with '_'\n"
            "  Handler not called      – Wrong event name (case-sensitive)\n"
            "  App freezes             – Blocking code in handler\n"
            "  api is None             – Old plugin with register(bus) instead of\n"
            "                            register(bus, api=None)\n"
        )

    def on_menu_manual(self, _event):
        """Öffnet das Handbuch in der konfigurierten Sprache."""
        if current_language() == "en":
            manual_text = self._get_manual_text_en()
            dlg_title = "TeamTalk VoiceOver Client – Manual"
            close_label = "&Close"
        else:
            manual_text = self._get_manual_text_de()
            dlg_title = "TeamTalk VoiceOver Client – Handbuch"
            close_label = "&Schließen"

        dlg = wx.Dialog(self, title=dlg_title,
                        style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        accel = wx.AcceleratorTable([(wx.ACCEL_CMD, ord("W"), wx.ID_CLOSE)])
        dlg.SetAcceleratorTable(accel)
        dlg.Bind(wx.EVT_MENU, lambda e: dlg.EndModal(wx.ID_CANCEL), id=wx.ID_CLOSE)
        dlg.SetSize((820, 680))
        dlg.Centre()
        sizer = wx.BoxSizer(wx.VERTICAL)
        txt = wx.TextCtrl(
            dlg,
            value=manual_text,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_NOHIDESEL,
        )
        txt.SetName(_("Handbuch"))
        txt.SetFont(wx.Font(11, wx.FONTFAMILY_TELETYPE, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        close_btn = wx.Button(dlg, wx.ID_CLOSE, close_label)
        close_btn.Bind(wx.EVT_BUTTON, lambda e: dlg.EndModal(wx.ID_CLOSE))
        sizer.Add(txt, 1, wx.ALL | wx.EXPAND, 4)
        sizer.Add(close_btn, 0, wx.ALL | wx.ALIGN_RIGHT, 8)
        dlg.SetSizer(sizer)
        txt.SetInsertionPoint(0)
        dlg.ShowModal()
        dlg.Destroy()

    def on_menu_hotkey_reference(self, _event):
        """Zeigt eine übersichtliche Tastenkürzel-Referenz als Text-Dialog."""
        s = self.settings_store.settings

        def _fmt(code):
            if not code:
                return "(nicht gesetzt)"
            import wx as _wx
            if code == _wx.WXK_SPACE:
                return "Leertaste"
            if _wx.WXK_F1 <= code <= _wx.WXK_F24:
                return f"F{code - _wx.WXK_F1 + 1}"
            if 32 <= code <= 126:
                return chr(code).upper()
            return str(code)

        rows = [
            ("Alles stummschalten",       _fmt(int(s.hotkey_mute_all or 0))),
            ("Sprachaktivierung",          _fmt(int(s.hotkey_voice_activation or 0))),
            ("Video senden",              _fmt(int(s.hotkey_video_tx or 0))),
            ("Eingangspegel ansagen",     _fmt(int(s.hotkey_announce_level or 0))),
            ("Nutzerinfo ansagen",        _fmt(int(s.hotkey_announce_user_info or 0))),
            ("Ping ansagen",              _fmt(int(s.hotkey_announce_ping or 0))),
            ("Braille-Status ansagen",    _fmt(int(getattr(s, "hotkey_announce_status", 0) or 0))),
            ("Privatantwort",             _fmt(int(s.hotkey_reply_last_sender or 0))),
            ("Sound-Profil wechseln",     _fmt(int(s.hotkey_cycle_sound_profile or 0))),
            ("Braille-Verbosität wechseln", _fmt(int(getattr(s, "hotkey_cycle_braille_verbosity", 0) or 0))),
            ("KI-Zusammenfassung",        _fmt(int(getattr(s, "hotkey_ai_summary", 0) or 0))),
            ("Lesezeichen 1",             _fmt(int(getattr(s, "hotkey_bookmark_1", 0) or 0))),
            ("Lesezeichen 2",             _fmt(int(getattr(s, "hotkey_bookmark_2", 0) or 0))),
            ("Lesezeichen 3",             _fmt(int(getattr(s, "hotkey_bookmark_3", 0) or 0))),
            ("Lesezeichen 4",             _fmt(int(getattr(s, "hotkey_bookmark_4", 0) or 0))),
            ("Lesezeichen 5",             _fmt(int(getattr(s, "hotkey_bookmark_5", 0) or 0))),
            ("Lesezeichen 6",             _fmt(int(getattr(s, "hotkey_bookmark_6", 0) or 0))),
            ("Lesezeichen 7",             _fmt(int(getattr(s, "hotkey_bookmark_7", 0) or 0))),
            ("Lesezeichen 8",             _fmt(int(getattr(s, "hotkey_bookmark_8", 0) or 0))),
            ("Lesezeichen 9",             _fmt(int(getattr(s, "hotkey_bookmark_9", 0) or 0))),
            ("Aufnahme umschalten",       _fmt(int(getattr(s, "hotkey_record_toggle", 0) or 0))),
            ("Status-Vorlage 1",          _fmt(int(getattr(s, "hotkey_status_template_1", 0) or 0))),
            ("Status-Vorlage 2",          _fmt(int(getattr(s, "hotkey_status_template_2", 0) or 0))),
            ("Status-Vorlage 3",          _fmt(int(getattr(s, "hotkey_status_template_3", 0) or 0))),
            ("Mikrofon-Boost hoch",       _fmt(int(getattr(s, "hotkey_mic_boost_up", 0) or 0))),
            ("Mikrofon-Boost runter",     _fmt(int(getattr(s, "hotkey_mic_boost_down", 0) or 0))),
            ("TTS abbrechen",             _fmt(int(getattr(s, "hotkey_tts_cancel", 0) or 0))),
        ]
        col_w = max(len(r[0]) for r in rows) + 2
        lines = ["App-Hotkeys (nur innerhalb der App)\n" + "=" * 50]
        for label, key in rows:
            lines.append(f"  {label:<{col_w}}{key}")
        if sys.platform == "darwin" and getattr(s, "global_hotkeys_enabled", False):
            lines.append("\nGlobale Hotkeys (systemweit)\n" + "=" * 50)
            try:
                from global_hotkeys import vk_to_name
                ptt_label = vk_to_name(int(s.global_hotkey_ptt or 0)) if s.global_hotkey_ptt else "(nicht gesetzt)"
                mute_label = vk_to_name(int(s.global_hotkey_mute or 0)) if s.global_hotkey_mute else "(nicht gesetzt)"
            except Exception:
                ptt_label = str(s.global_hotkey_ptt or "(nicht gesetzt)")
                mute_label = str(s.global_hotkey_mute or "(nicht gesetzt)")
            lines.append(f"  {'PTT (Sprechtaste)':<{col_w}}{ptt_label}")
            lines.append(f"  {'Stummschalten umschalten':<{col_w}}{mute_label}")

        text = "\n".join(lines)
        dlg = wx.Dialog(self, title="Tastenkürzel-Referenz",
                        style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        accel = wx.AcceleratorTable([(wx.ACCEL_CMD, ord("W"), wx.ID_CLOSE)])
        dlg.SetAcceleratorTable(accel)
        dlg.Bind(wx.EVT_MENU, lambda e: dlg.EndModal(wx.ID_CANCEL), id=wx.ID_CLOSE)
        root = wx.BoxSizer(wx.VERTICAL)
        txt = wx.TextCtrl(dlg, value=text,
                          style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2)
        txt.SetName("Tastenkürzel-Referenz")
        txt.SetMinSize((560, 460))
        root.Add(txt, 1, wx.ALL | wx.EXPAND, 10)
        btns = dlg.CreateButtonSizer(wx.OK)
        root.Add(btns, 0, wx.ALL | wx.ALIGN_RIGHT, 10)
        dlg.SetSizerAndFit(root)
        dlg.CentreOnParent()
        dlg.ShowModal()
        dlg.Destroy()

    def on_menu_about(self, _event):
        dlg = wx.Dialog(self, title="Über TeamTalk VoiceOver Client",
                        style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        accel = wx.AcceleratorTable([(wx.ACCEL_CMD, ord("W"), wx.ID_CLOSE)])
        dlg.SetAcceleratorTable(accel)
        dlg.Bind(wx.EVT_MENU, lambda e: dlg.EndModal(wx.ID_CANCEL), id=wx.ID_CLOSE)

        root = wx.BoxSizer(wx.VERTICAL)
        nb = wx.Notebook(dlg)
        nb.SetName("Über Reiter")

        # ---- Reiter 1: Allgemein ----
        p_general = wx.Panel(nb)
        p_general.SetName("Allgemein")
        gs = wx.BoxSizer(wx.VERTICAL)
        general_text = (
            f"TeamTalk VoiceOver Client  {APP_VERSION}\n"
            "\n"
            "Ein barrierefreier TeamTalk-Client, optimiert für VoiceOver und\n"
            "Braillezeilen auf macOS sowie für andere Screenreader auf Windows.\n"
            "\n"
            "Hauptentwickler\n"
            "  Florian Lichteblau (Flarion)\n"
            "\n"
            "Hinweis zur Plattformunterstützung\n"
            "  Ich entwickle dieses Projekt in erster Linie für macOS und\n"
            "  optimiere es für VoiceOver. Dank der Multiplattform-Fähigkeiten\n"
            "  von wxPython bin ich jedoch stets bemüht, auch für Windows und\n"
            "  Linux Lösungen bereitzustellen. Windows- und Linux-Nutzer sollten\n"
            "  allerdings beachten, dass es vereinzelt zu plattformspezifischen\n"
            "  Einschränkungen kommen kann, da macOS der primäre Entwicklungs-\n"
            "  und Testrahmen ist.\n"
            "\n"
            "Verwendete Bibliotheken und Werkzeuge\n"
            "  • TeamTalk SDK  –  BearWare (bearware.dk)\n"
            "  • wxPython  –  wxWidgets-Projekt\n"
            "  • PyInstaller  –  PyInstaller-Team\n"
            "  • espeak-ng  –  espeak-ng-Autoren\n"
            "  • yt-dlp  –  yt-dlp-Autoren\n"
            "  • certifi, urllib3, charset-normalizer, requests\n"
            "\n"
            "Plattformen\n"
            "  macOS (Apple Silicon & Intel)  ·  Windows  ·  Linux\n"
        )
        tc_general = wx.TextCtrl(p_general, value=general_text,
                                 style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2)
        tc_general.SetName("Allgemeine Informationen")
        tc_general.SetMinSize((640, 340))
        gs.Add(tc_general, 1, wx.ALL | wx.EXPAND, 10)
        p_general.SetSizer(gs)
        nb.AddPage(p_general, "Allgemein")

        # ---- Reiter 2: Danksagungen ----
        p_thanks = wx.Panel(nb)
        p_thanks.SetName("Danksagungen")
        ts = wx.BoxSizer(wx.VERTICAL)
        thanks_text = (
            "Beta-Tester und Unterstützer\n"
            "════════════════════════════════════════\n"
            "\n"
            "Garo\n"
            "  Herzlichen Dank für die Bereitstellung des Git-Servers,\n"
            "  auf dem dieses Projekt ganz oder in Teilen für die\n"
            "  Zusammenarbeit verfügbar gemacht wurde und wird.\n"
            "  Garo hat außerdem die Windows-Tests über die gesamte\n"
            "  Projektlaufzeit begleitet und aktiv Anpassungen vorgenommen.\n"
            "\n"
            "FVH\n"
            "  Dank für wichtige frühe Entwicklungsarbeit: die Einführung\n"
            "  der Tab-Struktur sowie die erste ElevenLabs-Unterstützung\n"
            "  in diesem Client.\n"
            "\n"
            "DHT\n"
            "  Dank für die ersten Tests und Experimente auf Windows sowie\n"
            "  weitere Tests unter macOS. Dank der Multiplattform-Fähigkeit\n"
            "  von wxPython wuchs die Nachfrage nach Windows- und\n"
            "  Linux-Unterstützung schnell – DHT war dabei von Anfang an.\n"
            "\n"
            "Korn\n"
            "  Dank für Unterstützung und Tests auf macOS mit\n"
            "  Apple-M1-Prozessor.\n"
            "\n"
            "de Losse\n"
            "  Dank für Tests unter macOS auf einem Mac mini.\n"
        )
        tc_thanks = wx.TextCtrl(p_thanks, value=thanks_text,
                                style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2)
        tc_thanks.SetName("Danksagungen Text")
        tc_thanks.SetMinSize((640, 340))
        ts.Add(tc_thanks, 1, wx.ALL | wx.EXPAND, 10)
        p_thanks.SetSizer(ts)
        nb.AddPage(p_thanks, "Danksagungen")

        # ---- Reiter 3: Lizenzen ----
        p_lic = wx.Panel(nb)
        p_lic.SetName("Lizenzen")
        ls = wx.BoxSizer(wx.VERTICAL)

        base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
        license_files = [
            ("TeamTalk VO Client – Lizenz",
             base / "licenses" / "TEAMTALK_VO_CLIENT_LICENSE.txt"),
            ("TeamTalk SDK – Lizenz",
             base / "licenses" / "TEAMTALK_SDK_LICENSE.txt"),
        ]

        ls.Add(wx.StaticText(p_lic,
               label="Wähle eine Lizenz aus und klicke auf 'Öffnen':"),
               0, wx.ALL, 10)
        lic_list = wx.ListBox(p_lic,
                              choices=[name for name, _ in license_files])
        lic_list.SetName("Lizenzen Liste")
        lic_list.SetMinSize((400, 120))
        if license_files:
            lic_list.SetSelection(0)
        ls.Add(lic_list, 0, wx.LEFT | wx.RIGHT | wx.EXPAND, 10)

        open_btn = wx.Button(p_lic, label="Lizenz öffnen")
        open_btn.SetName("Lizenz öffnen")
        ls.Add(open_btn, 0, wx.ALL, 10)

        ls.Add(wx.StaticText(p_lic,
               label="Weitere Abhängigkeiten: Lizenzen der jeweiligen Projekte beachten."),
               0, wx.LEFT | wx.BOTTOM, 10)
        p_lic.SetSizer(ls)
        nb.AddPage(p_lic, "Lizenzen")

        def on_open_license(_evt):
            idx = lic_list.GetSelection()
            if idx == wx.NOT_FOUND:
                return
            name, path = license_files[idx]
            if not path.exists():
                wx.MessageBox(f"Lizenzdatei nicht gefunden:\n{path}",
                              "Fehler", wx.OK | wx.ICON_ERROR, dlg)
                return
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except Exception as exc:
                wx.MessageBox(f"Datei konnte nicht gelesen werden:\n{exc}",
                              "Fehler", wx.OK | wx.ICON_ERROR, dlg)
                return
            ld = wx.Dialog(dlg, title=name,
                           style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
            la = wx.AcceleratorTable([(wx.ACCEL_CMD, ord("W"), wx.ID_CLOSE)])
            ld.SetAcceleratorTable(la)
            ld.Bind(wx.EVT_MENU, lambda e: ld.EndModal(wx.ID_CANCEL), id=wx.ID_CLOSE)
            lroot = wx.BoxSizer(wx.VERTICAL)
            ltc = wx.TextCtrl(ld, value=content,
                              style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2)
            ltc.SetName(name)
            ltc.SetMinSize((700, 520))
            lroot.Add(ltc, 1, wx.ALL | wx.EXPAND, 10)
            lroot.Add(ld.CreateButtonSizer(wx.OK), 0, wx.ALL | wx.ALIGN_RIGHT, 10)
            ld.SetSizerAndFit(lroot)
            ld.CentreOnParent()
            ld.ShowModal()
            ld.Destroy()

        open_btn.Bind(wx.EVT_BUTTON, on_open_license)
        lic_list.Bind(wx.EVT_LISTBOX_DCLICK, on_open_license)

        root.Add(nb, 1, wx.ALL | wx.EXPAND, 8)
        root.Add(dlg.CreateButtonSizer(wx.OK), 0, wx.ALL | wx.ALIGN_RIGHT, 10)
        dlg.SetSizerAndFit(root)
        dlg.CentreOnParent()
        dlg.ShowModal()
        dlg.Destroy()

    def on_menu_saved_messages(self, _event) -> None:
        """Zeigt gespeicherte Chat-Nachrichten in einem Dialog an."""
        items = self._saved_messages.items()
        dlg = wx.Dialog(self, title="Gespeicherte Nachrichten", style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        dlg.SetMinSize((680, 440))
        accel = wx.AcceleratorTable([(wx.ACCEL_CMD, ord("W"), wx.ID_CLOSE)])
        dlg.SetAcceleratorTable(accel)
        dlg.Bind(wx.EVT_MENU, lambda e: dlg.EndModal(wx.ID_CANCEL), id=wx.ID_CLOSE)

        root = wx.BoxSizer(wx.VERTICAL)
        if not items:
            root.Add(wx.StaticText(dlg, label="Keine gespeicherten Nachrichten."), 0, wx.ALL, 16)
        else:
            lbl = wx.StaticText(dlg, label=f"{len(items)} gespeicherte Nachricht(en):")
            root.Add(lbl, 0, wx.ALL, 8)
            lb = wx.ListBox(dlg)
            lb.SetName("Gespeicherte Nachrichten Liste")
            from ui.a11y import setup_list_accessible
            setup_list_accessible(lb)
            for m in items:
                srv = f" [{m.server}]" if m.server else ""
                lb.Append(f"{m.time_str}{srv}: {m.text[:120]}")
            lb.SetMinSize((-1, 280))
            root.Add(lb, 1, wx.LEFT | wx.RIGHT | wx.EXPAND, 8)

            btn_row = wx.BoxSizer(wx.HORIZONTAL)
            del_btn = wx.Button(dlg, label="&Löschen")
            del_btn.SetName("Ausgewählte Nachricht löschen")
            clear_btn = wx.Button(dlg, label="&Alle löschen")
            clear_btn.SetName("Alle gespeicherten Nachrichten löschen")
            copy_btn = wx.Button(dlg, label="&Kopieren")
            copy_btn.SetName("Nachricht kopieren")
            btn_row.Add(del_btn, 0, wx.RIGHT, 8)
            btn_row.Add(clear_btn, 0, wx.RIGHT, 8)
            btn_row.Add(copy_btn, 0)
            root.Add(btn_row, 0, wx.ALL, 8)

            def _on_delete(_e):
                idx = lb.GetSelection()
                if idx == wx.NOT_FOUND:
                    return
                self._saved_messages.remove(idx)
                lb.Delete(idx)
                if lb.GetCount() > 0:
                    lb.SetSelection(min(idx, lb.GetCount() - 1))

            def _on_clear(_e):
                confirm = wx.MessageDialog(
                    dlg, "Alle gespeicherten Nachrichten wirklich löschen?",
                    "Alle löschen", wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION,
                )
                if confirm.ShowModal() == wx.ID_YES:
                    self._saved_messages.clear()
                    lb.Clear()
                confirm.Destroy()

            def _on_copy(_e):
                idx = lb.GetSelection()
                if idx == wx.NOT_FOUND:
                    return
                saved_items = self._saved_messages.items()
                if idx < len(saved_items):
                    text = saved_items[idx].text
                    if wx.TheClipboard.Open():
                        wx.TheClipboard.SetData(wx.TextDataObject(text))
                        wx.TheClipboard.Close()
                        self.set_status("Nachricht in Zwischenablage kopiert")

            del_btn.Bind(wx.EVT_BUTTON, _on_delete)
            clear_btn.Bind(wx.EVT_BUTTON, _on_clear)
            copy_btn.Bind(wx.EVT_BUTTON, _on_copy)

        btn_sizer = wx.StdDialogButtonSizer()
        ok_btn = wx.Button(dlg, wx.ID_OK)
        btn_sizer.AddButton(ok_btn)
        btn_sizer.Realize()
        root.Add(btn_sizer, 0, wx.ALL | wx.ALIGN_RIGHT, 8)

        dlg.SetSizer(root)
        dlg.CentreOnParent()
        dlg.ShowModal()
        dlg.Destroy()

    def on_menu_changelog(self, _event):
        sections = self._build_changelog_sections()
        if not sections:
            text = self._build_changelog_text()
            dlg = wx.Dialog(self, title="Changelog", style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
            accel = wx.AcceleratorTable([(wx.ACCEL_CMD, ord("W"), wx.ID_CLOSE)])
            dlg.SetAcceleratorTable(accel)
            dlg.Bind(wx.EVT_MENU, lambda e: dlg.EndModal(wx.ID_CANCEL), id=wx.ID_CLOSE)
            root = wx.BoxSizer(wx.VERTICAL)
            info = wx.TextCtrl(
                dlg,
                value=text,
                style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2,
            )
            info.SetMinSize((720, 520))
            root.Add(info, 1, wx.ALL | wx.EXPAND, 10)
            btns = dlg.CreateButtonSizer(wx.OK)
            root.Add(btns, 0, wx.ALL | wx.ALIGN_RIGHT, 10)
            dlg.SetSizerAndFit(root)
            dlg.CentreOnParent()
            dlg.ShowModal()
            dlg.Destroy()
            return

        dlg = wx.Dialog(self, title="Changelog", style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        accel = wx.AcceleratorTable([(wx.ACCEL_CMD, ord("W"), wx.ID_CLOSE)])
        dlg.SetAcceleratorTable(accel)
        dlg.Bind(wx.EVT_MENU, lambda e: dlg.EndModal(wx.ID_CANCEL), id=wx.ID_CLOSE)
        root = wx.BoxSizer(wx.VERTICAL)
        splitter = wx.SplitterWindow(dlg, style=wx.SP_LIVE_UPDATE)
        left = wx.Panel(splitter)
        right = wx.Panel(splitter)

        left_sizer = wx.BoxSizer(wx.VERTICAL)
        left_label = wx.StaticText(left, label="Versionen")
        left_sizer.Add(left_label, 0, wx.ALL, 8)
        version_table = dv.DataViewListCtrl(left, style=wx.BORDER_SUNKEN | dv.DV_SINGLE)
        version_table.SetName("Changelog Versionen")
        version_table.AppendTextColumn("Version", width=200)
        left_sizer.Add(version_table, 1, wx.ALL | wx.EXPAND, 8)
        left.SetSizer(left_sizer)

        right_sizer = wx.BoxSizer(wx.VERTICAL)
        right_label = wx.StaticText(right, label="Details")
        right_sizer.Add(right_label, 0, wx.ALL, 8)
        detail = wx.TextCtrl(right, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2)
        detail.SetName("Changelog Details")
        right_sizer.Add(detail, 1, wx.ALL | wx.EXPAND, 8)
        right.SetSizer(right_sizer)

        titles = [title for title, _ in sections]
        for title in titles:
            version_table.AppendItem([title])
        if titles:
            version_table.SelectRow(0)
            detail.SetValue("\n".join(sections[0][1]).strip() + "\n")

        def on_select(_evt):
            row = version_table.GetSelectedRow()
            if row == -1:
                return
            if row >= len(sections):
                return
            detail.SetValue("\n".join(sections[row][1]).strip() + "\n")

        version_table.Bind(dv.EVT_DATAVIEW_SELECTION_CHANGED, on_select)

        splitter.SplitVertically(left, right, sashPosition=220)
        splitter.SetMinimumPaneSize(160)
        splitter.SetSashGravity(0.2)
        root.Add(splitter, 1, wx.ALL | wx.EXPAND, 10)
        btns = dlg.CreateButtonSizer(wx.OK)
        root.Add(btns, 0, wx.ALL | wx.ALIGN_RIGHT, 10)
        dlg.SetSizerAndFit(root)
        dlg.CentreOnParent()
        dlg.ShowModal()
        dlg.Destroy()

    def _build_changelog_text(self) -> str:
        base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
        changelog_path = base / "CHANGELOG.txt"
        if not changelog_path.exists():
            return "Kein Changelog vorhanden."
        try:
            return changelog_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return "Changelog konnte nicht geladen werden."

    def _build_changelog_sections(self) -> List[Tuple[str, List[str]]]:
        text = self._build_changelog_text()
        if not text or text.startswith("Kein Changelog"):
            return []
        lines = [ln.rstrip() for ln in text.splitlines()]
        sections: List[Tuple[str, List[str]]] = []
        current_title = ""
        current_lines: List[str] = []
        for line in lines:
            if line.strip() and line.startswith("20") and "(v" in line:
                if current_title:
                    sections.append((current_title, current_lines))
                current_title = line.strip()
                current_lines = []
                continue
            if current_title:
                current_lines.append(line)
        if current_title:
            sections.append((current_title, current_lines))
        return sections

    # ------------------------------------------------------------------
    # Connection logic (shared across tabs)
    # ------------------------------------------------------------------

    def connect_with_form(self):
        tab = self.connection_tab
        tab.connect_btn.Disable()
        self.set_status("Verbinde...")

        def worker():
            try:
                self.client.stop_event_loop_and_wait()
                _se = self.settings_store.settings.sound_events
                result = self.client.connect_and_login(
                    host=tab.host.GetValue().strip(),
                    tcp_port=int(tab.tcp_port.GetValue().strip()),
                    udp_port=int(tab.udp_port.GetValue().strip()),
                    nickname=tab.nickname.GetValue().strip(),
                    username=tab.username.GetValue().strip(),
                    password=tab.password.GetValue().strip(),
                    client_name=tab.client_name.GetValue().strip(),
                    encrypted=tab.encrypted.GetValue(),
                    timeout_ms=8000,
                    on_login_confirmed=lambda: self.sound_manager.play("server_connect", _se.get("server_connect")),
                )
                wx.CallAfter(self.handle_connect_result, result)
            except Exception as exc:
                wx.CallAfter(self.set_status, f"Fehler: {exc}")
            finally:
                wx.CallAfter(tab.connect_btn.Enable)

        threading.Thread(target=worker, daemon=True).start()

    def handle_connect_result(self, result: ConnectResult):
        self.set_status(result.message)
        # v4.9.0 – Audit-Log
        if result.ok:
            self._audit_log.log(A_SERVER_CONNECT, detail=self._get_server_key())
        if result.ok:
            self._reconnect_attempts = 0
            self._offline_buffering = False
            self._current_server_key = self._get_server_key()
            self._auto_init_sound_devices()
            self.client.start_event_loop(self.handle_tt_message)
            self._refresh_channels_with_retry()
            if self.files_tab is not None:
                wx.CallLater(800, self.files_tab.refresh_file_list)
            if self._pending_join is not None:
                wx.CallLater(500, self._join_from_pending)
            elif self.settings_store.settings.auto_join_last_channel:
                wx.CallLater(800, self._auto_join_last_channel)
            # v2.3.0 – Auto-Kanal nach Name beitreten
            elif getattr(self.settings_store.settings, "auto_join_channel_per_server", None):
                wx.CallLater(900, self._auto_join_channel_by_name)
            if self.audio_tab.voice_activation.GetValue() and not self._ptt_enabled:
                self.client.enable_voice_transmission(True)
            if self.admin_tab is not None:
                self.admin_tab.check_admin_visibility()
            api_key = self.settings_store.settings.elevenlabs_api_key or ""
            self._update_speak_tab(api_key)
            if self.settings_store.settings.save_chat_history:
                wx.CallLater(200, self._load_chat_history_to_ui)
            # Verbindungsansage
            wx.CallLater(600, self._announce_connected)
            # Offline-Ereignisse wiedergeben
            if self._offline_event_log:
                wx.CallLater(800, self._replay_offline_log)
            # v2.4.0 – Noise gate anwenden
            self._apply_noise_gate()
            # v2.5.0 – Auto-Antwort zurücksetzen
            self._auto_reply.reset()
            # v2.6.0 – Verbindungsqualitäts-Timer starten
            if not hasattr(self, "_quality_timer"):
                self._quality_timer = wx.Timer(self)
                self.Bind(wx.EVT_TIMER, self._on_quality_timer, self._quality_timer)
            self._quality_bad_announced = False
            self._quality_timer.Start(10_000)
            # v2.7.0 – HTTP-API starten (on-connect)
            if getattr(self.settings_store.settings, "http_api_enabled", False):
                try:
                    self._http_api.start(int(getattr(self.settings_store.settings, "http_api_port", 8765) or 8765))
                except Exception:
                    pass
            # v2.7.0 – Webhook: Verbindung
            self._webhook.emit("connect", {"server": self._current_server_key})

    def _auto_join_last_channel(self) -> None:
        """Tritt dem zuletzt verwendeten Kanal automatisch bei (falls gespeichert)."""
        key = self._get_server_key()
        if not key:
            return
        last = self.settings_store.settings.last_channel_per_server.get(key, 0)
        if not last:
            return
        self.logger.write(f"Auto-join last channel {last} for server {key}")
        self.join_channel(last)

    def _auto_join_channel_by_name(self) -> None:
        """Tritt dem konfigurierten Auto-Kanal (nach Name) bei – v2.3.0."""
        key = self._get_server_key()
        if not key:
            return
        mapping = getattr(self.settings_store.settings, "auto_join_channel_per_server", {}) or {}
        channel_name = mapping.get(key, "").strip()
        if not channel_name:
            return
        try:
            channels = list(self.client.get_channels() or [])
            name_l = channel_name.lower()
            for ch in channels:
                ch_name = (self.tt_str(getattr(ch, "szName", "")) or "").lower()
                if ch_name == name_l or name_l in ch_name:
                    self.join_channel(int(getattr(ch, "nChannelID", 0)))
                    return
            self.logger.write(f"Auto-join: Kanal '{channel_name}' nicht gefunden")
        except Exception as exc:
            self.logger.write(f"Auto-join Fehler: {exc}")

    def _save_last_channel(self, channel_id: int) -> None:
        key = self._get_server_key()
        if not key or not channel_id:
            return
        self.settings_store.settings.last_channel_per_server[key] = channel_id
        self.settings_store.save()

    def _on_favorites_menu_open(self, _event) -> None:
        """Aktualisiert die Favoriten-Menü-Labels mit echten Servernamen."""
        servers = self.store.items()
        for i, item in enumerate(self._favorites_menu_items):
            if i < len(servers):
                label = f"{i + 1}: {servers[i].name}\tCtrl+{i + 1}"
            else:
                label = f"Server {i + 1}\tCtrl+{i + 1}"
            try:
                item.SetItemLabel(label)
            except Exception:
                pass

    def _connect_favorite(self, index: int) -> None:
        """Verbindet mit dem N-ten Server aus der Serverliste (0-basiert)."""
        servers = self.store.items()
        if index >= len(servers):
            self.set_status(f"Kein Server #{index + 1} in der Liste")
            return
        profile = servers[index]
        self.connection_tab.fill_form(profile)
        self.set_status(f"Schnellverbindung zu: {profile.name}")
        self.connect_with_form()

    def _announce_connected(self) -> None:
        """Gibt Servername + Kanal via TTS aus (falls aktiviert)."""
        try:
            lc = getattr(self.client, "_last_connect", None)
            server = getattr(lc, "host", "") if lc else ""
            channel_name = ""
            try:
                ch_id = self.client.get_my_channel_id()
                if ch_id:
                    ch = self.client.get_channel(int(ch_id))
                    if ch:
                        channel_name = self.tt_str(ch.szName)
            except Exception:
                pass
            parts = [server] if server else []
            if channel_name:
                parts.append(f"Kanal {channel_name}")
            text = "Verbunden" + (", " + ", ".join(parts) if parts else "")
            self.tts.speak(text, kind="connect")
            self.bus.emit("connection_state_changed", connected=True, reason="login")
        except Exception:
            pass

    def _replay_offline_log(self) -> None:
        """Gibt im Offline-Puffer gesammelte Ereignisse im Chat aus."""
        if not self._offline_event_log:
            return
        log = list(self._offline_event_log)
        self._offline_event_log.clear()
        self.chat_tab.append_chat("--- Verpasste Ereignisse ---", kind="system", speak=False)
        for ts, text, kind in log:
            self.chat_tab.append_chat(f"[{ts}] {text}", kind=kind, speak=False)
        self.tts.speak(f"{len(log)} verpasste Ereignisse", kind="system")

    def _buffer_offline_event(self, text: str, kind: str) -> None:
        """Puffert ein Ereignis während der Offline-Phase (max. 50)."""
        if not self._offline_buffering:
            return
        ts = time.strftime("%H:%M:%S")
        self._offline_event_log.append((ts, text, kind))
        if len(self._offline_event_log) > 50:
            self._offline_event_log = self._offline_event_log[-50:]

    def _check_for_update(self) -> None:
        """Prüft im Hintergrund ob eine neuere Version verfügbar ist."""
        import urllib.request
        import urllib.error
        def _worker():
            try:
                url = "https://git.garogaming.xyz/api/v1/repos/flarion/TeamTalk-VO-Client/releases/latest"
                req = urllib.request.Request(
                    url, headers={"Authorization": f"token {_upd_tok()}"}
                )
                with urllib.request.urlopen(req, timeout=5) as resp:  # noqa: S310
                    data = json.loads(resp.read().decode("utf-8"))
                tag = str(data.get("tag_name", "") or "").lstrip("v")
                if tag and tag != APP_VERSION:
                    assets = data.get("assets", [])
                    dl_url = ""
                    if assets:
                        dl_url = str(assets[0].get("browser_download_url", "") or "")
                    if not dl_url:
                        dl_url = str(data.get("html_url", "") or "")
                    wx.CallAfter(
                        self.set_status,
                        f"Update verfügbar: v{tag} (aktuell: v{APP_VERSION})",
                    )
                    wx.CallAfter(self.tts.speak, f"Update verfügbar, Version {tag}", kind="system")
                    if dl_url:
                        wx.CallAfter(self._show_update_dialog, tag, dl_url)
            except Exception:
                pass
        threading.Thread(target=_worker, daemon=True).start()

    def _show_update_dialog(self, tag: str, url: str) -> None:
        dlg = wx.MessageDialog(
            self,
            f"Version {tag} ist verfügbar (aktuell: {APP_VERSION}).\n\nJetzt herunterladen?",
            "Update verfügbar",
            wx.YES_NO | wx.YES_DEFAULT | wx.ICON_INFORMATION,
        )
        dlg.SetYesNoLabels("Jetzt herunterladen", "Später")
        if dlg.ShowModal() == wx.ID_YES:
            wx.LaunchDefaultBrowser(url)
        dlg.Destroy()

    def scan_saved_servers_presence(self):
        servers = list(self.store.items())
        if not servers:
            self.set_status("Keine Server in der Liste")
            return

        self.connection_tab.server_check_btn.Disable()
        self.set_status("Prüfe Serverliste...")

        def _short_error(text: str, max_len: int = 380) -> str:
            cleaned = " ".join((text or "").split())
            if len(cleaned) <= max_len:
                return cleaned
            return cleaned[: max_len - 3] + "..."

        def worker():
            rows: List[Tuple[str, str, str, str]] = []
            restore_result: Optional[ConnectResult] = None
            had_active_connection = self.client.is_connected()
            saved_connect = self.client._last_connect
            sorted_servers = sorted(servers, key=lambda p: (p.encrypted, p.name.lower()))

            if had_active_connection:
                try:
                    self.client.stop_event_loop_and_wait()
                except Exception:
                    pass
                try:
                    self.client.disconnect_transport()
                except Exception:
                    pass

            for idx, profile in enumerate(sorted_servers):
                try:
                    payload = {
                        "host": profile.host,
                        "tcp_port": profile.tcp_port,
                        "udp_port": profile.udp_port,
                        "nickname": profile.nickname,
                        "username": profile.username,
                        "password": profile.password,
                        "client_name": profile.client_name,
                        "encrypted": bool(profile.encrypted),
                    }
                    data = _probe_server_payload(payload)

                    if not bool(data.get("ok", False)):
                        rows.append(
                            (
                                profile.name,
                                "Ja" if profile.encrypted else "Nein",
                                "Fehler",
                                _short_error(str(data.get("message", "Unbekannter Fehler"))),
                            )
                        )
                        continue

                    names = [str(n) for n in data.get("names", []) if str(n).strip()]
                    note = str(data.get("note", "") or "").strip()
                    if names:
                        details = ", ".join(names)
                        if note:
                            details = f"{details} ({note})"
                        rows.append(
                            (
                                profile.name,
                                "Ja" if profile.encrypted else "Nein",
                                f"{len(names)} online",
                                details,
                            )
                        )
                    else:
                        details = "-"
                        if note:
                            details = note
                        rows.append((profile.name, "Ja" if profile.encrypted else "Nein", "0 online", details))
                except Exception as exc:
                    rows.append((profile.name, "Ja" if profile.encrypted else "Nein", "Fehler", _short_error(str(exc))))
                if idx + 1 < len(sorted_servers):
                    time.sleep(0.35)

            self.client._last_connect = saved_connect

            if had_active_connection and saved_connect is not None:
                try:
                    restore_result = self.client.reconnect(timeout_ms=8000)
                except Exception as exc:
                    restore_result = ConnectResult(False, f"Reconnect fehlgeschlagen: {exc}")

            wx.CallAfter(self._finish_server_presence_scan, rows, restore_result)

        threading.Thread(target=worker, daemon=True).start()

    def _finish_server_presence_scan(
        self,
        rows: List[Tuple[str, str, str, str]],
        restore_result: Optional[ConnectResult] = None,
    ):
        self.connection_tab.server_check_btn.Enable()
        for server, _tls, status, details in rows:
            if status == "Fehler":
                line = f"{server}: nicht erreichbar ({details})"
            elif status == "0 online":
                line = f"{server}: niemand online"
            else:
                line = f"{server}: {status}" + (f" - {details}" if details else "")
            self.logger.write(f"Servercheck: {line}")

        if restore_result is not None:
            self.logger.write(f"Servercheck-Reconnect: {restore_result.message}")
            if restore_result.ok:
                self.client.start_event_loop(self.handle_tt_message)
                self._refresh_channels_with_retry()
                if self.files_tab is not None:
                    wx.CallLater(800, self.files_tab.refresh_file_list)

        self.set_status("Servercheck abgeschlossen")
        dlg = ServerCheckDialog(self, rows)
        dlg.ShowModal()
        dlg.Destroy()

    def join_channel(self, channel_id: int, password: str = "", _save_pw_to_keychain: bool = False):
        tab = self.connection_tab
        tab.join_root_btn.Disable()
        self.set_status("Trete Kanal bei...")

        def worker():
            try:
                self.client.stop_event_loop_and_wait()
                result = self.client.join_channel_by_id(channel_id, password=password, timeout_ms=8000)
                self.client.start_event_loop(self.handle_tt_message)
                if result.ok:
                    wx.CallAfter(self.set_status, result.message)
                    wx.CallAfter(self._save_last_channel, channel_id)
                    self.sound_manager.play("channel_join", self.settings_store.settings.sound_events.get("channel_join"))
                    wx.CallAfter(self.channels_tab.refresh_members_for_my_channel)
                    self.bus.emit("channel_joined", channel_id=channel_id)
                    # v2.8.0 – Letzte Kanäle
                    try:
                        ch = self.client.get_channel(channel_id)
                        ch_name = self.tt_str(getattr(ch, "szName", "")) if ch else str(channel_id)
                        wx.CallAfter(self._add_to_recent_channels, channel_id, ch_name or str(channel_id))
                        # v3.0.0 – Kanal-Thema beim Betreten vorlesen
                        if getattr(self.settings_store.settings, "tts_speak_channel_topic_on_join", True):
                            topic = self.tt_str(getattr(ch, "szTopic", "") or "") if ch else ""
                            if topic:
                                wx.CallAfter(self.tts.speak, f"Kanal-Thema: {topic}", kind="channel_topic")
                    except Exception:
                        pass
                    if self.files_tab is not None:
                        wx.CallAfter(self.files_tab.refresh_file_list)
                    # Keychain: Passwort nach erfolgreichem Beitritt speichern
                    if _save_pw_to_keychain and password:
                        try:
                            import keychain as kc
                            key = self._get_server_key()
                            if key:
                                kc.save_channel_password(key, channel_id, password)
                        except Exception:
                            pass
                elif result.error_code == 2001:  # CMDERR_INCORRECT_CHANNEL_PASSWORD
                    wx.CallAfter(self.set_status, "Kanal ist passwortgeschützt")
                    # Keychain-Eintrag löschen wenn er falsch war
                    if password:
                        try:
                            import keychain as kc
                            key = self._get_server_key()
                            if key:
                                kc.delete_channel_password(key, channel_id)
                        except Exception:
                            pass
                    wx.CallAfter(self._ask_channel_password, channel_id)
                else:
                    wx.CallAfter(self.set_status, result.message)
            except Exception as exc:
                self.client.start_event_loop(self.handle_tt_message)
                wx.CallAfter(self.set_status, f"Fehler: {exc}")
            finally:
                wx.CallAfter(tab.join_root_btn.Enable)

        threading.Thread(target=worker, daemon=True).start()

    def _ask_channel_password(self, channel_id: int):
        s = self.settings_store.settings
        # Keychain prüfen
        if s.save_channel_passwords:
            try:
                import keychain as kc
                key = self._get_server_key()
                if key:
                    saved_pw = kc.get_channel_password(key, channel_id)
                    if saved_pw is not None:
                        self.join_channel(channel_id, password=saved_pw)
                        return
            except Exception:
                pass
        # Benutzer fragen
        password = self._ask_text("Kanalpasswort", "Passwort für den Kanal eingeben:")
        if password is not None:
            save_to_keychain = bool(s.save_channel_passwords)
            self.join_channel(channel_id, password=password, _save_pw_to_keychain=save_to_keychain)

    def schedule_reconnect(self):
        if self._closing or not self._auto_reconnect:
            return
        s = self.settings_store.settings
        max_attempts = int(s.reconnect_max_attempts or 0)
        if max_attempts > 0 and self._reconnect_attempts >= max_attempts:
            self.set_status(f"Maximale Wiederverbindungsversuche ({max_attempts}) erreicht")
            return
        self._reconnect_attempts += 1
        min_delay_ms = max(1000, int(s.reconnect_delay_sec or 2) * 1000)
        delay = min(30000, min_delay_ms * (2 ** min(self._reconnect_attempts - 1, 4)))
        self._offline_buffering = True
        self.set_status(f"Wiederverbinden in {delay // 1000}s (Versuch {self._reconnect_attempts})")
        wx.CallLater(delay, self.connect_with_form)

    def _update_speak_tab(self, api_key: str) -> None:
        if api_key:
            if self.speak_tab is None:
                self.speak_tab = SpeakTab(self.content_panel, self)
            if not self._speak_tab_added:
                # Insert after "Kanäle und Chat" (index 1)
                self._panel_order.insert(1, "Sprechen")
                self._panels["Sprechen"] = self.speak_tab
                sizer = self.content_panel.GetSizer()
                sizer.Add(self.speak_tab, 1, wx.EXPAND)
                sizer.Show(self.speak_tab, False)
                self.tab_choice.SetItems(self._panel_order)
                self.tab_choice.SetSelection(self._panel_order.index("Kanäle und Chat"))
                self._speak_tab_added = True
            self.speak_tab.set_api_key(api_key)
        else:
            if self._speak_tab_added:
                sizer = self.content_panel.GetSizer()
                sizer.Detach(self.speak_tab)
                self.speak_tab.Hide()
                self._panels.pop("Sprechen", None)
                if "Sprechen" in self._panel_order:
                    self._panel_order.remove("Sprechen")
                self.tab_choice.SetItems(self._panel_order)
                self._speak_tab_added = False

    def _auto_init_sound_devices(self):
        """Initialize default sound devices after successful login."""
        try:
            indev, outdev = self.client.get_default_sound_devices()
            indev_id = int(getattr(indev, "value", indev))
            outdev_id = int(getattr(outdev, "value", outdev))
            input_ok = self.client.init_sound_input_device(indev_id)
            output_ok = self.client.init_sound_output_device(outdev_id)
            if input_ok and output_ok:
                self.logger.write(f"Auto-initialized sound devices: in={indev_id} out={outdev_id}")
            else:
                self.logger.write(f"Auto-init sound devices partial: input={input_ok} output={output_ok}")
        except Exception as exc:
            self.logger.write(f"Auto-init sound devices failed: {exc}")

    def _refresh_channels_with_retry(self, attempts: int = 8, delay_ms: int = 500):
        channels = list(self.client.get_server_channels() or [])
        if channels:
            self.channels_tab.refresh_channels_and_users()
            return
        if attempts <= 0:
            self.logger.write("No channels received after retries")
            return
        self.logger.write(f"Channels empty, retrying in {delay_ms}ms (left: {attempts})")
        wx.CallLater(delay_ms, lambda: self._refresh_channels_with_retry(attempts - 1, delay_ms))

    # ------------------------------------------------------------------
    # .tt file & pending join (complex join logic preserved)
    # ------------------------------------------------------------------

    def on_open_tt_file(self, _event):
        wildcard = "TeamTalk (*.tt;*.ini;*.txt;*.json;*.xml)|*.tt;*.ini;*.txt;*.json;*.xml|Alle Dateien|*.*"
        with wx.FileDialog(self, "TeamTalk-Datei öffnen", wildcard=wildcard) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            path = Path(dlg.GetPath())
        parsed = parse_teamtalk_file(path)
        if not parsed:
            self.set_status("Datei konnte nicht gelesen werden")
            return
        self.connection_tab.fill_form(parsed.profile)
        self.set_status(f"Profil geladen: {parsed.profile.name}")
        self._connect_from_profile(parsed)

    def _connect_from_profile(self, parsed: ParsedTeamTalkFile):
        def worker():
            self.client.stop_event_loop_and_wait()
            encrypted = bool(parsed.encrypted or parsed.profile.encrypted)
            verify_peer = parsed.verify_peer
            tls_has_custom_material = bool(
                (parsed.ca_certificate_pem or "").strip()
                or (parsed.client_certificate_pem or "").strip()
                or (parsed.client_private_key_pem or "").strip()
            )
            self.logger.write(
                f"Connect from .tt: host={parsed.profile.host} tcp={parsed.profile.tcp_port} "
                f"udp={parsed.profile.udp_port} user={parsed.profile.username} encrypted={encrypted} "
                f"verify_peer={verify_peer if verify_peer is not None else 'default'} "
                f"custom_material={tls_has_custom_material}"
            )
            _se = self.settings_store.settings.sound_events
            result = self.client.connect_and_login(
                host=parsed.profile.host,
                tcp_port=parsed.profile.tcp_port,
                udp_port=parsed.profile.udp_port,
                nickname=parsed.profile.nickname,
                username=parsed.profile.username,
                password=parsed.profile.password,
                client_name=parsed.profile.client_name,
                encrypted=encrypted,
                verify_peer=verify_peer,
                tls_has_custom_material=tls_has_custom_material,
                timeout_ms=8000,
                on_login_confirmed=lambda: self.sound_manager.play("server_connect", _se.get("server_connect")),
            )
            self._pending_join = parsed if result.ok else None
            wx.CallAfter(self.handle_connect_result, result)

        threading.Thread(target=worker, daemon=True).start()

    def _join_from_pending(self):
        parsed = self._pending_join
        self._pending_join = None
        if parsed is None:
            return
        if parsed.join_last_channel and not parsed.channel_path and parsed.channel_id is None:
            self.logger.write("join-last-channel enabled; waiting for server to place user")
            return

        def worker():
            try:
                self.client.stop_event_loop_and_wait()

                current_channel_id = self._wait_for_my_channel_id(timeout_sec=4)
                current_path = ""
                if current_channel_id and current_channel_id > 0:
                    try:
                        current_path = self.tt_str(self.client.get_channel_path(current_channel_id))
                    except Exception:
                        pass

                if parsed.channel_id is not None:
                    if current_channel_id == parsed.channel_id:
                        self.client.start_event_loop(self.handle_tt_message)
                        wx.CallAfter(self.set_status, "Bereits im Zielkanal")
                        return
                    result_join = self.client.join_channel_by_id(parsed.channel_id, parsed.channel_password or "", timeout_ms=8000)
                elif parsed.channel_path:
                    norm_t = self._normalize_channel_key(parsed.channel_path)
                    norm_c = self._normalize_channel_key(current_path)
                    if norm_t and norm_t == norm_c:
                        self.client.start_event_loop(self.handle_tt_message)
                        wx.CallAfter(self.set_status, "Bereits im Zielkanal")
                        return
                    result_join = self._join_by_path_or_lookup(parsed.channel_path, parsed.channel_password or "")
                else:
                    result_join = self.client.join_channel_by_id(self.client.get_root_channel_id(), timeout_ms=8000)

                self.client.start_event_loop(self.handle_tt_message)

                target_id = 0
                if parsed.channel_id is not None:
                    target_id = parsed.channel_id
                elif parsed.channel_path:
                    target_id = self._resolve_channel_path(parsed.channel_path, timeout_sec=2) or 0
                if target_id and self._verify_join(target_id, timeout_sec=4):
                    self.sound_manager.play("channel_join", self.settings_store.settings.sound_events.get("channel_join"))
                    wx.CallAfter(self.set_status, "Kanalbeitritt erfolgreich")
                    wx.CallAfter(self._save_last_channel, target_id)
                    wx.CallAfter(self.channels_tab.refresh_members_for_my_channel)
                    if self.files_tab is not None:
                        wx.CallAfter(self.files_tab.refresh_file_list)
                    return
                wx.CallAfter(self.set_status, result_join.message)
                if result_join.ok:
                    self.sound_manager.play("channel_join", self.settings_store.settings.sound_events.get("channel_join"))
                    wx.CallAfter(self._save_last_channel, parsed.channel_id or 0)
                    wx.CallAfter(self.channels_tab.refresh_members_for_my_channel)
                    if self.files_tab is not None:
                        wx.CallAfter(self.files_tab.refresh_file_list)
            except Exception as exc:
                self.client.start_event_loop(self.handle_tt_message)
                wx.CallAfter(self.set_status, f"Fehler beim Kanalbeitritt: {exc}")

        threading.Thread(target=worker, daemon=True).start()

    def _resolve_channel_path(self, path: str, timeout_sec: int = 5) -> Optional[int]:
        if not path:
            return None
        normalized = path.strip()
        if normalized.endswith("/") and len(normalized) > 1:
            normalized = normalized[:-1]
        end = time.time() + timeout_sec
        while time.time() < end:
            chan_id = self.client.get_channel_id_from_path(normalized)
            if chan_id and chan_id > 0:
                return chan_id
            time.sleep(0.25)
        return None

    def _normalize_channel_key(self, path: str) -> str:
        key = path.strip().strip("/")
        key = " ".join(key.split())
        return key.casefold()

    def _join_by_path_or_lookup(self, path: str, password: str) -> ConnectResult:
        result = self.client.join_channel_by_path(path, password or "", timeout_ms=8000)
        if result.ok:
            return result
        channels = list(self.client.get_server_channels())
        target_key = self._normalize_channel_key(path)
        for chan in channels:
            try:
                chan_path = self.tt_str(self.client.get_channel_path(chan.nChannelID))
            except Exception:
                chan_path = self.tt_str(chan.szName)
            if self._normalize_channel_key(chan_path) == target_key:
                return self.client.join_channel_by_id(int(chan.nChannelID), password or "", timeout_ms=8000)
        return result

    def _wait_for_my_channel_id(self, timeout_sec: int = 4) -> int:
        end = time.time() + timeout_sec
        while time.time() < end:
            chan_id = self.client.get_my_channel_id()
            if chan_id and chan_id > 0:
                return int(chan_id)
            time.sleep(0.25)
        return int(self.client.get_my_channel_id() or 0)

    def _verify_join(self, target_channel_id: int, timeout_sec: int = 4) -> bool:
        if target_channel_id <= 0:
            return False
        end = time.time() + timeout_sec
        while time.time() < end:
            if self.client.get_my_channel_id() == target_channel_id:
                return True
            time.sleep(0.25)
        return self.client.get_my_channel_id() == target_channel_id

    # ------------------------------------------------------------------
    # Server import / export
    # ------------------------------------------------------------------

    def on_import_servers(self, _event):
        with wx.FileDialog(self, "Serverliste importieren", wildcard="JSON (*.json)|*.json|Alle Dateien|*.*") as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            path = Path(dlg.GetPath())
        try:
            self.store.import_from(path)
            self.connection_tab.reload_server_list()
            self.set_status("Serverliste importiert")
        except Exception as exc:
            self.set_status(f"Import fehlgeschlagen: {exc}")

    def on_export_servers(self, _event):
        with wx.FileDialog(self, "Serverliste exportieren", wildcard="JSON (*.json)|*.json|Alle Dateien|*.*", style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            path = Path(dlg.GetPath())
        try:
            self.store.export_to(path)
            self.set_status("Serverliste exportiert")
        except Exception as exc:
            self.set_status(f"Export fehlgeschlagen: {exc}")

    def on_menu_settings_backup(self, _event) -> None:
        """Exportiert alle App-Daten als ZIP-Backup."""
        import zipfile as _zip
        import time as _time
        from platform_paths import app_data_dir as _app_data_dir
        app_dir = _app_data_dir()
        default_name = f"teamtalk_backup_{_time.strftime('%Y%m%d_%H%M%S')}.zip"
        with wx.FileDialog(
            self, "Einstellungen sichern",
            wildcard="ZIP-Backup (*.zip)|*.zip|Alle Dateien|*.*",
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
            defaultFile=default_name,
        ) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            dest = Path(dlg.GetPath())
        try:
            # Alle relevanten Dateien in ZIP schreiben
            _BACKUP_EXTENSIONS = {".db", ".json", ".txt"}
            with _zip.ZipFile(dest, "w", _zip.ZIP_DEFLATED) as zf:
                for f in app_dir.iterdir():
                    if f.is_file() and f.suffix.lower() in _BACKUP_EXTENSIONS:
                        zf.write(f, f.name)
            self.set_status(f"Backup erstellt: {dest.name}")
        except Exception as exc:
            self.set_status(f"Backup fehlgeschlagen: {exc}")

    def on_menu_settings_restore(self, _event) -> None:
        """Stellt ein ZIP-Backup wieder her (überschreibt aktuelle Einstellungen)."""
        import zipfile as _zip
        from platform_paths import app_data_dir as _app_data_dir
        app_dir = _app_data_dir()
        with wx.FileDialog(
            self, "Backup wiederherstellen",
            wildcard="ZIP-Backup (*.zip)|*.zip|Alle Dateien|*.*",
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        ) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            src = Path(dlg.GetPath())
        confirm = wx.MessageDialog(
            self,
            "Achtung: Die aktuellen Einstellungen werden überschrieben.\n"
            "Die App wird danach neu gestartet.\n\nFortfahren?",
            "Backup wiederherstellen",
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING,
        )
        if confirm.ShowModal() != wx.ID_YES:
            confirm.Destroy()
            return
        confirm.Destroy()
        try:
            with _zip.ZipFile(src, "r") as zf:
                zf.extractall(app_dir)
            self.set_status("Backup wiederhergestellt – App wird neu gestartet…")
            wx.CallLater(1500, self._restart_app)
        except Exception as exc:
            self.set_status(f"Wiederherstellung fehlgeschlagen: {exc}")

    def _restart_app(self) -> None:
        """Startet die App neu."""
        import subprocess as _sp
        _sp.Popen([sys.executable] + sys.argv)
        wx.CallAfter(self.on_menu_quit, None)

    # ------------------------------------------------------------------
    # Keyboard
    # ------------------------------------------------------------------

    def on_key_hook(self, event):
        key = event.GetKeyCode()
        if key == wx.WXK_F2:
            self.on_menu_connect(None)
            return
        if key == wx.WXK_F6:
            self.on_menu_user_message(None)
            return
        if key == wx.WXK_F5:
            if self.client.is_connected():
                self.channels_tab.refresh_channels_and_users()
            else:
                self.set_status("Nicht verbunden")
            return
        if key == wx.WXK_F9:
            at = self.audio_tab
            at.ptt_toggle.SetValue(not at.ptt_toggle.GetValue())
            at.on_ptt_toggle(None)
            return
        if not self._is_text_input_focused():
            settings = self.settings_store.settings
            if key and key == int(settings.hotkey_mute_all or 0):
                self._mute_all = not self._mute_all
                self.client.set_sound_output_mute(self._mute_all)
                self.set_status("Ausgabe stummgeschaltet" if self._mute_all else "Ausgabe aktiv")
                return
            if key and key == int(settings.hotkey_voice_activation or 0):
                self.on_menu_audio_va(None)
                return
            if key and key == int(settings.hotkey_video_tx or 0):
                self._video_tx_enabled = not self._video_tx_enabled
                self.video_tab.set_transmission_enabled(self._video_tx_enabled)
                return
            if key and key == int(settings.hotkey_announce_level or 0):
                self._announce_vu_level()
                return
            if key and key == int(settings.hotkey_announce_user_info or 0):
                self._announce_user_info()
                return
            if key and key == int(settings.hotkey_announce_ping or 0):
                self._announce_ping()
                return
            if key and key == int(settings.hotkey_reply_last_sender or 0):
                self._reply_last_sender()
                return
            if key and key == int(settings.hotkey_cycle_sound_profile or 0):
                self._cycle_sound_profile()
                return
            # v2.0.0
            if key and key == int(getattr(settings, "hotkey_cycle_braille_verbosity", 0) or 0):
                self.braille.cycle_verbosity()
                return
            if key and key == int(getattr(settings, "hotkey_ai_summary", 0) or 0):
                self._trigger_ai_summary()
                return
            # v2.2.0 / v3.8.0 – Lesezeichen-Hotkeys (1-9)
            for idx, hk_attr in enumerate([
                "hotkey_bookmark_1", "hotkey_bookmark_2", "hotkey_bookmark_3",
                "hotkey_bookmark_4", "hotkey_bookmark_5", "hotkey_bookmark_6",
                "hotkey_bookmark_7", "hotkey_bookmark_8", "hotkey_bookmark_9",
            ]):
                hk = int(getattr(settings, hk_attr, 0) or 0)
                if key and key == hk:
                    self._bookmarks.jump(self, idx)
                    return
            # v3.9.0 – KI-Antwortvorschläge
            hk_reply = int(getattr(settings, "hotkey_ai_reply_suggestions", 0) or 0)
            if key and key == hk_reply:
                self._show_ai_reply_suggestions()
                return
            # v2.3.0 – Makro-Hotkeys
            macro = self._macros.find_by_hotkey(key)
            if macro:
                self._macros.execute(macro)
                return
            # v2.4.0 – Aufnahme umschalten
            hk_rec = int(getattr(settings, "hotkey_record_toggle", 0) or 0)
            if key and key == hk_rec:
                if self._recording_active:
                    self.on_menu_record_stop(None)
                else:
                    self.on_menu_record_start(None)
                return
            # v2.5.0 – Status-Vorlagen
            for _idx, _hk_attr in enumerate(["hotkey_status_template_1", "hotkey_status_template_2", "hotkey_status_template_3"]):
                _hk = int(getattr(settings, _hk_attr, 0) or 0)
                if key and key == _hk:
                    self._apply_status_template(_idx)
                    return
            # v2.9.0 – Mikrofon-Boost
            hk_boost_up = int(getattr(settings, "hotkey_mic_boost_up", 0) or 0)
            hk_boost_down = int(getattr(settings, "hotkey_mic_boost_down", 0) or 0)
            if key and key == hk_boost_up:
                self._mic_boost_change(+1000)
                return
            if key and key == hk_boost_down:
                self._mic_boost_change(-1000)
                return
            # v3.1.0 – TTS abbrechen
            hk_tts_cancel = int(getattr(settings, "hotkey_tts_cancel", 0) or 0)
            if key and key == hk_tts_cancel:
                self.tts._stop_current()
                self.tts.clear_queue()
                self.set_status("TTS abgebrochen")
                return
            # v3.3.0 – Braille-Status ansagen
            hk_announce_status = int(getattr(settings, "hotkey_announce_status", 0) or 0)
            if key and key == hk_announce_status:
                self._announce_braille_status()
                return
        event.Skip()

    def on_key_down(self, event):
        if self._capture_ptt_hotkey or self._capture_hotkey_target:
            key = event.GetKeyCode()
            if key == wx.WXK_ESCAPE:
                self._capture_ptt_hotkey = False
                if self._capture_hotkey_target:
                    self.shortcuts_tab.set_capture_label(self._capture_hotkey_target, False)
                    self._capture_hotkey_target = None
                self.audio_tab.update_ptt_hotkey_label()
                self.set_status("PTT-Hotkey Aufnahme abgebrochen")
                return
            if self._capture_hotkey_target:
                target = self._capture_hotkey_target
                if target == "hotkey_mute_all":
                    self.settings_store.settings.hotkey_mute_all = int(key)
                elif target == "hotkey_voice_activation":
                    self.settings_store.settings.hotkey_voice_activation = int(key)
                elif target == "hotkey_video_tx":
                    self.settings_store.settings.hotkey_video_tx = int(key)
                elif target == "hotkey_announce_level":
                    self.settings_store.settings.hotkey_announce_level = int(key)
                elif target == "hotkey_announce_user_info":
                    self.settings_store.settings.hotkey_announce_user_info = int(key)
                elif target == "hotkey_announce_ping":
                    self.settings_store.settings.hotkey_announce_ping = int(key)
                elif target == "hotkey_reply_last_sender":
                    self.settings_store.settings.hotkey_reply_last_sender = int(key)
                elif target == "hotkey_cycle_sound_profile":
                    self.settings_store.settings.hotkey_cycle_sound_profile = int(key)
                elif target == "hotkey_cycle_braille_verbosity":
                    self.settings_store.settings.hotkey_cycle_braille_verbosity = int(key)
                elif target == "hotkey_ai_summary":
                    self.settings_store.settings.hotkey_ai_summary = int(key)
                elif target == "hotkey_bookmark_1":
                    self.settings_store.settings.hotkey_bookmark_1 = int(key)
                elif target == "hotkey_bookmark_2":
                    self.settings_store.settings.hotkey_bookmark_2 = int(key)
                elif target == "hotkey_bookmark_3":
                    self.settings_store.settings.hotkey_bookmark_3 = int(key)
                elif target == "hotkey_record_toggle":
                    self.settings_store.settings.hotkey_record_toggle = int(key)
                elif target == "hotkey_status_template_1":
                    self.settings_store.settings.hotkey_status_template_1 = int(key)
                elif target == "hotkey_status_template_2":
                    self.settings_store.settings.hotkey_status_template_2 = int(key)
                elif target == "hotkey_status_template_3":
                    self.settings_store.settings.hotkey_status_template_3 = int(key)
                elif target == "hotkey_mic_boost_up":
                    self.settings_store.settings.hotkey_mic_boost_up = int(key)
                elif target == "hotkey_mic_boost_down":
                    self.settings_store.settings.hotkey_mic_boost_down = int(key)
                elif target == "hotkey_tts_cancel":
                    self.settings_store.settings.hotkey_tts_cancel = int(key)
                elif target == "hotkey_announce_status":
                    self.settings_store.settings.hotkey_announce_status = int(key)
                self.settings_store.save()
                self.shortcuts_tab.set_capture_label(target, False)
                self._capture_hotkey_target = None
                self.set_status("Hotkey gespeichert")
                return
            self._ptt_hotkey = int(key)
            self.settings_store.settings.ptt_hotkey = int(key)
            self.settings_store.save()
            self._capture_ptt_hotkey = False
            self.audio_tab.update_ptt_hotkey_label()
            self.set_status("PTT-Hotkey gespeichert")
            return

        if self._ptt_enabled and event.GetKeyCode() == self._ptt_hotkey:
            if self._is_text_input_focused():
                event.Skip()
                return
            if not self._ptt_active:
                self._ptt_active = True
                self.client.enable_voice_transmission(True)
                self.set_status("Sprechen aktiv")
                # v2.8.0 – PTT-Zeitlimit
                ptt_max = int(getattr(self.settings_store.settings, "ptt_max_seconds", 0) or 0)
                if ptt_max > 0:
                    if self._ptt_timeout_call is not None:
                        try:
                            self._ptt_timeout_call.Stop()
                        except Exception:
                            pass
                    self._ptt_timeout_call = wx.CallLater(ptt_max * 1000, self._ptt_timeout_triggered)
            return
        event.Skip()

    def _mic_boost_change(self, delta: int) -> None:
        """v2.9.0 – Mikrofon-Gain um delta verändern und via TTS ansagen."""
        try:
            current = int(self.mic_gain_slider.GetValue())
            new_val = max(0, min(200, current + delta))
            self.mic_gain_slider.SetValue(new_val)
            # Apply to SDK (gain level is 0–32000; slider 0–200 maps roughly)
            sdk_val = new_val * 160  # 200 * 160 = 32000
            try:
                fn = getattr(self.client, "set_sound_input_gain_level", None)
                if fn:
                    fn(sdk_val)
            except Exception:
                pass
            self.tts.speak(f"Mikrofon {new_val}", kind="system")
        except Exception:
            pass

    def _ptt_timeout_triggered(self) -> None:
        if self._ptt_active:
            self._ptt_active = False
            self.client.enable_voice_transmission(False)
            self.set_status("PTT-Zeitlimit erreicht")
            self.tts.speak("PTT-Zeitlimit erreicht", kind="system")

    def on_key_up(self, event):
        if self._ptt_enabled and event.GetKeyCode() == self._ptt_hotkey:
            if self._ptt_active:
                self._ptt_active = False
                self.client.enable_voice_transmission(False)
                self.set_status("Sprechen aus")
                # v2.8.0 – PTT-Zeitlimit abbrechen
                if self._ptt_timeout_call is not None:
                    try:
                        self._ptt_timeout_call.Stop()
                    except Exception:
                        pass
                    self._ptt_timeout_call = None
            return
        event.Skip()

    def _is_text_input_focused(self) -> bool:
        focused = wx.Window.FindFocus()
        return isinstance(focused, (wx.TextCtrl, wx.ComboBox))

    def start_hotkey_capture(self, target: str) -> None:
        self._capture_hotkey_target = target
        self.shortcuts_tab.set_capture_label(target, True)
        self.set_status("Hotkey Aufnahme gestartet (ESC = Abbruch)")

    # ------------------------------------------------------------------
    # Push notifications
    # ------------------------------------------------------------------

    def _on_activate(self, event):
        self._window_focused = event.GetActive()
        # Pause audio polling when app is not focused to reduce CPU usage.
        if not self._window_focused:
            self.audio_tab.set_active(False)
            if self.desktop_tab is not None:
                self.desktop_tab.set_active(False)
        else:
            if self.settings_window.IsShown():
                self.audio_tab.set_active(True)
            if self.desktop_tab is not None:
                self.desktop_tab.set_active(True)
        event.Skip()

    def _send_notification(self, title: str, message: str):
        if not getattr(self.settings_store.settings, "notifications_enabled", True):
            return
        if self._window_focused and self.IsShown():
            return
        if sys.platform == "darwin":
            try:
                script = (
                    f'display notification {json.dumps(message)} '
                    f'with title {json.dumps(title)} '
                    f'subtitle "TeamTalk VO Client"'
                )
                subprocess.Popen(
                    ["osascript", "-e", script],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                return
            except Exception:
                pass
        try:
            notif = wx.adv.NotificationMessage(title, message, self)
            notif.Show()
        except Exception:
            pass

    def on_tab_changed(self, event):
        # Legacy handler — no longer used (panel switcher replaces wx.Notebook)
        pass

    def on_tab_choice_changed(self, event):
        idx = event.GetSelection()
        if idx == wx.NOT_FOUND:
            return
        try:
            label = self._panel_order[idx]
        except IndexError:
            return
        self._switch_to_panel(label)
        self._update_tab_info(idx)

    def _update_tab_info(self, idx: int) -> None:
        try:
            label = self._panel_order[idx]
        except (IndexError, TypeError):
            label = ""
        if label:
            info = self._tab_info_map.get(label, "")
            self.tab_info.SetLabel(info)
            if self.tab_choice.GetSelection() != idx:
                self.tab_choice.SetSelection(idx)

    def _switch_to_panel(self, label: str) -> None:
        """Show the panel for *label* and hide all others."""
        # Lazy-load if needed
        lazy_map = {
            "Aufnahme & Medien": ("media", MediaTab),
            "Desktop": ("desktop", DesktopTab),
            "Dateien": ("files", FilesTab),
            "Administration": ("admin", AdminTab),
        }
        if label in lazy_map:
            key, factory = lazy_map[label]
            if self._lazy_pages.get(key) is not None:
                self._replace_lazy_tab(key, factory)

        sizer = self.content_panel.GetSizer()
        for lbl, p in self._panels.items():
            if p is not None:
                sizer.Show(p, lbl == label)
        sizer.Layout()

        p = self._panels.get(label)
        if self.files_tab is not None and p is self.files_tab:
            wx.CallAfter(self.files_tab.refresh_file_list)

    def _ensure_lazy_tab(self, page: wx.Panel) -> None:
        # Replace placeholder panels with real tabs on first access.
        if page is self._lazy_pages.get("media"):
            self._replace_lazy_tab("media", MediaTab)
        elif page is self._lazy_pages.get("desktop"):
            self._replace_lazy_tab("desktop", DesktopTab)
        elif page is self._lazy_pages.get("files"):
            self._replace_lazy_tab("files", FilesTab)
        elif page is self._lazy_pages.get("admin"):
            self._replace_lazy_tab("admin", AdminTab)

    def _replace_lazy_tab(self, key: str, factory):
        placeholder = self._lazy_pages.get(key)
        if placeholder is None:
            return
        label_map = {
            "media": "Aufnahme & Medien",
            "desktop": "Desktop",
            "files": "Dateien",
            "admin": "Administration",
        }
        attr_map = {
            "media": "media_tab",
            "desktop": "desktop_tab",
            "files": "files_tab",
            "admin": "admin_tab",
        }
        label = label_map[key]
        try:
            new_tab = factory(self.content_panel, self)
        except Exception as exc:
            # Mark as done so we don't retry on every tab switch.
            self._lazy_pages[key] = None
            self.set_status(f"Fehler beim Laden des Tabs '{label}': {exc}")
            return
        setattr(self, attr_map[key], new_tab)
        self._panels[label] = new_tab
        sizer = self.content_panel.GetSizer()
        sizer.Replace(placeholder, new_tab)
        placeholder.Destroy()
        self._lazy_pages[key] = None
        sizer.Layout()

    # ------------------------------------------------------------------
    # Event handler (dispatches to tabs)
    # ------------------------------------------------------------------

    def handle_tt_message(self, msg):
        event = msg.nClientEvent
        tt = self.client.tt

        if event == tt.ClientEvent.CLIENTEVENT_CON_FAILED:
            wx.CallAfter(self.set_status, "Verbindung fehlgeschlagen")
            self._offline_buffering = True
            wx.CallAfter(self.schedule_reconnect)
            self.bus.emit("connection_state_changed", connected=False, reason="failed")
        elif event == tt.ClientEvent.CLIENTEVENT_CON_LOST:
            wx.CallAfter(self.set_status, "Verbindung verloren")
            self._offline_buffering = True
            wx.CallAfter(self.schedule_reconnect)
            self.sound_manager.play("server_disconnect", self.settings_store.settings.sound_events.get("server_disconnect"))
            self.bus.emit("connection_state_changed", connected=False, reason="lost")
        elif event == tt.ClientEvent.CLIENTEVENT_CON_CRYPT_ERROR:
            err = self.tt_str(msg.clienterrormsg.szErrorMsg)
            no = int(getattr(msg.clienterrormsg, "nErrorNo", 0) or 0)
            if err and no:
                wx.CallAfter(self.set_status, f"Verschlüsselungsfehler: {err} ({no})")
            elif err:
                wx.CallAfter(self.set_status, f"Verschlüsselungsfehler: {err}")
            elif no:
                wx.CallAfter(self.set_status, f"Verschlüsselungsfehler: {no}")
            else:
                wx.CallAfter(self.set_status, "Verschlüsselungsfehler")
        elif event == tt.ClientEvent.CLIENTEVENT_INTERNAL_ERROR:
            err = self.tt_str(msg.clienterrormsg.szErrorMsg)
            no = int(getattr(msg.clienterrormsg, "nErrorNo", 0) or 0)
            if err and no:
                wx.CallAfter(self.set_status, f"Interner Fehler: {err} ({no})")
            elif err:
                wx.CallAfter(self.set_status, f"Interner Fehler: {err}")
            elif no:
                wx.CallAfter(self.set_status, f"Interner Fehler: {no}")
            else:
                wx.CallAfter(self.set_status, "Interner Fehler")
        elif event == tt.ClientEvent.CLIENTEVENT_CMD_ERROR:
            err = self.tt_str(msg.clienterrormsg.szErrorMsg)
            wx.CallAfter(self.set_status, f"Fehler: {err}")
        elif event in (
            tt.ClientEvent.CLIENTEVENT_CMD_CHANNEL_NEW,
            tt.ClientEvent.CLIENTEVENT_CMD_CHANNEL_UPDATE,
            tt.ClientEvent.CLIENTEVENT_CMD_CHANNEL_REMOVE,
        ):
            if event == tt.ClientEvent.CLIENTEVENT_CMD_CHANNEL_UPDATE:
                try:
                    ch = getattr(msg, "channel", None)
                    if ch is not None:
                        my_ch = self.client.get_my_channel_id()
                        if my_ch and int(getattr(ch, "nChannelID", 0) or 0) == int(my_ch):
                            topic = self.tt_str(getattr(ch, "szTopic", "") or "")
                            if topic:
                                wx.CallAfter(self.tts.speak, f"Kanal-Thema: {topic}", kind="channel_topic")
                except Exception:
                    pass
            wx.CallAfter(self.channels_tab.refresh_channels_and_users)
        elif event in (
            tt.ClientEvent.CLIENTEVENT_CMD_USER_LOGGEDIN,
            tt.ClientEvent.CLIENTEVENT_CMD_USER_LOGGEDOUT,
            tt.ClientEvent.CLIENTEVENT_CMD_USER_JOINED,
            tt.ClientEvent.CLIENTEVENT_CMD_USER_LEFT,
            tt.ClientEvent.CLIENTEVENT_CMD_USER_UPDATE,
        ):
            # Capture values immediately in event thread before SDK buffer is overwritten
            _ev = event
            _user = getattr(msg, "user", None)
            _user_id = int(getattr(_user, "nUserID", 0) or 0) if _user else 0
            _user_ch = int(getattr(_user, "nChannelID", 0) or 0) if _user else 0
            _source = int(getattr(msg, "nSource", 0) or 0)
            # USER_UPDATE fires on every voice-state change (speaking, muting) —
            # skip the full list refresh to avoid O(n) SDK calls at audio rate.
            if _ev != tt.ClientEvent.CLIENTEVENT_CMD_USER_UPDATE:
                wx.CallAfter(self.channels_tab.refresh_members_for_my_channel)
            wx.CallAfter(self._emit_user_presence_event, msg, tt)
            wx.CallAfter(self._play_user_event_sound, _ev, _user_id, _user_ch, _source, tt)
            # v3.0.0 – Wer-spricht-Protokoll
            if _ev == tt.ClientEvent.CLIENTEVENT_CMD_USER_UPDATE and _user and _user_id:
                _speaking_flags = int(getattr(_user, "uUserState", 0) or 0)
                _is_talking = bool(_speaking_flags & 2)  # USERSTATE_TALKING = 2
                _uname = self.tt_str(getattr(_user, "szNickname", "")) or self.tt_str(getattr(_user, "szUsername", "")) or f"id{_user_id}"
                wx.CallAfter(self._track_speaking_log, _user_id, _uname, _is_talking)
            if self._user_recording_enabled:
                self._handle_user_recording_event(msg, tt)
        elif event == tt.ClientEvent.CLIENTEVENT_CMD_MYSELF_LOGGEDIN:
            wx.CallAfter(self.channels_tab.refresh_members_for_my_channel)
        elif event == tt.ClientEvent.CLIENTEVENT_CMD_USER_TEXTMSG:
            self._handle_text_message(msg, tt)
        elif event == tt.ClientEvent.CLIENTEVENT_STREAM_MEDIAFILE:
            if self.media_tab is not None:
                wx.CallAfter(self.media_tab.on_stream_update, msg.mediafileinfo)
        elif event == tt.ClientEvent.CLIENTEVENT_CMD_FILE_NEW:
            if self.files_tab is not None:
                wx.CallAfter(self.files_tab.refresh_file_list)
        elif event == tt.ClientEvent.CLIENTEVENT_CMD_FILE_REMOVE:
            if self.files_tab is not None:
                wx.CallAfter(self.files_tab.refresh_file_list)
        elif event == tt.ClientEvent.CLIENTEVENT_FILETRANSFER:
            if self.files_tab is not None:
                wx.CallAfter(self.files_tab.on_file_transfer_update, int(msg.nSource))
            try:
                if int(getattr(msg.filetransfer, "nStatus", 0)) == 2:  # FILETRANSFER_FINISHED
                    self.sound_manager.play("file_transfer", self.settings_store.settings.sound_events.get("file_transfer"))
                    try:
                        fname = self.tt_str(getattr(msg.filetransfer, "szRemoteFileName", "")) or "Datei"
                        wx.CallAfter(self.tts.speak, f"Dateitransfer abgeschlossen: {fname}", kind="file_transfer")
                        self.bus.emit("file_transfer_complete", filename=fname)
                    except Exception:
                        pass
            except Exception:
                pass
        elif event in (
            getattr(tt.ClientEvent, "CLIENTEVENT_SOUNDDEVICE_ADDED", -1),
            getattr(tt.ClientEvent, "CLIENTEVENT_SOUNDDEVICE_REMOVED", -1),
            getattr(tt.ClientEvent, "CLIENTEVENT_SOUNDDEVICE_UNPLUGGED", -1),
            getattr(tt.ClientEvent, "CLIENTEVENT_SOUNDDEVICE_NEW_DEFAULT_INPUT", -1),
            getattr(tt.ClientEvent, "CLIENTEVENT_SOUNDDEVICE_NEW_DEFAULT_OUTPUT", -1),
            getattr(tt.ClientEvent, "CLIENTEVENT_SOUNDDEVICE_NEW_DEFAULT_INPUT_COMDEVICE", -1),
            getattr(tt.ClientEvent, "CLIENTEVENT_SOUNDDEVICE_NEW_DEFAULT_OUTPUT_COMDEVICE", -1),
        ):
            wx.CallAfter(self.audio_tab.refresh_audio_devices, False, False, True)
        elif event == tt.ClientEvent.CLIENTEVENT_CMD_USERACCOUNT:
            if self.admin_tab is not None:
                wx.CallAfter(self.admin_tab.add_account_to_list, msg.useraccount)
        elif event == tt.ClientEvent.CLIENTEVENT_CMD_BANNEDUSER:
            if self.admin_tab is not None:
                wx.CallAfter(self.admin_tab.add_ban_to_list, msg.banneduser)
            if self.ban_dialog is not None:
                wx.CallAfter(self.ban_dialog.add_ban, msg.banneduser)
        elif event == tt.ClientEvent.CLIENTEVENT_CMD_SERVERSTATISTICS:
            if self.server_stats_dialog is not None:
                wx.CallAfter(self.server_stats_dialog.update_stats, msg.serverstatistics)
        elif event == tt.ClientEvent.CLIENTEVENT_USER_DESKTOPWINDOW:
            self.sound_manager.play("desktop_session", self.settings_store.settings.sound_events.get("desktop_session"))
            if self.desktop_tab is not None:
                try:
                    username = self.tt_str(msg.user.szNickname) or self.tt_str(msg.user.szUsername) or "Benutzer"
                except Exception:
                    username = "Benutzer"
                wx.CallAfter(self.desktop_tab.on_desktop_window, username)

    def _emit_user_presence_event(self, msg, tt):
        event = msg.nClientEvent
        user = getattr(msg, "user", None)
        if user is None:
            return
        me = self.client.get_my_user_id()
        if getattr(user, "nUserID", None) == me:
            return

        name = self.tt_str(user.szNickname) or self.tt_str(user.szUsername) or "Benutzer"
        channel_name = ""
        channel_id = 0

        if event == tt.ClientEvent.CLIENTEVENT_CMD_USER_JOINED:
            channel_id = int(getattr(user, "nChannelID", 0) or 0)
        elif event == tt.ClientEvent.CLIENTEVENT_CMD_USER_LEFT:
            channel_id = int(getattr(msg, "nSource", 0) or 0)

        if channel_id:
            ch = self.client.get_channel(channel_id)
            if ch is not None:
                channel_name = self.tt_str(ch.szName)

        if event == tt.ClientEvent.CLIENTEVENT_CMD_USER_LOGGEDIN:
            text = f"* {name} hat sich angemeldet"
            tts_kind = "system"
        elif event == tt.ClientEvent.CLIENTEVENT_CMD_USER_LOGGEDOUT:
            text = f"* {name} hat sich abgemeldet"
            tts_kind = "system"
        elif event == tt.ClientEvent.CLIENTEVENT_CMD_USER_JOINED:
            text = f"* {name} hat Kanal {channel_name or channel_id} betreten"
            # v2.8.0 – Nutzer-Notiz anhängen
            _note = self._get_user_note(name)
            if _note:
                text += f" (Notiz: {_note})"
            tts_kind = "user_join"
            user_id = int(getattr(user, "nUserID", 0) or 0)
            self.bus.emit("user_joined", user=name, user_id=user_id, channel_id=channel_id, channel_name=channel_name)
            # v2.4.0 – Gespeicherte Lautstärke anwenden
            if user_id:
                wx.CallAfter(self._apply_saved_user_volume, user_id)
            # v2.7.0 – Webhook
            self._webhook.emit("user_join", {"user": name, "channel": channel_name})
        elif event == tt.ClientEvent.CLIENTEVENT_CMD_USER_LEFT:
            text = f"* {name} hat Kanal {channel_name or channel_id} verlassen"
            tts_kind = "user_leave"
            user_id = int(getattr(user, "nUserID", 0) or 0)
            self.bus.emit("user_left", user=name, user_id=user_id, channel_id=channel_id, channel_name=channel_name)
            # v2.7.0 – Webhook
            self._webhook.emit("user_leave", {"user": name, "channel": channel_name})
        else:
            return

        self.chat_tab.append_chat(text, kind="system", speak=False)
        self.tts.speak(text, kind=tts_kind)
        self._buffer_offline_event(text, "system")
        self.emit_system_message(text, speak=False)
        self._send_notification("Status", text)

    def _play_user_event_sound(self, event, user_id: int, user_ch: int, source_ch: int, tt) -> None:
        """Wird auf dem Haupt-Thread ausgeführt; Werte wurden im Event-Thread erfasst."""
        se = self.settings_store.settings.sound_events
        my_id = int(self.client.get_my_user_id() or 0)
        my_ch = int(self.client.get_my_channel_id() or 0)

        if event == tt.ClientEvent.CLIENTEVENT_CMD_USER_JOINED:
            if my_id and user_id == my_id:
                # Ich selbst habe einen Kanal betreten
                self.sound_manager.play("channel_join", se.get("channel_join"))
            elif my_ch and user_ch == my_ch:
                # Anderer Benutzer betritt meinen Kanal
                self.sound_manager.play("user_join", se.get("user_join"))
        elif event == tt.ClientEvent.CLIENTEVENT_CMD_USER_LEFT:
            if my_id and user_id == my_id:
                pass  # eigenes Verlassen: direkt in on_leave_channel gespielt
            elif user_id and (not my_ch or source_ch == my_ch):
                # Anderer Benutzer verlässt meinen Kanal (oder channel unbekannt)
                self.sound_manager.play("user_leave", se.get("user_leave"))
        elif event == tt.ClientEvent.CLIENTEVENT_CMD_USER_LOGGEDIN:
            self.sound_manager.play("user_login", se.get("user_login"))
        elif event == tt.ClientEvent.CLIENTEVENT_CMD_USER_LOGGEDOUT:
            self.sound_manager.play("user_logout", se.get("user_logout"))

    def _handle_user_recording_event(self, msg, tt) -> None:
        event = msg.nClientEvent
        user = getattr(msg, "user", None)
        if user is None:
            return
        my_ch = self.client.get_my_channel_id()
        if not my_ch:
            return
        my_ch = int(my_ch)
        if event == tt.ClientEvent.CLIENTEVENT_CMD_USER_JOINED:
            if int(getattr(user, "nChannelID", 0) or 0) == my_ch:
                self._apply_user_recording_to_user(int(user.nUserID), True)
        elif event == tt.ClientEvent.CLIENTEVENT_CMD_USER_LEFT:
            self._apply_user_recording_to_user(int(user.nUserID), False)

    def configure_user_recording(
        self,
        enabled: bool,
        folder_path: str,
        filename_vars: str,
        audio_format: int,
        include_self: bool = True,
    ) -> None:
        self._user_recording_enabled = bool(enabled)
        self._user_recording_dir = folder_path or ""
        self._user_recording_pattern = filename_vars or ""
        self._user_recording_format = int(audio_format)
        self._user_recording_include_self = bool(include_self)
        if not self.client.is_connected():
            self.set_status("Konversationsaufzeichnung gespeichert (nicht verbunden)")
            return
        self._apply_user_recording_for_current_channel(self._user_recording_enabled)
        self.set_status(
            "Konversationsaufzeichnung aktiviert"
            if self._user_recording_enabled
            else "Konversationsaufzeichnung deaktiviert"
        )

    def _apply_user_recording_for_current_channel(self, enabled: bool) -> None:
        my_ch = self.client.get_my_channel_id()
        if not my_ch:
            return
        users = list(self.client.get_channel_users(int(my_ch)))
        for user in users:
            self._apply_user_recording_to_user(int(user.nUserID), enabled)
        if self._user_recording_include_self:
            self._apply_user_recording_to_user(0, enabled)

    def _apply_user_recording_to_user(self, user_id: int, enabled: bool) -> None:
        tt = self.client.tt
        if not enabled:
            self.client.set_user_media_storage_dir(
                user_id,
                "",
                "",
                int(tt.AudioFileFormat.AFF_NONE),
            )
            return
        self.client.set_user_media_storage_dir(
            user_id,
            self._user_recording_dir,
            self._user_recording_pattern,
            self._user_recording_format,
        )

    def _handle_text_message(self, msg, tt):
        key = (
            msg.textmessage.nFromUserID,
            msg.textmessage.nToUserID,
            msg.textmessage.nChannelID,
            msg.textmessage.nMsgType,
        )
        bucket = self._message_buffers.setdefault(key, [])
        bucket.append(msg.textmessage)
        if not msg.textmessage.bMore:
            content = tt.rebuildTextMessage(bucket)
            from_user = self.tt_str(msg.textmessage.szFromUsername)
            msg_type = int(msg.textmessage.nMsgType)
            from_id = int(msg.textmessage.nFromUserID)
            my_id = int(self.client.get_my_user_id() or 0)
            speak = True
            if from_id and my_id and from_id == my_id:
                # Avoid double TTS for own messages (server echo)
                speak = False
            if msg_type == int(tt.TextMsgType.MSGTYPE_USER):
                kind = "private"
            elif msg_type == int(tt.TextMsgType.MSGTYPE_CHANNEL):
                kind = "chat"
            elif msg_type == int(tt.TextMsgType.MSGTYPE_BROADCAST):
                kind = "system"
            else:
                kind = "chat"
            if msg_type == int(tt.TextMsgType.MSGTYPE_CHANNEL):
                timestamp = time.strftime("%H:%M:%S")
                channel_name = ""
                try:
                    chan = self.client.get_channel(int(msg.textmessage.nChannelID))
                    if chan:
                        channel_name = self.tt_str(getattr(chan, "szName", "")) or ""
                except Exception:
                    channel_name = ""
                if channel_name:
                    entry = f"[{timestamp}] {channel_name} {from_user}: {content}"
                else:
                    entry = f"[{timestamp}] {from_user}: {content}"
                self._channel_message_log.append(entry)
                if len(self._channel_message_log) > 200:
                    self._channel_message_log = self._channel_message_log[-200:]
            wx.CallAfter(self.chat_tab.append_chat, f"{from_user}: {content}", kind, speak)
            self._message_buffers.pop(key, None)
            # v2.8.0 – Stichwort-Alarm (nur Kanalnachrichten von anderen)
            if msg_type == int(tt.TextMsgType.MSGTYPE_CHANNEL) and not (from_id and my_id and from_id == my_id):
                wx.CallAfter(self._check_keyword_alert, content, from_user)
            # Bus-Event für Plugins
            self.bus.emit("chat_message", text=content, kind=kind, from_user=from_user, from_id=from_id)
            # Letzten privaten Absender merken (für Antwort-Hotkey)
            is_own = bool(from_id and my_id and from_id == my_id)
            if msg_type == int(tt.TextMsgType.MSGTYPE_USER) and not is_own and from_id:
                self._last_private_sender_id = from_id
                # v3.9.0 – für Antwortvorschläge
                self._last_private_message_text = str(content or "")
            # v3.9.0 – Echtzeit-Übersetzung (Hintergrundthread, nur fremde Nachrichten)
            if not is_own and self._translator.is_enabled():
                def _translate_and_append(txt=str(content or ""), kind_=kind, fu=from_user):
                    import threading as _t
                    def _worker():
                        translated = self._translator.translate(txt)
                        if translated and translated.strip() != txt.strip():
                            wx.CallAfter(
                                self.chat_tab.append_chat,
                                f"  ↳ [{self._translator.target_language()}] {translated}",
                                "system", False,
                            )
                    _t.Thread(target=_worker, daemon=True).start()
                wx.CallAfter(_translate_and_append)
                # v3.3.0 – VoiceOver-Ankündigung für eingehende Privatnachrichten
                from ui.a11y import post_voiceover_announcement
                wx.CallAfter(post_voiceover_announcement, f"Privatnachricht von {from_user}: {content}")
                # v3.5.0 – Makro-Trigger für eingehende Privatnachrichten
                self._macros.fire_event("private_msg", user=from_user or "", text=content or "")
            # Privatnachrichten-Verlauf speichern
            if msg_type == int(tt.TextMsgType.MSGTYPE_USER) and self.settings_store.settings.save_private_chat_history:
                server_key = self._get_server_key()
                if server_key:
                    partner = from_user or f"id{from_id}"
                    wx.CallAfter(
                        self._chat_history.append_private,
                        server_key, partner, f"{from_user}: {content}", kind,
                    )
            # Offline-Puffer für Chat-Nachrichten (bei Wiederverbindung)
            if msg_type == int(tt.TextMsgType.MSGTYPE_CHANNEL):
                wx.CallAfter(self._buffer_offline_event, f"{from_user}: {content}", kind)
            # Sound-Ereignisse
            se = self.settings_store.settings.sound_events
            if msg_type == int(tt.TextMsgType.MSGTYPE_USER):
                sound_key = "msg_private_tx" if is_own else "msg_private_rx"
                self.sound_manager.play(sound_key, se.get(sound_key))
            elif msg_type == int(tt.TextMsgType.MSGTYPE_CHANNEL):
                sound_key = "msg_channel_tx" if is_own else "msg_channel_rx"
                self.sound_manager.play(sound_key, se.get(sound_key))
            # Push notification
            if msg_type == int(tt.TextMsgType.MSGTYPE_USER):
                wx.CallAfter(self._send_notification, "Privatnachricht", f"{from_user}: {content}")
            elif msg_type == int(tt.TextMsgType.MSGTYPE_CHANNEL):
                wx.CallAfter(self._send_notification, "Kanalnachricht", f"{from_user}: {content}")
            elif msg_type == int(tt.TextMsgType.MSGTYPE_BROADCAST):
                wx.CallAfter(self._send_notification, "Rundnachricht", f"{from_user}: {content}")
            # v2.5.0 – Auto-Antwort
            if msg_type == int(tt.TextMsgType.MSGTYPE_USER) and not is_own and from_id:
                self._auto_reply.handle_private_message(from_id, from_user)
            # v2.7.0 – Webhook
            wh_event = {
                int(tt.TextMsgType.MSGTYPE_USER): "private_msg",
                int(tt.TextMsgType.MSGTYPE_CHANNEL): "channel_msg",
                int(tt.TextMsgType.MSGTYPE_BROADCAST): "broadcast_msg",
            }.get(msg_type)
            if wh_event:
                self._webhook.emit(wh_event, {"from_user": from_user, "text": content})

    def emit_system_message(self, text: str, speak: bool = False) -> None:
        self.system_tab.append_system(text)
        self.logger.write(f"SYSTEM {text}")
        if speak:
            self.tts.speak(text, kind="system")

    # ------------------------------------------------------------------
    # Close / lifecycle
    # ------------------------------------------------------------------

    def on_menu_quit(self, _event):
        self.force_close()

    def on_close(self, event):
        self.Hide()
        try:
            self.connection_window.Hide()
        except Exception:
            pass
        try:
            self.settings_window.Hide()
        except Exception:
            pass
        self.tray.SetIcon(self.tray._icon, f"TeamTalk VoiceOver Client {APP_VERSION} (im Tray)")
        self.set_status("Im Tray ausgeblendet")
        event.Veto()

    def force_close(self):
        if self._closing:
            return
        self._closing = True
        # Dismiss any open modal dialogs so Destroy() can proceed
        for win in wx.GetTopLevelWindows():
            try:
                if isinstance(win, wx.Dialog) and win.IsModal():
                    win.EndModal(wx.ID_CANCEL)
            except Exception:
                pass
        # Stop all timers first so no callbacks fire during teardown
        if hasattr(self, '_vu_timer'):
            self._vu_timer.Stop()
        if hasattr(self, '_scheduled_rec_timer'):
            self._scheduled_rec_timer.Stop()
        try:
            self.connection_tab.destroy_timers()
        except Exception:
            pass
        try:
            self.audio_tab.destroy_timers()
        except Exception:
            pass
        # Stop media / recording
        if self.media_tab is not None:
            try:
                self.media_tab.stop_all()
            except Exception:
                pass
        # Stop ElevenLabs streaming / cleanup
        if self.speak_tab is not None:
            try:
                self.speak_tab.cleanup()
            except Exception:
                pass
        # v2.0.0 – Sprachsteuerung beenden
        try:
            self._stop_voice_control()
        except Exception:
            pass
        # v2.3.0 – Zeitgesteuerte Stille beenden
        try:
            self._mute_scheduler.stop()
        except Exception:
            pass
        # v2.6.0 – Verbindungsqualitäts-Timer beenden
        try:
            if hasattr(self, "_quality_timer") and self._quality_timer.IsRunning():
                self._quality_timer.Stop()
        except Exception:
            pass
        # v2.7.0 – HTTP-API stoppen
        try:
            self._http_api.stop()
        except Exception:
            pass
        # v4.0.0 – Asyncio-Bridge stoppen
        try:
            self._async_bridge.stop()
        except Exception:
            pass
        # v2.0.0 – SQLite-DB schließen
        try:
            self._settings_db.close()
        except Exception:
            pass
        # Stop global hotkeys
        if self._global_hotkey_mgr is not None:
            try:
                self._global_hotkey_mgr.stop()
            except Exception:
                pass
        # Stop TTS worker thread
        try:
            self.tts.close()
        except Exception:
            pass
        # Stop SDK event thread and wait for it to finish before destroying wx objects
        try:
            self.client.stop_event_loop_and_wait(timeout=1.0)
            self.client.client.closeTeamTalk()
        except Exception:
            pass
        # Destroy UI
        try:
            self.tray.Destroy()
        except Exception:
            pass
        try:
            self.connection_window.Destroy()
        except Exception:
            pass
        try:
            self.settings_window.Destroy()
        except Exception:
            pass
        self.Destroy()


class App(wx.App):
    def OnInit(self) -> bool:
        from ui.a11y import patch_button_accessibility, patch_list_row_accessibility, patch_control_accessibility
        patch_button_accessibility()
        patch_list_row_accessibility()
        patch_control_accessibility()
        frame = MainFrame()
        frame.Show()
        return True

    def OnExit(self) -> int:
        # Force-terminate the process after all windows are destroyed.
        # Without this, PyObjC destructors run after wx cleanup on macOS and
        # trigger an NSException ("unerwartet beendet" crash report dialog).
        import os
        os._exit(0)
        return 0


def _probe_server_payload(payload: Dict[str, object]) -> Dict[str, object]:
    result_data: Dict[str, object] = {"ok": False, "message": "Probe-Parameter ungültig", "names": []}
    scanner = TeamTalkClient()
    try:
        host = str(payload.get("host", ""))
        tcp_port = int(payload.get("tcp_port", 0))
        udp_port = int(payload.get("udp_port", 0))
        nickname = str(payload.get("nickname", "VoiceOverUser"))
        username = str(payload.get("username", ""))
        password = str(payload.get("password", ""))
        client_name = str(payload.get("client_name", "TeamTalk VO"))
        encrypted = bool(payload.get("encrypted", False))

        def _probe_connect(user: str, pwd: str, retries: int, use_encrypted: Optional[bool] = None) -> ConnectResult:
            last = ConnectResult(False, "Unbekannter Fehler")
            effective_encrypted = encrypted if use_encrypted is None else use_encrypted
            for attempt in range(max(1, retries)):
                last = scanner.connect_and_login(
                    host=host,
                    tcp_port=tcp_port,
                    udp_port=udp_port,
                    nickname=nickname,
                    username=user,
                    password=pwd,
                    client_name=client_name,
                    encrypted=effective_encrypted,
                    remember_last_connect=False,
                    timeout_ms=12000,
                )
                if last.ok:
                    return last
                if attempt + 1 < retries:
                    time.sleep(0.3)
            return last

        result = _probe_connect(username, password, 6)
        tls_hint = ""
        if (
            not result.ok
            and encrypted
            and not username.strip()
            and not password.strip()
        ):
            # Some public encrypted servers still expect the legacy "guest" user.
            result = _probe_connect("guest", "", 4)
        if not result.ok and not encrypted:
            # Some servers only accept TLS even if the entry is stored as plain.
            tls_try = _probe_connect(username, password, 6, use_encrypted=True)
            if tls_try.ok:
                result = tls_try
                tls_hint = "Hinweis: Server erwartet TLS (verschlüsselt)."
        if not result.ok:
            result_data = {"ok": False, "message": result.message, "names": []}
        else:
            users = list(scanner.get_server_users() or [])
            names: List[str] = []
            for user in users:
                nickname = scanner.tt.ttstr(getattr(user, "szNickname", "")).strip()
                username = scanner.tt.ttstr(getattr(user, "szUsername", "")).strip()
                if nickname and username and nickname != username:
                    names.append(f"{nickname} ({username})")
                elif nickname or username:
                    names.append(nickname or username)
            names = sorted(names, key=str.casefold)
            result_data = {"ok": True, "message": "ok", "names": names}
            if tls_hint:
                result_data["note"] = tls_hint
    except Exception:
        result_data = {"ok": False, "message": traceback.format_exc(), "names": []}
    finally:
        try:
            scanner.disconnect_transport()
        except Exception:
            pass
        try:
            scanner.close()
        except Exception:
            pass
    return result_data


def _run_probe_server_once(argv: List[str]) -> int:
    out_path = ""
    payload_json = ""
    try:
        if "--probe-server" in argv:
            idx = argv.index("--probe-server")
            payload_json = argv[idx + 1]
        if "--probe-out" in argv:
            idx = argv.index("--probe-out")
            out_path = argv[idx + 1]
    except Exception:
        return 2
    if not payload_json or not out_path:
        return 2

    try:
        payload = json.loads(payload_json)
    except Exception:
        return 2

    result_data = _probe_server_payload(payload)
    try:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result_data, f, ensure_ascii=False)
    except Exception:
        return 3
    return 0


if __name__ == "__main__":
    try:
        if "--probe-server" in sys.argv:
            raise SystemExit(_run_probe_server_once(sys.argv))
        app = App(False)
        app.MainLoop()
    except Exception:
        from platform_paths import log_dir as _log_dir
        crash_dir = _log_dir()
        try:
            crash_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            if sys.platform == "win32":
                crash_dir = Path(os.environ.get("TEMP", "C:\\Temp")) / "TeamTalkVOClient"
            else:
                crash_dir = Path("/tmp") / "TeamTalkVOClient"
            crash_dir.mkdir(parents=True, exist_ok=True)
        crash_log = crash_dir / "last_crash.txt"
        crash_log.write_text(traceback.format_exc(), encoding="utf-8")
        raise
