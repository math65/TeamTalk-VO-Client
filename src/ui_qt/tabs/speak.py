from __future__ import annotations

import os
import tempfile
import threading
from typing import List, Optional, TYPE_CHECKING

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QFormLayout,
    QLabel, QLineEdit, QTextEdit, QComboBox, QSpinBox,
    QCheckBox, QPushButton, QListWidget, QAbstractItemView,
)

from i18n import _

if TYPE_CHECKING:
    from app_qt import MainWindow


class SpeakTab(QWidget):
    """Tab: ElevenLabs TTS → Kanal sprechen."""

    def __init__(self, parent: QWidget, window: "MainWindow") -> None:
        super().__init__(parent)
        self.window = window
        self._api_key: str = ""
        self._voice_ids: List[str] = []
        self._model_ids: List[str] = []
        self._generating = False
        self._temp_file: Optional[str] = None
        self._streaming_temp_file: Optional[str] = None
        self._history: List[str] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        tts_group = QGroupBox(_("ElevenLabs Text-to-Speech"))
        tts_layout = QVBoxLayout(tts_group)

        sel_form = QFormLayout()
        voice_row = QHBoxLayout()
        self.voice_choice = QComboBox()
        self.voice_choice.setAccessibleName(_("Stimme"))
        self.refresh_btn = QPushButton(_("&Aktualisieren"))
        self.refresh_btn.clicked.connect(self.on_refresh)
        voice_row.addWidget(self.voice_choice, 1)
        voice_row.addWidget(self.refresh_btn)
        sel_form.addRow(_("Stimme"), voice_row)

        self.model_choice = QComboBox()
        self.model_choice.setAccessibleName(_("Modell"))
        self.model_choice.currentIndexChanged.connect(self.on_model_changed)
        sel_form.addRow(_("Modell"), self.model_choice)

        self.streaming_check = QCheckBox(_("&Echtzeit-Streaming"))
        self.streaming_check.setAccessibleName(_("Echtzeit-Streaming"))
        sel_form.addRow("", self.streaming_check)
        tts_layout.addLayout(sel_form)

        settings_form = QFormLayout()
        self.stability_slider = QSpinBox()
        self.stability_slider.setRange(0, 100)
        self.stability_slider.setValue(50)
        self.stability_slider.setAccessibleName(_("Stabilität (0–100)"))
        settings_form.addRow(_("Stabilität (0–100)"), self.stability_slider)

        self.similarity_slider = QSpinBox()
        self.similarity_slider.setRange(0, 100)
        self.similarity_slider.setValue(75)
        self.similarity_slider.setAccessibleName(_("Ähnlichkeit (0–100)"))
        settings_form.addRow(_("Ähnlichkeit (0–100)"), self.similarity_slider)

        self.style_slider = QSpinBox()
        self.style_slider.setRange(0, 100)
        self.style_slider.setValue(0)
        self.style_slider.setAccessibleName(_("Stil (0–100)"))
        settings_form.addRow(_("Stil (0–100)"), self.style_slider)

        self.speaker_boost = QCheckBox(_("&Sprecher-Boost"))
        self.speaker_boost.setAccessibleName(_("Sprecher-Boost"))
        self.speaker_boost.setChecked(True)
        settings_form.addRow("", self.speaker_boost)

        self.api_key_field = QLineEdit()
        self.api_key_field.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_field.setPlaceholderText(_("API-Key eingeben..."))
        settings_form.addRow(_("API-Key"), self.api_key_field)
        tts_layout.addLayout(settings_form)

        tts_layout.addWidget(QLabel(_("Text zum Sprechen")))
        self.text_input = QTextEdit()
        self.text_input.setPlaceholderText(_("Text hier eingeben..."))
        tts_layout.addWidget(self.text_input, 1)

        btn_row = QHBoxLayout()
        self.speak_btn = QPushButton(_("S&prechen"))
        self.speak_btn.clicked.connect(self.on_speak)
        self.stop_btn = QPushButton(_("S&topp"))
        self.stop_btn.clicked.connect(self.on_stop)
        self.save_key_btn = QPushButton(_("API-Key &speichern"))
        self.save_key_btn.clicked.connect(self.on_save_api_key)
        btn_row.addWidget(self.speak_btn)
        btn_row.addWidget(self.stop_btn)
        btn_row.addWidget(self.save_key_btn)
        btn_row.addStretch()
        self.status_label = QLabel(_("Bereit"))
        btn_row.addWidget(self.status_label)
        tts_layout.addLayout(btn_row)

        # --- Textverlauf ---
        tts_layout.addWidget(QLabel(_("Verlauf (letzte Texte):")))
        self.history_lw = QListWidget()
        self.history_lw.setAccessibleName(_("Textverlauf"))
        self.history_lw.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.history_lw.setMinimumHeight(80)
        self.history_lw.itemDoubleClicked.connect(self._on_history_double_clicked)
        tts_layout.addWidget(self.history_lw)

        history_btn_row = QHBoxLayout()
        self.repeat_btn = QPushButton(_("&Erneut sprechen"))
        self.repeat_btn.clicked.connect(self._on_repeat)
        history_btn_row.addWidget(self.repeat_btn)
        history_btn_row.addStretch()
        tts_layout.addLayout(history_btn_row)

        root.addWidget(tts_group)

        try:
            saved_key = self.window.settings_store.settings.elevenlabs_api_key
            if saved_key:
                self.api_key_field.setText(saved_key)
                self.set_api_key(saved_key)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # API key & voice loading
    # ------------------------------------------------------------------

    def set_api_key(self, key: str) -> None:
        self._api_key = key
        if key.strip():
            self._set_status(_("Lade Stimmen und Modelle..."))
            threading.Thread(target=self._load_voices_and_models, daemon=True).start()

    def _load_voices_and_models(self) -> None:
        from ui_qt.call_after import call_after
        try:
            import requests as _req
            resp = _req.get(
                "https://api.elevenlabs.io/v1/voices",
                headers={"xi-api-key": self._api_key},
                timeout=10,
            )
            if resp.status_code != 200:
                msg = f"ElevenLabs API Fehler: HTTP {resp.status_code}"
                if resp.status_code == 401:
                    msg = _("ElevenLabs API Key ungültig (401)")
                call_after(self._set_status, msg)
                return
            voices = [
                {"voice_id": v["voice_id"], "name": v["name"]}
                for v in resp.json().get("voices", [])
            ]
            resp2 = _req.get(
                "https://api.elevenlabs.io/v1/models",
                headers={"xi-api-key": self._api_key},
                timeout=10,
            )
            models = (
                [{"model_id": m["model_id"], "name": m.get("name", m["model_id"])} for m in resp2.json()]
                if resp2.status_code == 200 else []
            )
            call_after(self._populate_voices, voices)
            call_after(self._populate_models, models)
            call_after(self._set_status, f"{len(voices)} Stimmen, {len(models)} Modelle geladen")
        except ImportError:
            from ui_qt.call_after import call_after as _ca
            _ca(self._set_status, _("Fehlendes Modul: requests"))
        except Exception as exc:
            from ui_qt.call_after import call_after as _ca
            _ca(self._set_status, f"Fehler beim Laden: {exc}")

    def _populate_voices(self, voices: list) -> None:
        self._voice_ids = [v["voice_id"] for v in voices]
        self.voice_choice.clear()
        for v in voices:
            self.voice_choice.addItem(v["name"])

    def _populate_models(self, models: list) -> None:
        self._model_ids = [m["model_id"] for m in models]
        self.model_choice.clear()
        for m in models:
            self.model_choice.addItem(m["name"])
        self._update_speaker_boost_state()

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def on_refresh(self) -> None:
        key = self.api_key_field.text().strip() or self._api_key
        if key:
            self._api_key = key
            self._set_status(_("Aktualisiere..."))
            threading.Thread(target=self._load_voices_and_models, daemon=True).start()

    def on_model_changed(self, idx: int) -> None:
        self._update_speaker_boost_state()

    def _update_speaker_boost_state(self) -> None:
        idx = self.model_choice.currentIndex()
        if idx < 0 or idx >= len(self._model_ids):
            return
        if self._model_ids[idx].startswith("eleven_v3"):
            self.speaker_boost.setChecked(False)
            self.speaker_boost.setEnabled(False)
        else:
            self.speaker_boost.setEnabled(True)

    def on_speak(self) -> None:
        text = self.text_input.toPlainText().strip()
        if not text:
            self._set_status(_("Bitte Text eingeben"))
            return
        vi = self.voice_choice.currentIndex()
        mi = self.model_choice.currentIndex()
        if vi < 0 or vi >= len(self._voice_ids):
            self._set_status(_("Bitte eine Stimme auswählen"))
            return
        if mi < 0 or mi >= len(self._model_ids):
            self._set_status(_("Bitte ein Modell auswählen"))
            return

        voice_id = self._voice_ids[vi]
        model_id = self._model_ids[mi]
        stability = self.stability_slider.value() / 100.0
        similarity = self.similarity_slider.value() / 100.0
        style = self.style_slider.value() / 100.0
        use_boost = self.speaker_boost.isChecked()
        use_streaming = self.streaming_check.isChecked() and self._can_stream(model_id)

        # Verlauf aktualisieren (Duplikate vermeiden, neuester Eintrag oben)
        if text not in self._history:
            self._history.insert(0, text)
            self._history = self._history[:10]
            self._refresh_history()

        self._generating = True
        self.speak_btn.setEnabled(False)
        if use_streaming:
            self._set_status(_("Echtzeit-Streaming..."))
            threading.Thread(
                target=self._generate_streaming,
                args=(text, voice_id, model_id, stability, similarity, style, use_boost),
                daemon=True,
            ).start()
        else:
            self._set_status(_("Generiere Audio..."))
            threading.Thread(
                target=self._speak_worker,
                args=(text, voice_id, model_id, stability, similarity, style, use_boost),
                daemon=True,
            ).start()

    def _refresh_history(self) -> None:
        self.history_lw.clear()
        for entry in self._history:
            display = entry if len(entry) <= 60 else entry[:57] + "..."
            self.history_lw.addItem(display)

    def _on_history_double_clicked(self, item) -> None:
        idx = self.history_lw.row(item)
        if 0 <= idx < len(self._history):
            self.text_input.setPlainText(self._history[idx])
            self.text_input.setFocus()

    def _on_repeat(self) -> None:
        idx = self.history_lw.currentRow()
        if idx < 0 or idx >= len(self._history):
            self._set_status(_("Kein Verlaufseintrag ausgewählt"))
            return
        self.text_input.setPlainText(self._history[idx])
        self.on_speak()

    def _speak_worker(self, text, voice_id, model_id, stability, similarity, style, use_boost) -> None:
        from ui_qt.call_after import call_after
        try:
            import requests as _req
            resp = _req.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
                json={
                    "text": text,
                    "model_id": model_id,
                    "voice_settings": {
                        "stability": stability,
                        "similarity_boost": similarity,
                        "style": style,
                        "use_speaker_boost": use_boost,
                    },
                },
                headers={
                    "xi-api-key": self._api_key,
                    "Content-Type": "application/json",
                    "Accept": "audio/mpeg",
                },
                timeout=30,
            )
            if resp.status_code != 200:
                call_after(self._set_status, f"ElevenLabs Fehler: HTTP {resp.status_code}")
                return
            audio_bytes = resp.content
            self._cleanup_temp()
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                f.write(audio_bytes)
                self._temp_file = f.name
            self.window.client.stop_streaming_media()
            ok = self.window.client.start_streaming_media_to_channel(self._temp_file)
            if ok:
                call_after(self._set_status, f"Streaming gestartet ({len(audio_bytes) // 1024} KB)")
            else:
                call_after(self._set_status, _("Streaming konnte nicht gestartet werden"))
        except Exception as exc:
            call_after(self._set_status, f"Fehler: {exc}")
        finally:
            self._generating = False
            call_after(lambda: self.speak_btn.setEnabled(True))

    def _can_stream(self, model_id: str) -> bool:
        return model_id.startswith("eleven_") and model_id != "eleven_turbo_v2_5"

    def _generate_streaming(self, text, voice_id, model_id, stability, similarity, style, use_boost) -> None:
        from ui_qt.call_after import call_after
        try:
            import requests as _req
        except ImportError:
            call_after(self._set_status, _("Fehlendes Modul: requests"))
            self._generating = False
            call_after(lambda: self.speak_btn.setEnabled(True))
            return

        try:
            with _req.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream",
                json={
                    "text": text,
                    "model_id": model_id,
                    "voice_settings": {
                        "stability": stability,
                        "similarity_boost": similarity,
                        "style": style,
                        "use_speaker_boost": use_boost,
                    },
                },
                headers={
                    "xi-api-key": self._api_key,
                    "Content-Type": "application/json",
                    "Accept": "audio/mpeg",
                },
                stream=True,
                timeout=30,
            ) as resp:
                if resp.status_code != 200:
                    call_after(self._set_status, f"ElevenLabs Fehler: HTTP {resp.status_code}")
                    return
                with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                    self._streaming_temp_file = tmp.name
                    received = 0
                    playback_started = False
                    for chunk in resp.iter_content(chunk_size=4096):
                        if not self._generating:
                            break
                        if chunk:
                            tmp.write(chunk)
                            tmp.flush()
                            received += len(chunk)
                            if not playback_started and received >= 32_768:
                                playback_started = True
                                call_after(self._start_streaming_playback, self._streaming_temp_file)
                if not playback_started and self._streaming_temp_file:
                    call_after(self._start_streaming_playback, self._streaming_temp_file)
                call_after(self._set_status, f"Streaming abgeschlossen ({received // 1024} KB)")
        except Exception as exc:
            call_after(self._set_status, f"Streaming Fehler: {exc}")
        finally:
            self._generating = False
            call_after(lambda: self.speak_btn.setEnabled(True))

    def _start_streaming_playback(self, filepath: str) -> None:
        try:
            self.window.client.stop_streaming_media()
            ok = self.window.client.start_streaming_media_to_channel(filepath)
            if not ok:
                self._set_status(_("Streaming-Wiedergabe konnte nicht gestartet werden"))
        except Exception as exc:
            self._set_status(f"Wiedergabe-Fehler: {exc}")

    def on_stop(self) -> None:
        self._generating = False
        try:
            self.window.client.stop_streaming_media()
        except Exception:
            pass
        self._cleanup_temp()
        self._cleanup_streaming_temp()
        self._set_status(_("Streaming gestoppt"))

    def on_save_api_key(self) -> None:
        key = self.api_key_field.text().strip()
        self._api_key = key
        try:
            self.window.settings_store.settings.elevenlabs_api_key = key
            self.window.settings_store.save()
            self.window.set_status(_("ElevenLabs API-Key gespeichert"))
            if key:
                self.set_api_key(key)
        except Exception as exc:
            self.window.set_status(f"Fehler: {exc}")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _set_status(self, text: str) -> None:
        self.status_label.setText(text)

    def _cleanup_temp(self) -> None:
        if self._temp_file and os.path.exists(self._temp_file):
            try:
                os.unlink(self._temp_file)
            except OSError:
                pass
            self._temp_file = None

    def _cleanup_streaming_temp(self) -> None:
        if self._streaming_temp_file and os.path.exists(self._streaming_temp_file):
            try:
                os.unlink(self._streaming_temp_file)
            except OSError:
                pass
            self._streaming_temp_file = None

    def cleanup(self) -> None:
        self._generating = False
        try:
            self.window.client.stop_streaming_media()
        except Exception:
            pass
        self._cleanup_temp()
        self._cleanup_streaming_temp()
