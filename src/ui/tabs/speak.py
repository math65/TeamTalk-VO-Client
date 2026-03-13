from __future__ import annotations

import os
import tempfile
import threading
from typing import List, Optional, TYPE_CHECKING

import wx

if TYPE_CHECKING:
    from app import MainFrame


class SpeakTab(wx.Panel):
    """Tab: Sprechen -- ElevenLabs TTS generation and streaming to channel."""

    def __init__(self, parent: wx.Window, frame: MainFrame) -> None:
        super().__init__(parent)
        self.frame = frame
        self.SetName("Sprechen")

        self._api_key: str = ""
        self._voice_ids: List[str] = []
        self._model_ids: List[str] = []
        self._generating = False
        self._temp_file: Optional[str] = None

        sizer = wx.BoxSizer(wx.VERTICAL)

        tts_box = wx.StaticBox(self, label="ElevenLabs Text-to-Speech")
        tts_sizer = wx.StaticBoxSizer(tts_box, wx.VERTICAL)

        # --- Voice / Model selection ---
        sel_form = wx.FlexGridSizer(cols=3, vgap=6, hgap=8)
        sel_form.AddGrowableCol(1)

        sel_form.Add(wx.StaticText(self, label="Stimme"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.voice_choice = wx.Choice(self)
        self.voice_choice.SetName("Stimme")
        sel_form.Add(self.voice_choice, 1, wx.EXPAND)
        self.refresh_btn = wx.Button(self, label="Aktualisieren")
        self.refresh_btn.SetName("Stimmen und Modelle aktualisieren")
        self.refresh_btn.Bind(wx.EVT_BUTTON, self.on_refresh)
        sel_form.Add(self.refresh_btn, 0)

        sel_form.Add(wx.StaticText(self, label="Modell"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.model_choice = wx.Choice(self)
        self.model_choice.SetName("Modell")
        self.model_choice.Bind(wx.EVT_CHOICE, self.on_model_changed)
        sel_form.Add(self.model_choice, 1, wx.EXPAND)
        sel_form.Add((0, 0), 0)  # empty cell

        tts_sizer.Add(sel_form, 0, wx.ALL | wx.EXPAND, 8)

        # --- Settings ---
        settings_form = wx.FlexGridSizer(cols=2, vgap=6, hgap=12)
        settings_form.AddGrowableCol(1)

        settings_form.Add(wx.StaticText(self, label="Stabilitaet"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.stability_slider = wx.Slider(self, value=50, minValue=0, maxValue=100)
        self.stability_slider.SetName("Stability")
        self.stability_slider.SetHelpText("Stimmstabilitaet (0-100)")
        settings_form.Add(self.stability_slider, 1, wx.EXPAND)

        settings_form.Add(wx.StaticText(self, label="Aehnlichkeit"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.similarity_slider = wx.Slider(self, value=75, minValue=0, maxValue=100)
        self.similarity_slider.SetName("Similarity")
        self.similarity_slider.SetHelpText("Aehnlichkeit zur Originalstimme (0-100)")
        settings_form.Add(self.similarity_slider, 1, wx.EXPAND)

        settings_form.Add(wx.StaticText(self, label="Stil"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.style_slider = wx.Slider(self, value=0, minValue=0, maxValue=100)
        self.style_slider.SetName("Style")
        self.style_slider.SetHelpText("Stil-Uebertreibung (0-100)")
        settings_form.Add(self.style_slider, 1, wx.EXPAND)

        settings_form.Add(wx.StaticText(self, label=""), 0)
        self.speaker_boost = wx.CheckBox(self, label="Sprecher-Boost")
        self.speaker_boost.SetName("Speaker Boost")
        self.speaker_boost.SetHelpText("Sprecherklarheit verstaerken (nicht bei v3)")
        self.speaker_boost.SetValue(True)
        settings_form.Add(self.speaker_boost, 0)

        tts_sizer.Add(settings_form, 0, wx.LEFT | wx.RIGHT | wx.EXPAND, 8)

        # --- Text input ---
        tts_sizer.Add(wx.StaticText(self, label="Text zum Sprechen"), 0, wx.LEFT | wx.TOP, 8)
        self.text_input = wx.TextCtrl(self, style=wx.TE_MULTILINE)
        self.text_input.SetName("Text zum Sprechen")
        self.text_input.SetHelpText("Text eingeben der vorgelesen werden soll")
        self.text_input.SetMinSize((-1, 100))
        tts_sizer.Add(self.text_input, 1, wx.ALL | wx.EXPAND, 8)

        # --- Buttons + Status ---
        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        self.speak_btn = wx.Button(self, label="Sprechen")
        self.speak_btn.SetName("Sprechen")
        self.speak_btn.Bind(wx.EVT_BUTTON, self.on_speak)
        self.stop_btn = wx.Button(self, label="Stopp")
        self.stop_btn.SetName("Stopp")
        self.stop_btn.Bind(wx.EVT_BUTTON, self.on_stop)
        btn_row.Add(self.speak_btn, 0, wx.RIGHT, 8)
        btn_row.Add(self.stop_btn, 0, wx.RIGHT, 12)

        self.status_label = wx.StaticText(self, label="Bereit")
        self.status_label.SetName("TTS Status")
        btn_row.Add(self.status_label, 1, wx.ALIGN_CENTER_VERTICAL)

        tts_sizer.Add(btn_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)

        sizer.Add(tts_sizer, 1, wx.ALL | wx.EXPAND, 8)
        self.SetSizer(sizer)
        self._set_tab_order()

    # ------------------------------------------------------------------
    # API key & data loading
    # ------------------------------------------------------------------

    def set_api_key(self, key: str) -> None:
        self._api_key = key
        if key.strip():
            self._set_status("Lade Stimmen und Modelle...")
            threading.Thread(target=self._load_voices_and_models, daemon=True).start()

    def _load_voices_and_models(self) -> None:
        try:
            import requests as _req

            # Validate API key first with a lightweight request
            resp = _req.get(
                "https://api.elevenlabs.io/v1/voices",
                headers={"xi-api-key": self._api_key},
                timeout=10,
            )
            if resp.status_code != 200:
                msg = f"ElevenLabs API Fehler: HTTP {resp.status_code}"
                if resp.status_code == 401:
                    msg = "ElevenLabs API Key ungueltig (401 Unauthorized)"
                elif resp.status_code == 403:
                    msg = "ElevenLabs API Zugriff verweigert (403 Forbidden)"
                wx.CallAfter(self._set_status, msg)
                return

            from fvhai import ElevenLabsClient
            client = ElevenLabsClient(api_key=self._api_key)
            voices = client.get_voices()
            models = client.get_models()

            if not voices and not models:
                wx.CallAfter(self._set_status, "Keine Stimmen/Modelle geladen - API Key pruefen")
                return

            wx.CallAfter(self._populate_voices, voices)
            wx.CallAfter(self._populate_models, models)
            wx.CallAfter(self._set_status, f"{len(voices)} Stimmen, {len(models)} Modelle geladen")
        except ImportError as exc:
            wx.CallAfter(self._set_status, f"Fehlendes Modul: {exc} - pip install requests")
        except Exception as exc:
            wx.CallAfter(self._set_status, f"Fehler beim Laden: {exc}")

    def _populate_voices(self, voices: list) -> None:
        self.voice_choice.Clear()
        self._voice_ids = []
        for v in voices:
            self.voice_choice.Append(v["name"])
            self._voice_ids.append(v["id"])
        if voices:
            self.voice_choice.SetSelection(0)

    def _populate_models(self, models: list) -> None:
        self.model_choice.Clear()
        self._model_ids = []
        for m in models:
            self.model_choice.Append(m["name"])
            self._model_ids.append(m["id"])
        if models:
            self.model_choice.SetSelection(0)
            self._update_speaker_boost_state()

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def on_refresh(self, _event) -> None:
        if self._api_key.strip():
            self._set_status("Aktualisiere...")
            threading.Thread(target=self._load_voices_and_models, daemon=True).start()

    def on_model_changed(self, _event) -> None:
        self._update_speaker_boost_state()

    def _update_speaker_boost_state(self) -> None:
        idx = self.model_choice.GetSelection()
        if idx == wx.NOT_FOUND or idx >= len(self._model_ids):
            return
        model_id = self._model_ids[idx]
        if model_id.startswith("eleven_v3"):
            self.speaker_boost.SetValue(False)
            self.speaker_boost.Disable()
        else:
            self.speaker_boost.Enable()

    def on_speak(self, _event) -> None:
        text = self.text_input.GetValue().strip()
        if not text:
            self._set_status("Bitte Text eingeben")
            return

        voice_idx = self.voice_choice.GetSelection()
        model_idx = self.model_choice.GetSelection()
        if voice_idx == wx.NOT_FOUND or voice_idx >= len(self._voice_ids):
            self._set_status("Bitte eine Stimme auswaehlen")
            return
        if model_idx == wx.NOT_FOUND or model_idx >= len(self._model_ids):
            self._set_status("Bitte ein Modell auswaehlen")
            return

        voice_id = self._voice_ids[voice_idx]
        model_id = self._model_ids[model_idx]
        stability = self.stability_slider.GetValue() / 100.0
        similarity = self.similarity_slider.GetValue() / 100.0
        style = self.style_slider.GetValue() / 100.0
        use_boost = self.speaker_boost.GetValue()

        self._generating = True
        self.speak_btn.Disable()
        self._set_status("Generiere Audio...")

        threading.Thread(
            target=self._speak_worker,
            args=(text, voice_id, model_id, stability, similarity, style, use_boost),
            daemon=True,
        ).start()

    def _speak_worker(
        self,
        text: str,
        voice_id: str,
        model_id: str,
        stability: float,
        similarity: float,
        style: float,
        use_boost: bool,
    ) -> None:
        try:
            from fvhai import ElevenLabsClient
            client = ElevenLabsClient(api_key=self._api_key)

            audio_bytes, chars = client.text_to_speech(
                text=text,
                voice_id=voice_id,
                model_id=model_id,
                stability=stability,
                similarity_boost=similarity,
                style=style,
                use_speaker_boost=use_boost,
            )

            if audio_bytes is None:
                wx.CallAfter(self._set_status, "Fehler bei der Audiogenerierung")
                return

            # Clean up previous temp file
            self._cleanup_temp()

            # Write MP3 to temp file
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                f.write(audio_bytes)
                self._temp_file = f.name

            # Stop any current streaming before starting new one
            self.frame.client.stop_streaming_media()

            # Stream to channel (non-blocking SDK call, no event loop conflict)
            ok = self.frame.client.start_streaming_media_to_channel(self._temp_file)
            if ok:
                wx.CallAfter(self._set_status, f"Streaming gestartet ({chars} Zeichen)")
            else:
                wx.CallAfter(self._set_status, "Streaming konnte nicht gestartet werden")
        except Exception as exc:
            wx.CallAfter(self._set_status, f"Fehler: {exc}")
        finally:
            self._generating = False
            wx.CallAfter(self.speak_btn.Enable)

    def on_stop(self, _event) -> None:
        self.frame.client.stop_streaming_media()
        self._set_status("Streaming gestoppt")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _set_status(self, text: str) -> None:
        self.status_label.SetLabel(text)

    def _cleanup_temp(self) -> None:
        if self._temp_file and os.path.exists(self._temp_file):
            try:
                os.unlink(self._temp_file)
            except OSError:
                pass
            self._temp_file = None

    def cleanup(self) -> None:
        """Called from force_close to stop streaming and remove temp files."""
        try:
            self.frame.client.stop_streaming_media()
        except Exception:
            pass
        self._cleanup_temp()

    def _set_tab_order(self):
        order = [
            self.voice_choice, self.refresh_btn, self.model_choice,
            self.stability_slider, self.similarity_slider, self.style_slider,
            self.speaker_boost, self.text_input, self.speak_btn, self.stop_btn,
        ]
        for i in range(1, len(order)):
            order[i].MoveAfterInTabOrder(order[i - 1])
