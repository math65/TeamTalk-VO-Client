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

        self.inner.addTab(self._build_general_tab(), "Allgemein")
        self.inner.addTab(self._build_connection_tab(), "Verbindung")
        self.inner.addTab(self._build_sound_events_tab(), "Sound-Ereignisse")
        self.inner.addTab(self._build_recording_tab(), "Aufnahmen")
        self.inner.addTab(self.audio_tab, "Audio")
        self.inner.addTab(self._build_audio_extras_tab(), "Audio-Extras")
        self.inner.addTab(self.video_tab, "Video")
        self.inner.addTab(self.shortcuts_tab, "Tastenkürzel")
        self.inner.addTab(self.system_tab, "TTS")
        self.inner.addTab(self._build_chat_tab(), "Chat & Automation")
        self.inner.addTab(self._build_ki_tab(), "KI & Integration")
        self.inner.addTab(self._build_user_volumes_tab(), "Nutzer-Lautstärken")
        self.inner.addTab(self._build_braille_tab(), "Braille")

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
        disp_group = QGroupBox("Darstellung & Verhalten")
        disp_form = QFormLayout(disp_group)

        self.start_minimized = QCheckBox("Minimiert starten")
        self.start_minimized.setChecked(bool(getattr(s, "start_minimized", False)))
        self.start_minimized.stateChanged.connect(lambda v: self._save_bool("start_minimized", v))
        disp_form.addRow("", self.start_minimized)

        self.close_to_tray = QCheckBox("In Taskleiste minimieren beim Schließen")
        self.close_to_tray.setChecked(bool(getattr(s, "close_to_tray", True)))
        self.close_to_tray.stateChanged.connect(lambda v: self._save_bool("close_to_tray", v))
        disp_form.addRow("", self.close_to_tray)

        self.always_on_top = QCheckBox("Immer im Vordergrund")
        self.always_on_top.setChecked(bool(getattr(s, "always_on_top", False)))
        self.always_on_top.stateChanged.connect(self._on_always_on_top)
        disp_form.addRow("", self.always_on_top)

        self.show_timestamps = QCheckBox("Zeitstempel im Chat anzeigen")
        self.show_timestamps.setChecked(bool(getattr(s, "show_timestamps", True)))
        self.show_timestamps.stateChanged.connect(lambda v: self._save_bool("show_timestamps", v))
        disp_form.addRow("", self.show_timestamps)

        self.desktop_notifications = QCheckBox("Desktop-Benachrichtigungen")
        self.desktop_notifications.setChecked(bool(getattr(s, "desktop_notifications", True)))
        self.desktop_notifications.stateChanged.connect(lambda v: self._save_bool("desktop_notifications", v))
        disp_form.addRow("", self.desktop_notifications)

        self.sounds_enabled = QCheckBox("Ereignis-Sounds aktivieren")
        self.sounds_enabled.setChecked(bool(getattr(s, "sounds_enabled", True)))
        self.sounds_enabled.stateChanged.connect(lambda v: self._save_bool("sounds_enabled", v))
        disp_form.addRow("", self.sounds_enabled)

        self.braille_compact = QCheckBox("Braille-Kompaktmodus")
        self.braille_compact.setChecked(bool(getattr(s, "braille_compact", False)))
        self.braille_compact.stateChanged.connect(lambda v: self._save_bool("braille_compact", v))
        disp_form.addRow("", self.braille_compact)

        lang_combo = QComboBox()
        lang_combo.addItems(["Deutsch", "English"])
        saved_lang = getattr(s, "app_language", "de") or "de"
        lang_combo.setCurrentIndex(0 if saved_lang == "de" else 1)
        lang_combo.currentIndexChanged.connect(self._on_lang_changed)
        disp_form.addRow("Sprache", lang_combo)

        layout.addWidget(disp_group)

        # --- Abwesenheits-Timer ---
        away_group = QGroupBox("Abwesenheit")
        away_form = QFormLayout(away_group)
        self.away_timer = QSpinBox()
        self.away_timer.setRange(0, 120)
        self.away_timer.setSuffix(" min (0 = aus)")
        self.away_timer.setValue(int(getattr(s, "away_timer_minutes", 0) or 0))
        self.away_timer.valueChanged.connect(lambda v: self._save_int("away_timer_minutes", v))
        away_form.addRow("Weg-Modus nach", self.away_timer)

        self.away_status = QLineEdit(getattr(s, "away_status_message", "Bin kurz weg") or "Bin kurz weg")
        self.away_status.setPlaceholderText("Status-Nachricht bei Abwesenheit")
        self.away_status.textChanged.connect(lambda v: self._save_str("away_status_message", v))
        away_form.addRow("Weg-Status", self.away_status)
        layout.addWidget(away_group)

        # --- Chat-Filter ---
        filter_group = QGroupBox("Chat-Filter")
        filter_form = QFormLayout(filter_group)

        self.highlight_keywords = QLineEdit(getattr(s, "highlight_keywords", "") or "")
        self.highlight_keywords.setPlaceholderText("Wort1, Wort2, … (Komma-getrennt)")
        self.highlight_keywords.textChanged.connect(lambda v: self._save_str("highlight_keywords", v))
        filter_form.addRow("Hervorheben", self.highlight_keywords)

        self.muted_users = QLineEdit(getattr(s, "muted_users", "") or "")
        self.muted_users.setPlaceholderText("Benutzername1, Benutzername2, …")
        self.muted_users.textChanged.connect(lambda v: self._save_str("muted_users", v))
        filter_form.addRow("Nutzer stummschalten", self.muted_users)
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
        rc_group = QGroupBox("Automatisch neu verbinden")
        rc_form = QFormLayout(rc_group)

        self.auto_reconnect = QCheckBox("Automatisch neu verbinden")
        self.auto_reconnect.setChecked(bool(getattr(s, "auto_reconnect_enabled", True)))
        self.auto_reconnect.stateChanged.connect(lambda v: self._save_bool("auto_reconnect_enabled", v))
        rc_form.addRow("", self.auto_reconnect)

        self.reconnect_delay = QSpinBox()
        self.reconnect_delay.setRange(5, 300)
        self.reconnect_delay.setSuffix(" s")
        self.reconnect_delay.setValue(int(getattr(s, "reconnect_delay_seconds", 10) or 10))
        self.reconnect_delay.valueChanged.connect(lambda v: self._save_int("reconnect_delay_seconds", v))
        rc_form.addRow("Wartezeit", self.reconnect_delay)

        self.reconnect_max = QSpinBox()
        self.reconnect_max.setRange(0, 9999)
        self.reconnect_max.setSuffix(" (0 = unbegrenzt)")
        self.reconnect_max.setValue(int(getattr(s, "reconnect_max_attempts", 0) or 0))
        self.reconnect_max.valueChanged.connect(lambda v: self._save_int("reconnect_max_attempts", v))
        rc_form.addRow("Max. Versuche", self.reconnect_max)
        layout.addWidget(rc_group)

        # Standard-Abonnements
        sub_group = QGroupBox("Standard-Abonnements beim Verbinden")
        sub_layout = QVBoxLayout(sub_group)
        self._sub_checks: dict = {}
        for label, key in _SUBSCRIPTIONS:
            cb = QCheckBox(label)
            cb.setChecked(bool(getattr(s, key, True)))
            cb.stateChanged.connect(lambda v, k=key: self._save_bool(k, v))
            sub_layout.addWidget(cb)
            self._sub_checks[key] = cb
        layout.addWidget(sub_group)

        # Port-Bindung
        port_group = QGroupBox("Port-Bindung (0 = automatisch)")
        port_form = QFormLayout(port_group)

        self.tcp_bind_port = QSpinBox()
        self.tcp_bind_port.setRange(0, 65535)
        self.tcp_bind_port.setValue(int(getattr(s, "tcp_bind_port", 0) or 0))
        self.tcp_bind_port.valueChanged.connect(lambda v: self._save_int("tcp_bind_port", v))
        port_form.addRow("TCP-Port", self.tcp_bind_port)

        self.udp_bind_port = QSpinBox()
        self.udp_bind_port.setRange(0, 65535)
        self.udp_bind_port.setValue(int(getattr(s, "udp_bind_port", 0) or 0))
        self.udp_bind_port.valueChanged.connect(lambda v: self._save_int("udp_bind_port", v))
        port_form.addRow("UDP-Port", self.udp_bind_port)
        layout.addWidget(port_group)

        # Verbindungsqualität
        quality_group = QGroupBox("Verbindungsqualität")
        quality_form = QFormLayout(quality_group)

        self.announce_bad_conn = QCheckBox("Schlechte Verbindung ankündigen")
        self.announce_bad_conn.setChecked(bool(getattr(s, "announce_bad_connection", False)))
        self.announce_bad_conn.stateChanged.connect(lambda v: self._save_bool("announce_bad_connection", v))
        quality_form.addRow("", self.announce_bad_conn)

        self.ping_threshold = QSpinBox()
        self.ping_threshold.setRange(50, 9999)
        self.ping_threshold.setSuffix(" ms")
        self.ping_threshold.setValue(int(getattr(s, "ping_threshold_ms", 500) or 500))
        self.ping_threshold.valueChanged.connect(lambda v: self._save_int("ping_threshold_ms", v))
        quality_form.addRow("Ping-Schwellwert", self.ping_threshold)
        layout.addWidget(quality_group)

        # BearWare Web-Login
        bw_group = QGroupBox("BearWare Web-Login")
        bw_form = QFormLayout(bw_group)

        self.bearware_enabled = QCheckBox("BearWare Web-Login verwenden")
        self.bearware_enabled.setChecked(bool(getattr(s, "bearware_login", False)))
        self.bearware_enabled.stateChanged.connect(lambda v: self._save_bool("bearware_login", v))
        bw_form.addRow("", self.bearware_enabled)

        self.bearware_username = QLineEdit(getattr(s, "bearware_username", "") or "")
        self.bearware_username.setPlaceholderText("BearWare-Benutzername")
        self.bearware_username.textChanged.connect(lambda v: self._save_str("bearware_username", v))
        bw_form.addRow("Benutzername", self.bearware_username)

        self.bearware_password = QLineEdit(getattr(s, "bearware_password", "") or "")
        self.bearware_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.bearware_password.setPlaceholderText("BearWare-Passwort")
        self.bearware_password.textChanged.connect(lambda v: self._save_str("bearware_password", v))
        bw_form.addRow("Passwort", self.bearware_password)
        layout.addWidget(bw_group)

        layout.addStretch()
        scroll.setWidget(inner)
        return scroll

    # ------------------------------------------------------------------
    # Sound-Ereignisse
    # ------------------------------------------------------------------

    def _build_sound_events_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        layout = QVBoxLayout(inner)
        s = self.window.settings_store.settings

        evt_group = QGroupBox("Sound-Ereignisse (WAV-Dateipfade)")
        evt_layout = QVBoxLayout(evt_group)
        self._sound_event_rows: dict = {}

        for label, key in _SOUND_EVENTS:
            row = QHBoxLayout()
            lbl = QLabel(label)
            lbl.setMinimumWidth(230)
            row.addWidget(lbl)
            field = QLineEdit()
            saved = getattr(s, f"sound_{key}", "") or ""
            field.setText(saved)
            field.setPlaceholderText("Leer = Standard")
            field.textChanged.connect(lambda v, k=key: self._save_str(f"sound_{k}", v))
            browse_btn = QPushButton("…")
            browse_btn.setFixedWidth(30)
            browse_btn.clicked.connect(lambda _, f=field: self._browse_sound(f))
            row.addWidget(field, 1)
            row.addWidget(browse_btn)
            evt_layout.addLayout(row)
            self._sound_event_rows[key] = field

        layout.addWidget(evt_group)
        layout.addStretch()
        scroll.setWidget(inner)
        return scroll

    # ------------------------------------------------------------------
    # Chat & Automation
    # ------------------------------------------------------------------

    def _build_chat_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        layout = QVBoxLayout(inner)
        s = self.window.settings_store.settings

        chat_group = QGroupBox("Chat-Verlauf")
        chat_form = QFormLayout(chat_group)

        self.save_chat_history = QCheckBox("Kanal-Chat-Verlauf speichern")
        self.save_chat_history.setChecked(bool(getattr(s, "save_chat_history", True)))
        self.save_chat_history.stateChanged.connect(lambda v: self._save_bool("save_chat_history", v))
        chat_form.addRow("", self.save_chat_history)

        self.save_private_chat = QCheckBox("Privatnachrichten-Verlauf speichern")
        self.save_private_chat.setChecked(bool(getattr(s, "save_private_chat_history", True)))
        self.save_private_chat.stateChanged.connect(lambda v: self._save_bool("save_private_chat_history", v))
        chat_form.addRow("", self.save_private_chat)

        self.auto_join_last = QCheckBox("Zuletzt besuchten Kanal automatisch betreten")
        self.auto_join_last.setChecked(bool(getattr(s, "auto_join_last_channel", False)))
        self.auto_join_last.stateChanged.connect(lambda v: self._save_bool("auto_join_last_channel", v))
        chat_form.addRow("", self.auto_join_last)
        layout.addWidget(chat_group)

        trans_group = QGroupBox("Chat-Übersetzung")
        trans_form = QFormLayout(trans_group)

        self.translation_enabled = QCheckBox("Übersetzung aktivieren")
        self.translation_enabled.setChecked(bool(getattr(s, "translation_enabled", False)))
        self.translation_enabled.stateChanged.connect(lambda v: self._save_bool("translation_enabled", v))
        trans_form.addRow("", self.translation_enabled)

        self.translation_target_lang = QLineEdit(getattr(s, "translation_target_lang", "de") or "de")
        self.translation_target_lang.setPlaceholderText("de / en / fr / …")
        self.translation_target_lang.textChanged.connect(lambda v: self._save_str("translation_target_lang", v))
        trans_form.addRow("Zielsprache", self.translation_target_lang)
        layout.addWidget(trans_group)

        auto_group = QGroupBox("Automation")
        auto_form = QFormLayout(auto_group)

        self.ai_summary_enabled = QCheckBox("KI-Kanal-Zusammenfassung aktivieren")
        self.ai_summary_enabled.setChecked(bool(getattr(s, "ai_summary_enabled", False)))
        self.ai_summary_enabled.stateChanged.connect(lambda v: self._save_bool("ai_summary_enabled", v))
        auto_form.addRow("", self.ai_summary_enabled)

        self.auto_reply_enabled = QCheckBox("Auto-Antwort aktivieren")
        self.auto_reply_enabled.setChecked(bool(getattr(s, "auto_reply_enabled", False)))
        self.auto_reply_enabled.stateChanged.connect(lambda v: self._save_bool("auto_reply_enabled", v))
        auto_form.addRow("", self.auto_reply_enabled)

        self.auto_reply_text = QLineEdit(getattr(s, "auto_reply_text", "") or "")
        self.auto_reply_text.setPlaceholderText("Text der automatischen Antwort")
        self.auto_reply_text.textChanged.connect(lambda v: self._save_str("auto_reply_text", v))
        auto_form.addRow("Auto-Antwort Text", self.auto_reply_text)

        self.mute_scheduler_enabled = QCheckBox("Stumm-Planer aktivieren")
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
        auto_form.addRow("Täglich stummschalten von", self.mute_from_time)

        mute_to_str = getattr(s, "mute_to_time", "07:00") or "07:00"
        self.mute_to_time = QTimeEdit()
        self.mute_to_time.setDisplayFormat("HH:mm")
        self.mute_to_time.setTime(QTime.fromString(mute_to_str, "HH:mm"))
        self.mute_to_time.timeChanged.connect(
            lambda t: self._save_str("mute_to_time", t.toString("HH:mm"))
        )
        auto_form.addRow("bis", self.mute_to_time)
        layout.addWidget(auto_group)

        # --- Chat-Filter ---
        cf_group = QGroupBox("Chat-Filter")
        cf_form = QFormLayout(cf_group)

        self.chat_filter_enabled = QCheckBox("Chat-Filter aktivieren")
        self.chat_filter_enabled.setChecked(bool(getattr(s, "chat_filter_enabled", False)))
        self.chat_filter_enabled.stateChanged.connect(lambda v: self._save_bool("chat_filter_enabled", v))
        cf_form.addRow("", self.chat_filter_enabled)

        self.chat_highlight_keywords = QLineEdit(getattr(s, "chat_highlight_keywords", "") or "")
        self.chat_highlight_keywords.setPlaceholderText("Wort1, Wort2, … (Komma-getrennt)")
        self.chat_highlight_keywords.textChanged.connect(lambda v: self._save_str("chat_highlight_keywords", v))
        cf_form.addRow("Schlüsselwörter hervorheben", self.chat_highlight_keywords)

        self.blocked_phrases = QTextEdit()
        self.blocked_phrases.setPlaceholderText("Ein Ausdruck pro Zeile")
        self.blocked_phrases.setPlainText(getattr(s, "blocked_phrases", "") or "")
        self.blocked_phrases.setFixedHeight(80)
        self.blocked_phrases.textChanged.connect(
            lambda: self._save_str("blocked_phrases", self.blocked_phrases.toPlainText())
        )
        cf_form.addRow("Gesperrte Ausdrücke", self.blocked_phrases)

        self.filter_case_insensitive = QCheckBox("Groß-/Kleinschreibung ignorieren")
        self.filter_case_insensitive.setChecked(bool(getattr(s, "filter_case_insensitive", True)))
        self.filter_case_insensitive.stateChanged.connect(lambda v: self._save_bool("filter_case_insensitive", v))
        cf_form.addRow("", self.filter_case_insensitive)

        self.filter_use_regex = QCheckBox("Regex-Muster")
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

        grp = QGroupBox("Aufnahmeeinstellungen")
        form = QFormLayout(grp)

        _FORMAT_LABELS = [
            "WAV (unkomprimiert)",
            "MP3 (128 kbps)",
            "MP3 (256 kbps)",
            "OGG Vorbis",
        ]
        _FORMAT_VALUES = ["wav", "mp3_128", "mp3_256", "ogg"]
        self.rec_format = QComboBox()
        self.rec_format.addItems(_FORMAT_LABELS)
        saved_fmt = getattr(s, "rec_format", "wav") or "wav"
        self.rec_format.setCurrentIndex(
            _FORMAT_VALUES.index(saved_fmt) if saved_fmt in _FORMAT_VALUES else 0
        )
        self.rec_format.currentIndexChanged.connect(
            lambda i: self._save_str("rec_format", _FORMAT_VALUES[i])
        )
        form.addRow("Aufnahmeformat", self.rec_format)

        self.rec_bitrate_kbps = QSpinBox()
        self.rec_bitrate_kbps.setRange(64, 320)
        self.rec_bitrate_kbps.setSuffix(" kbps")
        self.rec_bitrate_kbps.setValue(int(getattr(s, "rec_bitrate_kbps", 128) or 128))
        self.rec_bitrate_kbps.valueChanged.connect(lambda v: self._save_int("rec_bitrate_kbps", v))
        form.addRow("Bitrate (MP3)", self.rec_bitrate_kbps)

        dir_row = QHBoxLayout()
        self.rec_directory = QLineEdit(getattr(s, "rec_directory", "") or "")
        self.rec_directory.setPlaceholderText("Aufnahmeverzeichnis …")
        self.rec_directory.textChanged.connect(lambda v: self._save_str("rec_directory", v))
        dir_btn = QPushButton("Durchsuchen")
        dir_btn.clicked.connect(self._browse_rec_directory)
        dir_row.addWidget(self.rec_directory, 1)
        dir_row.addWidget(dir_btn)
        form.addRow("Aufnahmeverzeichnis", dir_row)

        self.rec_filename_pattern = QLineEdit(
            getattr(s, "rec_filename_pattern", "{date}_{server}_{channel}") or "{date}_{server}_{channel}"
        )
        self.rec_filename_pattern.setPlaceholderText("{date}_{server}_{channel}")
        self.rec_filename_pattern.textChanged.connect(lambda v: self._save_str("rec_filename_pattern", v))
        form.addRow("Dateinamen-Muster", self.rec_filename_pattern)

        self.rec_include_self = QCheckBox("Eigene Stimme aufnehmen")
        self.rec_include_self.setChecked(bool(getattr(s, "rec_include_self", True)))
        self.rec_include_self.stateChanged.connect(lambda v: self._save_bool("rec_include_self", v))
        form.addRow("", self.rec_include_self)

        self.rec_auto_start = QCheckBox("Bei Verbindung automatisch aufnehmen")
        self.rec_auto_start.setChecked(bool(getattr(s, "rec_auto_start", False)))
        self.rec_auto_start.stateChanged.connect(lambda v: self._save_bool("rec_auto_start", v))
        form.addRow("", self.rec_auto_start)

        self.rec_segment_minutes = QSpinBox()
        self.rec_segment_minutes.setRange(0, 120)
        self.rec_segment_minutes.setSuffix(" min (0 = deaktiviert)")
        self.rec_segment_minutes.setValue(int(getattr(s, "rec_segment_minutes", 0) or 0))
        self.rec_segment_minutes.valueChanged.connect(lambda v: self._save_int("rec_segment_minutes", v))
        form.addRow("Aufnahmen segmentieren alle", self.rec_segment_minutes)

        self.rec_skip_silence = QCheckBox("Stille erkennen und ignorieren")
        self.rec_skip_silence.setChecked(bool(getattr(s, "rec_skip_silence", False)))
        self.rec_skip_silence.stateChanged.connect(lambda v: self._save_bool("rec_skip_silence", v))
        form.addRow("", self.rec_skip_silence)

        layout.addWidget(grp)

        # Segmentierung
        seg_grp = QGroupBox("Aufnahme-Segmentierung (0 = deaktiviert)")
        seg_form = QFormLayout(seg_grp)

        self.rec_max_size = QSpinBox()
        self.rec_max_size.setRange(0, 10000)
        self.rec_max_size.setSuffix(" MB (0 = aus)")
        self.rec_max_size.setValue(int(getattr(s, "recording_max_size_mb", 0) or 0))
        self.rec_max_size.valueChanged.connect(lambda v: self._save_int("recording_max_size_mb", v))
        seg_form.addRow("Max. Dateigröße", self.rec_max_size)

        self.rec_max_minutes = QSpinBox()
        self.rec_max_minutes.setRange(0, 600)
        self.rec_max_minutes.setSuffix(" min (0 = aus)")
        self.rec_max_minutes.setValue(int(getattr(s, "recording_max_minutes", 0) or 0))
        self.rec_max_minutes.valueChanged.connect(lambda v: self._save_int("recording_max_minutes", v))
        seg_form.addRow("Max. Dauer", self.rec_max_minutes)
        layout.addWidget(seg_grp)

        # Stille-Erkennung
        sil_grp = QGroupBox("Stille-Erkennung")
        sil_form = QFormLayout(sil_grp)

        self.silence_detection_enabled = QCheckBox("Stille-Erkennung aktivieren")
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
        sil_form.addRow("Schwellenwert", self.silence_threshold)

        self.silence_timeout = QSpinBox()
        self.silence_timeout.setRange(0, 300)
        self.silence_timeout.setSuffix(" s")
        self.silence_timeout.setValue(int(getattr(s, "silence_detection_timeout_sec", 3) or 3))
        self.silence_timeout.valueChanged.connect(
            lambda v: self._save_int("silence_detection_timeout_sec", v)
        )
        sil_form.addRow("Timeout", self.silence_timeout)
        layout.addWidget(sil_grp)

        layout.addStretch()
        scroll.setWidget(inner)
        return scroll

    def _browse_rec_directory(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Aufnahmeverzeichnis wählen", "")
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
        ng_grp = QGroupBox("Noise Gate / Rauschunterdrückung")
        ng_form = QFormLayout(ng_grp)

        self.noise_gate_enabled = QCheckBox("Noise Gate aktivieren")
        self.noise_gate_enabled.setChecked(bool(getattr(s, "noise_gate_enabled", False)))
        self.noise_gate_enabled.stateChanged.connect(self._on_noise_gate_changed)
        ng_form.addRow("", self.noise_gate_enabled)

        self.noise_gate_threshold = QSpinBox()
        self.noise_gate_threshold.setRange(0, 10000)
        self.noise_gate_threshold.setValue(int(getattr(s, "noise_gate_threshold", 0) or 0))
        self.noise_gate_threshold.valueChanged.connect(self._on_noise_gate_changed)
        ng_form.addRow("Schwellenwert (0–10000)", self.noise_gate_threshold)
        layout.addWidget(ng_grp)

        # PTT-Zeitlimit
        ptt_grp = QGroupBox("PTT-Zeitlimit")
        ptt_form = QFormLayout(ptt_grp)

        self.ptt_max_seconds = QSpinBox()
        self.ptt_max_seconds.setRange(0, 600)
        self.ptt_max_seconds.setSuffix(" s (0 = aus)")
        self.ptt_max_seconds.setValue(int(getattr(s, "ptt_max_seconds", 0) or 0))
        self.ptt_max_seconds.valueChanged.connect(lambda v: self._save_int("ptt_max_seconds", v))
        ptt_form.addRow("PTT-Zeitlimit", self.ptt_max_seconds)
        layout.addWidget(ptt_grp)

        # VU-Pegel-Alarm
        vu_grp = QGroupBox("VU-Pegel-Alarm")
        vu_form = QFormLayout(vu_grp)

        self.vu_alert_enabled = QCheckBox("VU-Alarm aktivieren (bei zu hohem Eingangspegel)")
        self.vu_alert_enabled.setChecked(bool(getattr(s, "vu_alert_enabled", False)))
        self.vu_alert_enabled.stateChanged.connect(lambda v: self._save_bool("vu_alert_enabled", v))
        vu_form.addRow("", self.vu_alert_enabled)

        self.vu_alert_threshold = QSpinBox()
        self.vu_alert_threshold.setRange(0, 100)
        self.vu_alert_threshold.setSuffix(" %")
        self.vu_alert_threshold.setValue(int(getattr(s, "vu_alert_threshold", 90) or 90))
        self.vu_alert_threshold.valueChanged.connect(lambda v: self._save_int("vu_alert_threshold", v))
        vu_form.addRow("Schwellenwert", self.vu_alert_threshold)
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

        grp = QGroupBox("Gespeicherte Nutzer-Lautstärken")
        grp_layout = QVBoxLayout(grp)

        self._vol_preset_list = QListWidget()
        self._vol_preset_list.setMinimumHeight(180)
        grp_layout.addWidget(self._vol_preset_list, 1)

        self._vol_preset_usernames: list = []
        self._refresh_volume_presets_list()

        btn_row = QHBoxLayout()
        del_btn = QPushButton("&Entfernen")
        del_btn.clicked.connect(self._on_del_volume_preset)
        clear_btn = QPushButton("&Alle löschen")
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
            self.window.set_status("Bitte einen Eintrag auswählen")
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
            self, "Alle löschen", "Alle gespeicherten Nutzer-Lautstärken löschen?"
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.window.settings_store.settings.user_volume_presets = {}
            self.window.settings_store.save()
            self._refresh_volume_presets_list()
            self.window.set_status("Alle Lautstärke-Vorlagen gelöscht")

    # ------------------------------------------------------------------
    # Braille
    # ------------------------------------------------------------------

    def _build_braille_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        layout = QVBoxLayout(inner)
        s = self.window.settings_store.settings

        grp = QGroupBox("Braillezeilen-Einstellungen")
        form = QFormLayout(grp)

        self.braille_enabled = QCheckBox("Braillezeile aktiv")
        self.braille_enabled.setChecked(bool(getattr(s, "braille_enabled", False)))
        self.braille_enabled.stateChanged.connect(lambda v: self._save_bool("braille_enabled", v))
        form.addRow("", self.braille_enabled)

        _VERBOSITY_LABELS = ["Kompakt", "Normal", "Ausführlich"]
        _VERBOSITY_VALUES = ["compact", "normal", "verbose"]
        self.braille_verbosity = QComboBox()
        self.braille_verbosity.addItems(_VERBOSITY_LABELS)
        saved_verb = getattr(s, "braille_verbosity", "normal") or "normal"
        self.braille_verbosity.setCurrentIndex(
            _VERBOSITY_VALUES.index(saved_verb) if saved_verb in _VERBOSITY_VALUES else 1
        )
        self.braille_verbosity.currentIndexChanged.connect(
            lambda i: self._save_str("braille_verbosity", _VERBOSITY_VALUES[i])
        )
        form.addRow("Ausführlichkeit", self.braille_verbosity)

        self.braille_announce_channel = QCheckBox("Kanalwechsel ansagen")
        self.braille_announce_channel.setChecked(bool(getattr(s, "braille_announce_channel", True)))
        self.braille_announce_channel.stateChanged.connect(lambda v: self._save_bool("braille_announce_channel", v))
        form.addRow("", self.braille_announce_channel)

        self.braille_announce_user = QCheckBox("Nutzerwechsel ansagen")
        self.braille_announce_user.setChecked(bool(getattr(s, "braille_announce_user", True)))
        self.braille_announce_user.stateChanged.connect(lambda v: self._save_bool("braille_announce_user", v))
        form.addRow("", self.braille_announce_user)

        self.braille_read_messages = QCheckBox("Nachrichten vorlesen")
        self.braille_read_messages.setChecked(bool(getattr(s, "braille_read_messages", True)))
        self.braille_read_messages.stateChanged.connect(lambda v: self._save_bool("braille_read_messages", v))
        form.addRow("", self.braille_read_messages)

        self.braille_max_msg_len = QSpinBox()
        self.braille_max_msg_len.setRange(20, 200)
        self.braille_max_msg_len.setSuffix(" Zeichen")
        self.braille_max_msg_len.setValue(int(getattr(s, "braille_max_msg_len", 80) or 80))
        self.braille_max_msg_len.valueChanged.connect(lambda v: self._save_int("braille_max_msg_len", v))
        form.addRow("Maximale Nachrichtenlänge", self.braille_max_msg_len)

        layout.addWidget(grp)
        layout.addStretch()
        scroll.setWidget(inner)
        return scroll

    # ------------------------------------------------------------------
    # KI & Integration
    # ------------------------------------------------------------------

    def _build_ki_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        layout = QVBoxLayout(inner)
        s = self.window.settings_store.settings

        ki_group = QGroupBox("API-Schlüssel")
        ki_form = QFormLayout(ki_group)

        self.gemini_key = QLineEdit(getattr(s, "gemini_api_key", "") or "")
        self.gemini_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.gemini_key.setPlaceholderText("Gemini API-Key")
        self.gemini_key.textChanged.connect(lambda v: self._save_str("gemini_api_key", v))
        ki_form.addRow("Gemini", self.gemini_key)

        self.elevenlabs_key = QLineEdit(getattr(s, "elevenlabs_api_key", "") or "")
        self.elevenlabs_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.elevenlabs_key.setPlaceholderText("ElevenLabs API-Key")
        def _on_elevenlabs_key_changed(v: str) -> None:
            self._save_str("elevenlabs_api_key", v)
            if hasattr(self.window, "_update_speak_tab"):
                self.window._update_speak_tab(v)
        self.elevenlabs_key.textChanged.connect(_on_elevenlabs_key_changed)
        ki_form.addRow("ElevenLabs", self.elevenlabs_key)
        layout.addWidget(ki_group)

        http_group = QGroupBox("HTTP-Companion-API")
        http_form = QFormLayout(http_group)

        self.http_api_enabled = QCheckBox("HTTP-API aktivieren")
        self.http_api_enabled.setChecked(bool(getattr(s, "http_api_enabled", False)))
        self.http_api_enabled.stateChanged.connect(lambda v: self._save_bool("http_api_enabled", v))
        http_form.addRow("", self.http_api_enabled)

        self.http_api_port = QSpinBox()
        self.http_api_port.setRange(1024, 65535)
        self.http_api_port.setValue(int(getattr(s, "http_api_port", 8765) or 8765))
        self.http_api_port.valueChanged.connect(lambda v: self._save_int("http_api_port", v))
        http_form.addRow("Port", self.http_api_port)
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
        path, _ = QFileDialog.getOpenFileName(
            self, "Sound-Datei wählen", "",
            "WAV-Dateien (*.wav);;Alle Dateien (*.*)"
        )
        if path:
            field.setText(path)

    def _on_lang_changed(self, idx: int) -> None:
        lang = "de" if idx == 0 else "en"
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
