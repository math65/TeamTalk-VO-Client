"""VoiceCommandManager – Sprachsteuerung via Whisper (v2.0.0).

Lauscht im Hintergrund auf Sprachbefehle und führt sie aus.
Benötigt: openai-whisper, pyaudio (graceful fallback wenn nicht verfügbar).

Erkannte Befehle (Deutsch, fuzzy-tolerant):
  "stummschalten" / "stumm"      → Ausgabe stummschalten (toggle)
  "sprechen" / "push to talk"    → PTT toggle
  "kanal <Name>"                 → Kanal nach Name beitreten (fuzzy)
  "status"                       → aktuellen Status ansagen
  "hilfe" / "befehle"            → Befehlsliste vorlesen
  "beenden"                      → App beenden

Hinweis: Das Whisper-Modell "base" wird beim ersten start() geladen.
         Dies dauert einige Sekunden und erfordert ~150 MB Arbeitsspeicher.
"""
from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from app import MainFrame


def _has_whisper() -> bool:
    try:
        import whisper  # noqa: F401
        return True
    except ImportError:
        return False


def _has_pyaudio() -> bool:
    try:
        import pyaudio  # noqa: F401
        return True
    except ImportError:
        return False


_COMMANDS = {
    "hilfe": "hilfe",
    "befehle": "hilfe",
    "stummschalten": "mute",
    "stumm": "mute",
    "sprechen": "ptt",
    "push to talk": "ptt",
    "status": "status",
    "beenden": "quit",
}


