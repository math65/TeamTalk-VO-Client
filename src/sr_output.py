"""Einheitlicher Screen-Reader-Output-Layer (v8.0).

Hierarchie:
  macOS   — NSAccessibilityPostNotificationWithUserInfo (PyObjC, Prio High).
            Braille: automatisch via VoiceOver.
  Windows — SRAL (NVDA / JAWS / SAPI / Narrator + Braille via BRLTTY).
            Fallback: ScreenReaderAnnouncer (tolk / nvdaClient / SAPI5).
  Linux   — SRAL (Speech Dispatcher + libbrlapi).

Verwendung::

    import sr_output
    sr_output.speak("Kanal betreten")
    sr_output.braille("Kanal betreten")   # no-op auf macOS (VO macht es automatisch)
    sr_output.output("Kanal betreten")    # Sprache + Braille kombiniert
"""
from __future__ import annotations

import os
import sys


# ---------------------------------------------------------------------------
# Hilfsfunktion: SRAL-Bibliothekspfad
# ---------------------------------------------------------------------------

def _find_sral_lib() -> str | None:
    if getattr(sys, "frozen", False):
        base = sys._MEIPASS  # type: ignore[attr-defined]
    else:
        base = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "third_party", "sral")
        )

    if sys.platform == "darwin":
        candidate = os.path.join(base, "macOS", "libSRAL.dylib")
    elif os.name == "nt":
        candidate = os.path.join(base, "windows", "SRAL.dll")
    else:
        candidate = os.path.join(base, "linux", "libSRAL.so")

    return candidate if os.path.exists(candidate) else None


def _find_sral_binding() -> str | None:
    if getattr(sys, "frozen", False):
        base = sys._MEIPASS  # type: ignore[attr-defined]
    else:
        base = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "third_party", "sral")
        )
    candidate = os.path.join(base, "sral.py")
    return candidate if os.path.exists(candidate) else None


# ---------------------------------------------------------------------------
# macOS: direkte PyObjC-Implementierung (mit NSAccessibilityPriorityHigh)
# ---------------------------------------------------------------------------

def _speak_macos(text: str) -> None:
    try:
        import AppKit  # noqa: PLC0415
        user_info = {
            AppKit.NSAccessibilityAnnouncementKey: text,
            AppKit.NSAccessibilityPriorityKey: AppKit.NSAccessibilityPriorityHigh,
        }
        AppKit.NSAccessibilityPostNotificationWithUserInfo(
            AppKit.NSApp().mainWindow(),
            AppKit.NSAccessibilityAnnouncementRequestedNotification,
            user_info,
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# SRAL: ctypes-Binding (Windows primär, macOS / Linux optional)
# ---------------------------------------------------------------------------

_sral: object | None = None
_sral_tried: bool = False


def _load_sral() -> object | None:
    global _sral, _sral_tried
    if _sral_tried:
        return _sral
    _sral_tried = True

    lib_path = _find_sral_lib()
    binding_path = _find_sral_binding()
    if not lib_path or not binding_path:
        return None

    try:
        import ctypes, importlib.util, types  # noqa: PLC0415

        # Bibliothek vorladen (damit das Binding sie per CDLL('.') findet)
        ctypes.CDLL(lib_path)

        spec = importlib.util.spec_from_file_location("_sral_binding", binding_path)
        if spec is None or spec.loader is None:
            return None
        mod = types.ModuleType("_sral_binding")
        spec.loader.exec_module(mod)  # type: ignore[union-attr]

        obj = mod.SRAL()
        if obj.initialize():
            _sral = obj
    except Exception:
        pass

    return _sral


# ---------------------------------------------------------------------------
# Windows-Fallback: ScreenReaderAnnouncer (tolk / nvdaClient / SAPI)
# ---------------------------------------------------------------------------

_win_fallback: object | None = None
_win_fallback_tried: bool = False


def _load_win_fallback() -> object | None:
    global _win_fallback, _win_fallback_tried
    if _win_fallback_tried:
        return _win_fallback
    _win_fallback_tried = True
    if os.name != "nt":
        return None
    try:
        from screen_reader import ScreenReaderAnnouncer  # noqa: PLC0415
        sr = ScreenReaderAnnouncer()
        if sr.active:
            _win_fallback = sr
    except Exception:
        pass
    return _win_fallback


# ---------------------------------------------------------------------------
# Öffentliche API
# ---------------------------------------------------------------------------

def speak(text: str, interrupt: bool = False) -> None:
    """Spricht ``text`` über den aktiven Screen Reader."""
    if not text:
        return
    if sys.platform == "darwin":
        _speak_macos(text)
        return
    # Windows / Linux: SRAL zuerst, dann Windows-Fallback
    s = _load_sral()
    if s is not None:
        try:
            s.speak(text, interrupt=interrupt)
            return
        except Exception:
            pass
    fb = _load_win_fallback()
    if fb is not None:
        try:
            fb.speak(text, interrupt=interrupt)
        except Exception:
            pass


def braille(text: str) -> bool:
    """Gibt ``text`` auf der Braillezeile aus.

    macOS: no-op (VoiceOver leitet NSAccessibility-Announcements automatisch
    an angeschlossene Braillezeilen weiter).
    Windows / Linux: SRAL (BRLTTY / libbrlapi).
    """
    if sys.platform == "darwin":
        return False
    s = _load_sral()
    if s is not None:
        try:
            return bool(s.braille(text))
        except Exception:
            pass
    return False


def output(text: str, interrupt: bool = False) -> None:
    """Spricht ``text`` und gibt ihn auf der Braillezeile aus (kombiniert)."""
    if not text:
        return
    if sys.platform == "darwin":
        _speak_macos(text)
        return
    s = _load_sral()
    if s is not None:
        try:
            s.output(text, interrupt=interrupt)
            return
        except Exception:
            pass
    # Fallback: nur Sprache
    speak(text, interrupt=interrupt)


def stop() -> None:
    """Stoppt die laufende Sprachausgabe."""
    if sys.platform == "darwin":
        return
    s = _load_sral()
    if s is not None:
        try:
            s.stop_speech()
        except Exception:
            pass
    fb = _load_win_fallback()
    if fb is not None:
        try:
            fb.silence()
        except Exception:
            pass


def is_available() -> bool:
    """True wenn ein Screen Reader aktiv erkannt wurde."""
    if sys.platform == "darwin":
        try:
            import AppKit  # noqa: PLC0415
            return bool(AppKit.NSWorkspace.sharedWorkspace().isVoiceOverEnabled())
        except Exception:
            return False
    return _load_sral() is not None or _load_win_fallback() is not None
