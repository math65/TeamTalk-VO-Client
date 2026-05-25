from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QFormLayout,
    QLabel, QLineEdit, QCheckBox, QComboBox, QSpinBox,
    QPushButton, QTabWidget, QFileDialog, QScrollArea, QTextEdit, QTimeEdit,
)
from PySide6.QtCore import QTime

from ui_qt.tabs.audio import AudioTab
from ui_qt.tabs.video import VideoTab
from ui_qt.tabs.shortcuts import ShortcutsTab
from ui_qt.tabs.system import SystemTab

from i18n import _

if TYPE_CHECKING:
    from app_qt import MainWindow

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
    ("Kanal aktiv (Sprache beginnt)", "channel_active"),
    ("Kanal-Stille (letzter Sprecher)", "channel_silent"),
    ("Dateitransfer abgeschlossen", "file_transfer"),
    ("Video-Session gestartet", "video_session"),
    ("Desktop-Session gestartet", "desktop_session"),
    ("Frage-Modus geändert", "question_mode"),
    ("Desktopzugriff angefragt", "desktop_access"),
    ("Benutzer angemeldet", "user_login"),
    ("Benutzer abgemeldet", "user_logout"),
]

_SUBSCRIPTIONS = [
    ("Benutzernachrichten", "sub_user_msg"),
    ("Kanalnachrichten", "sub_channel_msg"),
    ("Broadcast-Nachrichten", "sub_broadcast"),
    ("Sprache", "sub_voice"),
    ("Video", "sub_video"),
    ("Desktop", "sub_desktop"),
    ("Mediendateien", "sub_mediafile"),
]


