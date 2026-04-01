"""screen_capture – plattformübergreifende Bildschirm- und Fenster-Aufnahme.

Liefert immer BGRA-Bytes, kompatibel mit TeamTalk BMP_RGB32 (Windows-Bitmap-Format).
mss liefert BGRA direkt → kein Konvertierungsaufwand bei scale=1.0.

Öffentliche API
---------------
list_monitors()                                    -> list[MonitorInfo]
list_windows()                                     -> list[WindowInfo]
capture_screen(monitor_idx, region, scale)         -> CaptureResult | None
capture_window(window, scale)                      -> CaptureResult | None
is_wayland()                                       -> bool
has_mss()                                          -> bool
"""
from __future__ import annotations

import os
import sys
import subprocess
from dataclasses import dataclass
from typing import Optional

# ---------------------------------------------------------------------------
# Plattform-Erkennung
# ---------------------------------------------------------------------------

_IS_MAC = sys.platform == "darwin"
_IS_WIN = sys.platform == "win32"
_IS_LINUX = sys.platform.startswith("linux")
_IS_WAYLAND = _IS_LINUX and bool(
    os.environ.get("WAYLAND_DISPLAY")
    or os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"
)


def is_wayland() -> bool:
    return _IS_WAYLAND


def has_mss() -> bool:
    try:
        import mss  # noqa: F401
        return True
    except ImportError:
        return False


# ---------------------------------------------------------------------------
# Datentypen
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MonitorInfo:
    index: int          # 1-basiert (mss-Konvention; 0 = alle kombiniert)
    left: int
    top: int
    width: int
    height: int

    def __str__(self) -> str:
        return f"Monitor {self.index} ({self.width}\u00d7{self.height})"


@dataclass(frozen=True)
class WindowInfo:
    window_id: object   # int (macOS/Win/X11) – nur intern verwendet
    title: str
    app_name: str
    left: int
    top: int
    width: int
    height: int

    def __str__(self) -> str:
        app = self.app_name or ""
        title = self.title or ""
        if app and title and app != title:
            return f"{app}: {title}"
        return app or title or "(Kein Titel)"


@dataclass(frozen=True)
class CaptureResult:
    data: bytes    # BGRA-Bytes (B=Byte 0, G=Byte 1, R=Byte 2, A=Byte 3)
    width: int
    height: int

    @property
    def bytes_per_line(self) -> int:
        return self.width * 4


# ---------------------------------------------------------------------------
# Interne Hilfsfunktionen
# ---------------------------------------------------------------------------

def _scale_bgra(data: bytes, width: int, height: int, scale: float) -> CaptureResult:
    """Skaliert BGRA-Rohdaten. Nutzt numpy (schnell) oder wx-Fallback."""
    new_w = max(1, int(width * scale))
    new_h = max(1, int(height * scale))

    # numpy: nearest-neighbor, kein Channel-Swap nötig
    try:
        import numpy as np  # optionale Abhängigkeit
        arr = np.frombuffer(data, dtype=np.uint8).reshape(height, width, 4)
        y_idx = (np.arange(new_h) * height / new_h).astype(np.int32)
        x_idx = (np.arange(new_w) * width / new_w).astype(np.int32)
        scaled = arr[np.ix_(y_idx, x_idx)].copy()
        return CaptureResult(scaled.tobytes(), new_w, new_h)
    except ImportError:
        pass

    # wx-Fallback: BGRA → PNG → wx.Image (bilinear) → BGRA
    try:
        import mss.tools
        import wx
        png = mss.tools.to_png(data, (width, height))
        stream = wx.MemoryInputStream(bytearray(png))
        img = wx.Image()
        img.LoadFile(stream, wx.BITMAP_TYPE_PNG)
        img = img.Scale(new_w, new_h, wx.IMAGE_QUALITY_NORMAL)
        rgb = bytes(img.GetData())  # wx liefert RGB (3 Byte/Pixel)
        bgra = _rgb_to_bgra(rgb, new_w * new_h)
        return CaptureResult(bgra, new_w, new_h)
    except Exception:
        pass

    return CaptureResult(data, width, height)  # Notfall: unkomprimiert


