from __future__ import annotations

import os
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def _init_startup_logging() -> None:
    from platform_paths import log_dir as _log_dir
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

import wx
import wx.adv

from teamtalk_client.client import TeamTalkClient, ConnectResult
from ui.models import (
    FileLogger,
    ParsedTeamTalkFile,
    ServerProfile,
    ServerStore,
)
from ui.tray import TrayIcon
from ui.tt_file_parser import parse_teamtalk_file
from ui.tabs.connection import ConnectionTab
from ui.tabs.channels import ChannelsTab
from ui.tabs.chat import ChatTab
from ui.tabs.media import MediaTab
from ui.tabs.files import FilesTab
from ui.tabs.admin import AdminTab
from ui.tabs.speak import SpeakTab
from ui.tabs.settings import SettingsTab
from tts import TTSManager


class MainFrame(wx.Frame):
    """Main window -- thin orchestrator that creates notebook tabs and dispatches events."""

    def __init__(self) -> None:
        super().__init__(None, title="TeamTalk VoiceOver Client")
        self.client = TeamTalkClient()

        # Shared state
        self._auto_reconnect = False
        self._reconnect_attempts = 0
        self._ptt_enabled = False
        self._ptt_active = False
        self._message_buffers: Dict[Tuple[int, int, int, int], List] = {}
        self._pending_join: Optional[ParsedTeamTalkFile] = None
        self._window_focused = True
        self.speak_tab: Optional[SpeakTab] = None
        self._speak_tab_added = False

        # Paths
        from platform_paths import app_data_dir
        app_dir = app_data_dir()
        app_dir.mkdir(parents=True, exist_ok=True)
        self.store = ServerStore(app_dir / "servers.json")
        self.logger = FileLogger(app_dir / "client.log")
        self.tts = TTSManager(self)

        # Tray
        self.tray = TrayIcon(self)

        # Menu
        self._build_menu()

        # --- Notebook ---
        panel = wx.Panel(self)
        panel.SetName("Hauptfenster")
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        title = wx.StaticText(panel, label="TeamTalk Client (VoiceOver-optimiert)")
        title.SetName("Titel")
        main_sizer.Add(title, 0, wx.ALL, 12)

        self.notebook = wx.Notebook(panel)
        self.notebook.SetName("Hauptnavigation")

        self.connection_tab = ConnectionTab(self.notebook, self)
        self.channels_tab = ChannelsTab(self.notebook, self)
        self.chat_tab = ChatTab(self.notebook, self)
        self.settings_tab = SettingsTab(self.notebook, self)
        self.audio_tab = self.settings_tab.audio_tab
        self.system_tab = self.settings_tab.system_tab
        self.media_tab = MediaTab(self.notebook, self)
        self.files_tab = FilesTab(self.notebook, self)
        self.admin_tab = AdminTab(self.notebook, self)

        self.notebook.AddPage(self.connection_tab, "Verbindung")
        self.notebook.AddPage(self.channels_tab, "Kanaele")
        self.notebook.AddPage(self.chat_tab, "Chat")
        self.notebook.AddPage(self.media_tab, "Aufnahme & Medien")
        self.notebook.AddPage(self.files_tab, "Dateien")
        self.notebook.AddPage(self.admin_tab, "Administration")
        self.notebook.AddPage(self.settings_tab, "Einstellungen")

        self.notebook.Bind(wx.EVT_NOTEBOOK_PAGE_CHANGED, self.on_tab_changed)
        main_sizer.Add(self.notebook, 1, wx.LEFT | wx.RIGHT | wx.EXPAND, 12)

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

        panel.SetSizer(main_sizer)
        self.SetSize((980, 980))
        self.Centre()

        # Tab order inside each tab is handled by the tab panels themselves.
        # Global keyboard hooks
        self.Bind(wx.EVT_CHAR_HOOK, self.on_key_hook)
        self.Bind(wx.EVT_KEY_DOWN, self.on_key_down)
        self.Bind(wx.EVT_KEY_UP, self.on_key_up)
        self.Bind(wx.EVT_CLOSE, self.on_close)
        self.Bind(wx.EVT_ACTIVATE, self._on_activate)

    # ------------------------------------------------------------------
    # Menu
    # ------------------------------------------------------------------

    def _build_menu(self):
        menubar = wx.MenuBar()
        file_menu = wx.Menu()
        open_tt = file_menu.Append(wx.ID_ANY, "TeamTalk-Datei oeffnen...\tCtrl+O")
        import_servers = file_menu.Append(wx.ID_ANY, "Serverliste importieren...")
        export_servers = file_menu.Append(wx.ID_ANY, "Serverliste exportieren...")
        file_menu.AppendSeparator()
        quit_item = file_menu.Append(wx.ID_EXIT, "Beenden\tCtrl+Q")

        menubar.Append(file_menu, "Datei")
        self.SetMenuBar(menubar)

        self.Bind(wx.EVT_MENU, self.on_open_tt_file, open_tt)
        self.Bind(wx.EVT_MENU, self.on_import_servers, import_servers)
        self.Bind(wx.EVT_MENU, self.on_export_servers, export_servers)
        self.Bind(wx.EVT_MENU, self.on_menu_quit, quit_item)

    # ------------------------------------------------------------------
    # Shared helpers (called from tabs)
    # ------------------------------------------------------------------

    def set_status(self, text: str) -> None:
        self.status.SetLabel(text)
        self.log.AppendText(text + "\n")
        self.logger.write(text)

    def tt_str(self, value) -> str:
        out = self.client.tt.ttstr(value)
        if isinstance(out, bytes):
            return out.decode("utf-8", errors="replace")
        return str(out)

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
            wx.CallLater(800, self.files_tab.refresh_file_list)
            if self._pending_join is not None:
                wx.CallLater(500, self._join_from_pending)
            if self.audio_tab.voice_activation.GetValue() and not self._ptt_enabled:
                self.client.enable_voice_transmission(True)
            self.admin_tab.check_admin_visibility()
            api_key = self.connection_tab.elevenlabs_key.GetValue().strip()
            self._update_speak_tab(api_key)

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
                    wx.CallAfter(self.channels_tab.refresh_channels_and_users)
                    wx.CallAfter(self.channels_tab.refresh_members_for_my_channel)
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
                self.speak_tab = SpeakTab(self.notebook, self)
            if not self._speak_tab_added:
                # Insert after "Chat" tab (index 3)
                self.notebook.InsertPage(3, self.speak_tab, "Sprechen")
                self._speak_tab_added = True
            self.speak_tab.set_api_key(api_key)
        else:
            if self._speak_tab_added:
                # Find and remove the Sprechen page
                for i in range(self.notebook.GetPageCount()):
                    if self.notebook.GetPageText(i) == "Sprechen":
                        self.notebook.RemovePage(i)
                        break
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
        with wx.FileDialog(self, "TeamTalk-Datei oeffnen", wildcard=wildcard) as dlg:
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
            self.logger.write(
                f"Connect from .tt: host={parsed.profile.host} tcp={parsed.profile.tcp_port} "
                f"udp={parsed.profile.udp_port} user={parsed.profile.username} encrypted={encrypted}"
            )
            result = self.client.connect_and_login(
                host=parsed.profile.host,
                tcp_port=parsed.profile.tcp_port,
                udp_port=parsed.profile.udp_port,
                nickname=parsed.profile.nickname,
                username=parsed.profile.username,
                password=parsed.profile.password,
                client_name=parsed.profile.client_name,
                encrypted=encrypted,
                timeout_ms=8000,
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
                    wx.CallAfter(self.set_status, "Kanalbeitritt erfolgreich")
                    wx.CallAfter(self.channels_tab.refresh_channels_and_users)
                    wx.CallAfter(self.channels_tab.refresh_members_for_my_channel)
                    wx.CallAfter(self.files_tab.refresh_file_list)
                    return
                wx.CallAfter(self.set_status, result_join.message)
                if result_join.ok:
                    wx.CallAfter(self.channels_tab.refresh_channels_and_users)
                    wx.CallAfter(self.channels_tab.refresh_members_for_my_channel)
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
        if key == wx.WXK_F5:
            self.channels_tab.refresh_channels_and_users()
            return
        if key == wx.WXK_F9:
            at = self.audio_tab
            at.ptt_toggle.SetValue(not at.ptt_toggle.GetValue())
            at.on_ptt_toggle(None)
            return
        event.Skip()

    def on_key_down(self, event):
        if self._ptt_enabled and event.GetKeyCode() == wx.WXK_SPACE:
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
        if self._ptt_enabled and event.GetKeyCode() == wx.WXK_SPACE:
            if self._ptt_active:
                self._ptt_active = False
                self.client.enable_voice_transmission(False)
                self.set_status("Sprechen aus")
            return
        event.Skip()

    def _is_text_input_focused(self) -> bool:
        focused = wx.Window.FindFocus()
        return isinstance(focused, wx.TextCtrl)

    # ------------------------------------------------------------------
    # Push notifications
    # ------------------------------------------------------------------

    def _on_activate(self, event):
        self._window_focused = event.GetActive()
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
        try:
            idx = event.GetSelection()
            if self.notebook.GetPage(idx) is self.files_tab:
                wx.CallAfter(self.files_tab.refresh_file_list)
        finally:
            event.Skip()

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
        elif event == tt.ClientEvent.CLIENTEVENT_CON_CRYPT_ERROR:
            wx.CallAfter(self.set_status, "Verschluesselungsfehler")
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
            wx.CallAfter(self.channels_tab.refresh_members_for_my_channel)
            wx.CallAfter(self._emit_user_presence_event, msg, tt)
        elif event == tt.ClientEvent.CLIENTEVENT_CMD_MYSELF_LOGGEDIN:
            wx.CallAfter(self.channels_tab.refresh_members_for_my_channel)
        elif event == tt.ClientEvent.CLIENTEVENT_CMD_USER_TEXTMSG:
            self._handle_text_message(msg, tt)
        elif event == tt.ClientEvent.CLIENTEVENT_STREAM_MEDIAFILE:
            wx.CallAfter(self.media_tab.on_stream_update, msg.mediafileinfo)
        elif event == tt.ClientEvent.CLIENTEVENT_CMD_FILE_NEW:
            wx.CallAfter(self.files_tab.refresh_file_list)
        elif event == tt.ClientEvent.CLIENTEVENT_CMD_FILE_REMOVE:
            wx.CallAfter(self.files_tab.refresh_file_list)
        elif event == tt.ClientEvent.CLIENTEVENT_FILETRANSFER:
            wx.CallAfter(self.files_tab.on_file_transfer_update, int(msg.nSource))
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
            wx.CallAfter(self.admin_tab.add_account_to_list, msg.useraccount)
        elif event == tt.ClientEvent.CLIENTEVENT_CMD_BANNEDUSER:
            wx.CallAfter(self.admin_tab.add_ban_to_list, msg.banneduser)

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
            # Push notification
            if msg_type == int(tt.TextMsgType.MSGTYPE_USER):
                wx.CallAfter(self._send_notification, "Privatnachricht", f"{from_user}: {content}")
            elif msg_type == int(tt.TextMsgType.MSGTYPE_CHANNEL):
                wx.CallAfter(self._send_notification, "Kanalnachricht", f"{from_user}: {content}")
            elif msg_type == int(tt.TextMsgType.MSGTYPE_BROADCAST):
                wx.CallAfter(self._send_notification, "Broadcast", f"{from_user}: {content}")

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
        self.tray.SetIcon(self.tray._icon, "TeamTalk VoiceOver Client (im Tray)")
        self.set_status("Im Tray ausgeblendet")
        event.Veto()

    def force_close(self):
        # Stop timers
        self.connection_tab.destroy_timers()
        self.audio_tab.destroy_timers()
        # Stop media / recording
        self.media_tab.stop_all()
        # Stop ElevenLabs streaming / cleanup
        if self.speak_tab is not None:
            self.speak_tab.cleanup()
        # Stop TTS
        self.tts.close()
        # Close SDK
        self.client.close()
        self.tray.Destroy()
        self.Destroy()


class App(wx.App):
    def OnInit(self) -> bool:
        frame = MainFrame()
        frame.Show()
        return True


if __name__ == "__main__":
    try:
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
