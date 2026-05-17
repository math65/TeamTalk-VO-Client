from __future__ import annotations

import os
import queue
import shutil
import subprocess
import threading
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple
import sys


@dataclass
class TTSSettings:
    enabled: bool = False
    speak_chat: bool = True
    speak_private: bool = True
    speak_system: bool = True
    speak_own: bool = True
    interrupt: bool = False
    speak_user_join: bool = True
    speak_user_leave: bool = True
    speak_file_transfer: bool = False
    speak_who_speaks: bool = False
    speak_channel_topic: bool = False
    connect_announce: bool = True
    speak_broadcast: bool = True
    speak_kicked: bool = True
    language: str = "de"
    voice: str = ""
    rate: int = 175
    volume: int = 100
    espeak_path: str = ""
    # v2.2.0 per-context overrides (0 / "" = use global)
    chat_rate: int = 0
    system_rate: int = 0
    channel_rate: int = 0
    chat_voice: str = ""
    system_voice: str = ""


class TTSManager:
    def __init__(self, frame):
        self.frame = frame
        self.settings = TTSSettings()
        self._queue: "queue.Queue[str]" = queue.Queue()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()
        self._current_proc: Optional[subprocess.Popen] = None
        self.last_text: str = ""
        self._missing_warned = False
        self._local_espeak_dir: Optional[Path] = None
        self._transcript: List[Tuple[str, str, str]] = []  # (timestamp, kind, text)
        # Batch-Announcements: 300ms Puffer für user_join/user_leave (wie ttaccessible)
        self._batch_buffer: List[str] = []
        self._batch_kind: str = "system"
        self._batch_timer: Optional[threading.Timer] = None
        self._batch_lock = threading.Lock()

    def ensure_local_espeak(self) -> Optional[Path]:
        """Copy bundled espeak-ng into App Support / AppData to avoid access prompts."""
        if not getattr(sys, "frozen", False) or not hasattr(sys, "_MEIPASS"):
            return None
        from platform_paths import app_data_dir
        target = app_data_dir() / "espeak-ng"
        if target.exists():
            self._local_espeak_dir = target
            return target
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            bundled = Path(sys._MEIPASS) / "espeak-ng"
            if bundled.exists():
                shutil.copytree(bundled, target, dirs_exist_ok=True)
                self._local_espeak_dir = target
                self.frame.logger.write("TTS: espeak-ng nach App Support kopiert")
                return target
        except Exception:
            pass
        return None

    def close(self) -> None:
        self._stop.set()
        try:
            self._queue.put_nowait("")
        except Exception:
            pass
        if self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._stop_current()

    def _resolve_binary(self) -> Optional[str]:
        if self.settings.espeak_path:
            return self.settings.espeak_path
        exe_name = "espeak-ng.exe" if sys.platform == "win32" else "espeak-ng"
        # Prefer local app-data copy if available
        if self._local_espeak_dir:
            cand = self._local_espeak_dir / "bin" / exe_name
            if cand.exists():
                return str(cand)
        # Prefer system-installed espeak-ng
        system_bin = shutil.which("espeak-ng") or shutil.which("espeak")
        if system_bin:
            return system_bin
        # Bundled binary (PyInstaller)
        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            bundled = Path(sys._MEIPASS) / "espeak-ng" / "bin" / exe_name
            if bundled.exists():
                return str(bundled)
        # Repo binary
        local = Path(__file__).resolve().parent.parent / "third_party" / "espeak-ng" / "bin" / exe_name
        if local.exists():
            return str(local)
        return None

    def _resolve_mbrola_bin(self) -> Optional[Path]:
        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            cand = Path(sys._MEIPASS) / "espeak-ng" / "bin" / "mbrola"
        else:
            cand = Path(__file__).resolve().parent.parent / "third_party" / "espeak-ng" / "bin" / "mbrola"
        return cand if cand.exists() else None

    def list_voices(self) -> list[dict]:
        # Prefer file-based voices to include variants (Max, Linda, etc.)
        voices = self._list_voices_from_files()
        if voices:
            return voices
        return self._list_voices_from_binary()

    def _voice_data_dir(self) -> Optional[Path]:
        if self._local_espeak_dir:
            data_dir = self._local_espeak_dir / "espeak-ng-data"
            if data_dir.exists():
                return data_dir
        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            base = Path(sys._MEIPASS) / "espeak-ng"
        else:
            base = Path(__file__).resolve().parent.parent / "third_party" / "espeak-ng"
        data_dir = base / "espeak-ng-data"
        return data_dir if data_dir.exists() else None

    def _list_voices_from_files(self) -> list[dict]:
        data_dir = self._voice_data_dir()
        if not data_dir:
            return []
        voices_dir = data_dir / "voices"
        if not voices_dir.exists():
            return []

        voices = []
        for path in voices_dir.rglob("*"):
            if not path.is_file():
                continue
            if path.name.startswith("."):
                continue
            rel = path.relative_to(voices_dir).as_posix()
            # Read first lines to extract metadata.
            name = ""
            lang = ""
            gender = ""
            try:
                for line in path.read_text(errors="ignore").splitlines()[:40]:
                    line = line.strip()
                    if line.startswith("name "):
                        name = line.split(" ", 1)[1].strip()
                    elif line.startswith("language "):
                        parts = line.split()
                        if len(parts) >= 2:
                            lang = parts[1].strip()
                    elif line.startswith("gender "):
                        parts = line.split()
                        if len(parts) >= 2:
                            gender = parts[1].strip()
            except Exception:
                continue
            voice_id = name or rel
            # Skip MBROLA voices (user requested removal)
            if rel.startswith("mb/") or "mbrola" in voice_id.lower():
                continue
            tag = "VAR" if rel.startswith("!v/") else ""
            voices.append(
                {
                    "language": lang or "unknown",
                    "age_gender": gender or "--",
                    "voice": voice_id,
                    "file": rel,
                    "tag": tag,
                }
            )

        # Add base language entries from espeak-ng-data/lang (e.g. de, en, fr)
        lang_dir = data_dir / "lang"
        if lang_dir.exists():
            for path in lang_dir.rglob("*"):
                if not path.is_file():
                    continue
                code = path.name
                if code.startswith("."):
                    continue
                voices.append(
                    {
                        "language": code,
                        "age_gender": "--",
                        "voice": code,
                        "file": str(path.relative_to(lang_dir)).replace("\\", "/"),
                        "tag": "LANG",
                    }
                )

        # unique by voice name, preserve order
        seen = set()
        out = []
        for v in voices:
            key = v["voice"]
            if key not in seen:
                out.append(v)
                seen.add(key)
        return out

    def _build_env(self, binary: str) -> dict:
        """Build environment dict for espeak-ng subprocess calls."""
        env = os.environ.copy()
        if "espeak-ng/bin" in binary or "third_party/espeak-ng/bin" in binary:
            if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
                base = Path(sys._MEIPASS) / "espeak-ng"
            else:
                base = Path(__file__).resolve().parent.parent / "third_party" / "espeak-ng"
            data_dir = base / "espeak-ng-data"
            lib_dir = base / "lib"
            if data_dir.exists():
                env["ESPEAK_DATA_PATH"] = str(data_dir)
            if lib_dir.exists():
                if sys.platform == "darwin":
                    env["DYLD_LIBRARY_PATH"] = f"{lib_dir}:{env.get('DYLD_LIBRARY_PATH', '')}".strip(":")
                else:
                    env["PATH"] = f"{lib_dir}{os.pathsep}{env.get('PATH', '')}"
        return env

    def _list_voices_from_binary(self) -> list[dict]:
        binary = self._resolve_binary()
        if not binary:
            return []
        env = self._build_env(binary)
        try:
            proc = subprocess.run(
                [binary, "--voices"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                env=env,
                text=True,
                check=False,
            )
            voices = []
            for line in proc.stdout.splitlines():
                line = line.strip()
                if not line or line.startswith("Pty"):
                    continue
                parts = line.split()
                if len(parts) >= 5:
                    voices.append(
                        {
                            "language": parts[1],
                            "age_gender": parts[2],
                            "voice": parts[3],
                            "file": parts[4],
                        }
                    )
            # unique by voice name, preserve order
            seen = set()
            out = []
            for v in voices:
                key = v["voice"]
                if key not in seen:
                    out.append(v)
                    seen.add(key)
            return out
        except Exception:
            return []

    def list_languages(self) -> list[str]:
        voices = self.list_voices()
        if not voices:
            return []
        seen = set()
        out = []
        for v in voices:
            lang = v.get("language", "")
            if lang and lang not in seen:
                out.append(lang)
                seen.add(lang)
        return out

    def _stop_current(self) -> None:
        if self._current_proc and self._current_proc.poll() is None:
            try:
                self._current_proc.terminate()
            except Exception:
                pass
        self._current_proc = None

    def clear_queue(self) -> None:
        try:
            while True:
                self._queue.get_nowait()
        except Exception:
            pass

    def speak(self, text: str, kind: str = "chat") -> None:
        if not self.settings.enabled:
            return
        if kind == "chat" and not self.settings.speak_chat:
            return
        if kind == "private" and not self.settings.speak_private:
            return
        if kind == "system" and not self.settings.speak_system:
            return
        if kind == "own" and not self.settings.speak_own:
            return
        if kind == "user_join" and not self.settings.speak_user_join:
            return
        if kind == "user_leave" and not self.settings.speak_user_leave:
            return
        if kind == "file_transfer" and not self.settings.speak_file_transfer:
            return
        if kind == "who_speaks" and not self.settings.speak_who_speaks:
            return
        if kind == "channel_topic" and not self.settings.speak_channel_topic:
            return
        if kind == "connect" and not self.settings.connect_announce:
            return
        if kind == "broadcast" and not self.settings.speak_broadcast:
            return
        if kind == "kicked" and not self.settings.speak_kicked:
            return

        if self.settings.interrupt:
            self._stop_current()
            self.clear_queue()
        # Apply pronunciation rules if available
        try:
            pm = getattr(self.frame, "_pronunciation", None)
            if pm is not None:
                text = pm.apply(text)
        except Exception:
            pass
        # Per-context rate/voice override stored as (rate, voice) tuple in queue item
        ctx_rate = 0
        ctx_voice = ""
        if kind in ("chat", "private"):
            ctx_rate = self.settings.chat_rate or 0
            ctx_voice = self.settings.chat_voice or ""
        elif kind in ("system", "connect"):
            ctx_rate = self.settings.system_rate or 0
            ctx_voice = self.settings.system_voice or ""
        elif kind in ("channel_topic", "user_join", "user_leave", "file_transfer"):
            ctx_rate = self.settings.channel_rate or 0
        self.last_text = text
        self._transcript.append((time.strftime("%H:%M:%S"), kind, text))
        if len(self._transcript) > 200:
            self._transcript = self._transcript[-200:]
        # Batch user_join/user_leave events within 300ms window (wie ttaccessible)
        if kind in ("user_join", "user_leave"):
            self._enqueue_batched(text, kind, ctx_rate)
            return
        try:
            self._queue.put_nowait((text, ctx_rate, ctx_voice))
        except Exception:
            pass

    def _enqueue_batched(self, text: str, kind: str, ctx_rate: int) -> None:
        with self._batch_lock:
            self._batch_buffer.append(text)
            self._batch_kind = kind
            self._batch_rate = ctx_rate
            if self._batch_timer is not None:
                self._batch_timer.cancel()
            t = threading.Timer(0.3, self._flush_batch)
            t.daemon = True
            self._batch_timer = t
            t.start()

    def _flush_batch(self) -> None:
        with self._batch_lock:
            if not self._batch_buffer:
                return
            combined = ". ".join(self._batch_buffer)
            rate = getattr(self, "_batch_rate", 0)
            self._batch_buffer.clear()
            self._batch_timer = None
        try:
            self._queue.put_nowait((combined, rate, ""))
        except Exception:
            pass

    def _worker(self) -> None:
        while not self._stop.is_set():
            item = self._queue.get()
            if self._stop.is_set():
                break
            if isinstance(item, tuple):
                text, ctx_rate, ctx_voice = item
            else:
                text, ctx_rate, ctx_voice = item, 0, ""
            if not text:
                continue
            binary = self._resolve_binary()
            if not binary:
                if not self._missing_warned:
                    self._missing_warned = True
                    try:
                        self.frame.logger.write("TTS: espeak-ng nicht gefunden")
                    except Exception:
                        pass
                continue
            env = self._build_env(binary)
            mbrola_bin = self._resolve_mbrola_bin()
            if mbrola_bin:
                env["PATH"] = f"{mbrola_bin.parent}{os.pathsep}{env.get('PATH','')}"
            try:
                eff_rate = ctx_rate if ctx_rate else self.settings.rate
                eff_voice = ctx_voice if ctx_voice else (self.settings.voice or self.settings.language or "de")
                selected = eff_voice

                def run_espeak(voice: str, _rate: int = eff_rate):
                    cmd = [
                        binary, "-v", voice,
                        "-s", str(_rate),
                        "-a", str(self.settings.volume),
                        "--stdout", text,
                    ]
                    return subprocess.run(
                        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
                    )

                if sys.platform == "darwin":
                    fallback_lang = self.settings.language or "en"
                    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                        tmp_path = tmp.name
                    try:
                        proc = run_espeak(selected)
                        if proc.returncode != 0 and fallback_lang and fallback_lang != selected:
                            proc = run_espeak(fallback_lang)
                        if proc.returncode != 0:
                            try:
                                if not self._stop.is_set():
                                    self.frame.logger.write(
                                        f"TTS: espeak-ng failed {proc.stderr.decode('utf-8', 'ignore')}"
                                    )
                            except Exception:
                                pass
                        elif proc.stdout:
                            with open(tmp_path, "wb") as f:
                                f.write(proc.stdout)
                            self._current_proc = subprocess.Popen(
                                ["afplay", tmp_path],
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                            )
                            self._current_proc.wait()
                    finally:
                        try:
                            os.unlink(tmp_path)
                        except Exception:
                            pass
                elif sys.platform == "win32":
                    import winsound
                    fallback_lang = self.settings.language or "en"
                    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                        tmp_path = tmp.name
                    try:
                        proc = run_espeak(selected)
                        if proc.returncode != 0 and fallback_lang and fallback_lang != selected:
                            proc = run_espeak(fallback_lang)
                        if proc.returncode != 0:
                            try:
                                if not self._stop.is_set():
                                    self.frame.logger.write(
                                        f"TTS: espeak-ng failed {proc.stderr.decode('utf-8', 'ignore')}"
                                    )
                            except Exception:
                                pass
                        elif proc.stdout:
                            with open(tmp_path, "wb") as f:
                                f.write(proc.stdout)
                            winsound.PlaySound(tmp_path, winsound.SND_FILENAME)
                    finally:
                        try:
                            os.unlink(tmp_path)
                        except Exception:
                            pass
                else:
                    cmd = [
                        binary,
                        "-v",
                        selected,
                        "-s",
                        str(eff_rate),
                        "-a",
                        str(self.settings.volume),
                        text,
                    ]
                    self._current_proc = subprocess.Popen(
                        cmd,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        env=env,
                    )
                    self._current_proc.wait()
            except Exception:
                pass
            finally:
                self._current_proc = None
