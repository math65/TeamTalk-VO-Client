"""Systemweite Hotkey-Überwachung via NSEvent (macOS-only)."""
from __future__ import annotations

import threading
from typing import Callable, Optional

# Virtual key codes frequently used as hotkeys (macOS)
_VK_NAMES = {
    0x00: "A", 0x01: "S", 0x02: "D", 0x03: "F", 0x04: "H", 0x05: "G",
    0x06: "Z", 0x07: "X", 0x08: "C", 0x09: "V", 0x0B: "B", 0x0C: "Q",
    0x0D: "W", 0x0E: "E", 0x0F: "R", 0x10: "Y", 0x11: "T", 0x12: "1",
    0x13: "2", 0x14: "3", 0x15: "4", 0x16: "6", 0x17: "5", 0x18: "=",
    0x19: "9", 0x1A: "7", 0x1B: "-", 0x1C: "8", 0x1D: "0", 0x1E: "]",
    0x1F: "O", 0x20: "U", 0x21: "[", 0x22: "I", 0x23: "P", 0x25: "L",
    0x26: "J", 0x27: "'", 0x28: "K", 0x29: ";", 0x2A: "\\", 0x2B: ",",
    0x2C: "/", 0x2D: "N", 0x2E: "M", 0x2F: ".", 0x32: "`",
    0x24: "Return", 0x30: "Tab", 0x31: "Leertaste", 0x33: "Backspace",
    0x35: "Escape", 0x36: "Cmd-R", 0x37: "Cmd-L",
    0x38: "Shift-L", 0x39: "CapsLock", 0x3A: "Alt-L", 0x3B: "Ctrl-L",
    0x3C: "Shift-R", 0x3D: "Alt-R", 0x3E: "Ctrl-R",
    0x60: "F5", 0x61: "F6", 0x62: "F7", 0x63: "F3", 0x64: "F8",
    0x65: "F9", 0x67: "F11", 0x69: "F13", 0x6B: "F14",
    0x6D: "F10", 0x6F: "F12", 0x71: "F15",
    0x7A: "F1", 0x78: "F2", 0x76: "F4",
    0x7B: "Links", 0x7C: "Rechts", 0x7D: "Unten", 0x7E: "Oben",
    0x73: "Pos1", 0x74: "Bild-Auf", 0x75: "Entf", 0x77: "Ende",
    0x79: "Bild-Ab",
}


def vk_to_name(vk: int) -> str:
    """Gibt einen lesbaren Namen für einen macOS Virtual Key Code zurück."""
    if not vk:
        return "(nicht gesetzt)"
    return _VK_NAMES.get(vk, f"VK-{vk:#04x}")


class GlobalHotkeyManager:
    """Überwacht systemweite Tastenanschläge via NSEvent.

    Funktioniert nur auf macOS; auf anderen Plattformen werden alle Methoden
    zu No-ops degradiert.
    """

    def __init__(self) -> None:
        self._monitor = None          # global NSEvent monitor
        self._local_monitor = None    # local NSEvent monitor for capture
        self._capture_monitor = None
        self._ptt_vk: int = 0
        self._mute_vk: int = 0
        self._on_ptt_down: Optional[Callable] = None
        self._on_ptt_up: Optional[Callable] = None
        self._on_mute: Optional[Callable] = None
        self._ptt_pressed = False
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._loop = None  # NSRunLoop reference

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(
        self,
        ptt_vk: int,
        mute_vk: int,
        on_ptt_down: Callable,
        on_ptt_up: Callable,
        on_mute: Callable,
    ) -> None:
        self.stop()
        self._ptt_vk = ptt_vk
        self._mute_vk = mute_vk
        self._on_ptt_down = on_ptt_down
        self._on_ptt_up = on_ptt_up
        self._on_mute = on_mute
        self._ptt_pressed = False
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="GlobalHotkeys")
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        self._remove_monitors()
        if self._loop is not None:
            try:
                from AppKit import NSRunLoop, NSDate  # type: ignore
                self._loop.performSelector_target_argument_order_modes_(  # type: ignore
                    "stop:", self._loop, None, 0, None
                )
            except Exception:
                pass
            self._loop = None
        self._thread = None

    def capture_key_vk(self, callback: Callable[[int], None]) -> None:
        """Installiert einen einmaligen lokalen NSEvent-Monitor für die nächste Taste.

        callback wird mit dem macOS Virtual Key Code aufgerufen.
        Läuft im Haupt-Thread (via wx.CallAfter aus dem Haupt-NSRunLoop).
        """
        try:
            import wx
            from AppKit import NSEvent, NSKeyDownMask  # type: ignore

            self._remove_capture_monitor()

            def _handler(event):  # type: ignore
                vk = int(event.keyCode())
                self._remove_capture_monitor()
                wx.CallAfter(callback, vk)
                return event  # pass event through

            self._capture_monitor = NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
                NSKeyDownMask, _handler
            )
        except Exception:
            pass

    def remove_capture_monitor(self) -> None:
        self._remove_capture_monitor()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _remove_monitors(self) -> None:
        try:
            from AppKit import NSEvent  # type: ignore
            if self._monitor is not None:
                NSEvent.removeMonitor_(self._monitor)
                self._monitor = None
        except Exception:
            pass

    def _remove_capture_monitor(self) -> None:
        try:
            from AppKit import NSEvent  # type: ignore
            if self._capture_monitor is not None:
                NSEvent.removeMonitor_(self._capture_monitor)
                self._capture_monitor = None
        except Exception:
            pass

    def _run_loop(self) -> None:
        try:
            import wx
            from AppKit import NSEvent, NSKeyDownMask, NSKeyUpMask, NSRunLoop, NSDate  # type: ignore

            mask = NSKeyDownMask | NSKeyUpMask

            def _handler(event):  # type: ignore
                if not self._running:
                    return
                vk = int(event.keyCode())
                event_type = int(event.type())
                # NSEventTypeKeyDown = 10, NSEventTypeKeyUp = 11
                is_down = (event_type == 10)
                is_up = (event_type == 11)

                if self._ptt_vk and vk == self._ptt_vk:
                    if is_down and not self._ptt_pressed:
                        self._ptt_pressed = True
                        if self._on_ptt_down:
                            wx.CallAfter(self._on_ptt_down)
                    elif is_up and self._ptt_pressed:
                        self._ptt_pressed = False
                        if self._on_ptt_up:
                            wx.CallAfter(self._on_ptt_up)
                elif self._mute_vk and vk == self._mute_vk and is_down:
                    if self._on_mute:
                        wx.CallAfter(self._on_mute)

            self._monitor = NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
                mask, _handler
            )

            self._loop = NSRunLoop.currentRunLoop()
            # Spin the run loop in small increments so we can check _running
            while self._running:
                self._loop.runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.1))

        except Exception:
            pass
        finally:
            self._remove_monitors()