class SettingsTab(QWidget):
    """Einstellungs-Tab mit vollständigen Unterreitern."""

    def __init__(self, parent: QWidget, window: "MainWindow") -> None:
        super().__init__(parent)
        self.window = window

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)

        self.inner = QTabWidget()
        root.addWidget(self.inner)

        self.audio_tab = AudioTab(self, window)
        self.video_tab = VideoTab(self, window)
        self.shortcuts_tab = ShortcutsTab(self, window)
        self.system_tab = SystemTab(self, window)

        self.inner.addTab(self._build_general_tab(), _("Allgemein"))
        self.inner.addTab(self._build_connection_tab(), _("Verbindung"))
        self.inner.addTab(self._build_sound_events_tab(), _("Sound-Ereignisse"))
        self.inner.addTab(self._build_recording_tab(), _("Aufnahmen"))
        self.inner.addTab(self.audio_tab, _("Audio"))
        self.inner.addTab(self._build_audio_extras_tab(), _("Audio-Extras"))
        self.inner.addTab(self.video_tab, _("Video"))
        self.inner.addTab(self.shortcuts_tab, _("Tastenkürzel"))
        self.inner.addTab(self.system_tab, "TTS")
        self.inner.addTab(self._build_chat_tab(), _("Chat & Automation"))
        self.inner.addTab(self._build_ki_tab(), _("KI & Integration"))
        self.inner.addTab(self._build_user_volumes_tab(), _("Nutzer-Lautstärken"))
        self.inner.addTab(self._build_braille_tab(), _("Braille"))

    # ------------------------------------------------------------------
    # Allgemein
    # ------------------------------------------------------------------

    def _build_general_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        layout = QVBoxLayout(inner)
        s = self.window.settings_store.settings

        # --- Darstellung ---
        disp_group = QGroupBox(_("Darstellung & Verhalten"))
        disp_form = QFormLayout(disp_group)

        self.start_minimized = QCheckBox(_("Minimiert starten"))
        self.start_minimized.setChecked(bool(getattr(s, "start_minimized", False)))
        self.start_minimized.stateChanged.connect(lambda v: self._save_bool("start_minimized", v))
        disp_form.addRow("", self.start_minimized)

        self.close_to_tray = QCheckBox(_("In Taskleiste minimieren beim Schließen"))
        self.close_to_tray.setChecked(bool(getattr(s, "close_to_tray", True)))
        self.close_to_tray.stateChanged.connect(lambda v: self._save_bool("close_to_tray", v))
        disp_form.addRow("", self.close_to_tray)

        self.always_on_top = QCheckBox(_("Immer im Vordergrund"))
        self.always_on_top.setChecked(bool(getattr(s, "always_on_top", False)))
        self.always_on_top.stateChanged.connect(self._on_always_on_top)
        disp_form.addRow("", self.always_on_top)

        self.show_timestamps = QCheckBox(_("Zeitstempel im Chat anzeigen"))
        self.show_timestamps.setChecked(bool(getattr(s, "show_timestamps", True)))
        self.show_timestamps.stateChanged.connect(lambda v: self._save_bool("show_timestamps", v))
        disp_form.addRow("", self.show_timestamps)

        self.relative_timestamps = QCheckBox(_("Relative Zeitstempel (gerade eben / vor X Min.)"))
        self.relative_timestamps.setChecked(bool(getattr(s, "chat_relative_timestamps", False)))
        self.relative_timestamps.stateChanged.connect(lambda v: self._save_bool("chat_relative_timestamps", v))
        disp_form.addRow("", self.relative_timestamps)

        self.desktop_notifications = QCheckBox(_("Desktop-Benachrichtigungen"))
        self.desktop_notifications.setChecked(bool(getattr(s, "desktop_notifications", True)))
        self.desktop_notifications.stateChanged.connect(lambda v: self._save_bool("desktop_notifications", v))
        disp_form.addRow("", self.desktop_notifications)

        self.sounds_enabled = QCheckBox(_("Ereignis-Sounds aktivieren"))
        self.sounds_enabled.setChecked(bool(getattr(s, "sounds_enabled", True)))
        self.sounds_enabled.stateChanged.connect(lambda v: self._save_bool("sounds_enabled", v))
        disp_form.addRow("", self.sounds_enabled)

        self.braille_compact = QCheckBox(_("Braille-Kompaktmodus"))
        self.braille_compact.setChecked(bool(getattr(s, "braille_compact", False)))
        self.braille_compact.stateChanged.connect(lambda v: self._save_bool("braille_compact", v))
        disp_form.addRow("", self.braille_compact)

        _LANG_CODES = ["de", "en", "fr", "es"]
        _LANG_LABELS = ["Deutsch", "English", "Français", "Español"]
        lang_combo = QComboBox()
        lang_combo.addItems(_LANG_LABELS)
        lang_combo.setAccessibleName(_("App-Sprache"))
        lang_combo._lang_codes = _LANG_CODES
        self._lang_combo = lang_combo
        saved_lang = getattr(s, "app_language", "de") or "de"
        sel = _LANG_CODES.index(saved_lang) if saved_lang in _LANG_CODES else 0
        lang_combo.setCurrentIndex(sel)
        lang_combo.currentIndexChanged.connect(self._on_lang_changed)
        disp_form.addRow(_("Sprache"), lang_combo)

        layout.addWidget(disp_group)

        # --- Abwesenheits-Timer ---
        away_group = QGroupBox(_("Abwesenheit"))
        away_form = QFormLayout(away_group)
        self.away_timer = QSpinBox()
        self.away_timer.setRange(0, 120)
        self.away_timer.setSuffix(_(" min (0 = aus)"))
        self.away_timer.setValue(int(getattr(s, "away_timer_min", 0) or 0))
        self.away_timer.setAccessibleName(_("Weg-Modus nach (Minuten)"))
        self.away_timer.valueChanged.connect(lambda v: self._save_int("away_timer_min", v))
        away_form.addRow(_("Weg-Modus nach"), self.away_timer)

        self.away_status = QLineEdit(getattr(s, "away_status_message", "Bin kurz weg") or "Bin kurz weg")
        self.away_status.setPlaceholderText(_("Status-Nachricht bei Abwesenheit"))
        self.away_status.setAccessibleName(_("Weg-Status-Nachricht"))
        self.away_status.textChanged.connect(lambda v: self._save_str("away_status_message", v))
        away_form.addRow(_("Weg-Status"), self.away_status)
        layout.addWidget(away_group)

        # --- Chat-Filter ---
        filter_group = QGroupBox(_("Chat-Filter"))
        filter_form = QFormLayout(filter_group)

        self.highlight_keywords = QLineEdit(getattr(s, "highlight_keywords", "") or "")
        self.highlight_keywords.setPlaceholderText(_("Wort1, Wort2, … (Komma-getrennt)"))
        self.highlight_keywords.setAccessibleName(_("Hervorhebungs-Schlüsselwörter (kommagetrennt)"))
        self.highlight_keywords.textChanged.connect(lambda v: self._save_str("highlight_keywords", v))
        filter_form.addRow(_("Hervorheben"), self.highlight_keywords)

        self.muted_users = QLineEdit(getattr(s, "muted_users", "") or "")
        self.muted_users.setPlaceholderText(_("Benutzername1, Benutzername2, …"))
        self.muted_users.setAccessibleName(_("Stummgeschaltete Nutzer (kommagetrennt)"))
        self.muted_users.textChanged.connect(lambda v: self._save_str("muted_users", v))
        filter_form.addRow(_("Nutzer stummschalten"), self.muted_users)
        layout.addWidget(filter_group)

        layout.addStretch()
        scroll.setWidget(inner)
        return scroll

    # ------------------------------------------------------------------
    # Verbindung
    # ------------------------------------------------------------------

    def _build_connection_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        layout = QVBoxLayout(inner)
        s = self.window.settings_store.settings

        # Auto-Reconnect
        rc_group = QGroupBox(_("Automatisch neu verbinden"))
        rc_form = QFormLayout(rc_group)

        self.auto_reconnect = QCheckBox(_("Automatisch neu verbinden"))
        self.auto_reconnect.setChecked(bool(getattr(s, "auto_reconnect_enabled", True)))
        self.auto_reconnect.stateChanged.connect(lambda v: self._save_bool("auto_reconnect_enabled", v))
        rc_form.addRow("", self.auto_reconnect)

        self.reconnect_delay = QSpinBox()
        self.reconnect_delay.setRange(5, 300)
        self.reconnect_delay.setSuffix(" s")
        self.reconnect_delay.setValue(int(getattr(s, "reconnect_delay_seconds", 10) or 10))
        self.reconnect_delay.setAccessibleName(_("Reconnect-Wartezeit in Sekunden"))
        self.reconnect_delay.valueChanged.connect(lambda v: self._save_int("reconnect_delay_seconds", v))
        rc_form.addRow(_("Wartezeit"), self.reconnect_delay)

        self.reconnect_max = QSpinBox()
        self.reconnect_max.setRange(0, 9999)
        self.reconnect_max.setSuffix(_(" (0 = unbegrenzt)"))
        self.reconnect_max.setValue(int(getattr(s, "reconnect_max_attempts", 0) or 0))
        self.reconnect_max.setAccessibleName(_("Maximale Reconnect-Versuche (0 unbegrenzt)"))
        self.reconnect_max.valueChanged.connect(lambda v: self._save_int("reconnect_max_attempts", v))
        rc_form.addRow(_("Max. Versuche"), self.reconnect_max)
        layout.addWidget(rc_group)

        # Standard-Abonnements
        sub_group = QGroupBox(_("Standard-Abonnements beim Verbinden"))
        sub_layout = QVBoxLayout(sub_group)
        self._sub_checks: dict = {}
        for label, key in _SUBSCRIPTIONS:
            cb = QCheckBox(_(label))
            cb.setChecked(bool(getattr(s, key, True)))
            cb.stateChanged.connect(lambda v, k=key: self._save_bool(k, v))
            sub_layout.addWidget(cb)
            self._sub_checks[key] = cb
        layout.addWidget(sub_group)

        # Port-Bindung
        port_group = QGroupBox(_("Port-Bindung (0 = automatisch)"))
        port_form = QFormLayout(port_group)

        self.tcp_bind_port = QSpinBox()
        self.tcp_bind_port.setRange(0, 65535)
        self.tcp_bind_port.setValue(int(getattr(s, "tcp_bind_port", 0) or 0))
        self.tcp_bind_port.setAccessibleName(_("TCP-Bindungsport (0 automatisch)"))
        self.tcp_bind_port.valueChanged.connect(lambda v: self._save_int("tcp_bind_port", v))
        port_form.addRow(_("TCP-Port"), self.tcp_bind_port)

        self.udp_bind_port = QSpinBox()
        self.udp_bind_port.setRange(0, 65535)
        self.udp_bind_port.setValue(int(getattr(s, "udp_bind_port", 0) or 0))
        self.udp_bind_port.setAccessibleName(_("UDP-Bindungsport (0 automatisch)"))
        self.udp_bind_port.valueChanged.connect(lambda v: self._save_int("udp_bind_port", v))
        port_form.addRow(_("UDP-Port"), self.udp_bind_port)
        layout.addWidget(port_group)

        # Verbindungsqualität
        quality_group = QGroupBox(_("Verbindungsqualität"))
        quality_form = QFormLayout(quality_group)

        self.announce_bad_conn = QCheckBox(_("Schlechte Verbindung ankündigen"))
        self.announce_bad_conn.setChecked(bool(getattr(s, "announce_bad_connection", False)))
        self.announce_bad_conn.stateChanged.connect(lambda v: self._save_bool("announce_bad_connection", v))
        quality_form.addRow("", self.announce_bad_conn)

        self.ping_threshold = QSpinBox()
        self.ping_threshold.setRange(50, 9999)
        self.ping_threshold.setSuffix(" ms")
        self.ping_threshold.setValue(int(getattr(s, "ping_threshold_ms", 500) or 500))
        self.ping_threshold.setAccessibleName(_("Ping-Schwellwert in Millisekunden"))
        self.ping_threshold.valueChanged.connect(lambda v: self._save_int("ping_threshold_ms", v))
        quality_form.addRow(_("Ping-Schwellwert"), self.ping_threshold)
        layout.addWidget(quality_group)

        # BearWare Web-Login
        bw_group = QGroupBox(_("BearWare Web-Login"))
        bw_form = QFormLayout(bw_group)

        self.bearware_enabled = QCheckBox(_("BearWare Web-Login verwenden"))
        self.bearware_enabled.setChecked(bool(getattr(s, "bearware_login", False)))
        self.bearware_enabled.stateChanged.connect(lambda v: self._save_bool("bearware_login", v))
        bw_form.addRow("", self.bearware_enabled)

        self.bearware_username = QLineEdit(getattr(s, "bearware_username", "") or "")
        self.bearware_username.setPlaceholderText(_("BearWare-Benutzername"))
        self.bearware_username.textChanged.connect(lambda v: self._save_str("bearware_username", v))
        bw_form.addRow(_("Benutzername"), self.bearware_username)

        self.bearware_password = QLineEdit(getattr(s, "bearware_password", "") or "")
        self.bearware_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.bearware_password.setPlaceholderText(_("BearWare-Passwort"))
        self.bearware_password.textChanged.connect(lambda v: self._save_str("bearware_password", v))
        bw_form.addRow(_("Passwort"), self.bearware_password)
        layout.addWidget(bw_group)

        # Serverliste & Verhalten
        misc_group = QGroupBox(_("Serverliste & Verhalten"))
        misc_form = QFormLayout(misc_group)
        from PySide6.QtWidgets import QComboBox as _QComboBox
        self.server_sort_combo = _QComboBox()
        self.server_sort_combo.addItems([_("Manuell"), _("Name"), _("Host")])
        _sort_idx = {"manual": 0, "name": 1, "host": 2}.get(str(getattr(s, "server_list_sort", "manual") or "manual"), 0)
        self.server_sort_combo.setCurrentIndex(_sort_idx)
        self.server_sort_combo.setAccessibleName(_("Serverliste sortieren nach"))
        self.server_sort_combo.currentIndexChanged.connect(self._on_server_sort_changed)
        misc_form.addRow(_("Sortierung"), self.server_sort_combo)
        self.skip_kick_cb = QCheckBox(_("Kick-Bestätigung überspringen"))
        self.skip_kick_cb.setChecked(bool(getattr(s, "skip_kick_confirmation", False)))
        self.skip_kick_cb.stateChanged.connect(lambda v: self._save_bool("skip_kick_confirmation", v))
        misc_form.addRow("", self.skip_kick_cb)
        self.jitter_cb = QCheckBox(_("Adaptiver Jitter-Buffer"))
        self.jitter_cb.setChecked(bool(getattr(s, "adaptive_jitter_buffer", False)))
        self.jitter_cb.stateChanged.connect(lambda v: self._save_bool("adaptive_jitter_buffer", v))
        misc_form.addRow("", self.jitter_cb)
        layout.addWidget(misc_group)

        # Hintergrund-Benachrichtigungen
        bg_notif_group = QGroupBox(_("Hintergrund-Benachrichtigungen"))
        bg_notif_form = QFormLayout(bg_notif_group)
        self.notify_bg_private = QCheckBox(_("Privatnachrichten"))
        self.notify_bg_private.setChecked(bool(getattr(s, "notify_background_private", True)))
        self.notify_bg_private.stateChanged.connect(lambda v: self._save_bool("notify_background_private", v))
        bg_notif_form.addRow("", self.notify_bg_private)
        self.notify_bg_channel = QCheckBox(_("Kanalnachrichten"))
        self.notify_bg_channel.setChecked(bool(getattr(s, "notify_background_channel", False)))
        self.notify_bg_channel.stateChanged.connect(lambda v: self._save_bool("notify_background_channel", v))
        bg_notif_form.addRow("", self.notify_bg_channel)
        self.notify_bg_broadcast = QCheckBox(_("Rundnachrichten"))
        self.notify_bg_broadcast.setChecked(bool(getattr(s, "notify_background_broadcast", True)))
        self.notify_bg_broadcast.stateChanged.connect(lambda v: self._save_bool("notify_background_broadcast", v))
        bg_notif_form.addRow("", self.notify_bg_broadcast)
        layout.addWidget(bg_notif_group)

        # Auto-Kanal per Server-Schlüssel
        ac_group = QGroupBox(_("Automatisch beitreten (pro Server)"))
        ac_form = QFormLayout(ac_group)
        ac_info = QLabel(
            _("Kanalname, der nach dem Verbinden automatisch betreten wird.\n"
              "Leer lassen = deaktiviert. Wird pro Server gespeichert.\n"
              "Gilt nur wenn im Serverprofil kein Kanal eingetragen ist.")
        )
        ac_info.setWordWrap(True)
        ac_form.addRow(ac_info)
        server_key = getattr(self.window, "_current_server_key", "") or ""
        ajc = getattr(s, "auto_join_channel_per_server", {}) or {}
        self._auto_join_channel = QLineEdit(ajc.get(server_key, ""))
        self._auto_join_channel.setAccessibleName(_("Auto-Kanal Kanalname"))
        self._auto_join_channel.setPlaceholderText(_("Kanalname (ohne Schrägstrich)"))
        self._auto_join_channel.textChanged.connect(self._on_auto_join_channel_changed)
        ac_form.addRow(_("Kanalname"), self._auto_join_channel)
        layout.addWidget(ac_group)

        layout.addStretch()
        scroll.setWidget(inner)
        return scroll

    def _on_server_sort_changed(self, idx: int) -> None:
        _choices = ["manual", "name", "host"]
        val = _choices[idx] if 0 <= idx < len(_choices) else "manual"
        self._save_str("server_list_sort", val)

    def _on_auto_join_channel_changed(self, text: str) -> None:
        s = self.window.settings_store.settings
        server_key = getattr(self.window, "_current_server_key", "") or ""
        if not server_key:
            return
        ajc = dict(getattr(s, "auto_join_channel_per_server", {}) or {})
        if text.strip():
            ajc[server_key] = text.strip()
        else:
            ajc.pop(server_key, None)
        s.auto_join_channel_per_server = ajc
        self.window.settings_store.save()

    # ------------------------------------------------------------------
    # Sound-Ereignisse
    # ------------------------------------------------------------------

    def _build_sound_events_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        layout = QVBoxLayout(inner)
        s = self.window.settings_store.settings

        # Sound-Pack-Ordner
        pack_group = QGroupBox(_("Sound-Pack-Ordner"))
        pack_layout = QVBoxLayout(pack_group)
        pack_layout.addWidget(QLabel(
            _("Ordner mit .wav-Dateien (Dateinamen wie Standard-Pack): "
              "überschreibt alle Einzel-Einstellungen.")
        ))
        pack_row = QHBoxLayout()
        self.sound_pack_dir = QLineEdit(getattr(s, "sound_pack_dir", "") or "")
        self.sound_pack_dir.setPlaceholderText(_("Leer = eingebettetes Standard-Pack"))
        self.sound_pack_dir.setAccessibleName(_("Sound-Pack-Ordner"))
        self.sound_pack_dir.textChanged.connect(self._on_sound_pack_dir_changed)
        pack_browse = QPushButton(_("&Ordner…"))
        pack_browse.clicked.connect(self._browse_sound_pack_dir)
        pack_row.addWidget(self.sound_pack_dir, 1)
        pack_row.addWidget(pack_browse)
        pack_layout.addLayout(pack_row)
        layout.addWidget(pack_group)

        # Individuelle Ereignis-Sounds
        evt_group = QGroupBox(_("Einzelne Ereignis-Sounds (überschreiben Sound-Pack)"))
        evt_layout = QVBoxLayout(evt_group)
        self._sound_event_rows: dict = {}
        sound_events = getattr(s, "sound_events", {}) or {}

        for label, key in _SOUND_EVENTS:
            row = QHBoxLayout()
            tr_label = _(label)
            lbl = QLabel(tr_label)
            lbl.setMinimumWidth(230)
            row.addWidget(lbl)
            field = QLineEdit()
            field.setText(sound_events.get(key, "") or "")
            field.setPlaceholderText(_("Leer = Standard"))
            field.setAccessibleName(f"Sound-Datei: {tr_label}")
            field.textChanged.connect(lambda v, k=key: self._save_sound_event(k, v))
            test_btn = QPushButton("▶")
            test_btn.setFixedWidth(28)
            test_btn.setAccessibleName(f"Testen: {tr_label}")
            test_btn.clicked.connect(lambda _ck, k=key: self.window.sound_manager.play(k))
            browse_btn = QPushButton("…")
            browse_btn.setFixedWidth(30)
            browse_btn.setAccessibleName(f"Datei wählen: {tr_label}")
            browse_btn.clicked.connect(lambda _ck, f=field: self._browse_sound(f))
            row.addWidget(field, 1)
            row.addWidget(test_btn)
            row.addWidget(browse_btn)
            evt_layout.addLayout(row)
            self._sound_event_rows[key] = field

        layout.addWidget(evt_group)
        layout.addStretch()
        scroll.setWidget(inner)
        return scroll

    def _on_sound_pack_dir_changed(self, value: str) -> None:
        try:
            self.window.settings_store.settings.sound_pack_dir = value
            self.window.settings_store.save()
            self.window.sound_manager.set_pack_dir(value)
        except Exception:
            pass

    def _browse_sound_pack_dir(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        directory = QFileDialog.getExistingDirectory(self, _("Sound-Pack-Ordner wählen"))
        if directory:
            self.sound_pack_dir.setText(directory)

    def _save_sound_event(self, key: str, value: str) -> None:
        try:
            s = self.window.settings_store.settings
            events = dict(getattr(s, "sound_events", {}) or {})
            if value:
                events[key] = value
            else:
                events.pop(key, None)
            s.sound_events = events
            self.window.settings_store.save()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Chat & Automation
    # ------------------------------------------------------------------

    def _build_chat_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        layout = QVBoxLayout(inner)
        s = self.window.settings_store.settings

        chat_group = QGroupBox(_("Chat-Verlauf"))
        chat_form = QFormLayout(chat_group)

        self.save_chat_history = QCheckBox(_("Kanal-Chat-Verlauf speichern"))
        self.save_chat_history.setChecked(bool(getattr(s, "save_chat_history", True)))
        self.save_chat_history.stateChanged.connect(lambda v: self._save_bool("save_chat_history", v))
        chat_form.addRow("", self.save_chat_history)

        self.save_private_chat = QCheckBox(_("Privatnachrichten-Verlauf speichern"))
        self.save_private_chat.setChecked(bool(getattr(s, "save_private_chat_history", True)))
        self.save_private_chat.stateChanged.connect(lambda v: self._save_bool("save_private_chat_history", v))
        chat_form.addRow("", self.save_private_chat)

        self.auto_join_last = QCheckBox(_("Zuletzt besuchten Kanal automatisch betreten"))
        self.auto_join_last.setChecked(bool(getattr(s, "auto_join_last_channel", False)))
        self.auto_join_last.stateChanged.connect(lambda v: self._save_bool("auto_join_last_channel", v))
        chat_form.addRow("", self.auto_join_last)
        layout.addWidget(chat_group)

        trans_group = QGroupBox(_("Chat-Übersetzung"))
        trans_form = QFormLayout(trans_group)

        self.translation_enabled = QCheckBox(_("Übersetzung aktivieren"))
        self.translation_enabled.setChecked(bool(getattr(s, "translation_enabled", False)))
        self.translation_enabled.stateChanged.connect(lambda v: self._save_bool("translation_enabled", v))
        trans_form.addRow("", self.translation_enabled)

        self.translation_target_lang = QLineEdit(getattr(s, "translation_target_lang", "de") or "de")
        self.translation_target_lang.setPlaceholderText("de / en / fr / …")
        self.translation_target_lang.textChanged.connect(lambda v: self._save_str("translation_target_lang", v))
        trans_form.addRow(_("Zielsprache"), self.translation_target_lang)
        layout.addWidget(trans_group)

        auto_group = QGroupBox(_("Automation"))
        auto_form = QFormLayout(auto_group)

        self.ai_summary_enabled = QCheckBox(_("KI-Kanal-Zusammenfassung aktivieren"))
        self.ai_summary_enabled.setChecked(bool(getattr(s, "ai_summary_enabled", False)))
        self.ai_summary_enabled.stateChanged.connect(lambda v: self._save_bool("ai_summary_enabled", v))
        auto_form.addRow("", self.ai_summary_enabled)

        self.auto_greeting_enabled = QCheckBox(_("Automatisch beim Kanalbetreten grüßen"))
        self.auto_greeting_enabled.setAccessibleName(_("Automatisch grüßen"))
        self.auto_greeting_enabled.setChecked(bool(getattr(s, "auto_greeting_enabled", False)))
        self.auto_greeting_enabled.stateChanged.connect(lambda v: self._save_bool("auto_greeting_enabled", bool(v)))
        auto_form.addRow("", self.auto_greeting_enabled)

        self.auto_greeting_text = QLineEdit(str(getattr(s, "auto_greeting_text", "") or ""))
        self.auto_greeting_text.setAccessibleName(_("Begrüßungstext"))
        self.auto_greeting_text.setPlaceholderText(_("z. B. Hallo zusammen!"))
        self.auto_greeting_text.editingFinished.connect(
            lambda: self._save_str("auto_greeting_text", self.auto_greeting_text.text().strip())
        )
        auto_form.addRow(_("Begrüßungstext"), self.auto_greeting_text)

        self.auto_reply_enabled = QCheckBox(_("Auto-Antwort aktivieren"))
        self.auto_reply_enabled.setChecked(bool(getattr(s, "auto_reply_enabled", False)))
        self.auto_reply_enabled.stateChanged.connect(lambda v: self._save_bool("auto_reply_enabled", v))
        auto_form.addRow("", self.auto_reply_enabled)

        self.auto_reply_text = QLineEdit(getattr(s, "auto_reply_text", "") or "")
        self.auto_reply_text.setPlaceholderText(_("Text der automatischen Antwort"))
        self.auto_reply_text.textChanged.connect(lambda v: self._save_str("auto_reply_text", v))
        auto_form.addRow(_("Auto-Antwort Text"), self.auto_reply_text)

        self.mute_scheduler_enabled = QCheckBox(_("Stumm-Planer aktivieren"))
        self.mute_scheduler_enabled.setChecked(bool(getattr(s, "mute_scheduler_enabled", False)))
        self.mute_scheduler_enabled.stateChanged.connect(lambda v: self._save_bool("mute_scheduler_enabled", v))
        auto_form.addRow("", self.mute_scheduler_enabled)

        mute_from_str = getattr(s, "mute_from_time", "22:00") or "22:00"
        self.mute_from_time = QTimeEdit()
        self.mute_from_time.setDisplayFormat("HH:mm")
        self.mute_from_time.setTime(QTime.fromString(mute_from_str, "HH:mm"))
        self.mute_from_time.timeChanged.connect(
            lambda t: self._save_str("mute_from_time", t.toString("HH:mm"))
        )
        auto_form.addRow(_("Täglich stummschalten von"), self.mute_from_time)

        mute_to_str = getattr(s, "mute_to_time", "07:00") or "07:00"
        self.mute_to_time = QTimeEdit()
        self.mute_to_time.setDisplayFormat("HH:mm")
        self.mute_to_time.setTime(QTime.fromString(mute_to_str, "HH:mm"))
        self.mute_to_time.timeChanged.connect(
            lambda t: self._save_str("mute_to_time", t.toString("HH:mm"))
        )
        auto_form.addRow(_("bis"), self.mute_to_time)
        layout.addWidget(auto_group)

        # --- Chat-Filter ---
        cf_group = QGroupBox(_("Chat-Filter"))
        cf_form = QFormLayout(cf_group)

        self.chat_filter_enabled = QCheckBox(_("Chat-Filter aktivieren"))
        self.chat_filter_enabled.setChecked(bool(getattr(s, "chat_filter_enabled", False)))
        self.chat_filter_enabled.stateChanged.connect(lambda v: self._save_bool("chat_filter_enabled", v))
        cf_form.addRow("", self.chat_filter_enabled)

        self.chat_highlight_keywords = QLineEdit(getattr(s, "chat_highlight_keywords", "") or "")
        self.chat_highlight_keywords.setPlaceholderText(_("Wort1, Wort2, … (Komma-getrennt)"))
        self.chat_highlight_keywords.textChanged.connect(lambda v: self._save_str("chat_highlight_keywords", v))
        cf_form.addRow(_("Schlüsselwörter hervorheben"), self.chat_highlight_keywords)

        self.blocked_phrases = QTextEdit()
        self.blocked_phrases.setPlaceholderText(_("Ein Ausdruck pro Zeile"))
        self.blocked_phrases.setPlainText(getattr(s, "blocked_phrases", "") or "")
        self.blocked_phrases.setFixedHeight(80)
        self.blocked_phrases.textChanged.connect(
            lambda: self._save_str("blocked_phrases", self.blocked_phrases.toPlainText())
        )
        cf_form.addRow(_("Gesperrte Ausdrücke"), self.blocked_phrases)

        self.filter_case_insensitive = QCheckBox(_("Groß-/Kleinschreibung ignorieren"))
        self.filter_case_insensitive.setChecked(bool(getattr(s, "filter_case_insensitive", True)))
        self.filter_case_insensitive.stateChanged.connect(lambda v: self._save_bool("filter_case_insensitive", v))
        cf_form.addRow("", self.filter_case_insensitive)

        self.filter_use_regex = QCheckBox(_("Regex-Muster"))
        self.filter_use_regex.setChecked(bool(getattr(s, "filter_use_regex", False)))
        self.filter_use_regex.stateChanged.connect(lambda v: self._save_bool("filter_use_regex", v))
        cf_form.addRow("", self.filter_use_regex)
        layout.addWidget(cf_group)

        layout.addStretch()
        scroll.setWidget(inner)
        return scroll

    # ------------------------------------------------------------------
    # Aufnahmen
    # ------------------------------------------------------------------

    def _build_recording_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        layout = QVBoxLayout(inner)
        s = self.window.settings_store.settings

        grp = QGroupBox(_("Aufnahmeeinstellungen"))
        form = QFormLayout(grp)

        _FORMAT_LABELS = [
            _("WAV (unkomprimiert)"),
            "MP3 (128 kbps)",
            "MP3 (256 kbps)",
            "OGG Vorbis",
        ]
        _FORMAT_VALUES = ["wav", "mp3_128", "mp3_256", "ogg"]
        self.rec_format = QComboBox()
        self.rec_format.addItems(_FORMAT_LABELS)
        self.rec_format.setAccessibleName(_("Aufnahmeformat"))
        saved_fmt = getattr(s, "rec_format", "wav") or "wav"
        self.rec_format.setCurrentIndex(
            _FORMAT_VALUES.index(saved_fmt) if saved_fmt in _FORMAT_VALUES else 0
        )
        self.rec_format.currentIndexChanged.connect(
            lambda i: self._save_str("rec_format", _FORMAT_VALUES[i])
        )
        form.addRow(_("Aufnahmeformat"), self.rec_format)

        self.rec_bitrate_kbps = QSpinBox()
        self.rec_bitrate_kbps.setRange(64, 320)
        self.rec_bitrate_kbps.setSuffix(" kbps")
        self.rec_bitrate_kbps.setValue(int(getattr(s, "rec_bitrate_kbps", 128) or 128))
        self.rec_bitrate_kbps.setAccessibleName(_("Bitrate für MP3-Aufnahmen in kbps"))
        self.rec_bitrate_kbps.valueChanged.connect(lambda v: self._save_int("rec_bitrate_kbps", v))
        form.addRow(_("Bitrate (MP3)"), self.rec_bitrate_kbps)

        dir_row = QHBoxLayout()
        self.rec_directory = QLineEdit(getattr(s, "rec_directory", "") or "")
        self.rec_directory.setPlaceholderText(_("Aufnahmeverzeichnis …"))
        self.rec_directory.setAccessibleName(_("Aufnahmeverzeichnis"))
        self.rec_directory.textChanged.connect(lambda v: self._save_str("rec_directory", v))
        dir_btn = QPushButton(_("Durchsuchen"))
        dir_btn.clicked.connect(self._browse_rec_directory)
        dir_row.addWidget(self.rec_directory, 1)
        dir_row.addWidget(dir_btn)
        form.addRow(_("Aufnahmeverzeichnis"), dir_row)

        self.rec_filename_pattern = QLineEdit(
            getattr(s, "rec_filename_pattern", "{date}_{server}_{channel}") or "{date}_{server}_{channel}"
        )
        self.rec_filename_pattern.setPlaceholderText("{date}_{server}_{channel}")
        self.rec_filename_pattern.textChanged.connect(lambda v: self._save_str("rec_filename_pattern", v))
        form.addRow(_("Dateinamen-Muster"), self.rec_filename_pattern)

        self.rec_include_self = QCheckBox(_("Eigene Stimme aufnehmen"))
        self.rec_include_self.setChecked(bool(getattr(s, "rec_include_self", True)))
        self.rec_include_self.stateChanged.connect(lambda v: self._save_bool("rec_include_self", v))
        form.addRow("", self.rec_include_self)

        self.rec_auto_start = QCheckBox(_("Bei Verbindung automatisch aufnehmen"))
        self.rec_auto_start.setChecked(bool(getattr(s, "rec_auto_start", False)))
        self.rec_auto_start.stateChanged.connect(lambda v: self._save_bool("rec_auto_start", v))
        form.addRow("", self.rec_auto_start)

        self.rec_segment_minutes = QSpinBox()
        self.rec_segment_minutes.setRange(0, 120)
        self.rec_segment_minutes.setSuffix(_(" min (0 = deaktiviert)"))
        self.rec_segment_minutes.setValue(int(getattr(s, "rec_segment_minutes", 0) or 0))
        self.rec_segment_minutes.valueChanged.connect(lambda v: self._save_int("rec_segment_minutes", v))
        form.addRow(_("Aufnahmen segmentieren alle"), self.rec_segment_minutes)

        self.rec_skip_silence = QCheckBox(_("Stille erkennen und ignorieren"))
        self.rec_skip_silence.setChecked(bool(getattr(s, "rec_skip_silence", False)))
        self.rec_skip_silence.stateChanged.connect(lambda v: self._save_bool("rec_skip_silence", v))
        form.addRow("", self.rec_skip_silence)

        layout.addWidget(grp)

        # Segmentierung
        seg_grp = QGroupBox(_("Aufnahme-Segmentierung (0 = deaktiviert)"))
        seg_form = QFormLayout(seg_grp)

        self.rec_max_size = QSpinBox()
        self.rec_max_size.setRange(0, 10000)
        self.rec_max_size.setSuffix(_(" MB (0 = aus)"))
        self.rec_max_size.setValue(int(getattr(s, "recording_max_size_mb", 0) or 0))
        self.rec_max_size.valueChanged.connect(lambda v: self._save_int("recording_max_size_mb", v))
        seg_form.addRow(_("Max. Dateigröße"), self.rec_max_size)

        self.rec_max_minutes = QSpinBox()
        self.rec_max_minutes.setRange(0, 600)
        self.rec_max_minutes.setSuffix(_(" min (0 = aus)"))
        self.rec_max_minutes.setValue(int(getattr(s, "recording_max_minutes", 0) or 0))
        self.rec_max_minutes.valueChanged.connect(lambda v: self._save_int("recording_max_minutes", v))
        seg_form.addRow(_("Max. Dauer"), self.rec_max_minutes)
        layout.addWidget(seg_grp)

        # Stille-Erkennung
        sil_grp = QGroupBox(_("Stille-Erkennung"))
        sil_form = QFormLayout(sil_grp)

        self.silence_detection_enabled = QCheckBox(_("Stille-Erkennung aktivieren"))
        self.silence_detection_enabled.setChecked(bool(getattr(s, "silence_detection_enabled", False)))
        self.silence_detection_enabled.stateChanged.connect(
            lambda v: self._save_bool("silence_detection_enabled", v)
        )
        sil_form.addRow("", self.silence_detection_enabled)

        self.silence_threshold = QSpinBox()
        self.silence_threshold.setRange(0, 100)
        self.silence_threshold.setSuffix(" %")
        self.silence_threshold.setValue(int(getattr(s, "silence_detection_threshold_pct", 5) or 5))
        self.silence_threshold.valueChanged.connect(
            lambda v: self._save_int("silence_detection_threshold_pct", v)
        )
        sil_form.addRow(_("Schwellenwert"), self.silence_threshold)

        self.silence_timeout = QSpinBox()
        self.silence_timeout.setRange(0, 300)
        self.silence_timeout.setSuffix(" s")
        self.silence_timeout.setValue(int(getattr(s, "silence_detection_timeout_sec", 3) or 3))
        self.silence_timeout.valueChanged.connect(
            lambda v: self._save_int("silence_detection_timeout_sec", v)
        )
        sil_form.addRow(_("Timeout"), self.silence_timeout)
        layout.addWidget(sil_grp)

        layout.addStretch()
        scroll.setWidget(inner)
        return scroll

    def _browse_rec_directory(self) -> None:
        path = QFileDialog.getExistingDirectory(self, _("Aufnahmeverzeichnis wählen"), "")
        if path:
            self.rec_directory.setText(path)

    # ------------------------------------------------------------------
    # Audio-Extras (Noise Gate, PTT-Limit, VU-Alarm)
    # ------------------------------------------------------------------

    def _build_audio_extras_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        layout = QVBoxLayout(inner)
        s = self.window.settings_store.settings

        # Noise Gate
        ng_grp = QGroupBox(_("Noise Gate / Rauschunterdrückung"))
        ng_form = QFormLayout(ng_grp)

        self.noise_gate_enabled = QCheckBox(_("Noise Gate aktivieren"))
        self.noise_gate_enabled.setChecked(bool(getattr(s, "noise_gate_enabled", False)))
        self.noise_gate_enabled.stateChanged.connect(self._on_noise_gate_changed)
        ng_form.addRow("", self.noise_gate_enabled)

        self.noise_gate_threshold = QSpinBox()
        self.noise_gate_threshold.setRange(0, 10000)
        self.noise_gate_threshold.setValue(int(getattr(s, "noise_gate_threshold", 0) or 0))
        self.noise_gate_threshold.valueChanged.connect(self._on_noise_gate_changed)
        ng_form.addRow(_("Schwellenwert (0–10000)"), self.noise_gate_threshold)
        layout.addWidget(ng_grp)

        # PTT-Zeitlimit
        ptt_grp = QGroupBox(_("PTT-Zeitlimit"))
        ptt_form = QFormLayout(ptt_grp)

        self.ptt_max_seconds = QSpinBox()
        self.ptt_max_seconds.setRange(0, 600)
        self.ptt_max_seconds.setSuffix(_(" s (0 = aus)"))
        self.ptt_max_seconds.setValue(int(getattr(s, "ptt_max_seconds", 0) or 0))
        self.ptt_max_seconds.valueChanged.connect(lambda v: self._save_int("ptt_max_seconds", v))
        ptt_form.addRow(_("PTT-Zeitlimit"), self.ptt_max_seconds)
        layout.addWidget(ptt_grp)

        # VU-Pegel-Alarm
        vu_grp = QGroupBox(_("VU-Pegel-Alarm"))
        vu_form = QFormLayout(vu_grp)

        self.vu_alert_enabled = QCheckBox(_("VU-Alarm aktivieren (bei zu hohem Eingangspegel)"))
        self.vu_alert_enabled.setChecked(bool(getattr(s, "vu_alert_enabled", False)))
        self.vu_alert_enabled.stateChanged.connect(lambda v: self._save_bool("vu_alert_enabled", v))
        vu_form.addRow("", self.vu_alert_enabled)

        self.vu_alert_threshold = QSpinBox()
        self.vu_alert_threshold.setRange(0, 100)
        self.vu_alert_threshold.setSuffix(" %")
        self.vu_alert_threshold.setValue(int(getattr(s, "vu_alert_threshold", 90) or 90))
        self.vu_alert_threshold.valueChanged.connect(lambda v: self._save_int("vu_alert_threshold", v))
        vu_form.addRow(_("Schwellenwert"), self.vu_alert_threshold)
        layout.addWidget(vu_grp)

        layout.addStretch()
        scroll.setWidget(inner)
        return scroll

    def _on_noise_gate_changed(self) -> None:
        enabled = self.noise_gate_enabled.isChecked()
        threshold = self.noise_gate_threshold.value()
        self._save_bool("noise_gate_enabled", enabled)
        self._save_int("noise_gate_threshold", threshold)
        try:
            self.window._apply_noise_gate()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Nutzer-Lautstärken
    # ------------------------------------------------------------------

    def _build_user_volumes_tab(self) -> QWidget:
        from PySide6.QtWidgets import QListWidget
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        layout = QVBoxLayout(inner)
        s = self.window.settings_store.settings

        grp = QGroupBox(_("Gespeicherte Nutzer-Lautstärken"))
        grp_layout = QVBoxLayout(grp)

        self._vol_preset_list = QListWidget()
        self._vol_preset_list.setAccessibleName(_("Gespeicherte Nutzer-Lautstärken"))
        self._vol_preset_list.setMinimumHeight(180)
        grp_layout.addWidget(self._vol_preset_list, 1)

        self._vol_preset_usernames: list = []
        self._refresh_volume_presets_list()

        btn_row = QHBoxLayout()
        del_btn = QPushButton(_("&Entfernen"))
        del_btn.clicked.connect(self._on_del_volume_preset)
        clear_btn = QPushButton(_("&Alle löschen"))
        clear_btn.clicked.connect(self._on_clear_volume_presets)
        btn_row.addWidget(del_btn)
        btn_row.addWidget(clear_btn)
        btn_row.addStretch()
        grp_layout.addLayout(btn_row)
        layout.addWidget(grp)

        layout.addStretch()
        scroll.setWidget(inner)
        return scroll

    def _refresh_volume_presets_list(self) -> None:
        try:
            presets = getattr(self.window.settings_store.settings, "user_volume_presets", {}) or {}
            self._vol_preset_usernames = sorted(presets.keys())
            self._vol_preset_list.clear()
            for user in self._vol_preset_usernames:
                self._vol_preset_list.addItem(f"{user}: {presets[user]}")
        except Exception:
            pass

    def _on_del_volume_preset(self) -> None:
        row = self._vol_preset_list.currentRow()
        if row < 0 or row >= len(self._vol_preset_usernames):
            self.window.set_status(_("Bitte einen Eintrag auswählen"))
            return
        username = self._vol_preset_usernames[row]
        presets = getattr(self.window.settings_store.settings, "user_volume_presets", {}) or {}
        presets.pop(username, None)
        self.window.settings_store.settings.user_volume_presets = presets
        self.window.settings_store.save()
        self._refresh_volume_presets_list()
        self.window.set_status(f"Lautstärke-Vorlage für {username} gelöscht")

    def _on_clear_volume_presets(self) -> None:
        from PySide6.QtWidgets import QMessageBox
        answer = QMessageBox.question(
            self, _("Alle löschen"), _("Alle gespeicherten Nutzer-Lautstärken löschen?")
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.window.settings_store.settings.user_volume_presets = {}
            self.window.settings_store.save()
            self._refresh_volume_presets_list()
            self.window.set_status(_("Alle Lautstärke-Vorlagen gelöscht"))

    # ------------------------------------------------------------------
    # Braille
    # ------------------------------------------------------------------

    def _build_braille_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        layout = QVBoxLayout(inner)
        s = self.window.settings_store.settings

        grp = QGroupBox(_("Braillezeilen-Einstellungen"))
        form = QFormLayout(grp)

        self.braille_enabled = QCheckBox(_("Braillezeile aktiv"))
        self.braille_enabled.setChecked(bool(getattr(s, "braille_enabled", False)))
        self.braille_enabled.stateChanged.connect(lambda v: self._save_bool("braille_enabled", v))
        form.addRow("", self.braille_enabled)

        _VERBOSITY_LABELS = [_("Kompakt"), _("Normal"), _("Ausführlich")]
        _VERBOSITY_VALUES = ["compact", "normal", "verbose"]
        self.braille_verbosity = QComboBox()
        self.braille_verbosity.setAccessibleName(_("Braille-Ausführlichkeit"))
        self.braille_verbosity.addItems(_VERBOSITY_LABELS)
        saved_verb = getattr(s, "braille_verbosity", "normal") or "normal"
        self.braille_verbosity.setCurrentIndex(
            _VERBOSITY_VALUES.index(saved_verb) if saved_verb in _VERBOSITY_VALUES else 1
        )
        self.braille_verbosity.currentIndexChanged.connect(
            lambda i: self._save_str("braille_verbosity", _VERBOSITY_VALUES[i])
        )
        form.addRow(_("Ausführlichkeit"), self.braille_verbosity)

        self.braille_announce_channel = QCheckBox(_("Kanalwechsel ansagen"))
        self.braille_announce_channel.setChecked(bool(getattr(s, "braille_announce_channel", True)))
        self.braille_announce_channel.stateChanged.connect(lambda v: self._save_bool("braille_announce_channel", v))
        form.addRow("", self.braille_announce_channel)

        self.braille_announce_user = QCheckBox(_("Nutzerwechsel ansagen"))
        self.braille_announce_user.setChecked(bool(getattr(s, "braille_announce_user", True)))
        self.braille_announce_user.stateChanged.connect(lambda v: self._save_bool("braille_announce_user", v))
        form.addRow("", self.braille_announce_user)

        self.braille_read_messages = QCheckBox(_("Nachrichten vorlesen"))
        self.braille_read_messages.setChecked(bool(getattr(s, "braille_read_messages", True)))
        self.braille_read_messages.stateChanged.connect(lambda v: self._save_bool("braille_read_messages", v))
        form.addRow("", self.braille_read_messages)

        self.braille_max_msg_len = QSpinBox()
        self.braille_max_msg_len.setRange(20, 200)
        self.braille_max_msg_len.setSuffix(_(" Zeichen"))
        self.braille_max_msg_len.setValue(int(getattr(s, "braille_max_msg_len", 80) or 80))
        self.braille_max_msg_len.valueChanged.connect(lambda v: self._save_int("braille_max_msg_len", v))
        form.addRow(_("Maximale Nachrichtenlänge"), self.braille_max_msg_len)

        layout.addWidget(grp)
        layout.addStretch()
        scroll.setWidget(inner)
        return scroll

    # ------------------------------------------------------------------
    # KI & Integration
    # ------------------------------------------------------------------

    def _build_ki_tab(self) -> QWidget:
        import threading
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        layout = QVBoxLayout(inner)
        s = self.window.settings_store.settings

        # ── ElevenLabs ──────────────────────────────────────────────────────
        el_group = QGroupBox(_("ElevenLabs Text-to-Speech"))
        el_layout = QVBoxLayout(el_group)
        el_form = QFormLayout()

        self.elevenlabs_key = QLineEdit(getattr(s, "elevenlabs_api_key", "") or "")
        self.elevenlabs_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.elevenlabs_key.setPlaceholderText(_("API-Key von elevenlabs.io"))
        self.elevenlabs_key.setAccessibleName(_("ElevenLabs API-Schlüssel"))
        def _on_elevenlabs_key_changed(v: str) -> None:
            self._save_str("elevenlabs_api_key", v)
            if hasattr(self.window, "_update_speak_tab"):
                self.window._update_speak_tab(v)
        self.elevenlabs_key.textChanged.connect(_on_elevenlabs_key_changed)
        el_form.addRow(_("API-Schlüssel:"), self.elevenlabs_key)
        el_layout.addLayout(el_form)

        el_btn_row = QHBoxLayout()
        self._el_verify_btn = QPushButton(_("Schlüssel prüfen"))
        self._el_verify_btn.setAccessibleName(_("ElevenLabs Schlüssel prüfen"))
        self._el_status = QLabel("")
        self._el_status.setAccessibleName(_("ElevenLabs Schlüssel-Status"))

        def _verify_elevenlabs():
            key = self.elevenlabs_key.text().strip()
            if not key:
                self._el_status.setText(_("Kein Schlüssel eingegeben."))
                return
            self._el_verify_btn.setEnabled(False)
            self._el_status.setText(_("Prüfe…"))
            def worker():
                try:
                    import requests as _req
                    resp = _req.get("https://api.elevenlabs.io/v1/user",
                                   headers={"xi-api-key": key}, timeout=10)
                    if resp.status_code == 200:
                        data = resp.json()
                        name = (data.get("first_name") or "").strip()
                        tier = (data.get("subscription") or {}).get("tier") or ""
                        lbl = f"✓ Gültig{(' – ' + name) if name else ''}{(' (' + tier + ')') if tier else ''}"
                    elif resp.status_code == 401:
                        lbl = "✗ Ungültig (401 Unauthorized)"
                    else:
                        lbl = f"✗ Fehler: HTTP {resp.status_code}"
                except Exception as exc:
                    lbl = f"✗ Fehler: {exc}"
                from PySide6.QtCore import QMetaObject, Qt
                self._el_verify_btn.setEnabled(True)
                self._el_status.setText(lbl)
            threading.Thread(target=worker, daemon=True).start()

        self._el_verify_btn.clicked.connect(_verify_elevenlabs)
        el_btn_row.addWidget(self._el_verify_btn)
        el_btn_row.addWidget(self._el_status, 1)
        el_layout.addLayout(el_btn_row)
        layout.addWidget(el_group)

        # ── Claude (Anthropic) ───────────────────────────────────────────────
        claude_group = QGroupBox(_("Claude KI (Anthropic)"))
        claude_layout = QVBoxLayout(claude_group)
        claude_form = QFormLayout()

        self.claude_key = QLineEdit(getattr(s, "claude_api_key", "") or "")
        self.claude_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.claude_key.setPlaceholderText(_("API-Key von console.anthropic.com"))
        self.claude_key.setAccessibleName(_("Claude API-Schlüssel"))
        self.claude_key.textChanged.connect(lambda v: self._save_str("claude_api_key", v))
        claude_form.addRow(_("API-Schlüssel:"), self.claude_key)
        claude_layout.addLayout(claude_form)

        claude_btn_row = QHBoxLayout()
        self._claude_verify_btn = QPushButton(_("Schlüssel prüfen"))
        self._claude_verify_btn.setAccessibleName(_("Claude Schlüssel prüfen"))
        self._claude_status = QLabel("")
        self._claude_status.setAccessibleName(_("Claude Schlüssel-Status"))

        def _verify_claude():
            key = self.claude_key.text().strip()
            if not key:
                self._claude_status.setText(_("Kein Schlüssel eingegeben."))
                return
            self._claude_verify_btn.setEnabled(False)
            self._claude_status.setText(_("Prüfe…"))
            def worker():
                try:
                    import anthropic
                    client = anthropic.Anthropic(api_key=key)
                    count = len(list(client.models.list().data))
                    lbl = f"✓ Gültig ({count} Modelle verfügbar)"
                except Exception as exc:
                    lbl = f"✗ {type(exc).__name__}: {str(exc)[:60]}"
                self._claude_verify_btn.setEnabled(True)
                self._claude_status.setText(lbl)
            threading.Thread(target=worker, daemon=True).start()

        self._claude_verify_btn.clicked.connect(_verify_claude)
        claude_btn_row.addWidget(self._claude_verify_btn)
        claude_btn_row.addWidget(self._claude_status, 1)
        claude_layout.addLayout(claude_btn_row)
        layout.addWidget(claude_group)

        # ── Google Gemini ────────────────────────────────────────────────────
        gemini_group = QGroupBox(_("Google Gemini KI"))
        gemini_layout = QVBoxLayout(gemini_group)
        gemini_form = QFormLayout()

        self.gemini_key = QLineEdit(getattr(s, "gemini_api_key", "") or "")
        self.gemini_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.gemini_key.setPlaceholderText(_("API-Key von aistudio.google.com/app/apikey"))
        self.gemini_key.setAccessibleName(_("Gemini API-Schlüssel"))
        self.gemini_key.textChanged.connect(lambda v: self._save_str("gemini_api_key", v))
        gemini_form.addRow(_("API-Schlüssel:"), self.gemini_key)
        gemini_layout.addLayout(gemini_form)

        gemini_btn_row = QHBoxLayout()
        self._gemini_verify_btn = QPushButton(_("API-Key prüfen"))
        self._gemini_verify_btn.setAccessibleName(_("Gemini API-Key prüfen"))
        self._gemini_status = QLabel("")
        self._gemini_status.setAccessibleName(_("Gemini API-Key-Status"))

        def _verify_gemini():
            key = self.gemini_key.text().strip()
            if not key:
                self._gemini_status.setText(_("Kein Schlüssel eingegeben."))
                return
            self._gemini_verify_btn.setEnabled(False)
            self._gemini_status.setText(_("Prüfe…"))
            def worker():
                try:
                    import google.genai as genai
                    client = genai.Client(api_key=key)
                    models = list(client.models.list())
                    lbl = f"✓ Gültig ({len(models)} Modelle verfügbar)"
                except Exception as exc:
                    lbl = f"✗ {type(exc).__name__}: {str(exc)[:60]}"
                self._gemini_verify_btn.setEnabled(True)
                self._gemini_status.setText(lbl)
            threading.Thread(target=worker, daemon=True).start()

        self._gemini_verify_btn.clicked.connect(_verify_gemini)
        gemini_btn_row.addWidget(self._gemini_verify_btn)
        gemini_btn_row.addWidget(self._gemini_status, 1)
        gemini_layout.addLayout(gemini_btn_row)
        layout.addWidget(gemini_group)

        http_group = QGroupBox(_("HTTP-Companion-API"))
        http_form = QFormLayout(http_group)

        self.http_api_enabled = QCheckBox(_("HTTP-API aktivieren"))
        self.http_api_enabled.setChecked(bool(getattr(s, "http_api_enabled", False)))
        self.http_api_enabled.stateChanged.connect(lambda v: self._save_bool("http_api_enabled", v))
        http_form.addRow("", self.http_api_enabled)

        self.http_api_port = QSpinBox()
        self.http_api_port.setRange(1024, 65535)
        self.http_api_port.setValue(int(getattr(s, "http_api_port", 8765) or 8765))
        self.http_api_port.valueChanged.connect(lambda v: self._save_int("http_api_port", v))
        http_form.addRow(_("Port"), self.http_api_port)
        layout.addWidget(http_group)

        layout.addStretch()
        scroll.setWidget(inner)
        return scroll

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _save_bool(self, key: str, value) -> None:
        try:
            setattr(self.window.settings_store.settings, key, bool(value))
            self.window.settings_store.save()
        except Exception:
            pass

    def _save_int(self, key: str, value: int) -> None:
        try:
            setattr(self.window.settings_store.settings, key, int(value))
            self.window.settings_store.save()
        except Exception:
            pass

    def _save_str(self, key: str, value: str) -> None:
        try:
            setattr(self.window.settings_store.settings, key, value)
            self.window.settings_store.save()
        except Exception:
            pass

    def _browse_sound(self, field: QLineEdit) -> None:
        path, _flt = QFileDialog.getOpenFileName(
            self, _("Sound-Datei wählen"), "",
            _("WAV-Dateien (*.wav);;Alle Dateien (*.*)")
        )
        if path:
            field.setText(path)

    def _on_lang_changed(self, idx: int) -> None:
        codes = getattr(self._lang_combo, "_lang_codes", ["de", "en", "fr", "es"])
        lang = codes[idx] if 0 <= idx < len(codes) else "de"
        self._save_str("app_language", lang)
        try:
            from i18n import set_language
            set_language(lang)
        except Exception:
            pass

    def _on_always_on_top(self, value: int) -> None:
        self._save_bool("always_on_top", value)
        try:
            from PySide6.QtCore import Qt
            w = self.window
            flags = w.windowFlags()
            if value:
                w.setWindowFlags(flags | Qt.WindowType.WindowStaysOnTopHint)
            else:
                w.setWindowFlags(flags & ~Qt.WindowType.WindowStaysOnTopHint)
            w.show()
        except Exception:
            pass