def _rgb_to_bgra(rgb: bytes, n_pixels: int) -> bytes:
    """Konvertiert RGB- in BGRA-Bytes (Python-Loop, nur für Fallback-Pfade)."""
    out = bytearray(n_pixels * 4)
    for i in range(n_pixels):
        out[i * 4]     = rgb[i * 3 + 2]  # B ← rgb R
        out[i * 4 + 1] = rgb[i * 3 + 1]  # G
        out[i * 4 + 2] = rgb[i * 3]      # R ← rgb B
        out[i * 4 + 3] = 0               # A
    return bytes(out)


def _png_to_capture(png_bytes: bytes) -> Optional[CaptureResult]:
    """Dekodiert PNG-Bytes (z. B. von grim) zu BGRA via wx."""
    try:
        import wx
        stream = wx.MemoryInputStream(bytearray(png_bytes))
        img = wx.Image()
        if not img.LoadFile(stream, wx.BITMAP_TYPE_PNG):
            return None
        w, h = img.GetWidth(), img.GetHeight()
        rgb = bytes(img.GetData())
        bgra = _rgb_to_bgra(rgb, w * h)
        return CaptureResult(bgra, w, h)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Monitor-Liste
# ---------------------------------------------------------------------------

def list_monitors() -> list[MonitorInfo]:
    """Gibt alle verfügbaren Monitore zurück (Index 1 = primärer Monitor)."""
    try:
        import mss
        with mss.mss() as sct:
            return [
                MonitorInfo(
                    index=i,
                    left=m["left"], top=m["top"],
                    width=m["width"], height=m["height"],
                )
                for i, m in enumerate(sct.monitors)
                if i > 0  # Index 0 = alle Monitore kombiniert (überspringen)
            ]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Fensterliste
# ---------------------------------------------------------------------------

def list_windows() -> list[WindowInfo]:
    """Gibt alle sichtbaren Fenster zurück (plattformspezifisch)."""
    if _IS_MAC:
        return _list_windows_macos()
    if _IS_WIN:
        return _list_windows_win32()
    if _IS_LINUX:
        return _list_windows_linux()
    return []


def _list_windows_macos() -> list[WindowInfo]:
    """Fensterliste via Quartz (pyobjc, bereits Abhängigkeit auf macOS)."""
    try:
        from Quartz import (  # type: ignore[import]
            CGWindowListCopyWindowInfo,
            kCGWindowListOptionOnScreenOnly,
            kCGWindowListExcludeDesktopElements,
            kCGNullWindowID,
        )
        options = kCGWindowListOptionOnScreenOnly | kCGWindowListExcludeDesktopElements
        raw = CGWindowListCopyWindowInfo(options, kCGNullWindowID)
        result: list[WindowInfo] = []
        for info in (raw or []):
            bounds = info.get("kCGWindowBounds", {})
            w = int(bounds.get("Width", 0))
            h = int(bounds.get("Height", 0))
            if w < 100 or h < 50:
                continue
            result.append(WindowInfo(
                window_id=int(info.get("kCGWindowNumber", 0)),
                title=info.get("kCGWindowName") or "",
                app_name=info.get("kCGWindowOwnerName") or "",
                left=int(bounds.get("X", 0)),
                top=int(bounds.get("Y", 0)),
                width=w,
                height=h,
            ))
        return result
    except Exception:
        return []


def _list_windows_win32() -> list[WindowInfo]:
    """Fensterliste via win32gui (pywin32)."""
    try:
        import win32gui  # type: ignore[import]
        result: list[WindowInfo] = []

        def _enum_cb(hwnd: int, _: object) -> None:
            if not win32gui.IsWindowVisible(hwnd):
                return
            title = win32gui.GetWindowText(hwnd)
            if not title:
                return
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            w, h = right - left, bottom - top
            if w < 100 or h < 50:
                return
            result.append(WindowInfo(
                window_id=hwnd,
                title=title,
                app_name="",
                left=left, top=top,
                width=w, height=h,
            ))

        win32gui.EnumWindows(_enum_cb, None)
        return result
    except Exception:
        return []


