"""system_audio – Systemton-Erkennung und Loopback-Geräte-Klassifikation.

Erkennt auf allen Plattformen virtuelle Audio-Loopback-Geräte in der
TeamTalk-Geräteliste und markiert sie für die UI.

Auf macOS: Erkennt BlackHole und bietet eine Installationshilfe an,
sofern das gebündelte PKG unter third_party/blackhole/ vorhanden ist.

Öffentliche API
---------------
classify_devices(devices, tt_str)   -> list[DeviceEntry]
is_loopback_installed()             -> bool   (macOS: BlackHole vorhanden?)
open_loopback_installer(parent)     -> None   (macOS: PKG starten / brew / web)
loopback_hint()                     -> str    (Hinweistext je Plattform)
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Callable, List, Optional

_IS_MAC = sys.platform == "darwin"
_IS_WIN = sys.platform == "win32"
_IS_LINUX = sys.platform.startswith("linux")

# Namensbestandteile die auf Loopback/Monitor-Geräte hinweisen (Kleinbuchstaben)
_LOOPBACK_KEYWORDS = (
    "blackhole",        # macOS BlackHole (2ch, 16ch)
    "soundflower",      # macOS Soundflower (veraltet)
    "loopback",         # Windows/Linux generisch, Rogue Amoeba Loopback
    "stereo mix",       # Windows: Realtek-Treiber
    "what u hear",      # Windows: Creative-Treiber
    "wave out mix",     # Windows: ältere Realtek-Treiber
    "cable output",     # Windows: VB-Audio Virtual Cable
    "virtual audio",    # generisch (VB-Audio, VoiceMeeter)
    "voicemeeter",      # Windows: VoiceMeeter
    "monitor of",       # Linux: PulseAudio-Monitor-Quellen
    "pulse audio monitor",
)

# Namensbestandteile speziell für BlackHole (macOS)
_BLACKHOLE_KEYWORDS = ("blackhole",)


# ---------------------------------------------------------------------------
# Datentyp
# ---------------------------------------------------------------------------

@dataclass
class DeviceEntry:
    """Angereicherte Gerätebeschreibung für die UI."""
    device: object          # Original-TT-Geräteobjekt
    label: str              # Anzeigename (ggf. mit [Systemton]-Markierung)
    is_loopback: bool       # True wenn Loopback/Monitor-Gerät erkannt


# Namensbestandteile die auf echte eingebaute Hardware hinweisen
_PREFER_KEYWORDS = ("built-in", "internal", "macbook", "eingebaut", "mikrofon", "microphone", "headset")


# ---------------------------------------------------------------------------
# Geräteklassifikation
# ---------------------------------------------------------------------------

def classify_devices(
    devices: list,
    tt_str: Callable[[object], str],
) -> List[DeviceEntry]:
    """Klassifiziert TT-Geräteobjekte und fügt Loopback-Markierung hinzu.

    Args:
        devices:  Liste von TT-Geräteobjekten (mit szDeviceName).
        tt_str:   Callback zum Dekodieren von TT-Strings (frame.tt_str).

    Returns:
        Liste von DeviceEntry; Loopback-Geräte erhalten das Präfix "[Systemton] ".
    """
    result: List[DeviceEntry] = []
    for dev in devices:
        name = tt_str(dev.szDeviceName)
        loopback = _is_loopback_name(name)
        label = f"[Systemton] {name}" if loopback else name
        result.append(DeviceEntry(device=dev, label=label, is_loopback=loopback))
    return result


def preferred_input_device(devices: list, tt_str: Callable[[object], str]):
    """Wählt das beste echte Eingabegerät; bevorzugt eingebaute Hardware vor virtuellen.

    Gibt das erste Gerät zurück das nicht in _LOOPBACK_KEYWORDS ist und
    möglichst _PREFER_KEYWORDS enthält. Wenn alle Geräte virtuell sind,
    wird das erste zurückgegeben.
    """
    if not devices:
        return None
    non_loopback = [d for d in devices if not _is_loopback_name(tt_str(d.szDeviceName))]
    candidates = non_loopback if non_loopback else devices
    for d in candidates:
        name = tt_str(d.szDeviceName).lower()
        if any(kw in name for kw in _PREFER_KEYWORDS):
            return d
    return candidates[0]


def _is_loopback_name(name: str) -> bool:
    lower = name.lower()
    return any(kw in lower for kw in _LOOPBACK_KEYWORDS)


def _is_blackhole_name(name: str) -> bool:
    lower = name.lower()
    return any(kw in lower for kw in _BLACKHOLE_KEYWORDS)


# ---------------------------------------------------------------------------
# macOS: BlackHole-Erkennung
# ---------------------------------------------------------------------------

def is_loopback_installed() -> bool:
    """Gibt True zurück wenn ein bekanntes Loopback-Gerät gefunden wird.

    Nutzt PyAudio für die Abfrage (schnell, kein SDK nötig).
    Funktioniert plattformübergreifend; auf Windows/Linux fast immer True
    weil Stereo-Mix oder PulseAudio-Monitor standardmäßig vorhanden sind.
    """
    try:
        import pyaudio
        pa = pyaudio.PyAudio()
        try:
            for i in range(pa.get_device_count()):
                info = pa.get_device_info_by_index(i)
                if info.get("maxInputChannels", 0) > 0:
                    if _is_loopback_name(str(info.get("name", ""))):
                        return True
            return False
        finally:
            pa.terminate()
    except Exception:
        return False


def is_blackhole_installed() -> bool:
    """macOS: True wenn BlackHole als CoreAudio-Gerät erkannt wird."""
    if not _IS_MAC:
        return False
    try:
        import pyaudio
        pa = pyaudio.PyAudio()
        try:
            for i in range(pa.get_device_count()):
                info = pa.get_device_info_by_index(i)
                if _is_blackhole_name(str(info.get("name", ""))):
                    return True
            return False
        finally:
            pa.terminate()
    except Exception:
        return False


# ---------------------------------------------------------------------------
# macOS: BlackHole installieren
# ---------------------------------------------------------------------------

def _bundled_pkg_path() -> Optional[str]:
    """Sucht das gebündelte BlackHole-PKG relativ zur laufenden App."""
    # Im Entwicklungsmodus: src/../third_party/blackhole/
    candidates = [
        os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "third_party", "blackhole", "BlackHole2ch.pkg",
        ),
        # Im PyInstaller-Bundle: <bundle>/Contents/MacOS/third_party/blackhole/
        os.path.join(
            os.path.dirname(sys.executable),
            "third_party", "blackhole", "BlackHole2ch.pkg",
        ),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def open_loopback_installer(parent=None) -> None:
    """Öffnet den BlackHole-Installer (macOS) oder zeigt einen Hinweis.

    Reihenfolge:
    1. Gebündeltes PKG öffnen (falls vorhanden)
    2. Homebrew: brew install blackhole-2ch (falls brew vorhanden)
    3. Fallback: Website-Link via wx.MessageBox
    """
    if not _IS_MAC:
        _show_platform_hint(parent)
        return

    # 1. Gebündeltes PKG
    pkg = _bundled_pkg_path()
    if pkg:
        # PKG in temp-Verzeichnis kopieren und öffnen (Sandbox-Kompatibilität)
        import tempfile
        tmp = tempfile.mkdtemp()
        tmp_pkg = os.path.join(tmp, "BlackHole2ch.pkg")
        shutil.copy2(pkg, tmp_pkg)
        subprocess.Popen(["open", tmp_pkg])
        _info(
            parent,
            "BlackHole-Installer wurde gestartet.\n\n"
            "Folgen Sie den Anweisungen des Installers. "
            "Starten Sie danach die Audio-Geräte in diesem Fenster neu.",
        )
        return

    # 2. Homebrew
    brew = shutil.which("brew")
    if brew:
        try:
            ret = subprocess.run(
                [brew, "install", "blackhole-2ch"],
                capture_output=True, timeout=120,
            )
            if ret.returncode == 0:
                _info(
                    parent,
                    'BlackHole wurde via Homebrew installiert.\n\n'
                    'Klicken Sie auf "Geräte aktualisieren" um das neue Gerät zu sehen.',
                )
                return
        except Exception:
            pass

    # 3. Fallback: Hinweistext
    _info(
        parent,
        "BlackHole ist nicht installiert.\n\n"
        "Installationsoptionen:\n"
        "  Homebrew:  brew install blackhole-2ch\n"
        "  Download:  existingaudio.com/BlackHole\n\n"
        'Nach der Installation "Geräte aktualisieren" klicken.',
    )


def _show_platform_hint(parent=None) -> None:
    """Zeigt einen plattformspezifischen Hinweis (Windows/Linux)."""
    _info(parent, loopback_hint())


def _info(parent, msg: str) -> None:
    try:
        import wx
        wx.MessageBox(msg, "Systemton", wx.OK | wx.ICON_INFORMATION, parent)
    except Exception:
        print(msg)


# ---------------------------------------------------------------------------
# Plattform-Hinweistexte
# ---------------------------------------------------------------------------

def loopback_hint() -> str:
    """Gibt einen Hinweistext zurück der erklärt wie Systemton aktiviert wird."""
    if _IS_MAC:
        if is_blackhole_installed():
            return (
                'BlackHole erkannt. Wählen Sie "[Systemton] BlackHole 2ch" '
                "als Eingabegerät und wenden Sie Audio an."
            )
        return (
            "Für Systemton-Übertragung wird BlackHole benötigt.\n"
            'Klicken Sie auf "BlackHole installieren" um fortzufahren.'
        )
    if _IS_WIN:
        return (
            'Wählen Sie "[Systemton] Stereo Mix" (oder "Was du hörst") '
            "als Eingabegerät.\n"
            "Falls kein Systemton-Gerät sichtbar ist: "
            "Systemsteuerung > Sound > Aufnahme > "
            "Rechtsklick > Deaktivierte Geräte anzeigen."
        )
    if _IS_LINUX:
        return (
            'Wählen Sie "[Systemton] Monitor of ..." als Eingabegerät.\n'
            "Falls keines sichtbar ist: "
            "pactl load-module module-loopback eingeben."
        )
    return "Wählen Sie ein Systemton-/Loopback-Gerät als Eingabegerät."
