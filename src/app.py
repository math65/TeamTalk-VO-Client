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


APP_VERSION = "0.10.8"


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
    try:
        stream = log_file.open("a", encoding="utf-8")
        sys.stdout = stream
        sys.stderr = stream
        print("\n=== Startup", time.strftime("%Y-%m-%d %H:%M:%S"), "===")
        print("sys.argv:", sys.argv)
        print("sys.frozen:", getattr(sys, "frozen", False))
        print("sys._MEIPASS:", getattr(sys, "_MEIPASS", None))
    except Exception:
        pass


_init_startup_logging()

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
        self._status_mode = 0
        self._status_message = ""
        self._capture_hotkey_target: Optional[str] = None
        self._user_volume_levels: Dict[int, int] = {}
        self._user_media_volume_levels: Dict[int, int] = {}
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
        self.store = ServerStore(app_dir / "servers.json")
        self.settings_store = SettingsStore(app_dir / "settings.json")
        self.logger = FileLogger(app_dir / "client.log")
        self.tts = TTSManager(self)
        self.sound_manager = SoundManager()
        self._ptt_hotkey = int(self.settings_store.settings.ptt_hotkey or 0) or wx.WXK_SPACE

        # Tray
        self.tray = TrayIcon(self)

        # Menu
        self._build_menu()

        # --- Notebook ---
        panel = wx.Panel(self)
        panel.SetName("Hauptfenster")
        main_sizer = wx.BoxSizer(wx.VERTICAL)

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

        self.tb_ptt = wx.CheckBox(qa_panel, label="PTT")
        self.tb_ptt.SetName("Push-to-Talk")
        self.tb_va = wx.CheckBox(qa_panel, label="Sprachaktivierung")
        self.tb_va.SetName("Sprachaktivierung")
        self.tb_video = wx.CheckBox(qa_panel, label="Video")
        self.tb_video.SetName("Video senden")
        self.tb_desktop = wx.CheckBox(qa_panel, label="Desktop")
        self.tb_desktop.SetName("Desktop freigeben")
        self.tb_mute = wx.CheckBox(qa_panel, label="Stumm")
        self.tb_mute.SetName("Alles stummschalten")
        self.tb_record = wx.CheckBox(qa_panel, label="Aufnahme")
        self.tb_record.SetName("Aufnahme")
        self.tb_question = wx.CheckBox(qa_panel, label="?-Modus")
        self.tb_question.SetName("Frage-Modus")

        for btn in (self.tb_ptt, self.tb_va, self.tb_video, self.tb_desktop,
                    self.tb_mute, self.tb_record, self.tb_question):
            qa_sizer.Add(btn, 0, wx.RIGHT, 4)

        qa_sizer.AddSpacer(16)

        # Master volume slider (output)
        qa_sizer.Add(wx.StaticText(qa_panel, label="Ausgabe:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        self.master_volume_slider = wx.Slider(qa_panel, value=100, minValue=0, maxValue=200, style=wx.SL_HORIZONTAL)
        self.master_volume_slider.SetName("Ausgabelautstärke")
        self.master_volume_slider.SetMinSize((100, -1))
        qa_sizer.Add(self.master_volume_slider, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 12)

        # Mic gain slider
        qa_sizer.Add(wx.StaticText(qa_panel, label="Mikrofon:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        self.mic_gain_slider = wx.Slider(qa_panel, value=100, minValue=0, maxValue=200, style=wx.SL_HORIZONTAL)
        self.mic_gain_slider.SetName("Mikrofon-Gain")
        self.mic_gain_slider.SetMinSize((100, -1))
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
            "Kanäle und Chat": "Kanäle, Nutzerliste, Chat und Privatnachrichten.",
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
        self.master_volume_slider.Bind(wx.EVT_SLIDER, self._on_master_volume_slider)
        self.mic_gain_slider.Bind(wx.EVT_SLIDER, self._on_mic_gain_slider)
        # VU meter timer
        self._vu_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_vu_timer, self._vu_timer)
        self._vu_timer.Start(100)

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
            self.audio_tab.output_volume.SetValue(level)
        except Exception:
            pass

    def _on_mic_gain_slider(self, event):
        level = event.GetEventObject().GetValue()
        sdk_level = int(level * 160)
        try:
            self.client.set_sound_input_gain(sdk_level)
            self.audio_tab.input_gain.SetValue(level)
        except Exception:
            pass

    def _on_vu_timer(self, _event):
        try:
            level = self.client.get_sound_input_level()
            if level is not None:
                self.vu_meter.SetValue(min(100, int(level * 100 / 32768)))
        except Exception:
            pass

    def apply_display_settings(self) -> None:
        """Wendet Anzeigeeinstellungen auf das Hauptfenster an (Toolbar, Log, Immer-vorne)."""
        s = self.settings_store.settings
        self.qa_panel.Show(bool(s.show_toolbar))
        self.log.Show(bool(s.show_event_log))
        if bool(s.always_on_top):
            self.SetWindowStyle(self.GetWindowStyle() | wx.STAY_ON_TOP)
        else:
            self.SetWindowStyle(self.GetWindowStyle() & ~wx.STAY_ON_TOP)
        self.Layout()

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
        con_server_check = file_menu.Append(wx.ID_ANY, "Server prüfen")
        file_menu.AppendSeparator()
        import_servers = file_menu.Append(wx.ID_ANY, "Serverliste importieren...")
        export_servers = file_menu.Append(wx.ID_ANY, "Serverliste exportieren...")
        file_menu.AppendSeparator()
        quit_item = file_menu.Append(wx.ID_EXIT, "Beenden\tCtrl+Q")

        menubar.Append(file_menu, "Datei")

        

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
        chan_msg = chan_menu.Append(wx.ID_ANY, "Kanalnachricht senden...")
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
        chan_stream_radio = chan_stream_menu.Append(wx.ID_ANY, "Webradio streamen...")
        chan_stream_podcast = chan_stream_menu.Append(wx.ID_ANY, "Podcast streamen...")
        chan_stream_twitch = chan_stream_menu.Append(wx.ID_ANY, "Twitch streamen...")
        chan_menu.AppendSubMenu(chan_stream_menu, "Streaming")
        menubar.Append(chan_menu, "Kanal")

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
        user_adv = wx.Menu()
        user_vol_up = user_adv.Append(wx.ID_ANY, "Lauter\tCtrl+Right")
        user_vol_down = user_adv.Append(wx.ID_ANY, "Leiser\tCtrl+Left")
        user_relay_voice = user_adv.Append(wx.ID_ANY, "Sprachstream weiterleiten")
        user_relay_media = user_adv.Append(wx.ID_ANY, "Medienstream weiterleiten")
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
        user_menu.AppendSubMenu(user_tx_menu, "Sendekontrolle")
        user_menu.AppendSeparator()
        user_subs = user_menu.Append(wx.ID_ANY, "Abonnements...")
        user_move = user_menu.Append(wx.ID_ANY, "Benutzer verschieben...")
        user_store_move = user_menu.Append(wx.ID_ANY, "Zielkanal merken")
        user_move_stored = user_menu.Append(wx.ID_ANY, "In Zielkanal verschieben")
        user_menu.AppendSeparator()
        user_mute_all = user_menu.AppendCheckItem(wx.ID_ANY, "Alles stummschalten")
        menubar.Append(user_menu, "Benutzer")

        # Server
        server_menu = wx.Menu()
        server_online = server_menu.Append(wx.ID_ANY, "Online-Benutzer...")
        server_broadcast = server_menu.Append(wx.ID_ANY, "Servernachricht senden...")
        server_stats = server_menu.Append(wx.ID_ANY, "Serverstatistiken...")
        server_bans = server_menu.Append(wx.ID_ANY, "Sperren (Server) anzeigen...")
        server_admin = server_menu.Append(wx.ID_ANY, "Administration öffnen")
        server_props = server_menu.Append(wx.ID_ANY, "Servereigenschaften...")
        server_save_config = server_menu.Append(wx.ID_ANY, "Konfiguration speichern")
        menubar.Append(server_menu, "Server")

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
        menubar.Append(profile_menu, "Profil")

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
        menubar.Append(audio_menu, "Audio")

        # Video
        video_menu = wx.Menu()
        video_tx = video_menu.AppendCheckItem(wx.ID_ANY, "Video senden")
        video_menu.AppendSeparator()
        video_settings = video_menu.Append(wx.ID_ANY, "Video-Einstellungen...")
        video_refresh = video_menu.Append(wx.ID_ANY, "Video-Geräte aktualisieren")
        menubar.Append(video_menu, "Video")

        # Aufnahmen
        rec_menu = wx.Menu()
        rec_convo = rec_menu.Append(wx.ID_ANY, "Konversationen aufzeichnen...")
        rec_menu.AppendSeparator()
        rec_start = rec_menu.Append(wx.ID_ANY, "Aufnahme starten...")
        rec_stop = rec_menu.Append(wx.ID_ANY, "Aufnahme stoppen")
        menubar.Append(rec_menu, "Aufnahmen")

        # Hilfe
        help_menu = wx.Menu()
        help_settings = help_menu.Append(wx.ID_PREFERENCES, "Einstellungen...\tCmd+,")
        help_logs = help_menu.Append(wx.ID_ANY, "Logs exportieren...")
        help_stats = help_menu.Append(wx.ID_ANY, "Verbindungsstatistiken...")
        help_stats_speak = help_menu.Append(wx.ID_ANY, "Statistiken vorlesen")
        help_menu.AppendSeparator()
        help_changelog = help_menu.Append(wx.ID_ANY, "Changelog")
        help_about = help_menu.Append(wx.ID_ANY, "Über")
        menubar.Append(help_menu, "Hilfe")

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
        self.Bind(wx.EVT_MENU, self.on_menu_channel_message, chan_msg)
        self.Bind(wx.EVT_MENU, self.on_menu_channel_file_upload, chan_file_upload)
        self.Bind(wx.EVT_MENU, self.on_menu_channel_file_download, chan_file_download)
        self.Bind(wx.EVT_MENU, self.on_menu_channel_file_delete, chan_file_delete)
        self.Bind(wx.EVT_MENU, self.on_menu_channel_file_refresh, chan_file_refresh)
        self.Bind(wx.EVT_MENU, lambda e: self.on_menu_channel_stream_mode(0, e), chan_stream_file)
        self.Bind(wx.EVT_MENU, lambda e: self.on_menu_channel_stream_mode(1, e), chan_stream_yt)
        self.Bind(wx.EVT_MENU, lambda e: self.on_menu_channel_stream_mode(2, e), chan_stream_radio)
        self.Bind(wx.EVT_MENU, lambda e: self.on_menu_channel_stream_mode(3, e), chan_stream_podcast)
        self.Bind(wx.EVT_MENU, lambda e: self.on_menu_channel_stream_mode(4, e), chan_stream_twitch)

        self.Bind(wx.EVT_MENU, self.on_menu_user_info, user_info)
        self.Bind(wx.EVT_MENU, self.on_menu_user_info_speak, user_info_speak)
        self.Bind(wx.EVT_MENU, self.on_menu_user_message, user_message)
        self.Bind(wx.EVT_MENU, self.on_menu_user_mute_voice, user_mute_voice)
        self.Bind(wx.EVT_MENU, self.on_menu_user_mute_media, user_mute_media)
        self.Bind(wx.EVT_MENU, self.on_menu_user_volume, user_volume)
        self.Bind(wx.EVT_MENU, self.on_menu_user_volume_up, user_vol_up)
        self.Bind(wx.EVT_MENU, self.on_menu_user_volume_down, user_vol_down)
        self.Bind(wx.EVT_MENU, self.on_menu_user_relay_voice, user_relay_voice)
        self.Bind(wx.EVT_MENU, self.on_menu_user_relay_media, user_relay_media)
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

        self.Bind(wx.EVT_MENU, self.on_menu_video_toggle, video_tx)
        self.Bind(wx.EVT_MENU, self.on_menu_video_settings, video_settings)
        self.Bind(wx.EVT_MENU, self.on_menu_video_refresh, video_refresh)

        self.Bind(wx.EVT_MENU, self.on_menu_record_start, rec_start)
        self.Bind(wx.EVT_MENU, self.on_menu_record_stop, rec_stop)
        self.Bind(wx.EVT_MENU, self.on_menu_record_conversations, rec_convo)

        self.Bind(wx.EVT_MENU, self.on_menu_settings, help_settings)
        self.Bind(wx.EVT_MENU, self.on_menu_export_logs, help_logs)
        self.Bind(wx.EVT_MENU, self.on_menu_client_stats, help_stats)
        self.Bind(wx.EVT_MENU, self.on_menu_client_stats_speak, help_stats_speak)
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
            focus_map = {
                0: getattr(self.media_tab, "media_path", None),
                1: getattr(self.media_tab, "yt_url", None),
                2: getattr(self.media_tab, "radio_search", None),
                3: getattr(self.media_tab, "podcast_list", None),
                4: getattr(self.media_tab, "twitch_url", None),
            }
            ctrl = focus_map.get(int(mode_idx))
            if ctrl is not None:
                wx.CallAfter(ctrl.SetFocus)
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
        return volume

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
        self.set_status("Verbindung getrennt")

    def on_menu_reconnect(self, _event):
        self.connection_tab.on_reconnect(None)

    def on_menu_auto_reconnect(self, event):
        enabled = event.IsChecked()
        self._auto_reconnect = enabled
        self.connection_tab.auto_reconnect.SetValue(enabled)

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

    def on_menu_audio_settings(self, _event):
        if not self.settings_window.IsShown():
            self.settings_window.Show()
        self.settings_window.Raise()
        self.settings_tab.show_section("Audio")
        wx.CallAfter(self.settings_tab.section_choice.SetFocus)

    def on_sound_menu_open(self, event):
        menu = event.GetMenu()
        if menu is self._sound_input_menu:
            self._populate_sound_device_menu(menu, kind="input")
        elif menu is self._sound_output_menu:
            self._populate_sound_device_menu(menu, kind="output")
        event.Skip()

    def _populate_sound_device_menu(self, menu: wx.Menu, kind: str) -> None:
        menu.Clear()
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

    def on_menu_about(self, _event):
        text = self._build_about_text()
        dlg = wx.Dialog(self, title="Über", style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        accel = wx.AcceleratorTable([(wx.ACCEL_CMD, ord("W"), wx.ID_CLOSE)])
        dlg.SetAcceleratorTable(accel)
        dlg.Bind(wx.EVT_MENU, lambda e: dlg.EndModal(wx.ID_CANCEL), id=wx.ID_CLOSE)
        root = wx.BoxSizer(wx.VERTICAL)
        info = wx.TextCtrl(
            dlg,
            value=text,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2,
        )
        info.SetMinSize((700, 520))
        root.Add(info, 1, wx.ALL | wx.EXPAND, 10)
        btns = dlg.CreateButtonSizer(wx.OK)
        root.Add(btns, 0, wx.ALL | wx.ALIGN_RIGHT, 10)
        dlg.SetSizerAndFit(root)
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

    def _build_about_text(self) -> str:
        parts: List[str] = []
        parts.append(f"TeamTalk VoiceOver Client {APP_VERSION}")
        parts.append("Entwickler: Flarion")
        parts.append("Hinweis: Beta-Tester werden später aufgeführt.")
        parts.append("")
        parts.append("Bestandteile:")
        parts.append("- TeamTalk SDK (BearWare)")
        parts.append("- wxPython")
        parts.append("- PyInstaller")
        parts.append("- espeak-ng")
        parts.append("- yt-dlp")
        parts.append("- certifi, urllib3, charset-normalizer")
        parts.append("")
        parts.append("Lizenzen:")

        base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
        license_paths = [
            base / "licenses" / "TEAMTALK_VO_CLIENT_LICENSE.txt",
            base / "licenses" / "TEAMTALK_SDK_LICENSE.txt",
        ]

        for lp in license_paths:
            parts.append("")
            if not lp.exists():
                continue
            parts.append(f"--- {lp.name} ---")
            try:
                parts.append(lp.read_text(encoding="utf-8", errors="replace"))
            except Exception:
                continue

        parts.append("")
        parts.append("Weitere Abhängigkeiten sind enthalten; falls Lizenztexte fehlen,")
        parts.append("bitte die jeweiligen Projekte konsultieren.")
        return "\n".join(parts)

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
        if result.ok:
            self._reconnect_attempts = 0
            self._auto_init_sound_devices()
            self.client.start_event_loop(self.handle_tt_message)
            self._refresh_channels_with_retry()
            if self.files_tab is not None:
                wx.CallLater(800, self.files_tab.refresh_file_list)
            if self._pending_join is not None:
                wx.CallLater(500, self._join_from_pending)
            if self.audio_tab.voice_activation.GetValue() and not self._ptt_enabled:
                self.client.enable_voice_transmission(True)
            if self.admin_tab is not None:
                self.admin_tab.check_admin_visibility()
            api_key = self.connection_tab.elevenlabs_key.GetValue().strip()
            self._update_speak_tab(api_key)

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

    def join_channel(self, channel_id: int):
        tab = self.connection_tab
        tab.join_root_btn.Disable()
        self.set_status("Trete Kanal bei...")

        def worker():
            try:
                self.client.stop_event_loop_and_wait()
                result = self.client.join_channel_by_id(channel_id, timeout_ms=8000)
                self.client.start_event_loop(self.handle_tt_message)
                wx.CallAfter(self.set_status, result.message)
                if result.ok:
                    self.sound_manager.play("channel_join", self.settings_store.settings.sound_events.get("channel_join"))
                    wx.CallAfter(self.channels_tab.refresh_channels_and_users)
                    wx.CallAfter(self.channels_tab.refresh_members_for_my_channel)
                    if self.files_tab is not None:
                        wx.CallAfter(self.files_tab.refresh_file_list)
            except Exception as exc:
                self.client.start_event_loop(self.handle_tt_message)
                wx.CallAfter(self.set_status, f"Fehler: {exc}")
            finally:
                wx.CallAfter(tab.join_root_btn.Enable)

        threading.Thread(target=worker, daemon=True).start()

    def schedule_reconnect(self):
        if not self._auto_reconnect:
            return
        self._reconnect_attempts += 1
        delay = min(30000, 1000 * (2 ** min(self._reconnect_attempts, 5)))
        self.set_status(f"Reconnection in {delay // 1000}s")
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
        channels = list(self.client.get_server_channels())
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
                    wx.CallAfter(self.channels_tab.refresh_channels_and_users)
                    wx.CallAfter(self.channels_tab.refresh_members_for_my_channel)
                    if self.files_tab is not None:
                        wx.CallAfter(self.files_tab.refresh_file_list)
                    return
                wx.CallAfter(self.set_status, result_join.message)
                if result_join.ok:
                    self.sound_manager.play("channel_join", self.settings_store.settings.sound_events.get("channel_join"))
                    wx.CallAfter(self.channels_tab.refresh_channels_and_users)
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
            return
        event.Skip()

    def on_key_up(self, event):
        if self._ptt_enabled and event.GetKeyCode() == self._ptt_hotkey:
            if self._ptt_active:
                self._ptt_active = False
                self.client.enable_voice_transmission(False)
                self.set_status("Sprechen aus")
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
        if self._window_focused and self.IsShown():
            return
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
        new_tab = factory(self.content_panel, self)
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
            wx.CallAfter(self.schedule_reconnect)
        elif event == tt.ClientEvent.CLIENTEVENT_CON_LOST:
            wx.CallAfter(self.set_status, "Verbindung verloren")
            wx.CallAfter(self.schedule_reconnect)
            self.sound_manager.play("server_disconnect", self.settings_store.settings.sound_events.get("server_disconnect"))
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
        elif event == tt.ClientEvent.CLIENTEVENT_CMD_USER_LOGGEDOUT:
            text = f"* {name} hat sich abgemeldet"
        elif event == tt.ClientEvent.CLIENTEVENT_CMD_USER_JOINED:
            text = f"* {name} hat Kanal {channel_name or channel_id} betreten"
        elif event == tt.ClientEvent.CLIENTEVENT_CMD_USER_LEFT:
            text = f"* {name} hat Kanal {channel_name or channel_id} verlassen"
        else:
            return

        self.chat_tab.append_chat(text, kind="system")
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
            wx.CallAfter(self.chat_tab.append_chat, f"{from_user}: {content}", kind, speak)
            self._message_buffers.pop(key, None)
            # Sound-Ereignisse
            se = self.settings_store.settings.sound_events
            is_own = bool(from_id and my_id and from_id == my_id)
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
        # Stop timers
        self.connection_tab.destroy_timers()
        self.audio_tab.destroy_timers()
        # Stop media / recording
        if self.media_tab is not None:
            self.media_tab.stop_all()
        # Stop ElevenLabs streaming / cleanup
        if self.speak_tab is not None:
            self.speak_tab.cleanup()
        # Stop TTS
        self.tts.close()
        # Close SDK
        self.client.close()
        self.tray.Destroy()
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
