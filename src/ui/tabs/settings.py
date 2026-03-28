from __future__ import annotations

import subprocess
import sys
from typing import TYPE_CHECKING, List

import wx
import zipfile
from datetime import datetime

from .audio import AudioTab
from .video import VideoTab
from .shortcuts import ShortcutsTab
from .system import SystemTab
from platform_paths import app_data_dir, log_dir

if TYPE_CHECKING:
    from app import MainFrame


_SOUND_EVENTS = [
    ("Server-Verbindung erfolgreich", "server_connect"),
    ("Server-Verbindung getrennt", "server_disconnect"),
    ("Eigenen Kanal betreten", "channel_join"),
    ("Benutzer betritt Kanal", "user_join"),
    ("Benutzer verlässt Kanal", "user_leave"),
    ("Privatnachricht empfangen", "msg_private_rx"),
    ("Privatnachricht gesendet", "msg_private_tx"),
    ("Kanalnachricht empfangen", "msg_channel_rx"),
    ("Kanalnachricht gesendet", "msg_channel_tx"),
    ("PTT aktiviert", "ptt_on"),
    ("Kanal-Stille (letzter Sprecher)", "channel_silent"),
    ("Dateitransfer abgeschlossen", "file_transfer"),
    ("Video-Session gestartet", "video_session"),
    ("Desktop-Session gestartet", "desktop_session"),
    ("Frage-Status geändert", "question_mode"),
    ("Desktop-Zugriff angefragt", "desktop_access"),
    ("Benutzer angemeldet", "user_login"),
    ("Benutzer abgemeldet", "user_logout"),
]

_SUBSCRIPTION_FLAGS = [
    ("&Benutzernachrichten", "SUBSCRIBE_USER_MSG"),
    ("&Kanalnachrichten", "SUBSCRIBE_CHANNEL_MSG"),
    ("&Rundnachricht", "SUBSCRIBE_BROADCAST_MSG"),
    ("&Sprache", "SUBSCRIBE_VOICE"),
    ("&Video", "SUBSCRIBE_VIDEOCAPTURE"),
    ("&Desktop", "SUBSCRIBE_DESKTOP"),
    ("&Mediendatei", "SUBSCRIBE_MEDIAFILE"),
]