def _list_windows_linux() -> list[WindowInfo]:
    """Fensterliste via xdotool (X11). Wayland: nicht unterstützt."""
    if _IS_WAYLAND:
        return []
    try:
        ids_proc = subprocess.run(
            ["xdotool", "search", "--onlyvisible", "--name", ""],
            capture_output=True, text=True, timeout=3,
        )
        result: list[WindowInfo] = []
        for wid_str in ids_proc.stdout.strip().splitlines():
            try:
                wid = int(wid_str)
            except ValueError:
                continue
            name_proc = subprocess.run(
                ["xdotool", "getwindowname", wid_str],
                capture_output=True, text=True, timeout=2,
            )
            geo_proc = subprocess.run(
                ["xdotool", "getwindowgeometry", "--shell", wid_str],
                capture_output=True, text=True, timeout=2,
            )
            title = name_proc.stdout.strip()
            geo = {
                k: v
                for line in geo_proc.stdout.strip().splitlines()
                if "=" in line
                for k, v in [line.split("=", 1)]
            }
            x = int(geo.get("X", 0))
            y = int(geo.get("Y", 0))
            w = int(geo.get("WIDTH", 0))
            h = int(geo.get("HEIGHT", 0))
            if not title or w < 100 or h < 50:
                continue
            result.append(WindowInfo(
                window_id=wid, title=title, app_name="",
                left=x, top=y, width=w, height=h,
            ))
        return result
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Bildschirm-Capture (Vollbild / Region)
# ---------------------------------------------------------------------------

def capture_screen(
    monitor_idx: int = 1,
    region: Optional[dict] = None,
    scale: float = 1.0,
) -> Optional[CaptureResult]:
    """Nimmt einen Monitor oder eine rechteckige Region auf.

    Args:
        monitor_idx: 1 = primärer Monitor (wird ignoriert wenn region gesetzt).
        region:      Optional {'left', 'top', 'width', 'height'} in Bildschirmpixeln.
        scale:       Skalierungsfaktor 0.25–1.0; 1.0 = original, kein Umwandlungsaufwand.

    Returns:
        CaptureResult (BGRA-Bytes + Dimensionen) oder None bei Fehler.
    """
    if _IS_WAYLAND:
        return _capture_wayland_screen(region)
    try:
        import mss
        with mss.mss() as sct:
            target = region if region else sct.monitors[max(1, monitor_idx)]
            shot = sct.grab(target)
            raw = bytes(shot.raw)  # BGRA direkt aus mss
            if scale < 1.0:
                return _scale_bgra(raw, shot.width, shot.height, scale)
            return CaptureResult(raw, shot.width, shot.height)
    except Exception:
        return None


def _capture_wayland_screen(region: Optional[dict] = None) -> Optional[CaptureResult]:
    """Wayland-Fallback via grim (muss auf dem System installiert sein)."""
    cmd = ["grim", "-"]
    if region:
        x = region.get("left", 0)
        y = region.get("top", 0)
        w = region.get("width", 0)
        h = region.get("height", 0)
        cmd = ["grim", "-g", f"{x},{y} {w}x{h}", "-"]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=5)
        if proc.returncode != 0 or not proc.stdout:
            return None
        return _png_to_capture(proc.stdout)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Fenster-Capture
# ---------------------------------------------------------------------------

def capture_window(window: WindowInfo, scale: float = 1.0) -> Optional[CaptureResult]:
    """Nimmt den Bildschirmbereich eines Fensters auf.

    Schneidet den sichtbaren Bildschirmbereich aus (kein Off-Screen-Rendering).
    Überdeckte Bereiche werden so aufgenommen wie sie am Bildschirm erscheinen.
    """
    if window.width < 1 or window.height < 1:
        return None
    region = {
        "left": max(0, window.left),
        "top":  max(0, window.top),
        "width":  window.width,
        "height": window.height,
    }
    return capture_screen(region=region, scale=scale)
