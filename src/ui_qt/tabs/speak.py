from __future__ import annotations

import os
import tempfile
import threading
from typing import List, Optional, TYPE_CHECKING

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QFormLayout,
    QLabel, QLineEdit, QTextEdit, QComboBox, QSpinBox,
    QCheckBox, QPushButton,
)

if TYPE_CHECKING:
    from app_qt import MainWindow


class SpeakTab(QWidget):
    """Tab 8: ElevenLabs TTS → Kanal sprechen."""

    def __init__(self, parent: QWidget, window: "MainWindow") -> None:
        super().__init__(parent)
        self.window = window
        self._api_key = ""
        self._voice_ids: List[str] = []
        self._model_ids: List[str] = []
        self._generating = False
        self._temp_file: Optional[str] = None

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        tts_group = QGroupBox("ElevenLabs Text-to-Speech")
        tts_layout = QVBoxLayout(tts_group)

        # Voice/model selection
        sel_form = QFormLayout()
        voice_row = QHBoxLayout()
        self.voice_choice = QComboBox()
        self.voice_choice.setObjectName("Stimme")
        self.refresh_btn = QPushButton("&Aktualisieren")
        self.refresh_btn.clicked.connect(self.on_refresh)
        voice_row.addWidget(self.voice_choice, 1)
        voice_row.addWidget(self.refresh_btn)
        sel_form.addRow(QLabel("Stimme"), voice_row)

        self.model_choice = QComboBox()
        self.model_choice.setObjectName("Modell")
        self.model_choice.currentIndexChanged.connect(self.on_model_changed)
        sel_form.addRow(QLabel("Modell"), self.model_choice)

        self.streaming_check = QCheckBox("&Echtzeit-Streaming")
        sel_form.addRow("", self.streaming_check)
        tts_layout.addLayout(sel_form)

        # Settings
        settings_form = QFormLayout()
        self.stability_slider = QSpinBox()
        self.stability_slider.setRange(0, 100)
        self.stability_slider.setValue(50)
        settings_form.addRow(QLabel("Stabilität (0–100)"), self.stability_slider)

        self.similarity_slider = QSpinBox()
        self.similarity_slider.setRange(0, 100)
        self.similarity_slider.setValue(75)
        settings_form.addRow(QLabel("Ähnlichkeit (0–100)"), self.similarity_slider)

        self.api_key_field = QLineEdit()
        self.api_key_field.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_field.setObjectName("ElevenLabs API-Key")
        self.api_key_field.setPlaceholderText("API-Key eingeben...")
        settings_form.addRow(QLabel("API-Key"), self.api_key_field)
        tts_layout.addLayout(settings_form)

        # Text input
        tts_layout.addWidget(QLabel("Text zum Vorlesen"))
        self.text_input = QTextEdit()
        self.text_input.setObjectName("Text zum Vorlesen")
        self.text_input.setPlaceholderText("Text hier eingeben...")
        tts_layout.addWidget(self.text_input, 1)

        # Action buttons
        btn_row = QHBoxLayout()
        self.generate_btn = QPushButton("&Generieren und senden")
        self.generate_btn.clicked.connect(self.on_generate)
        self.preview_btn = QPushButton("&Vorschau")
        self.preview_btn.clicked.connect(self.on_preview)
        self.stop_btn = QPushButton("&Stopp")
        self.stop_btn.clicked.connect(self.on_stop)
        self.save_key_btn = QPushButton("API-Key &speichern")
        self.save_key_btn.clicked.connect(self.on_save_api_key)
        for btn in (self.generate_btn, self.preview_btn, self.stop_btn, self.save_key_btn):
            btn_row.addWidget(btn)
        btn_row.addStretch()
        tts_layout.addLayout(btn_row)

        root.addWidget(tts_group)

        # Load saved API key
        try:
            saved_key = self.window.settings_store.settings.elevenlabs_api_key
            if saved_key:
                self.api_key_field.setText(saved_key)
                self._api_key = saved_key
        except Exception:
            pass

    def on_refresh(self) -> None:
        self.window.refresh_elevenlabs_voices(self)

    def on_model_changed(self, idx: int) -> None:
        pass

    def on_generate(self) -> None:
        text = self.text_input.toPlainText().strip()
        if not text:
            return
        voice_idx = self.voice_choice.currentIndex()
        voice_id = self._voice_ids[voice_idx] if 0 <= voice_idx < len(self._voice_ids) else ""
        model_idx = self.model_choice.currentIndex()
        model_id = self._model_ids[model_idx] if 0 <= model_idx < len(self._model_ids) else "eleven_multilingual_v2"
        stability = self.stability_slider.value() / 100.0
        similarity = self.similarity_slider.value() / 100.0
        streaming = self.streaming_check.isChecked()
        self.window.elevenlabs_generate_and_send(
            text, voice_id, model_id, stability, similarity, streaming
        )

    def on_preview(self) -> None:
        text = self.text_input.toPlainText().strip()
        if not text:
            return
        self.window.elevenlabs_preview(text, self)

    def on_stop(self) -> None:
        self.window.elevenlabs_stop()

    def on_save_api_key(self) -> None:
        key = self.api_key_field.text().strip()
        self._api_key = key
        try:
            self.window.settings_store.settings.elevenlabs_api_key = key
            self.window.settings_store.save()
            self.window.set_status("ElevenLabs API-Key gespeichert")
        except Exception as exc:
            self.window.set_status(f"Fehler: {exc}")

    def update_voices(self, voices: list, models: list) -> None:
        self._voice_ids = [v.get("voice_id", "") for v in voices]
        self.voice_choice.clear()
        for v in voices:
            self.voice_choice.addItem(v.get("name", "?"))
        self._model_ids = [m.get("model_id", "") for m in models]
        self.model_choice.clear()
        for m in models:
            self.model_choice.addItem(m.get("name", m.get("model_id", "?")))