class SettingsTab(wx.Panel):
    """Settings container for Audio and System/TTS sections."""

    def __init__(self, parent: wx.Window, frame: MainFrame) -> None:
        super().__init__(parent)
        self.frame = frame
        self.SetName("Einstellungen")

        root = wx.BoxSizer(wx.VERTICAL)

        top_row = wx.BoxSizer(wx.HORIZONTAL)
        top_row.Add(wx.StaticText(self, label="Bereich"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.section_choice = wx.Choice(self, choices=[
            "Allgemein", "Anzeige", "Verbindung", "Sound-Ereignisse",
            "Audio", "Video", "Tastenkürzel", "System & TTS", "ElevenLabs",
            "KI & Barrierefreiheit",
        ])
        self.section_choice.SetName("Einstellungsbereich")
        self.section_choice.SetSelection(0)
        self.section_choice.Bind(wx.EVT_CHOICE, self._on_section_changed)
        top_row.Add(self.section_choice, 1, wx.EXPAND)
        root.Add(top_row, 0, wx.ALL | wx.EXPAND, 8)

        # --- Log sharing ---
        log_row = wx.BoxSizer(wx.HORIZONTAL)
        self.share_logs_btn = wx.Button(self, label="&Logs senden")
        self.share_logs_btn.SetName("Logs senden")
        self.share_logs_btn.Bind(wx.EVT_BUTTON, self._on_share_logs_menu)
        log_row.Add(self.share_logs_btn, 0, wx.RIGHT, 8)
        log_row.Add(wx.StaticText(self, label="Sende deine Logs an den Entwickler"), 0, wx.ALIGN_CENTER_VERTICAL)
        root.Add(log_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # --- Existing section panels ---
        self.audio_tab = AudioTab(self, frame)
        self.video_tab = VideoTab(self, frame)
        self.shortcuts_tab = ShortcutsTab(self, frame)
        self.system_tab = SystemTab(self, frame)

        # --- New section panels ---
        self.general_tab = self._build_general_tab()
        self.display_tab = self._build_display_tab()
        self.connection_tab_settings = self._build_connection_tab()
        self.sound_events_tab = self._build_sound_events_tab()
        self.elevenlabs_tab = self._build_elevenlabs_tab()
        self.ai_tab = self._build_ai_tab()

        self._sections = {
            "Allgemein": self.general_tab,
            "Anzeige": self.display_tab,
            "Verbindung": self.connection_tab_settings,
            "Sound-Ereignisse": self.sound_events_tab,
            "Audio": self.audio_tab,
            "Video": self.video_tab,
            "Tastenkürzel": self.shortcuts_tab,
            "System & TTS": self.system_tab,
            "ElevenLabs": self.elevenlabs_tab,
            "KI & Barrierefreiheit": self.ai_tab,
        }

        for panel in self._sections.values():
            root.Add(panel, 1, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)

        self.SetSizer(root)
        self._show_section("Allgemein")

    # ------------------------------------------------------------------
    # Build helpers for new panels
    # ------------------------------------------------------------------

    def _build_general_tab(self) -> wx.Panel:
        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)
        s = self.frame.settings_store.settings

        # Gender
        gender_choices = ["Männlich", "Weiblich", "Keine Angabe"]
        self._gender_radio = wx.RadioBox(panel, label="Geschlecht", choices=gender_choices, majorDimension=1, style=wx.RA_SPECIFY_ROWS)
        self._gender_radio.SetName("Geschlecht")
        current_gender = s.gender or "Keine Angabe"
        if current_gender in gender_choices:
            self._gender_radio.SetSelection(gender_choices.index(current_gender))
        else:
            self._gender_radio.SetSelection(2)
        sizer.Add(self._gender_radio, 0, wx.ALL | wx.EXPAND, 8)

        # Away timer
        away_row = wx.BoxSizer(wx.HORIZONTAL)
        away_lbl = wx.StaticText(panel, label="Abwesenheits-Timer (Min., 0=aus)")
        self._away_timer = wx.SpinCtrl(panel, min=0, max=120, initial=int(s.away_timer_min or 0))
        self._away_timer.SetName("Abwesenheits-Timer")
        away_row.Add(away_lbl, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        away_row.Add(self._away_timer, 0)
        sizer.Add(away_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # BearWare
        bearware_box = wx.StaticBox(panel, label="BearWare Web-Login")
        bearware_sizer = wx.StaticBoxSizer(bearware_box, wx.VERTICAL)
        self._bearware_enable = wx.CheckBox(panel, label="&BearWare Web-Login verwenden")
        self._bearware_enable.SetName("BearWare Web-Login verwenden")
        self._bearware_enable.SetValue(bool(s.bearware_login))
        bearware_sizer.Add(self._bearware_enable, 0, wx.ALL, 4)

        bw_form = wx.FlexGridSizer(cols=2, vgap=4, hgap=8)
        bw_form.AddGrowableCol(1)
        bw_form.Add(wx.StaticText(panel, label="Benutzername"), 0, wx.ALIGN_CENTER_VERTICAL)
        self._bearware_user = wx.TextCtrl(panel, value=str(s.bearware_username or ""))
        self._bearware_user.SetName("BearWare Benutzername")
        bw_form.Add(self._bearware_user, 1, wx.EXPAND)
        bw_form.Add(wx.StaticText(panel, label="Passwort"), 0, wx.ALIGN_CENTER_VERTICAL)
        self._bearware_pass = wx.TextCtrl(panel, value=str(s.bearware_password or ""), style=wx.TE_PASSWORD)
        self._bearware_pass.SetName("BearWare Passwort")
        bw_form.Add(self._bearware_pass, 1, wx.EXPAND)
        bearware_sizer.Add(bw_form, 0, wx.ALL | wx.EXPAND, 4)
        sizer.Add(bearware_sizer, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)

        # v1.3.0 feature checkboxes
        self._save_chat_history = wx.CheckBox(panel, label="&Chat-Verlauf speichern (pro Server)")
        self._save_chat_history.SetName("Chat-Verlauf speichern")
        self._save_chat_history.SetValue(bool(s.save_chat_history))
        sizer.Add(self._save_chat_history, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        self._auto_join_last_channel = wx.CheckBox(panel, label="&Letzten Kanal automatisch beitreten")
        self._auto_join_last_channel.SetName("Letzten Kanal automatisch beitreten")
        self._auto_join_last_channel.SetValue(bool(s.auto_join_last_channel))
        sizer.Add(self._auto_join_last_channel, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        self._save_private_history = wx.CheckBox(panel, label="&Privatnachrichten-Verlauf speichern")
        self._save_private_history.SetName("Privatnachrichten-Verlauf speichern")
        self._save_private_history.SetValue(bool(s.save_private_chat_history))
        sizer.Add(self._save_private_history, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        self._update_check = wx.CheckBox(panel, label="Beim &Start auf Updates prüfen")
        self._update_check.SetName("Auf Updates prüfen")
        self._update_check.SetValue(bool(s.update_check_on_start))
        sizer.Add(self._update_check, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        self._braille_compact = wx.CheckBox(panel, label="&Braillezeilen-Kompaktmodus (kürzere Labels)")
        self._braille_compact.SetName("Braillezeilen-Kompaktmodus")
        self._braille_compact.SetValue(bool(s.braille_compact_mode))
        sizer.Add(self._braille_compact, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        self._save_channel_passwords = wx.CheckBox(panel, label="Kanalpasswörter in &Keychain speichern")
        self._save_channel_passwords.SetName("Kanalpasswörter in Keychain speichern")
        self._save_channel_passwords.SetValue(bool(s.save_channel_passwords))
        sizer.Add(self._save_channel_passwords, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # Chat filter
        filter_box = wx.StaticBox(panel, label="Chat-Filter")
        filter_sizer = wx.StaticBoxSizer(filter_box, wx.VERTICAL)
        filter_form = wx.FlexGridSizer(cols=2, vgap=4, hgap=8)
        filter_form.AddGrowableCol(1)
        filter_form.Add(wx.StaticText(panel, label="Stichwörter hervorheben"), 0, wx.ALIGN_CENTER_VERTICAL)
        self._highlight_keywords = wx.TextCtrl(panel, value=str(s.chat_highlight_keywords or ""))
        self._highlight_keywords.SetName("Stichwörter hervorheben")
        self._highlight_keywords.SetHelpText("Komma-getrennte Stichwörter, z. B.: wichtig,dringend")
        filter_form.Add(self._highlight_keywords, 1, wx.EXPAND)
        filter_form.Add(wx.StaticText(panel, label="Nutzer stumm"), 0, wx.ALIGN_CENTER_VERTICAL)
        self._muted_users = wx.TextCtrl(panel, value=str(s.chat_muted_users or ""))
        self._muted_users.SetName("Nutzer stumm")
        self._muted_users.SetHelpText("Komma-getrennte Nutzernamen, deren Nachrichten ausgeblendet werden")
        filter_form.Add(self._muted_users, 1, wx.EXPAND)
        filter_sizer.Add(filter_form, 0, wx.ALL | wx.EXPAND, 6)
        sizer.Add(filter_sizer, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)

        # Save button
        save_btn = wx.Button(panel, label="&Speichern")
        save_btn.SetName("Allgemein speichern")
        save_btn.Bind(wx.EVT_BUTTON, self._on_save_general)
        sizer.Add(save_btn, 0, wx.LEFT | wx.BOTTOM, 8)

        panel.SetSizer(sizer)
        panel.Show(False)
        return panel

    def _build_display_tab(self) -> wx.Panel:
        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)
        s = self.frame.settings_store.settings

        self._minimize_to_tray = wx.CheckBox(panel, label="&Im Tray minimieren (statt schließen)")
        self._minimize_to_tray.SetName("Im Tray minimieren")
        self._minimize_to_tray.SetValue(bool(s.minimize_to_tray))
        sizer.Add(self._minimize_to_tray, 0, wx.ALL, 8)

        self._always_on_top = wx.CheckBox(panel, label="Immer im &Vordergrund")
        self._always_on_top.SetName("Immer im Vordergrund")
        self._always_on_top.SetValue(bool(s.always_on_top))
        self._always_on_top.Bind(wx.EVT_CHECKBOX, self._on_always_on_top_changed)
        sizer.Add(self._always_on_top, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        chat_choices = ["Liste", "Textfeld"]
        self._chat_format = wx.RadioBox(panel, label="Chat-Verlauf Format", choices=chat_choices, majorDimension=1, style=wx.RA_SPECIFY_ROWS)
        self._chat_format.SetName("Chat-Verlauf Format")
        fmt = s.chat_history_format or "Liste"
        if fmt in chat_choices:
            self._chat_format.SetSelection(chat_choices.index(fmt))
        sizer.Add(self._chat_format, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)

        self._show_vu_meter = wx.CheckBox(panel, label="VU-&Meter anzeigen")
        self._show_vu_meter.SetName("VU-Meter anzeigen")
        self._show_vu_meter.SetValue(bool(s.show_vu_meter))
        self._show_vu_meter.Bind(wx.EVT_CHECKBOX, self._on_vu_meter_changed)
        sizer.Add(self._show_vu_meter, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        self._show_server_title = wx.CheckBox(panel, label="&Fenstertitel zeigt Server/Kanal")
        self._show_server_title.SetName("Fenstertitel zeigt Server/Kanal")
        self._show_server_title.SetValue(bool(s.show_server_in_title))
        sizer.Add(self._show_server_title, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        note = wx.StaticText(panel, label="Hinweis: Toolbar und Protokoll sind standardmäßig versteckt\n(empfohlen für Screenreader/VoiceOver/NVDA).")
        note.SetName("Barrierefreiheitshinweis")
        sizer.Add(note, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        self._show_toolbar = wx.CheckBox(panel, label="&Toolbar / Schnellaktionen anzeigen")
        self._show_toolbar.SetName("Toolbar anzeigen")
        self._show_toolbar.SetValue(bool(s.show_toolbar))
        self._show_toolbar.Bind(wx.EVT_CHECKBOX, self._on_toolbar_changed)
        sizer.Add(self._show_toolbar, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        self._show_event_log = wx.CheckBox(panel, label="&Ereignisprotokoll anzeigen")
        self._show_event_log.SetName("Ereignisprotokoll anzeigen")
        self._show_event_log.SetValue(bool(s.show_event_log))
        self._show_event_log.Bind(wx.EVT_CHECKBOX, self._on_event_log_changed)
        sizer.Add(self._show_event_log, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        save_btn = wx.Button(panel, label="&Speichern")
        save_btn.SetName("Anzeige speichern")
        save_btn.Bind(wx.EVT_BUTTON, self._on_save_display)
        sizer.Add(save_btn, 0, wx.LEFT | wx.BOTTOM, 8)

        panel.SetSizer(sizer)
        panel.Show(False)
        return panel

    def _build_connection_tab(self) -> wx.Panel:
        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)
        s = self.frame.settings_store.settings

        # Default subscriptions
        subs_box = wx.StaticBox(panel, label="Standard-Abonnements")
        subs_sizer = wx.StaticBoxSizer(subs_box, wx.VERTICAL)
        self._sub_checkboxes: list = []
        current_subs = int(s.default_subscriptions or 0)
        # We need the tt subscription constants - get them at save time
        for label, _flag_name in _SUBSCRIPTION_FLAGS:
            cb = wx.CheckBox(panel, label=label)
            cb.SetName(label)
            cb.SetValue(False)  # will be updated when tt client is available
            subs_sizer.Add(cb, 0, wx.ALL, 4)
            self._sub_checkboxes.append((cb, _flag_name))
        # Store raw int for initial display
        self._default_subs_raw = current_subs
        sizer.Add(subs_sizer, 0, wx.ALL | wx.EXPAND, 8)

        # Reconnect config
        reconnect_box = wx.StaticBox(panel, label="Automatische Wiederverbindung")
        reconnect_sizer = wx.StaticBoxSizer(reconnect_box, wx.VERTICAL)
        reconnect_form = wx.FlexGridSizer(cols=2, vgap=4, hgap=8)
        reconnect_form.AddGrowableCol(1)
        reconnect_form.Add(wx.StaticText(panel, label="Max. Versuche (0=unbegrenzt)"), 0, wx.ALIGN_CENTER_VERTICAL)
        self._reconnect_max = wx.SpinCtrl(panel, min=0, max=999, initial=int(s.reconnect_max_attempts or 0))
        self._reconnect_max.SetName("Max. Reconnect-Versuche")
        reconnect_form.Add(self._reconnect_max, 0)
        reconnect_form.Add(wx.StaticText(panel, label="Mindestverzögerung (Sek.)"), 0, wx.ALIGN_CENTER_VERTICAL)
        self._reconnect_delay = wx.SpinCtrl(panel, min=1, max=300, initial=int(s.reconnect_delay_sec or 2))
        self._reconnect_delay.SetName("Reconnect-Verzögerung")
        reconnect_form.Add(self._reconnect_delay, 0)
        reconnect_sizer.Add(reconnect_form, 0, wx.ALL | wx.EXPAND, 6)
        sizer.Add(reconnect_sizer, 0, wx.ALL | wx.EXPAND, 8)

        # Port binding
        ports_box = wx.StaticBox(panel, label="Port-Bindung")
        ports_sizer = wx.StaticBoxSizer(ports_box, wx.VERTICAL)
        port_form = wx.FlexGridSizer(cols=2, vgap=4, hgap=8)
        port_form.AddGrowableCol(1)
        port_form.Add(wx.StaticText(panel, label="TCP-Port (0=auto)"), 0, wx.ALIGN_CENTER_VERTICAL)
        self._tcp_bind_port = wx.SpinCtrl(panel, min=0, max=65535, initial=int(s.tcp_bind_port or 0))
        self._tcp_bind_port.SetName("TCP-Port Bindung")
        port_form.Add(self._tcp_bind_port, 0)
        port_form.Add(wx.StaticText(panel, label="UDP-Port (0=auto)"), 0, wx.ALIGN_CENTER_VERTICAL)
        self._udp_bind_port = wx.SpinCtrl(panel, min=0, max=65535, initial=int(s.udp_bind_port or 0))
        self._udp_bind_port.SetName("UDP-Port Bindung")
        port_form.Add(self._udp_bind_port, 0)
        ports_sizer.Add(port_form, 0, wx.ALL | wx.EXPAND, 8)
        sizer.Add(ports_sizer, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)

        save_btn = wx.Button(panel, label="S&peichern")
        save_btn.SetName("Verbindung speichern")
        save_btn.Bind(wx.EVT_BUTTON, self._on_save_connection)
        sizer.Add(save_btn, 0, wx.LEFT | wx.BOTTOM, 8)

        panel.SetSizer(sizer)
        panel.Show(False)
        return panel

    def _build_sound_events_tab(self) -> wx.Panel:
        panel = wx.Panel(self)
        outer = wx.BoxSizer(wx.VERTICAL)
        s = self.frame.settings_store.settings

        # Scrollable area for events
        scroll = wx.ScrolledWindow(panel, style=wx.VSCROLL)
        scroll.SetScrollRate(0, 20)
        scroll_sizer = wx.BoxSizer(wx.VERTICAL)

        self._sound_event_paths: dict = {}  # key -> TextCtrl

        grid = wx.FlexGridSizer(cols=4, vgap=4, hgap=8)
        grid.AddGrowableCol(1)

        for label, key in _SOUND_EVENTS:
            lbl = wx.StaticText(scroll, label=label)
            path_ctrl = wx.TextCtrl(scroll, value=str(s.sound_events.get(key, "") or ""))
            path_ctrl.SetName(f"Sound: {label}")
            browse_btn = wx.Button(scroll, label="...")
            browse_btn.SetName(f"Durchsuchen: {label}")
            test_btn = wx.Button(scroll, label="Testen")
            test_btn.SetName(f"Test: {label}")

            browse_btn.Bind(wx.EVT_BUTTON, lambda e, k=key, tc=path_ctrl: self._on_browse_sound(k, tc))
            test_btn.Bind(wx.EVT_BUTTON, lambda e, k=key, tc=path_ctrl: self._on_test_sound(k, tc))

            grid.Add(lbl, 0, wx.ALIGN_CENTER_VERTICAL)
            grid.Add(path_ctrl, 1, wx.EXPAND)
            grid.Add(browse_btn, 0)
            grid.Add(test_btn, 0)

            self._sound_event_paths[key] = path_ctrl

        scroll_sizer.Add(grid, 0, wx.ALL | wx.EXPAND, 8)
        scroll.SetSizer(scroll_sizer)
        outer.Add(scroll, 1, wx.EXPAND)

        # Volume and play mode
        bottom_sizer = wx.BoxSizer(wx.VERTICAL)

        vol_row = wx.BoxSizer(wx.HORIZONTAL)
        vol_row.Add(wx.StaticText(panel, label="Lautstärke"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self._sound_volume = wx.SpinCtrl(panel, value="100", min=0, max=100)
        self._sound_volume.SetName("Sound-Lautstärke")
        vol_row.Add(self._sound_volume, 0)
        bottom_sizer.Add(vol_row, 0, wx.ALL | wx.EXPAND, 8)

        mode_row = wx.BoxSizer(wx.HORIZONTAL)
        mode_row.Add(wx.StaticText(panel, label="Abspielmodus"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self._sound_play_mode = wx.Choice(panel, choices=["Standard", "Nacheinander", "Gleichzeitig"])
        self._sound_play_mode.SetName("Abspielmodus")
        self._sound_play_mode.SetSelection(0)
        mode_row.Add(self._sound_play_mode, 0)
        bottom_sizer.Add(mode_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        save_btn = wx.Button(panel, label="&Speichern")
        save_btn.SetName("Sound-Ereignisse speichern")
        save_btn.Bind(wx.EVT_BUTTON, self._on_save_sound_events)
        bottom_sizer.Add(save_btn, 0, wx.LEFT | wx.BOTTOM, 8)

        # Sound-Profile
        profile_box = wx.StaticBox(panel, label="Sound-Profile")
        profile_sizer = wx.StaticBoxSizer(profile_box, wx.VERTICAL)
        profile_row = wx.BoxSizer(wx.HORIZONTAL)
        profile_row.Add(wx.StaticText(panel, label="Aktives Profil:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self._sound_profile_choice = wx.Choice(panel, choices=["Standard", "Minimal", "Stumm"])
        self._sound_profile_choice.SetName("Aktives Sound-Profil")
        active = s.active_sound_profile or "Standard"
        choices = self._sound_profile_choice.GetStrings()
        if active in choices:
            self._sound_profile_choice.SetSelection(choices.index(active))
        else:
            self._sound_profile_choice.SetSelection(0)
        self._sound_profile_choice.Bind(wx.EVT_CHOICE, self._on_sound_profile_changed)
        profile_row.Add(self._sound_profile_choice, 1)
        profile_sizer.Add(profile_row, 0, wx.ALL | wx.EXPAND, 8)
        profile_btn_row = wx.BoxSizer(wx.HORIZONTAL)
        save_profile_btn = wx.Button(panel, label="Als Profil &speichern...")
        save_profile_btn.SetName("Als Sound-Profil speichern")
        save_profile_btn.Bind(wx.EVT_BUTTON, self._on_save_sound_profile)
        delete_profile_btn = wx.Button(panel, label="Profil &löschen")
        delete_profile_btn.SetName("Sound-Profil löschen")
        delete_profile_btn.Bind(wx.EVT_BUTTON, self._on_delete_sound_profile)
        profile_btn_row.Add(save_profile_btn, 0, wx.RIGHT, 8)
        profile_btn_row.Add(delete_profile_btn, 0)
        profile_sizer.Add(profile_btn_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        bottom_sizer.Add(profile_sizer, 0, wx.ALL | wx.EXPAND, 8)

        outer.Add(bottom_sizer, 0, wx.EXPAND)
        panel.SetSizer(outer)
        panel.Show(False)
        return panel

    # ------------------------------------------------------------------
    # Save handlers for new sections
    # ------------------------------------------------------------------

    def _on_save_general(self, _event):
        s = self.frame.settings_store.settings
        gender_choices = ["Männlich", "Weiblich", "Keine Angabe"]
        sel = self._gender_radio.GetSelection()
        s.gender = gender_choices[sel] if 0 <= sel < len(gender_choices) else ""
        s.away_timer_min = int(self._away_timer.GetValue())
        s.bearware_username = self._bearware_user.GetValue().strip()
        s.bearware_password = self._bearware_pass.GetValue()
        s.bearware_login = self._bearware_enable.GetValue()
        s.save_chat_history = self._save_chat_history.GetValue()
        s.auto_join_last_channel = self._auto_join_last_channel.GetValue()
        s.save_private_chat_history = self._save_private_history.GetValue()
        s.update_check_on_start = self._update_check.GetValue()
        s.braille_compact_mode = self._braille_compact.GetValue()
        s.save_channel_passwords = self._save_channel_passwords.GetValue()
        s.chat_highlight_keywords = self._highlight_keywords.GetValue().strip()
        s.chat_muted_users = self._muted_users.GetValue().strip()
        self.frame.settings_store.save()
        self.frame.apply_general_settings()
        self.frame.set_status("Allgemeine Einstellungen gespeichert")

    def _on_save_display(self, _event):
        s = self.frame.settings_store.settings
        s.minimize_to_tray = self._minimize_to_tray.GetValue()
        s.always_on_top = self._always_on_top.GetValue()
        chat_choices = ["Liste", "Textfeld"]
        sel = self._chat_format.GetSelection()
        s.chat_history_format = chat_choices[sel] if 0 <= sel < len(chat_choices) else "Liste"
        s.show_server_in_title = self._show_server_title.GetValue()
        s.show_toolbar = self._show_toolbar.GetValue()
        s.show_event_log = self._show_event_log.GetValue()
        s.show_vu_meter = self._show_vu_meter.GetValue()
        self.frame.settings_store.save()
        self.frame.apply_display_settings()
        self._on_vu_meter_changed(None)
        self.frame.set_status("Anzeigeeinstellungen gespeichert")

    def _on_toolbar_changed(self, _event):
        self.frame.qa_panel.Show(self._show_toolbar.GetValue())
        self.frame.Layout()

    def _on_event_log_changed(self, _event):
        self.frame.log.Show(self._show_event_log.GetValue())
        self.frame.Layout()

    def _on_always_on_top_changed(self, _event):
        checked = self._always_on_top.GetValue()
        style = self.frame.GetWindowStyle()
        if checked:
            self.frame.SetWindowStyle(style | wx.STAY_ON_TOP)
        else:
            self.frame.SetWindowStyle(style & ~wx.STAY_ON_TOP)

    def _on_vu_meter_changed(self, _event):
        checked = self._show_vu_meter.GetValue()
        try:
            self.frame.vu_meter.Show(checked)
            self.frame.vu_meter.GetParent().Layout()
        except Exception:
            pass

    def _on_save_connection(self, _event):
        s = self.frame.settings_store.settings
        s.reconnect_max_attempts = int(self._reconnect_max.GetValue())
        s.reconnect_delay_sec = int(self._reconnect_delay.GetValue())
        # Compute subscriptions bitmask using tt constants if available
        total = 0
        try:
            tt = self.frame.client.tt
            flag_map = {
                "SUBSCRIBE_USER_MSG": int(tt.Subscription.SUBSCRIBE_USER_MSG),
                "SUBSCRIBE_CHANNEL_MSG": int(tt.Subscription.SUBSCRIBE_CHANNEL_MSG),
                "SUBSCRIBE_BROADCAST_MSG": int(tt.Subscription.SUBSCRIBE_BROADCAST_MSG),
                "SUBSCRIBE_VOICE": int(tt.Subscription.SUBSCRIBE_VOICE),
                "SUBSCRIBE_VIDEOCAPTURE": int(tt.Subscription.SUBSCRIBE_VIDEOCAPTURE),
                "SUBSCRIBE_DESKTOP": int(tt.Subscription.SUBSCRIBE_DESKTOP),
                "SUBSCRIBE_MEDIAFILE": int(tt.Subscription.SUBSCRIBE_MEDIAFILE),
            }
            for cb, flag_name in self._sub_checkboxes:
                if cb.GetValue() and flag_name in flag_map:
                    total |= flag_map[flag_name]
        except Exception:
            pass
        s.default_subscriptions = total
        s.tcp_bind_port = int(self._tcp_bind_port.GetValue())
        s.udp_bind_port = int(self._udp_bind_port.GetValue())
        self.frame.settings_store.save()
        self.frame.set_status("Verbindungseinstellungen gespeichert")

    def _on_save_sound_events(self, _event):
        s = self.frame.settings_store.settings
        events = {}
        for key, ctrl in self._sound_event_paths.items():
            val = ctrl.GetValue().strip()
            if val:
                events[key] = val
        s.sound_events = events
        self.frame.settings_store.save()
        self.frame.set_status("Sound-Ereignisse gespeichert")

    def _on_browse_sound(self, key: str, ctrl: wx.TextCtrl):
        with wx.FileDialog(
            self,
            "Sounddatei auswählen",
            wildcard="WAV-Dateien (*.wav)|*.wav|Alle Dateien|*.*",
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        ) as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                ctrl.SetValue(dlg.GetPath())

    def _on_test_sound(self, key: str, ctrl: wx.TextCtrl):
        custom = ctrl.GetValue().strip()
        # Nutzt den Sound-Manager: fällt auf eingebettetes Sound-Pack zurück
        self.frame.sound_manager.play(key, custom or None)
        if not custom:
            self.frame.set_status("Standard-Sound wird abgespielt")

    # ---------------------------------------------------------------
    # Sound-Profile
    # ---------------------------------------------------------------

    _BUILTIN_PROFILES = {
        "Minimal": {"server_connect", "msg_private_rx"},
        "Stumm": set(),
    }

    def _apply_sound_profile(self, profile_name: str) -> None:
        """Wendet ein Sound-Profil auf die aktuellen Sound-Events an."""
        s = self.frame.settings_store.settings
        if profile_name == "Standard":
            # Standard: nichts ändern – der Nutzer hat self._sound_event_paths
            pass
        elif profile_name in self._BUILTIN_PROFILES:
            active_keys = self._BUILTIN_PROFILES[profile_name]
            for key, ctrl in self._sound_event_paths.items():
                if key not in active_keys:
                    ctrl.SetValue("")
        else:
            # Benutzerdefiniertes Profil laden
            for p in s.sound_profiles:
                if p.get("name") == profile_name:
                    for key, ctrl in self._sound_event_paths.items():
                        ctrl.SetValue(str(p.get(key, "") or ""))
                    break
        s.active_sound_profile = profile_name
        self.frame.settings_store.save()
        self.frame.set_status(f"Sound-Profil: {profile_name}")

    def _on_sound_profile_changed(self, _event) -> None:
        idx = self._sound_profile_choice.GetSelection()
        if idx == wx.NOT_FOUND:
            return
        name = self._sound_profile_choice.GetString(idx)
        self._apply_sound_profile(name)

    def _on_save_sound_profile(self, _event) -> None:
        dlg = wx.TextEntryDialog(self, "Profilname:", "Als Sound-Profil speichern")
        if dlg.ShowModal() != wx.ID_OK:
            dlg.Destroy()
            return
        name = dlg.GetValue().strip()
        dlg.Destroy()
        if not name or name in ("Standard", "Minimal", "Stumm"):
            wx.MessageBox("Bitte einen anderen Namen wählen (Standard/Minimal/Stumm sind reserviert).",
                          "Hinweis", wx.OK | wx.ICON_WARNING, self)
            return
        s = self.frame.settings_store.settings
        profile: dict = {"name": name}
        for key, ctrl in self._sound_event_paths.items():
            profile[key] = ctrl.GetValue().strip()
        # Vorhandenes überschreiben
        s.sound_profiles = [p for p in s.sound_profiles if p.get("name") != name]
        s.sound_profiles.append(profile)
        s.active_sound_profile = name
        self.frame.settings_store.save()
        # Choice aktualisieren
        existing = list(self._sound_profile_choice.GetStrings())
        if name not in existing:
            self._sound_profile_choice.Append(name)
            existing.append(name)
        self._sound_profile_choice.SetSelection(existing.index(name))
        self.frame.set_status(f"Sound-Profil gespeichert: {name}")

    def _on_delete_sound_profile(self, _event) -> None:
        idx = self._sound_profile_choice.GetSelection()
        if idx == wx.NOT_FOUND:
            return
        name = self._sound_profile_choice.GetString(idx)
        if name in ("Standard", "Minimal", "Stumm"):
            wx.MessageBox("Eingebaute Profile können nicht gelöscht werden.",
                          "Hinweis", wx.OK | wx.ICON_INFORMATION, self)
            return
        s = self.frame.settings_store.settings
        s.sound_profiles = [p for p in s.sound_profiles if p.get("name") != name]
        s.active_sound_profile = "Standard"
        self.frame.settings_store.save()
        self._sound_profile_choice.Delete(idx)
        self._sound_profile_choice.SetSelection(0)
        self.frame.set_status(f"Sound-Profil gelöscht: {name}")

    def _build_elevenlabs_tab(self) -> wx.Panel:
        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)
        s = self.frame.settings_store.settings

        el_box = wx.StaticBox(panel, label="ElevenLabs Text-to-Speech")
        el_sizer = wx.StaticBoxSizer(el_box, wx.VERTICAL)

        info = wx.StaticText(panel, label=(
            "Tragen Sie hier Ihren ElevenLabs API-Schlüssel ein.\n"
            "Er wird global für alle Serverprofile gespeichert."
        ))
        info.SetName("ElevenLabs Info")
        el_sizer.Add(info, 0, wx.ALL, 8)

        key_form = wx.FlexGridSizer(cols=2, vgap=6, hgap=12)
        key_form.AddGrowableCol(1)
        key_form.Add(wx.StaticText(panel, label="API-Schlüssel"), 0, wx.ALIGN_CENTER_VERTICAL)
        self._elevenlabs_key = wx.TextCtrl(panel, value=str(s.elevenlabs_api_key or ""), style=wx.TE_PASSWORD)
        self._elevenlabs_key.SetName("ElevenLabs API-Schlüssel")
        key_form.Add(self._elevenlabs_key, 1, wx.EXPAND)
        el_sizer.Add(key_form, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)

        sizer.Add(el_sizer, 0, wx.ALL | wx.EXPAND, 8)

        save_btn = wx.Button(panel, label="&Speichern")
        save_btn.SetName("ElevenLabs speichern")
        save_btn.Bind(wx.EVT_BUTTON, self._on_save_elevenlabs)
        sizer.Add(save_btn, 0, wx.LEFT | wx.BOTTOM, 8)

        panel.SetSizer(sizer)
        panel.Show(False)
        return panel

    def _on_save_elevenlabs(self, _event):
        key = self._elevenlabs_key.GetValue().strip()
        self.frame.settings_store.settings.elevenlabs_api_key = key
        self.frame.settings_store.save()
        self.frame._update_speak_tab(key)
        self.frame.set_status("ElevenLabs API-Schlüssel gespeichert")

    # ------------------------------------------------------------------
    # KI & Barrierefreiheit (v2.0.0)
    # ------------------------------------------------------------------

    def _build_ai_tab(self) -> wx.Panel:
        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)
        s = self.frame.settings_store.settings

        # --- Claude API ---
        claude_box = wx.StaticBox(panel, label="Claude KI (Anthropic)")
        claude_sizer = wx.StaticBoxSizer(claude_box, wx.VERTICAL)

        info_claude = wx.StaticText(panel, label=(
            "Claude-API-Schlüssel für KI-Chat-Zusammenfassungen.\n"
            "Alternativ: Umgebungsvariable ANTHROPIC_API_KEY setzen.\n"
            "Ohne Schlüssel: Ollama (lokal) oder einfache Extraktion."
        ))
        info_claude.SetName("Claude Info")
        claude_sizer.Add(info_claude, 0, wx.ALL, 8)

        key_form = wx.FlexGridSizer(cols=2, vgap=6, hgap=12)
        key_form.AddGrowableCol(1)
        key_form.Add(wx.StaticText(panel, label="API-Schlüssel"), 0, wx.ALIGN_CENTER_VERTICAL)
        self._claude_api_key = wx.TextCtrl(
            panel, value=str(getattr(s, "claude_api_key", "") or ""), style=wx.TE_PASSWORD
        )
        self._claude_api_key.SetName("Claude API-Schlüssel")
        key_form.Add(self._claude_api_key, 1, wx.EXPAND)
        claude_sizer.Add(key_form, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)
        sizer.Add(claude_sizer, 0, wx.ALL | wx.EXPAND, 8)

        # --- Google Gemini ---
        gemini_box = wx.StaticBox(panel, label="Google Gemini KI")
        gemini_sizer = wx.StaticBoxSizer(gemini_box, wx.VERTICAL)

        info_gemini = wx.StaticText(panel, label=(
            "API-Key aus https://aistudio.google.com/app/apikey\n"
            "oder Via Google anmelden (Browser-OAuth, kein Key nötig).\n"
            "Für OAuth: client_secrets.json aus Google Cloud Console\n"
            "in den App-Daten-Ordner legen."
        ))
        info_gemini.SetName("Gemini Info")
        gemini_sizer.Add(info_gemini, 0, wx.ALL, 8)

        gemini_form = wx.FlexGridSizer(cols=2, vgap=6, hgap=12)
        gemini_form.AddGrowableCol(1)
        gemini_form.Add(wx.StaticText(panel, label="API-Schlüssel"), 0, wx.ALIGN_CENTER_VERTICAL)
        self._gemini_api_key = wx.TextCtrl(
            panel, value=str(getattr(s, "gemini_api_key", "") or ""), style=wx.TE_PASSWORD
        )
        self._gemini_api_key.SetName("Gemini API-Schlüssel")
        gemini_form.Add(self._gemini_api_key, 1, wx.EXPAND)
        gemini_sizer.Add(gemini_form, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)

        gemini_btn_row = wx.BoxSizer(wx.HORIZONTAL)
        self._gemini_login_btn = wx.Button(panel, label="&Via Google anmelden")
        self._gemini_login_btn.SetName("Via Google anmelden")
        self._gemini_login_btn.Bind(wx.EVT_BUTTON, self._on_gemini_login)
        self._gemini_logout_btn = wx.Button(panel, label="&Abmelden")
        self._gemini_logout_btn.SetName("Google Abmelden")
        self._gemini_logout_btn.Bind(wx.EVT_BUTTON, self._on_gemini_logout)
        gemini_btn_row.Add(self._gemini_login_btn, 0, wx.RIGHT, 8)
        gemini_btn_row.Add(self._gemini_logout_btn, 0, wx.RIGHT, 12)
        self._gemini_status_label = wx.StaticText(panel, label="")
        self._gemini_status_label.SetName("Gemini Auth-Status")
        gemini_btn_row.Add(self._gemini_status_label, 1, wx.ALIGN_CENTER_VERTICAL)
        gemini_sizer.Add(gemini_btn_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        sizer.Add(gemini_sizer, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)
        # Status initial befüllen
        wx.CallAfter(self._refresh_gemini_status)

        # --- Sprachsteuerung ---
        vc_box = wx.StaticBox(panel, label="Sprachsteuerung (Whisper)")
        vc_sizer = wx.StaticBoxSizer(vc_box, wx.VERTICAL)

        info_vc = wx.StaticText(panel, label=(
            "Erfordert: pip install openai-whisper pyaudio\n"
            "Beim Start wird Whisper-Modell 'base' geladen (~150 MB)."
        ))
        info_vc.SetName("Sprachsteuerung Info")
        vc_sizer.Add(info_vc, 0, wx.ALL, 8)

        self._voice_control_enabled = wx.CheckBox(panel, label="&Sprachsteuerung beim Start aktivieren")
        self._voice_control_enabled.SetName("Sprachsteuerung aktivieren")
        self._voice_control_enabled.SetValue(bool(getattr(s, "voice_control_enabled", False)))
        vc_sizer.Add(self._voice_control_enabled, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        vc_btn_row = wx.BoxSizer(wx.HORIZONTAL)
        self._vc_start_btn = wx.Button(panel, label="&Jetzt starten")
        self._vc_start_btn.SetName("Sprachsteuerung jetzt starten")
        self._vc_start_btn.Bind(wx.EVT_BUTTON, self._on_vc_start)
        self._vc_stop_btn = wx.Button(panel, label="&Stoppen")
        self._vc_stop_btn.SetName("Sprachsteuerung stoppen")
        self._vc_stop_btn.Bind(wx.EVT_BUTTON, self._on_vc_stop)
        vc_btn_row.Add(self._vc_start_btn, 0, wx.RIGHT, 8)
        vc_btn_row.Add(self._vc_stop_btn, 0)
        vc_sizer.Add(vc_btn_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        sizer.Add(vc_sizer, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)

        # --- Braille-Verbosität ---
        braille_box = wx.StaticBox(panel, label="Braillezeilen-Ausgabe")
        braille_sizer = wx.StaticBoxSizer(braille_box, wx.VERTICAL)

        braille_row = wx.BoxSizer(wx.HORIZONTAL)
        braille_row.Add(wx.StaticText(panel, label="Verbositätsstufe"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self._braille_verbosity = wx.Choice(panel, choices=["kompakt", "normal", "ausführlich"])
        self._braille_verbosity.SetName("Braille-Verbositätsstufe")
        _vmap = {"compact": 0, "normal": 1, "verbose": 2}
        self._braille_verbosity.SetSelection(_vmap.get(getattr(s, "braille_verbosity", "normal"), 1))
        braille_row.Add(self._braille_verbosity, 0)
        braille_sizer.Add(braille_row, 0, wx.ALL, 8)
        sizer.Add(braille_sizer, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)

        # --- Live-Transkription ---
        trans_box = wx.StaticBox(panel, label="Live-Transkription")
        trans_sizer = wx.StaticBoxSizer(trans_box, wx.VERTICAL)

        info_trans = wx.StaticText(panel, label=(
            "Erfordert: pip install openai-whisper numpy\n"
            "Transkribiert Kanal-Sprache und zeigt sie im Kanäle-Tab an."
        ))
        info_trans.SetName("Transkription Info")
        trans_sizer.Add(info_trans, 0, wx.ALL, 8)

        self._transcription_enabled = wx.CheckBox(panel, label="Live-&Transkription aktivieren")
        self._transcription_enabled.SetName("Live-Transkription aktivieren")
        self._transcription_enabled.SetValue(bool(getattr(s, "transcription_enabled", False)))
        trans_sizer.Add(self._transcription_enabled, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        sizer.Add(trans_sizer, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)

        # --- Speichern ---
        save_btn = wx.Button(panel, label="&Speichern")
        save_btn.SetName("KI & Barrierefreiheit speichern")
        save_btn.Bind(wx.EVT_BUTTON, self._on_save_ai)
        sizer.Add(save_btn, 0, wx.LEFT | wx.BOTTOM, 8)

        panel.SetSizer(sizer)
        panel.Show(False)
        return panel

    def _on_save_ai(self, _event) -> None:
        s = self.frame.settings_store.settings
        s.claude_api_key = self._claude_api_key.GetValue().strip()
        s.gemini_api_key = self._gemini_api_key.GetValue().strip()
        s.voice_control_enabled = self._voice_control_enabled.GetValue()
        _vmap_rev = {0: "compact", 1: "normal", 2: "verbose"}
        verbosity = _vmap_rev.get(self._braille_verbosity.GetSelection(), "normal")
        s.braille_verbosity = verbosity
        self.frame.braille.verbosity = verbosity
        s.transcription_enabled = self._transcription_enabled.GetValue()
        # Transkription starten/stoppen je nach Einstellung
        self._apply_transcription_setting(s.transcription_enabled)
        self.frame.settings_store.save()
        self.frame.set_status("KI & Barrierefreiheit gespeichert")

    def _apply_transcription_setting(self, enabled: bool) -> None:
        try:
            mgr = getattr(self.frame, "_transcription_mgr", None)
            if enabled and mgr is None:
                from transcription import TranscriptionManager
                self.frame._transcription_mgr = TranscriptionManager(self.frame.bus)
                self.frame._transcription_mgr.load_model()
                self.frame._transcription_mgr.start()
            elif not enabled and mgr is not None:
                mgr.stop()
                self.frame._transcription_mgr = None
        except Exception as exc:
            self.frame.set_status(f"Transkription: {exc}")

    def _refresh_gemini_status(self) -> None:
        try:
            label = self.frame._gemini_auth.auth_status_label()
            self._gemini_status_label.SetLabel(label)
        except Exception:
            pass

    def _on_gemini_login(self, _event) -> None:
        self._gemini_login_btn.Disable()
        self._gemini_status_label.SetLabel("Browser öffnet sich...")

        def _on_success(_creds) -> None:
            import wx as _wx
            _wx.CallAfter(self._gemini_login_btn.Enable)
            _wx.CallAfter(self._refresh_gemini_status)
            _wx.CallAfter(self.frame.set_status, "Google-Anmeldung erfolgreich")

        def _on_error(msg: str) -> None:
            import wx as _wx
            _wx.CallAfter(self._gemini_login_btn.Enable)
            _wx.CallAfter(self._gemini_status_label.SetLabel, f"Fehler: {msg[:60]}")
            _wx.CallAfter(self.frame.set_status, f"Gemini-Anmeldung fehlgeschlagen: {msg}")

        try:
            self.frame._gemini_auth.start_oauth_flow(
                on_success=_on_success,
                on_error=_on_error,
            )
        except Exception as exc:
            self._gemini_login_btn.Enable()
            self._gemini_status_label.SetLabel(f"Fehler: {exc}")

    def _on_gemini_logout(self, _event) -> None:
        try:
            self.frame._gemini_auth.revoke()
            self._refresh_gemini_status()
            self.frame.set_status("Google-Abmeldung erfolgreich")
        except Exception as exc:
            self.frame.set_status(f"Gemini-Abmeldung: {exc}")

    def _on_vc_start(self, _event) -> None:
        try:
            self.frame._start_voice_control()
        except Exception as exc:
            self.frame.set_status(f"Sprachsteuerung: {exc}")

    def _on_vc_stop(self, _event) -> None:
        try:
            self.frame._stop_voice_control()
            self.frame.set_status("Sprachsteuerung gestoppt")
        except Exception as exc:
            self.frame.set_status(f"Sprachsteuerung: {exc}")

    # ------------------------------------------------------------------
    # Section navigation
    # ------------------------------------------------------------------

    def show_section(self, section: str) -> None:
        if section in self._sections:
            self.section_choice.SetStringSelection(section)
            self._show_section(section)

    def _on_section_changed(self, _event):
        self._show_section(self.section_choice.GetStringSelection())

    def _on_share_logs_menu(self, _event):
        menu = wx.Menu()
        export_item = menu.Append(wx.ID_ANY, "Logs exportieren (ZIP)")
        copy_item = menu.Append(wx.ID_ANY, "Logs kopieren")
        both_item = menu.Append(wx.ID_ANY, "Beides (ZIP + Kopieren)")
        self.Bind(wx.EVT_MENU, lambda evt: self._export_logs_zip(), export_item)
        self.Bind(wx.EVT_MENU, lambda evt: self._copy_logs_to_clipboard(), copy_item)
        self.Bind(wx.EVT_MENU, lambda evt: self._export_and_copy_logs(), both_item)
        self.PopupMenu(menu)
        menu.Destroy()

    def _collect_log_paths(self) -> List:
        paths = []
        # Primary logs
        paths.append(app_data_dir() / "client.log")
        paths.append(log_dir() / "startup.log")
        paths.append(log_dir() / "last_crash.txt")
        return [p for p in paths if p.exists()]

    def _copy_logs_to_clipboard(self) -> None:
        paths = self._collect_log_paths()
        if not paths:
            self.frame.set_status("Keine Logdateien gefunden")
            return
        parts = []
        for path in paths:
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except Exception as exc:
                text = f"[Fehler beim Lesen: {exc}]"
            parts.append(f"===== {path.name} =====\n{text}\n")
        payload = "\n".join(parts)
        if wx.TheClipboard.Open():
            wx.TheClipboard.SetData(wx.TextDataObject(payload))
            wx.TheClipboard.Close()
            self.frame.set_status("Logs in die Zwischenablage kopiert")
        else:
            self.frame.set_status("Zwischenablage konnte nicht geöffnet werden")

    def _export_logs_zip(self) -> None:
        paths = self._collect_log_paths()
        if not paths:
            self.frame.set_status("Keine Logdateien gefunden")
            return
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"TeamTalkVOClient_logs_{ts}.zip"
        with wx.FileDialog(
            self,
            "Logs exportieren",
            wildcard="ZIP (*.zip)|*.zip",
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
            defaultFile=default_name,
        ) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            out_path = dlg.GetPath()
        try:
            with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                for path in paths:
                    zf.write(path, arcname=path.name)
            self.frame.set_status(f"Logs exportiert: {out_path}")
        except Exception as exc:
            self.frame.set_status(f"Log-Export fehlgeschlagen: {exc}")

    def _export_and_copy_logs(self) -> None:
        self._export_logs_zip()
        self._copy_logs_to_clipboard()

    def _show_section(self, section: str) -> None:
        for name, panel in self._sections.items():
            panel.Show(name == section)
        self.Layout()
