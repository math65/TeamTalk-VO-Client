from __future__ import annotations

import time
from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QTextEdit,
    QCheckBox, QLabel, QComboBox, QLineEdit, QSpinBox, QListWidget,
    QPushButton, QFormLayout, QScrollArea,
)

from i18n import _

if TYPE_CHECKING:
    from app_qt import MainWindow


def _format_uptime(seconds: float) -> str:
    s = int(seconds)
    h, r = divmod(s, 3600)
    m, s = divmod(r, 60)
    if h > 0:
        return f"{h}h {m}m {s}s"
    if m > 0:
        return f"{m}m {s}s"
    return f"{s}s"


class SystemTab(QWidget):
    """Tab 12: Systemmeldungen + TTS-Einstellungen."""

    def __init__(self, parent: QWidget, window: "MainWindow") -> None:
        super().__init__(parent)
        self.window = window
        self._voice_labels: list[str] = []
        self._voice_label_to_id: dict[str, str] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        # Sitzungsstatistik
        stats_group = QGroupBox(_("Sitzungsstatistik"))
        stats_form = QFormLayout(stats_group)
        self._stat_uptime = QLabel("–")
        self._stat_uptime.setAccessibleName(_("Verbindungsdauer"))
        stats_form.addRow(_("Verbindungsdauer:"), self._stat_uptime)
        self._stat_sent = QLabel("–")
        self._stat_sent.setAccessibleName(_("Gesendete Nachrichten"))
        stats_form.addRow(_("Gesendete Nachrichten:"), self._stat_sent)
        self._stat_received = QLabel("–")
        self._stat_received.setAccessibleName(_("Empfangene Nachrichten"))
        stats_form.addRow(_("Empfangene Nachrichten:"), self._stat_received)
        self._stat_connects = QLabel("–")
        self._stat_connects.setAccessibleName(_("Verbindungsanzahl"))
        stats_form.addRow(_("Verbindungsanzahl:"), self._stat_connects)
        stats_btn_row = QHBoxLayout()
        self._btn_stats_refresh = QPushButton(_("Statistik &aktualisieren"))
        self._btn_stats_reset = QPushButton(_("Statistik &zurücksetzen"))
        stats_btn_row.addWidget(self._btn_stats_refresh)
        stats_btn_row.addWidget(self._btn_stats_reset)
        stats_btn_row.addStretch()
        stats_form.addRow(stats_btn_row)
        root.addWidget(stats_group)

        # System log
        sys_group = QGroupBox(_("Systemmeldungen"))
        sys_layout = QVBoxLayout(sys_group)
        self.system_log = QTextEdit()
        self.system_log.setReadOnly(True)
        self.system_log.setAccessibleName(_("Systemmeldungen"))
        sys_layout.addWidget(self.system_log)
        root.addWidget(sys_group, 1)

        # TTS settings
        tts_group = QGroupBox(_("Sprachausgabe (espeak-ng)"))
        tts_layout = QVBoxLayout(tts_group)

        row1 = QHBoxLayout()
        self.tts_enabled = QCheckBox(_("&TTS aktiv"))
        self.tts_interrupt = QCheckBox(_("&Neue Meldung unterbricht"))
        row1.addWidget(self.tts_enabled)
        row1.addWidget(self.tts_interrupt)
        row1.addStretch()
        tts_layout.addLayout(row1)

        row2 = QHBoxLayout()
        self.tts_chat = QCheckBox(_("&Chat vorlesen"))
        self.tts_private = QCheckBox(_("&Privat vorlesen"))
        self.tts_system = QCheckBox(_("&System vorlesen"))
        self.tts_own = QCheckBox(_("&Eigene Nachrichten vorlesen"))
        for cb in (self.tts_chat, self.tts_private, self.tts_system, self.tts_own):
            row2.addWidget(cb)
        row2.addStretch()
        tts_layout.addLayout(row2)

        row3 = QHBoxLayout()
        self.tts_user_join = QCheckBox(_("&Beitritt"))
        self.tts_user_leave = QCheckBox(_("Ab&gang"))
        self.tts_file_transfer = QCheckBox(_("&Dateitransfer"))
        self.tts_channel_topic = QCheckBox(_("Kanal-&Thema"))
        self.tts_connect_announce = QCheckBox(_("&Verbindung"))
        for cb in (self.tts_user_join, self.tts_user_leave,
                   self.tts_file_transfer, self.tts_channel_topic,
                   self.tts_connect_announce):
            row3.addWidget(cb)
        row3.addStretch()
        tts_layout.addLayout(row3)

        form = QFormLayout()
        self.tts_language = QComboBox()
        self.tts_language.setAccessibleName(_("TTS Sprache"))
        form.addRow(QLabel(_("Sprache")), self.tts_language)

        self.tts_voice_filter = QLineEdit()
        self.tts_voice_filter.setAccessibleName(_("TTS Stimme Filter"))
        form.addRow(QLabel(_("Stimmenfilter")), self.tts_voice_filter)

        self.tts_voice = QListWidget()
        self.tts_voice.setAccessibleName(_("TTS Stimme"))
        form.addRow(QLabel(_("Stimme")), self.tts_voice)

        self.tts_rate = QSpinBox()
        self.tts_rate.setRange(80, 400)
        self.tts_rate.setValue(175)
        self.tts_rate.setAccessibleName(_("TTS Sprechtempo"))
        form.addRow(QLabel(_("Sprechtempo (80–400)")), self.tts_rate)

        self.tts_volume = QSpinBox()
        self.tts_volume.setRange(0, 200)
        self.tts_volume.setValue(100)
        self.tts_volume.setAccessibleName(_("TTS Lautstärke"))
        form.addRow(QLabel(_("Lautstärke (0–200)")), self.tts_volume)

        self.tts_path = QLineEdit()
        self.tts_path.setAccessibleName(_("espeak-ng Pfad"))
        form.addRow(QLabel(_("espeak-ng Pfad")), self.tts_path)

        tts_layout.addLayout(form)

        btn_row = QHBoxLayout()
        self.tts_refresh = QPushButton(_("St&immen aktualisieren"))
        self.tts_test = QPushButton(_("Test vo&rlesen"))
        btn_row.addWidget(self.tts_refresh)
        btn_row.addWidget(self.tts_test)
        btn_row.addStretch()
        tts_layout.addLayout(btn_row)

        root.addWidget(tts_group)

        # TTS per-context rates + voices
        ctx_group = QGroupBox(_("Sprechgeschwindigkeit je Kontext (0 = global)"))
        ctx_form = QFormLayout(ctx_group)
        self.tts_chat_rate = QSpinBox()
        self.tts_chat_rate.setRange(0, 400)
        self.tts_chat_rate.setAccessibleName(_("TTS Chat-/Privat-Rate"))
        ctx_form.addRow(_("Chat / Privat (Wörter/Min, 0=global)"), self.tts_chat_rate)
        self.tts_system_rate = QSpinBox()
        self.tts_system_rate.setRange(0, 400)
        self.tts_system_rate.setAccessibleName(_("TTS System-Rate"))
        ctx_form.addRow(_("Systemmeldungen (0=global)"), self.tts_system_rate)
        self.tts_channel_rate = QSpinBox()
        self.tts_channel_rate.setRange(0, 400)
        self.tts_channel_rate.setAccessibleName(_("TTS Kanal-Rate"))
        ctx_form.addRow(_("Kanal-Thema / Beitritt (0=global)"), self.tts_channel_rate)
        self.tts_chat_voice = QLineEdit()
        self.tts_chat_voice.setPlaceholderText(_("leer = global"))
        self.tts_chat_voice.setAccessibleName(_("TTS Chat-Stimme"))
        ctx_form.addRow(_("Chat-Stimme (leer=global)"), self.tts_chat_voice)
        self.tts_system_voice = QLineEdit()
        self.tts_system_voice.setPlaceholderText(_("leer = global"))
        self.tts_system_voice.setAccessibleName(_("TTS System-Stimme"))
        ctx_form.addRow(_("System-Stimme (leer=global)"), self.tts_system_voice)
        root.addWidget(ctx_group)

        # Pronunciation dictionary
        pron_group = QGroupBox(_("Aussprache-Wörterbuch (Wort=Ersatz, eine Regel pro Zeile)"))
        pron_layout = QVBoxLayout(pron_group)
        pron_layout.addWidget(QLabel(_("Beispiel: TeamTalk=Timtock")))
        self.pron_edit = QTextEdit()
        self.pron_edit.setAccessibleName(_("Aussprache-Wörterbuch"))
        self.pron_edit.setMaximumHeight(120)
        pron_layout.addWidget(self.pron_edit)
        pron_save = QPushButton(_("Aussprache-Regeln &speichern"))
        pron_save.clicked.connect(self._save_pronunciation)
        pron_layout.addWidget(pron_save)
        root.addWidget(pron_group)

        self._bind_events()
        self._sync_from_manager()
        self._refresh_stats()

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
        self._btn_stats_refresh.clicked.connect(self._refresh_stats)
        self._btn_stats_reset.clicked.connect(self._reset_stats)
        self.tts_chat_rate.valueChanged.connect(self._apply_settings)
        self.tts_system_rate.valueChanged.connect(self._apply_settings)
        self.tts_channel_rate.valueChanged.connect(self._apply_settings)
        self.tts_chat_voice.textChanged.connect(self._apply_settings)
        self.tts_system_voice.textChanged.connect(self._apply_settings)

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
        self.tts_chat_rate.setValue(s.chat_rate or 0)
        self.tts_system_rate.setValue(s.system_rate or 0)
        self.tts_channel_rate.setValue(s.channel_rate or 0)
        self.tts_chat_voice.setText(s.chat_voice or "")
        self.tts_system_voice.setText(s.system_voice or "")
        pron = self.window.settings_store.settings.pronunciation_dict or {}
        self.pron_edit.setPlainText("\n".join(f"{k}={v}" for k, v in pron.items()))

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
        s.chat_rate = self.tts_chat_rate.value()
        s.system_rate = self.tts_system_rate.value()
        s.channel_rate = self.tts_channel_rate.value()
        s.chat_voice = self.tts_chat_voice.text().strip()
        s.system_voice = self.tts_system_voice.text().strip()
        app.tts_chat_rate = s.chat_rate
        app.tts_system_rate = s.system_rate
        app.tts_channel_rate = s.channel_rate
        app.tts_chat_voice = s.chat_voice
        app.tts_system_voice = s.system_voice
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

    def _save_pronunciation(self) -> None:
        rules: dict[str, str] = {}
        for line in self.pron_edit.toPlainText().splitlines():
            line = line.strip()
            if "=" in line:
                k, _sep, v = line.partition("=")
                k, v = k.strip(), v.strip()
                if k:
                    rules[k] = v
        app = self.window.settings_store.settings
        app.pronunciation_dict = rules
        self.window.settings_store.save()
        pm = getattr(self.window, "_pronunciation", None)
        if pm is not None:
            pm._rules = rules

    def _on_test(self) -> None:
        self.window.tts.speak(_("Das ist ein TTS Test"), kind="system")

    def _refresh_stats(self) -> None:
        """Aktualisiert die Sitzungsstatistik-Anzeige."""
        analytics = getattr(self.window, "_analytics", None)
        current = getattr(analytics, "_current", None)

        # Verbindungsdauer
        if current is not None:
            elapsed = time.time() - current.connected_at
            self._stat_uptime.setText(_format_uptime(elapsed))
        else:
            session_start = getattr(self.window, "_session_start", None)
            if session_start is not None:
                elapsed = time.time() - session_start
                self._stat_uptime.setText(_format_uptime(elapsed))
            else:
                self._stat_uptime.setText(_("Nicht verbunden"))

        # Gesendete Nachrichten
        if current is not None:
            self._stat_sent.setText(str(current.messages_sent))
        else:
            self._stat_sent.setText("–")

        # Empfangene Nachrichten
        if current is not None:
            self._stat_received.setText(str(current.messages_received))
        else:
            self._stat_received.setText("–")

        # Verbindungsanzahl (abgeschlossene + laufende Sitzung)
        if analytics is not None:
            sessions = getattr(analytics, "_sessions", [])
            count = len(sessions) + (1 if current is not None else 0)
            self._stat_connects.setText(str(count))
        else:
            self._stat_connects.setText("–")

    def _reset_stats(self) -> None:
        """Setzt die Sitzungsstatistik der aktuellen Verbindung zurück."""
        analytics = getattr(self.window, "_analytics", None)
        current = getattr(analytics, "_current", None)
        if current is not None:
            current.messages_sent = 0
            current.messages_received = 0
            current.connected_at = time.time()
        self._refresh_stats()

    def append_system(self, text: str) -> None:
        self.system_log.append(text)
