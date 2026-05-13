"""Windows Screen Reader Integration.

Sendet Text an den aktiven Screen Reader (NVDA, JAWS, SAPI5).
Reihenfolge:
  1. tolk.dll  – unterstützt NVDA, JAWS, SAPI, ZoomText, SuperNova, …
  2. nvdaControllerClient64.dll – nur NVDA (aus NVDA-Installation kopieren)
  3. SAPI5 via win32com – immer verfügbar auf Windows (kein Screen Reader nötig)
  4. No-op auf nicht-Windows-Plattformen.

Verwendung::

    from screen_reader import ScreenReaderAnnouncer
    sr = ScreenReaderAnnouncer()
    sr.speak("Verbunden")
    sr.stop()
"""
from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path
from typing import Optional

_IS_WIN = sys.platform == "win32"


def _dll_search_paths() -> list[str]:
    """Liefert Suchpfade für screen-reader DLLs."""
    paths: list[str] = []
    # 1. Neben der EXE / tolk-Unterordner (PyInstaller-Bundle)
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        paths.append(exe_dir)
        paths.append(os.path.join(exe_dir, "tolk"))
    # 2. Projektverzeichnis / third_party/tolk
    here = Path(__file__).resolve().parent
    paths.append(str(here / "third_party" / "tolk"))
    paths.append(str(here.parent / "third_party" / "tolk"))
    # 3. NVDA-Standardinstallation
    prog86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    paths.append(os.path.join(prog86, "NVDA"))
    prog64 = os.environ.get("ProgramFiles", r"C:\Program Files")
    paths.append(os.path.join(prog64, "NVDA"))
    return paths


def _find_dll(name: str) -> Optional[str]:
    for folder in _dll_search_paths():
        candidate = os.path.join(folder, name)
        if os.path.isfile(candidate):
            return candidate
    return None


# ---------------------------------------------------------------------------
# Backend: tolk.dll
# ---------------------------------------------------------------------------

class _TolkBackend:
    def __init__(self) -> None:
        self._lib: Optional[ctypes.CDLL] = None

    def try_load(self) -> bool:
        if not _IS_WIN:
            return False
        path = _find_dll("tolk.dll")
        if not path:
            return False
        try:
            lib = ctypes.CDLL(path)
            lib.Tolk_Load()
            lib.Tolk_HasSpeech.restype = ctypes.c_bool
            lib.Tolk_Speak.argtypes = [ctypes.c_wchar_p, ctypes.c_bool]
            lib.Tolk_Speak.restype = ctypes.c_bool
            lib.Tolk_Output.argtypes = [ctypes.c_wchar_p, ctypes.c_bool]
            lib.Tolk_Output.restype = ctypes.c_bool
            lib.Tolk_Silence.restype = ctypes.c_bool
            self._lib = lib
            return bool(lib.Tolk_HasSpeech())
        except Exception:
            return False

    def speak(self, text: str, interrupt: bool = True) -> bool:
        if not self._lib:
            return False
        try:
            return bool(self._lib.Tolk_Output(text, interrupt))
        except Exception:
            return False

    def silence(self) -> None:
        if self._lib:
            try:
                self._lib.Tolk_Silence()
            except Exception:
                pass

    def unload(self) -> None:
        if self._lib:
            try:
                self._lib.Tolk_Unload()
            except Exception:
                pass
            self._lib = None


# ---------------------------------------------------------------------------
# Backend: nvdaControllerClient64.dll (NVDA-only)
# ---------------------------------------------------------------------------

class _NvdaBackend:
    _NVDA_RUNNING = 0

    def __init__(self) -> None:
        self._lib: Optional[ctypes.CDLL] = None

    def try_load(self) -> bool:
        if not _IS_WIN:
            return False
        path = _find_dll("nvdaControllerClient64.dll")
        if not path:
            path = _find_dll("nvdaControllerClient32.dll")
        if not path:
            return False
        try:
            lib = ctypes.CDLL(path)
            lib.nvdaController_testIfRunning.restype = ctypes.c_int
            lib.nvdaController_speakText.argtypes = [ctypes.c_wchar_p]
            lib.nvdaController_speakText.restype = ctypes.c_int
            lib.nvdaController_cancelSpeech.restype = ctypes.c_int
            if lib.nvdaController_testIfRunning() != self._NVDA_RUNNING:
                return False
            self._lib = lib
            return True
        except Exception:
            return False

    def speak(self, text: str, interrupt: bool = True) -> bool:
        if not self._lib:
            return False
        try:
            if interrupt:
                self._lib.nvdaController_cancelSpeech()
            return self._lib.nvdaController_speakText(text) == self._NVDA_RUNNING
        except Exception:
            return False

    def silence(self) -> None:
        if self._lib:
            try:
                self._lib.nvdaController_cancelSpeech()
            except Exception:
                pass

    def unload(self) -> None:
        self._lib = None


# ---------------------------------------------------------------------------
# Backend: SAPI5 via win32com (kein Screen Reader nötig)
# ---------------------------------------------------------------------------

class _SapiBackend:
    def __init__(self) -> None:
        self._voice = None

    def try_load(self) -> bool:
        if not _IS_WIN:
            return False
        try:
            import win32com.client  # noqa: PLC0415
            self._voice = win32com.client.Dispatch("SAPI.SpVoice")
            return True
        except Exception:
            return False

    def speak(self, text: str, interrupt: bool = True) -> bool:
        if not self._voice:
            return False
        try:
            SVSFlagsAsync = 1
            SVSFPurgeBeforeSpeak = 2
            flags = SVSFlagsAsync
            if interrupt:
                flags |= SVSFPurgeBeforeSpeak
            self._voice.Speak(text, flags)
            return True
        except Exception:
            return False

    def silence(self) -> None:
        if self._voice:
            try:
                self._voice.Speak("", 3)  # SVSFlagsAsync | SVSFPurgeBeforeSpeak
            except Exception:
                pass

    def unload(self) -> None:
        self._voice = None


# ---------------------------------------------------------------------------
# Öffentliche Klasse
# ---------------------------------------------------------------------------

class ScreenReaderAnnouncer:
    """Wählt automatisch den besten verfügbaren Screen-Reader-Backend."""

    def __init__(self) -> None:
        self._backend: Optional[object] = None
        self._backend_name = "none"
        self._init()

    def _init(self) -> None:
        if not _IS_WIN:
            return
        for cls, name in [
            (_TolkBackend, "tolk"),
            (_NvdaBackend, "nvda"),
            (_SapiBackend, "sapi"),
        ]:
            b = cls()
            try:
                if b.try_load():
                    self._backend = b
                    self._backend_name = name
                    return
            except Exception:
                pass

    @property
    def active(self) -> bool:
        return self._backend is not None

    @property
    def backend_name(self) -> str:
        return self._backend_name

    def speak(self, text: str, interrupt: bool = True) -> bool:
        if not self._backend or not text:
            return False
        try:
            return bool(self._backend.speak(text, interrupt))
        except Exception:
            return False

    def silence(self) -> None:
        if self._backend:
            try:
                self._backend.silence()
            except Exception:
                pass

    def stop(self) -> None:
        if self._backend:
            try:
                self._backend.unload()
            except Exception:
                pass
            self._backend = None