class VoiceCommandManager:
    """Hintergrunddienst für Sprachsteuerung."""

    SAMPLE_RATE = 16_000
    CHUNK = 1_024
    SILENCE_THRESHOLD = 500       # RMS-Amplitude unter der Stille angenommen wird
    SILENCE_SECS = 0.8            # Stille-Dauer bevor Segment verarbeitet wird
    MAX_SEGMENT_SECS = 8          # Maximale Segmentlänge

    def __init__(self, frame: "MainFrame") -> None:
        self._frame = frame
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._model = None
        self._available = _has_whisper() and _has_pyaudio()

    def is_available(self) -> bool:
        return self._available

    def start(self) -> bool:
        """Startet den Sprachsteuerungs-Thread. Gibt True bei Erfolg zurück."""
        if not self._available:
            return False
        if self._running:
            return True
        self._running = True
        self._thread = threading.Thread(
            target=self._listen_loop,
            name="VoiceControl",
            daemon=True,
        )
        self._thread.start()
        return True

    def stop(self) -> None:
        """Stoppt den Sprachsteuerungs-Thread."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        self._thread = None

    # ------------------------------------------------------------------
    # Hintergrundthread
    # ------------------------------------------------------------------

    def _listen_loop(self) -> None:
        try:
            import whisper
            import pyaudio
            import numpy as np
            import struct
        except ImportError as exc:
            print(f"[VoiceControl] Import fehlgeschlagen: {exc}")
            self._running = False
            return

        # Modell beim ersten Start laden
        if self._model is None:
            try:
                self._model = whisper.load_model("base")
            except Exception as exc:
                print(f"[VoiceControl] Whisper-Modell konnte nicht geladen werden: {exc}")
                self._running = False
                return

        pa = pyaudio.PyAudio()
        stream = None
        try:
            stream = pa.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=self.SAMPLE_RATE,
                input=True,
                frames_per_buffer=self.CHUNK,
            )

            audio_frames: list = []
            silent_chunks = 0
            silent_limit = int(self.SILENCE_SECS * self.SAMPLE_RATE / self.CHUNK)
            max_chunks = int(self.MAX_SEGMENT_SECS * self.SAMPLE_RATE / self.CHUNK)

            while self._running:
                try:
                    data = stream.read(self.CHUNK, exception_on_overflow=False)
                except Exception:
                    time.sleep(0.05)
                    continue

                # RMS berechnen
                shorts = struct.unpack(f"{len(data) // 2}h", data)
                rms = int((sum(s * s for s in shorts) / len(shorts)) ** 0.5) if shorts else 0

                if rms < self.SILENCE_THRESHOLD:
                    silent_chunks += 1
                    if audio_frames:
                        audio_frames.append(data)
                else:
                    silent_chunks = 0
                    audio_frames.append(data)

                # Segment verarbeiten wenn Stille erkannt oder zu lang
                should_process = (
                    (silent_chunks >= silent_limit and audio_frames)
                    or len(audio_frames) >= max_chunks
                )
                if should_process and audio_frames:
                    raw = b"".join(audio_frames)
                    audio_frames = []
                    silent_chunks = 0
                    self._process_audio(raw, np)

        except Exception as exc:
            print(f"[VoiceControl] Fehler im Listen-Loop: {exc}")
        finally:
            if stream:
                try:
                    stream.stop_stream()
                    stream.close()
                except Exception:
                    pass
            pa.terminate()
            self._running = False

    def _process_audio(self, raw_pcm: bytes, np) -> None:
        """Transkribiert einen Audio-Chunk und verarbeitet den Befehl."""
        if self._model is None:
            return
        try:
            audio = np.frombuffer(raw_pcm, dtype=np.int16).astype(np.float32) / 32768.0
            result = self._model.transcribe(audio, language="de", fp16=False)
            text = (result.get("text") or "").strip().lower()
            if text:
                print(f"[VoiceControl] Erkannt: {text!r}")
                self._handle_command(text)
        except Exception as exc:
            print(f"[VoiceControl] Transkription fehlgeschlagen: {exc}")

    def _handle_command(self, text: str) -> None:
        """Führt den erkannten Befehl aus."""
        import wx

        # Direktbefehle
        for phrase, cmd in _COMMANDS.items():
            if phrase in text:
                if cmd == "hilfe":
                    wx.CallAfter(self._announce_help)
                elif cmd == "mute":
                    wx.CallAfter(self._toggle_mute)
                elif cmd == "ptt":
                    wx.CallAfter(self._toggle_ptt)
                elif cmd == "status":
                    wx.CallAfter(self._announce_status)
                elif cmd == "quit":
                    wx.CallAfter(self._frame.Close)
                return

        # Kanal-Befehl: "kanal <name>"
        if "kanal" in text:
            parts = text.split("kanal", 1)
            if len(parts) > 1:
                channel_name = parts[1].strip()
                if channel_name:
                    wx.CallAfter(self._join_channel_by_name, channel_name)

    # ------------------------------------------------------------------
    # Befehls-Aktionen
    # ------------------------------------------------------------------

    def _toggle_mute(self) -> None:
        try:
            new_val = not self._frame._mute_all
            self._frame._mute_all = new_val
            self._frame.client.set_sound_output_mute(new_val)
            msg = "Ausgabe stummgeschaltet" if new_val else "Ausgabe aktiv"
            self._frame.tts.speak(msg, kind="system")
        except Exception as exc:
            print(f"[VoiceControl] Mute-Toggle fehlgeschlagen: {exc}")

    def _toggle_ptt(self) -> None:
        try:
            new_val = not self._frame._ptt_enabled
            self._frame._ptt_enabled = new_val
            if not new_val and self._frame._ptt_active:
                self._frame._ptt_active = False
                self._frame.client.enable_voice_transmission(False)
            msg = "PTT aktiv" if new_val else "PTT deaktiviert"
            self._frame.tts.speak(msg, kind="system")
        except Exception as exc:
            print(f"[VoiceControl] PTT-Toggle fehlgeschlagen: {exc}")

    def _announce_status(self) -> None:
        try:
            if self._frame.client.is_connected():
                profile = getattr(self._frame, "_current_profile", None)
                server = profile.name if profile else "Server"
                chan_id = self._frame.client.get_my_channel_id()
                chan_name = ""
                if chan_id:
                    try:
                        ch = self._frame.client.get_channel(chan_id)
                        chan_name = self._frame.tt_str(getattr(ch, "szName", "")) or ""
                    except Exception:
                        pass
                msg = f"Verbunden mit {server}"
                if chan_name:
                    msg += f", Kanal {chan_name}"
            else:
                msg = "Nicht verbunden"
            self._frame.tts.speak(msg, kind="system")
        except Exception as exc:
            print(f"[VoiceControl] Status-Ansage fehlgeschlagen: {exc}")

    def _announce_help(self) -> None:
        commands = (
            "Verfügbare Sprachbefehle: "
            "Stumm, Sprechen, Kanal Name, Status, Hilfe, Beenden."
        )
        try:
            self._frame.tts.speak(commands, kind="system")
        except Exception:
            pass

    def _join_channel_by_name(self, name: str) -> None:
        """Sucht einen Kanal nach Name und tritt bei (fuzzy)."""
        try:
            channels = list(self._frame.client.get_channels() or [])
            name_lower = name.lower()
            best = None
            best_score = 0
            for ch in channels:
                ch_name = (self._frame.tt_str(getattr(ch, "szName", "")) or "").lower()
                if ch_name == name_lower:
                    best = ch
                    break
                if name_lower in ch_name or ch_name in name_lower:
                    score = len(set(name_lower) & set(ch_name))
                    if score > best_score:
                        best_score = score
                        best = ch
            if best is not None:
                chan_id = int(getattr(best, "nChannelID", 0))
                self._frame.join_channel(chan_id)
            else:
                self._frame.tts.speak(f"Kanal {name} nicht gefunden", kind="system")
        except Exception as exc:
            print(f"[VoiceControl] Kanal-Join fehlgeschlagen: {exc}")
