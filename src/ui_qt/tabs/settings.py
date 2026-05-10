from __future__ import annotations

from typing import List, TYPE_CHECKING

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QFormLayout,
    QLabel, QLineEdit, QCheckBox, QComboBox, QSpinBox,
    QPushButton, QTabWidget, QFileDialog, QListWidget,
    QScrollArea,
)
from PySide6.QtCore import Qt

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
]


class SettingsTab(QWidget):
    """Tab 10: Einstellungen."""

    def __init__(self, parent: QWidget, window: "MainWindow") -> None:
        super().__init__(parent)
        self.window = window

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)

        self.inner = QTabWidget()
        root.addWidget(self.inner)

        # Sub-tabs that reference window directly
        self.audio_tab = AudioTab(self, window)
        self.video_tab = VideoTab(self, window)
        self.shortcuts_tab = ShortcutsTab(self, window)
        self.system_tab = SystemTab(self, window)

        self.inner.addTab(self._build_general_tab(), "Allgemein")
        self.inner.addTab(self._build_connection_tab(), "Verbindung")
        self.inner.addTab(self._build_sound_events_tab(), "Sound-Ereignisse")
        self.inner.addTab(self.audio_tab, "Audio")
        self.inner.addTab(self.video_tab, "Video")
        self.inner.addTab(self.shortcuts_tab, "Tastenkürzel")
        self.inner.addTab(self.system_tab, "TTS")
        self.inner.addTab(self._build_chat_tab(), "Chat & Automation")
        self.inner.addTab(self._build_ki_tab(), "KI & Integration")

    def _build_general_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        layout = QVBoxLayout(inner)
        s = self.window.settings_store.settings

        gen_group = QGroupBox("Allgemein")
        gen_form = QFormLayout(gen_group)
        self.start_minimized = QCheckBox("Minimiert starten")
        self.start_minimized.setChecked(bool(getattr(s, "start_minimized", False)))
        self.start_minimized.stateChanged.connect(lambda v: self._save_bool("start_minimized", v))
        gen_form.addRow("", self.start_minimized)

        self.close_to_tray = QCheckBox("In Taskleiste minimieren beim Schließen")
        self.close_to_tray.setChecked(bool(getattr(s, "close_to_tray", True)))
        self.close_to_tray.stateChanged.connect(lambda v: self._save_bool("close_to_tray", v))
        gen_form.addRow("", self.close_to_tray)

        self.sounds_enabled = QCheckBox("Ereignis-Sounds aktivieren")
        self.sounds_enabled.setChecked(bool(getattr(s, "sounds_enabled", True)))
        self.sounds_enabled.stateChanged.connect(lambda v: self._save_bool("sounds_enabled", v))
        gen_form.addRow("", self.sounds_enabled)

        lang_row = QHBoxLayout()
        self.ui_lang = QComboBox()
        self.ui_lang.addItems(["Deutsch", "English"])
        saved_lang = getattr(s, "ui_language", "de")
        self.ui_lang.setCurrentIndex(0 if saved_lang == "de" else 1)
        self.ui_lang.currentIndexChanged.connect(self._on_lang_changed)
        lang_row.addWidget(self.ui_lang)
        gen_form.addRow("UI-Sprache", lang_row)

        layout.addWidget(gen_group)
        layout.addStretch()
        scroll.setWidget(inner)
        return scroll

    def _build_connection_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        layout = QVBoxLayout(inner)
        s = self.window.settings_store.settings

        conn_group = QGroupBox("Verbindungseinstellungen")
        conn_form = QFormLayout(conn_group)

        self.auto_reconnect = QCheckBox("Automatisch neu verbinden")
        self.auto_reconnect.setChecked(bool(getattr(s, "auto_reconnect", False)))
        self.auto_reconnect.stateChanged.connect(lambda v: self._save_bool("auto_reconnect", v))
        conn_form.addRow("", self.auto_reconnect)

        self.reconnect_delay = QSpinBox()
        self.reconnect_delay.setRange(5, 300)
        self.reconnect_delay.setValue(int(getattr(s, "reconnect_delay_seconds", 10)))
        self.reconnect_delay.valueChanged.connect(lambda v: self._save_int("reconnect_delay_seconds", v))
        conn_form.addRow("Wartezeit bei Neuverbindung (s)", self.reconnect_delay)

        layout.addWidget(conn_group)
        layout.addStretch()
        scroll.setWidget(inner)
        return scroll

    def _build_sound_events_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        layout = QVBoxLayout(inner)
        s = self.window.settings_store.settings

        evt_group = QGroupBox("Sound-Ereignisse")
        evt_layout = QVBoxLayout(evt_group)
        self._sound_event_rows: dict = {}
        for label, key in _SOUND_EVENTS:
            row = QHBoxLayout()
            row.addWidget(QLabel(label))
            field = QLineEdit()
            field.setObjectName(f"sound_{key}")
            saved = getattr(s, f"sound_{key}", "")
            field.setText(saved or "")
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

    def _build_chat_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        layout = QVBoxLayout(inner)
        s = self.window.settings_store.settings

        chat_group = QGroupBox("Chat")
        chat_form = QFormLayout(chat_group)

        self.save_chat_history = QCheckBox("Chat-Verlauf speichern")
        self.save_chat_history.setChecked(bool(getattr(s, "save_chat_history", True)))
        self.save_chat_history.stateChanged.connect(lambda v: self._save_bool("save_chat_history", v))
        chat_form.addRow("", self.save_chat_history)

        self.save_private_chat_history = QCheckBox("Privatnachrichten-Verlauf speichern")
        self.save_private_chat_history.setChecked(bool(getattr(s, "save_private_chat_history", True)))
        self.save_private_chat_history.stateChanged.connect(
            lambda v: self._save_bool("save_private_chat_history", v)
        )
        chat_form.addRow("", self.save_private_chat_history)

        layout.addWidget(chat_group)
        layout.addStretch()
        scroll.setWidget(inner)
        return scroll

    def _build_ki_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        layout = QVBoxLayout(inner)
        s = self.window.settings_store.settings

        ki_group = QGroupBox("KI & Integration")
        ki_form = QFormLayout(ki_group)

        self.gemini_key = QLineEdit()
        self.gemini_key.setEchoMode(QLineEdit.EchoMode.Password)
        saved_key = getattr(s, "gemini_api_key", "") or ""
        self.gemini_key.setText(saved_key)
        self.gemini_key.textChanged.connect(lambda v: self._save_str("gemini_api_key", v))
        ki_form.addRow("Gemini API-Key", self.gemini_key)

        self.elevenlabs_key = QLineEdit()
        self.elevenlabs_key.setEchoMode(QLineEdit.EchoMode.Password)
        saved_el = getattr(s, "elevenlabs_api_key", "") or ""
        self.elevenlabs_key.setText(saved_el)
        self.elevenlabs_key.textChanged.connect(lambda v: self._save_str("elevenlabs_api_key", v))
        ki_form.addRow("ElevenLabs API-Key", self.elevenlabs_key)

        self.http_api_enabled = QCheckBox("HTTP-API aktivieren")
        self.http_api_enabled.setChecked(bool(getattr(s, "http_api_enabled", False)))
        self.http_api_enabled.stateChanged.connect(lambda v: self._save_bool("http_api_enabled", v))
        ki_form.addRow("", self.http_api_enabled)

        self.http_api_port = QSpinBox()
        self.http_api_port.setRange(1024, 65535)
        self.http_api_port.setValue(int(getattr(s, "http_api_port", 8765)))
        self.http_api_port.valueChanged.connect(lambda v: self._save_int("http_api_port", v))
        ki_form.addRow("HTTP-API Port", self.http_api_port)

        layout.addWidget(ki_group)
        layout.addStretch()
        scroll.setWidget(inner)
        return scroll

    def _save_bool(self, key: str, value: int) -> None:
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
        self._save_str("ui_language", lang)
        try:
            from i18n import set_language
            set_language(lang)
        except Exception:
            pass
