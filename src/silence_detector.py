"""SilenceDetector – Stille-Erkennung in WAV-Aufnahmen (v4.7.0).

Analysiert eine WAV-Datei und gibt stille Abschnitte als Zeitstempel-Paare zurück.
Kann genutzt werden um Aufnahmen automatisch zu trimmen oder zu segmentieren.

Anforderungen: nur Python-Standardbibliothek (wave, struct, array).
"""
from __future__ import annotations

import array
import struct
import wave
from pathlib import Path
from typing import List, Tuple


def detect_silence(
    wav_path: Path,
    threshold: float = 0.02,
    min_silence_ms: int = 500,
    sample_window_ms: int = 50,
) -> List[Tuple[float, float]]:
    """Erkennt stille Abschnitte in einer WAV-Datei.

    Args:
        wav_path: Pfad zur WAV-Datei.
        threshold: RMS-Schwellenwert (0.0–1.0) unter dem Stille angenommen wird.
        min_silence_ms: Minimale Stillzeit in ms damit ein Abschnitt als Stille gilt.
        sample_window_ms: Fenstergröße für die RMS-Berechnung in ms.

    Returns:
        Liste von (start_s, end_s) Tupeln für stille Abschnitte.
    """
    silent_regions: List[Tuple[float, float]] = []

    try:
        with wave.open(str(wav_path), "rb") as wf:
            n_channels = wf.getnchannels()
            samp_width = wf.getsampwidth()
            framerate = wf.getframerate()
            n_frames = wf.getnframes()

            # Nur 16-bit PCM unterstützt
            if samp_width != 2:
                return []

            window_frames = max(1, int(framerate * sample_window_ms / 1000))
            min_silence_frames = int(framerate * min_silence_ms / 1000)
            max_amplitude = 32768.0

            silence_start: float | None = None
            pos = 0

            while pos < n_frames:
                raw = wf.readframes(window_frames)
                if not raw:
                    break
                actual_frames = len(raw) // (n_channels * samp_width)
                if actual_frames == 0:
                    break

                # Samples lesen (16-bit signed)
                fmt = f"<{len(raw) // 2}h"
                try:
                    samples = struct.unpack(fmt, raw)
                except struct.error:
                    break

                # RMS berechnen (alle Kanäle gemittelt)
                rms = (sum(s * s for s in samples) / len(samples)) ** 0.5
                rms_norm = rms / max_amplitude

                t = pos / framerate
                if rms_norm < threshold:
                    if silence_start is None:
                        silence_start = t
                else:
                    if silence_start is not None:
                        silence_len_frames = int((t - silence_start) * framerate)
                        if silence_len_frames >= min_silence_frames:
                            silent_regions.append((silence_start, t))
                        silence_start = None

                pos += actual_frames

            # Letzte Stille bis Ende
            if silence_start is not None:
                end_t = n_frames / framerate
                silence_len_frames = int((end_t - silence_start) * framerate)
                if silence_len_frames >= min_silence_frames:
                    silent_regions.append((silence_start, end_t))

    except Exception:
        return []

    return silent_regions


def get_audio_duration(wav_path: Path) -> float:
    """Gibt die Länge einer WAV-Datei in Sekunden zurück (0 bei Fehler)."""
    try:
        with wave.open(str(wav_path), "rb") as wf:
            return wf.getnframes() / wf.getframerate()
    except Exception:
        return 0.0


def audio_waveform_text(wav_path: Path, width: int = 40) -> str:
    """Erstellt eine einfache ASCII-Waveform-Darstellung.

    v4.7.0 – Text-basierte Vorschau für VoiceOver-Nutzer.
    """
    try:
        with wave.open(str(wav_path), "rb") as wf:
            n_channels = wf.getnchannels()
            samp_width = wf.getsampwidth()
            framerate = wf.getframerate()
            n_frames = wf.getnframes()

            if samp_width != 2 or n_frames == 0:
                return "[keine Vorschau]"

            frames_per_col = max(1, n_frames // width)
            bars = []
            for _ in range(width):
                raw = wf.readframes(frames_per_col)
                if not raw or len(raw) < 2:
                    bars.append(" ")
                    continue
                fmt = f"<{len(raw) // 2}h"
                try:
                    samples = struct.unpack(fmt, raw)
                    peak = max(abs(s) for s in samples) / 32768.0
                except Exception:
                    peak = 0.0
                # 5-stufige Amplitude
                if peak > 0.8:
                    bars.append("█")
                elif peak > 0.5:
                    bars.append("▇")
                elif peak > 0.3:
                    bars.append("▅")
                elif peak > 0.1:
                    bars.append("▃")
                elif peak > 0.01:
                    bars.append("▁")
                else:
                    bars.append(" ")

            duration = n_frames / framerate
            return f"[{''.join(bars)}] {duration:.1f}s"
    except Exception:
        return "[keine Vorschau]"
