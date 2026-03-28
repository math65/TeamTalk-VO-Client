"""TranscriptionManager – Live-Transkription von Kanal-Sprache (v2.0.0).

Puffert PCM-Audio und transkribiert es regelmäßig via Whisper (lokal).
Das Ergebnis wird als Event auf dem Bus gesendet:

    bus.on("transcription_result", lambda text, language: ...)

Benötigt: openai-whisper, numpy (graceful fallback wenn nicht verfügbar).

Typische Verwendung:
    mgr = TranscriptionManager(frame.bus)
    mgr.load_model()          # einmalig, startet Thread
    mgr.start()
    # ... aus TeamTalk-Audio-Callback:
    mgr.feed_audio(pcm_bytes, sample_rate=48000)
    mgr.stop()
"""
from __future__ import annotations

import threading
import time
from typing import Optional

from event_bus import EventBus


def _has_whisper() -> bool:
    try:
        import whisper  # noqa: F401
        import numpy  # noqa: F401
        return True
    except ImportError:
        return False


class TranscriptionManager:
    """Transkribiert eingehende PCM-Audio-Daten via Whisper."""

    TARGET_RATE = 16_000          # Whisper erwartet 16 kHz
    MAX_BUFFER_SECS = 30          # Puffer-Obergrenze in Sekunden
    PROCESS_INTERVAL = 5.0        # Sekunden zwischen Verarbeitungsschritten

    def __init__(self, bus: EventBus, model_name: str = "base") -> None:
        self._bus = bus
        self._model_name = model_name
        self._model = None
        self._running = False
        self._available = _has_whisper()
        self._audio_buffer: list = []          # list of (bytes, sample_rate)
        self._buffer_lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._load_thread: Optional[threading.Thread] = None

    def is_available(self) -> bool:
        return self._available

    def load_model(self) -> None:
        """Lädt das Whisper-Modell asynchron im Hintergrund."""
        if not self._available or self._model is not None:
            return
        self._load_thread = threading.Thread(
            target=self._load_model_thread,
            name="TranscriptionModelLoad",
            daemon=True,
        )
        self._load_thread.start()

    def _load_model_thread(self) -> None:
        try:
            import whisper
            self._model = whisper.load_model(self._model_name)
            self._bus.emit("transcription_model_loaded", model=self._model_name)
            print(f"[Transcription] Modell '{self._model_name}' geladen.")
        except Exception as exc:
            print(f"[Transcription] Modell konnte nicht geladen werden: {exc}")
            self._available = False

    def start(self) -> None:
        """Startet den Verarbeitungsthread."""
        if not self._available or self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._process_loop,
            name="TranscriptionProcessor",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Stoppt den Verarbeitungsthread."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=4.0)
        self._thread = None

    def feed_audio(self, pcm_bytes: bytes, sample_rate: int = 16_000) -> None:
        """Fügt PCM-Daten zum Puffer hinzu (thread-sicher).

        pcm_bytes: 16-bit signed little-endian PCM.
        """
        if not self._available or not self._running:
            return
        max_bytes = self.MAX_BUFFER_SECS * sample_rate * 2  # 2 bytes/sample
        with self._buffer_lock:
            self._audio_buffer.append((pcm_bytes, sample_rate))
            # Älteste Daten verwerfen wenn Puffer zu groß
            total = sum(len(b) for b, _ in self._audio_buffer)
            while total > max_bytes and self._audio_buffer:
                removed, _ = self._audio_buffer.pop(0)
                total -= len(removed)

    # ------------------------------------------------------------------
    # Verarbeitungsthread
    # ------------------------------------------------------------------

    def _process_loop(self) -> None:
        while self._running:
            time.sleep(self.PROCESS_INTERVAL)
            if self._model is None:
                continue
            with self._buffer_lock:
                chunks = list(self._audio_buffer)
                self._audio_buffer.clear()
            if not chunks:
                continue
            # Mindestens 1 Sekunde Audio
            total_samples = sum(len(b) // 2 for b, _ in chunks)
            if total_samples < self.TARGET_RATE:
                continue
            result = self._transcribe_chunks(chunks)
            if result:
                self._bus.emit(
                    "transcription_result",
                    text=result["text"],
                    language=result.get("language", "de"),
                )

    def _transcribe_chunks(self, chunks: list) -> Optional[dict]:
        """Resampelt und transkribiert einen Liste von PCM-Chunks."""
        try:
            import numpy as np
            import whisper

            # Alle Chunks zu einem Float32-Array zusammenführen
            arrays = []
            for pcm_bytes, rate in chunks:
                arr = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
                # Einfaches Resampling wenn nötig (lineare Interpolation)
                if rate != self.TARGET_RATE:
                    old_len = len(arr)
                    new_len = int(old_len * self.TARGET_RATE / rate)
                    arr = np.interp(
                        np.linspace(0, old_len - 1, new_len),
                        np.arange(old_len),
                        arr,
                    )
                arrays.append(arr)

            audio = np.concatenate(arrays)
            result = self._model.transcribe(audio, language="de", fp16=False)
            return result
        except Exception as exc:
            print(f"[Transcription] Transkription fehlgeschlagen: {exc}")
            return None
