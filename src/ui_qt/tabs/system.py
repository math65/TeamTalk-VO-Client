from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QTextEdit,
    QCheckBox, QLabel, QComboBox, QLineEdit, QSpinBox, QListWidget,
    QPushButton, QFormLayout,
)

if TYPE_CHECKING:
    from app_qt import MainWindow


class SystemTab(QWidget):
    """Tab 12: Systemmeldungen + TTS-Einstellungen."""

    def __init__(self, parent: QWidget, window: "MainWindow") -> None:
        super().__init__(parent)
        self.window = window
        self._voice_labels: list[str] = []
        self._voice_label_to_id: dict[str, str] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        # System log
        sys_group = QGroupBox("Systemmeldungen")
        sys_layout = QVBoxLayout(sys_group)
        self.system_log = QTextEdit()
        self.system_log.setReadOnly(True)
        self.system_log.setObjectName("Systemmeldungen")
        sys_layout.addWidget(self.system_log)
        root.addWidget(sys_group, 1)

        # TTS settings
        tts_group = QGroupBox("Sprachausgabe (espeak-ng)")
        tts_layout = QVBoxLayout(tts_group)

        row1 = QHBoxLayout()
        self.tts_enabled = QCheckBox("&TTS aktiv")
        self.tts_interrupt = QCheckBox("&Neue Meldung unterbricht")
        row1.addWidget(self.tts_enabled)
        row1.addWidget(self.tts_interrupt)
        row1.addStretch()
        tts_layout.addLayout(row1)

        row2 = QHBoxLayout()
        self.tts_chat = QCheckBox("&Chat vorlesen")
        self.tts_private = QCheckBox("&Privat vorlesen")
        self.tts_system = QCheckBox("&System vorlesen")
        self.tts_own = QCheckBox("&Eigene Nachrichten vorlesen")
        for cb in (self.tts_chat, self.tts_private, self.tts_system, self.tts_own):
            row2.addWidget(cb)
        row2.addStretch()
        tts_layout.addLayout(row2)

        row3 = QHBoxLayout()
        self.tts_user_join = QCheckBox("&Beitritt")
        self.tts_user_leave = QCheckBox("Ab&gang")
        self.tts_file_transfer = QCheckBox("&Dateitransfer")
        self.tts_channel_topic = QCheckBox("Kanal-&Thema")
        self.tts_connect_announce = QCheckBox("&Verbindung")
        for cb in (self.tts_user_join, self.tts_user_leave,
                   self.tts_file_transfer, self.tts_channel_topic,
                   self.tts_connect_announce):
            row3.addWidget(cb)
        row3.addStretch()
        tts_layout.addLayout(row3)

        form = QFormLayout()
        self.tts_language = QComboBox()
        self.tts_language.setObjectName("TTS Sprache")
        form.addRow(QLabel("Sprache"), self.tts_language)

        self.tts_voice_filter = QLineEdit()
        self.tts_voice_filter.setObjectName("TTS Stimme Filter")
        form.addRow(QLabel("Stimmenfilter"), self.tts_voice_filter)

        self.tts_voice = QListWidget()
        self.tts_voice.setObjectName("TTS Stimme")
        form.addRow(QLabel("Stimme"), self.tts_voice)

        self.tts_rate = QSpinBox()
        self.tts_rate.setRange(80, 400)
        self.tts_rate.setValue(175)
        self.tts_rate.setObjectName("TTS Sprechtempo")
        form.addRow(QLabel("Sprechtempo (80–400)"), self.tts_rate)

        self.tts_volume = QSpinBox()
        self.tts_volume.setRange(0, 200)
        self.tts_volume.setValue(100)
        self.tts_volume.setObjectName("TTS Lautstärke")
        form.addRow(QLabel("Lautstärke (0–200)"), self.tts_volume)

        self.tts_path = QLineEdit()
        self.tts_path.setObjectName("espeak-ng Pfad")
        form.addRow(QLabel("espeak-ng Pfad"), self.tts_path)

        tts_layout.addLayout(form)

        btn_row = QHBoxLayout()
        self.tts_refresh = QPushButton("St&immen aktualisieren")
        self.tts_test = QPushButton("Test vo&rlesen")
        btn_row.addWidget(self.tts_refresh)
        btn_row.addWidget(self.tts_test)
        btn_row.addStretch()
        tts_layout.addLayout(btn_row)

        root.addWidget(tts_group)

        self._bind_events()
        self._sync_from_manager()

    def _bind_events(self) -> None:
        self.tts_enabled.stateChanged.connect(self._on_enable_changed)
        self.tts_interrupt.stateChanged.connect(self._apply_settings)
        self.tts_chat.stateChanged.connect(self._apply_settings)
        self.tts_private.stateChanged.connect(self._apply_settings)
        self.tts_system.stateChanged.connect(self._apply_settings)
        self.tts_own.stateChanged.connect(self._apply_settings)
        self.tts_user_join.stateChanged.connect(self._apply_settings)
        self.tts_user_leave.stateChanged.connect(self._apply_settings)
        self.tts_file_transfer.stateChanged.connect(self._apply_settings)
        self.tts_channel_topic.stateChanged.connect(self._apply_settings)
        self.tts_connect_announce.stateChanged.connect(self._apply_settings)
        self.tts_language.currentIndexChanged.connect(self._refresh_voices)
        self.tts_voice_filter.textChanged.connect(self._refresh_voices)
        self.tts_voice.currentRowChanged.connect(self._apply_settings)
        self.tts_rate.valueChanged.connect(self._apply_settings)
        self.tts_volume.valueChanged.connect(self._apply_settings)
        self.tts_path.textChanged.connect(self._apply_settings)
        self.tts_refresh.clicked.connect(lambda: self._refresh_voices(force=True))
        self.tts_test.clicked.connect(self._on_test)

    def _sync_from_manager(self) -> None:
        s = self.window.tts.settings
        self.tts_enabled.setChecked(s.enabled)
        self.tts_interrupt.setChecked(s.interrupt)
        self.tts_chat.setChecked(s.speak_chat)
        self.tts_private.setChecked(s.speak_private)
        self.tts_system.setChecked(s.speak_system)
        self.tts_own.setChecked(s.speak_own)
        self.tts_user_join.setChecked(s.speak_user_join)
        self.tts_user_leave.setChecked(s.speak_user_leave)
        self.tts_file_transfer.setChecked(s.speak_file_transfer)
        self.tts_channel_topic.setChecked(s.speak_channel_topic)
        self.tts_connect_announce.setChecked(s.connect_announce)
        if s.enabled:
            self._refresh_languages(force=True)
            self._set_language_value(s.language)
            self._refresh_voices(force=True)
            self._set_voice_value(s.voice)
        else:
            self.tts_language.clear()
            self.tts_language.addItems(["Alle", "de"])
            self._set_language_value(s.language or "de")
            self.tts_voice.clear()
        self.tts_rate.setValue(s.rate)
        self.tts_volume.setValue(s.volume)
        self.tts_path.setText(s.espeak_path)

    def _apply_settings(self, *_) -> None:
        s = self.window.tts.settings
        s.enabled = self.tts_enabled.isChecked()
        s.interrupt = self.tts_interrupt.isChecked()
        s.speak_chat = self.tts_chat.isChecked()
        s.speak_private = self.tts_private.isChecked()
        s.speak_system = self.tts_system.isChecked()
        s.speak_own = self.tts_own.isChecked()
        s.speak_user_join = self.tts_user_join.isChecked()
        s.speak_user_leave = self.tts_user_leave.isChecked()
        s.speak_file_transfer = self.tts_file_transfer.isChecked()
        s.speak_channel_topic = self.tts_channel_topic.isChecked()
        s.connect_announce = self.tts_connect_announce.isChecked()
        s.language = self._get_language_value() or "de"
        s.voice = self._get_voice_value()
        s.rate = self.tts_rate.value()
        s.volume = self.tts_volume.value()
        s.espeak_path = self.tts_path.text().strip()
        app = self.window.settings_store.settings
        app.tts_enabled = s.enabled
        app.tts_speak_chat = s.speak_chat
        app.tts_speak_private = s.speak_private
        app.tts_speak_system = s.speak_system
        app.tts_speak_own = s.speak_own
        app.tts_interrupt = s.interrupt
        app.tts_language = s.language
        app.tts_voice = s.voice
        app.tts_rate = s.rate
        app.tts_volume = s.volume
        app.tts_espeak_path = s.espeak_path
        app.tts_speak_user_join = s.speak_user_join
        app.tts_speak_user_leave = s.speak_user_leave
        app.tts_speak_file_transfer = s.speak_file_transfer
        app.tts_speak_channel_topic = s.speak_channel_topic
        app.tts_connect_announce = s.connect_announce
        self.window.settings_store.save()

    def _refresh_voices(self, *_, force: bool = False) -> None:
        if not self.tts_enabled.isChecked() and not force:
            return
        voices = self.window.tts.list_voices()
        if not voices:
            voices = [
                {"language": "de", "age_gender": "--/M", "voice": "de", "file": "de"},
                {"language": "en", "age_gender": "--/M", "voice": "en", "file": "en"},
            ]
        lang = self._get_language_value()
        labels: list[str] = []
        self._voice_label_to_id = {}
        for v in voices:
            if lang in ("de", "de+variant"):
                if v["language"] not in ("de", "variant"):
                    continue
            elif lang and v["language"] != lang:
                continue
            tag = v.get("tag", "")
            tag_txt = f" {tag}" if tag else ""
            label = f"{v['voice']} [{v['language']}] ({v['age_gender']}){tag_txt}"
            labels.append(label)
            self._voice_label_to_id[label] = v["voice"]
        filt = self.tts_voice_filter.text().strip().lower()
        if filt:
            labels = [l for l in labels if filt in l.lower()]
        self._voice_labels = labels
        self.tts_voice.blockSignals(True)
        self.tts_voice.clear()
        self.tts_voice.addItems(labels)
        self.tts_voice.blockSignals(False)
        self._set_voice_value(self.window.tts.settings.voice)

    def _refresh_languages(self, force: bool = False) -> None:
        if not self.tts_enabled.isChecked() and not force:
            return
        langs = self.window.tts.list_languages()
        if not langs:
            langs = ["de", "en"]
        langs = sorted(set(langs))
        all_label, variant_label, de_all_label = "Alle", "Varianten", "de + Varianten"
        if "variant" in langs:
            items = [all_label, variant_label, de_all_label] + [l for l in langs if l != "variant"]
        else:
            items = [all_label, de_all_label] + langs
        current = self.tts_language.currentText().strip()
        self.tts_language.blockSignals(True)
        self.tts_language.clear()
        self.tts_language.addItems(items)
        if current in items:
            self.tts_language.setCurrentText(current)
        else:
            self._set_language_value(self.window.tts.settings.language)
        self.tts_language.blockSignals(False)

    def _get_language_value(self) -> str:
        val = self.tts_language.currentText().strip()
        if val == "Alle":
            return ""
        if val == "Varianten":
            return "variant"
        if val == "de + Varianten":
            return "de+variant"
        return val

    def _set_language_value(self, lang: str) -> None:
        if not lang:
            self.tts_language.setCurrentText("Alle")
        elif lang == "variant":
            self.tts_language.setCurrentText("Varianten")
        elif lang == "de+variant":
            self.tts_language.setCurrentText("de + Varianten")
        else:
            self.tts_language.setCurrentText(lang)

    def _on_enable_changed(self, *_) -> None:
        self._apply_settings()
        if self.tts_enabled.isChecked():
            self.window.tts.ensure_local_espeak()
            self._refresh_languages(force=True)
            self._refresh_voices(force=True)

    def _get_voice_value(self) -> str:
        idx = self.tts_voice.currentRow()
        if idx < 0 or idx >= len(self._voice_labels):
            return ""
        return self._voice_label_to_id.get(self._voice_labels[idx], self._voice_labels[idx])

    def _set_voice_value(self, voice: str) -> None:
        if not voice:
            return
        for idx, label in enumerate(self._voice_labels):
            if self._voice_label_to_id.get(label) == voice:
                self.tts_voice.setCurrentRow(idx)
                return
        if self._voice_labels:
            self.tts_voice.setCurrentRow(0)

    def _on_test(self) -> None:
        self.window.tts.speak("Das ist ein TTS Test", kind="system")

    def append_system(self, text: str) -> None:
        self.system_log.append(text)
