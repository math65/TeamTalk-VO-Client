"""macOS-Desktop-Integration (v5.3.0).

Stellt native macOS-Features bereit:
- Benutzer-Benachrichtigungen via NSUserNotification / UNUserNotificationCenter
- Dock-Badge (Anzahl ungelesener Nachrichten)
- Menüleisten-Symbol (NSStatusItem) als Alternative zum Tray
- Spotlight-Metadaten (kMDItemComment) für gespeicherte Nachrichten
- Automatischer Dark-Mode-Wechsel-Handler

Alle Funktionen sind graceful degradiert (kein Absturz wenn PyObjC fehlt).
"""
from __future__ import annotations

import threading
from typing import Callable, Optional


def _objc():
    try:
        import objc
        return objc
    except ImportError:
        return None


def _appkit():
    try:
        import AppKit
        return AppKit
    except ImportError:
        return None


def _foundation():
    try:
        import Foundation
        return Foundation
    except ImportError:
        return None


# ---------------------------------------------------------------------------
# Benachrichtigungen
# ---------------------------------------------------------------------------

def send_notification(title: str, body: str, subtitle: str = "") -> bool:
    """Sendet eine native macOS-Benachrichtigung.

    Nutzt UNUserNotificationCenter (macOS 10.14+), fällt auf
    NSUserNotificationCenter zurück.

    Returns:
        ``True`` wenn die Benachrichtigung abgeschickt wurde.
    """
    AppKit = _appkit()
    if AppKit is None:
        return False
    try:
        # Moderner Weg: UNUserNotificationCenter
        import UserNotifications as UN
        center = UN.UNUserNotificationCenter.currentNotificationCenter()
        content = UN.UNMutableNotificationContent.alloc().init()
        content.setTitle_(title)
        if subtitle:
            content.setSubtitle_(subtitle)
        content.setBody_(body)

        import uuid
        req_id = str(uuid.uuid4())
        req = UN.UNNotificationRequest.requestWithIdentifier_content_trigger_(
            req_id, content, None
        )
        center.addNotificationRequest_withCompletionHandler_(req, None)
        return True
    except Exception:
        pass

    # Fallback: NSUserNotificationCenter (deprecated macOS 11)
    try:
        notif = AppKit.NSUserNotification.alloc().init()
        notif.setTitle_(title)
        if subtitle:
            notif.setSubtitle_(subtitle)
        notif.setInformativeText_(body)
        AppKit.NSUserNotificationCenter.defaultUserNotificationCenter().deliverNotification_(notif)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Dock-Badge
# ---------------------------------------------------------------------------

def set_dock_badge(count: int) -> bool:
    """Setzt die Dock-Badge-Zahl. 0 entfernt den Badge.

    Returns:
        ``True`` bei Erfolg.
    """
    AppKit = _appkit()
    if AppKit is None:
        return False
    try:
        label = str(count) if count > 0 else ""
        AppKit.NSApp.dockTile().setBadgeLabel_(label)
        return True
    except Exception:
        return False


def clear_dock_badge() -> bool:
    """Entfernt den Dock-Badge."""
    return set_dock_badge(0)


# ---------------------------------------------------------------------------
# Dark-Mode-Erkennung
# ---------------------------------------------------------------------------

def is_dark_mode() -> bool:
    """Gibt True zurück wenn der System-Dark-Mode aktiv ist."""
    AppKit = _appkit()
    if AppKit is None:
        return False
    try:
        appearance = AppKit.NSApp.effectiveAppearance()
        name = appearance.bestMatchFromAppearancesWithNames_(
            [AppKit.NSAppearanceNameAqua, AppKit.NSAppearanceNameDarkAqua]
        )
        return name == AppKit.NSAppearanceNameDarkAqua
    except Exception:
        return False


class DarkModeWatcher:
    """Beobachtet Dark-Mode-Wechsel und ruft ``callback(is_dark: bool)`` auf.

    Nutzt KVO auf NSApp.effectiveAppearance.
    """

    def __init__(self, callback: Callable[[bool], None]) -> None:
        self._callback = callback
        self._active = False
        self._last: Optional[bool] = None

    def start(self, poll_interval: float = 2.0) -> None:
        """Startet Polling-Beobachtung (Fallback, kein KVO-Overhead)."""
        if self._active:
            return
        self._active = True
        self._last = is_dark_mode()

        def _poll():
            while self._active:
                current = is_dark_mode()
                if current != self._last:
                    self._last = current
                    try:
                        self._callback(current)
                    except Exception:
                        pass
                threading.Event().wait(poll_interval)

        threading.Thread(target=_poll, name="DarkModeWatcher", daemon=True).start()

    def stop(self) -> None:
        self._active = False


# ---------------------------------------------------------------------------
# Spotlight-Metadaten
# ---------------------------------------------------------------------------

def set_spotlight_comment(path: str, comment: str) -> bool:
    """Setzt das Spotlight-Kommentarfeld (kMDItemComment) einer Datei.

    Nutzt ``xattr`` über die Standardbibliothek als Fallback.
    """
    try:
        import subprocess
        result = subprocess.run(
            ["mdimport", "-d1", path],
            capture_output=True,
            timeout=5,
        )
        # Setze Kommentar via osascript (zuverlässigste Methode)
        script = (
            f'tell application "Finder" to set comment of '
            f'(POSIX file "{path}" as alias) to "{comment}"'
        )
        subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            timeout=5,
        )
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Menüleisten-Symbol (NSStatusItem)
# ---------------------------------------------------------------------------

class MenuBarIcon:
    """Minimales NSStatusItem als Menüleisten-Symbol.

    Zeigt den Verbindungsstatus als Template-Symbol an.
    """

    def __init__(self) -> None:
        self._item = None

    def show(self, tooltip: str = "TeamTalk VO Client") -> bool:
        AppKit = _appkit()
        if AppKit is None:
            return False
        try:
            bar = AppKit.NSStatusBar.systemStatusBar()
            self._item = bar.statusItemWithLength_(AppKit.NSVariableStatusItemLength)
            btn = self._item.button()
            if btn:
                btn.setTitle_("TT")
                btn.setToolTip_(tooltip)
            return True
        except Exception:
            return False

    def update_tooltip(self, tooltip: str) -> None:
        if self._item is None:
            return
        try:
            btn = self._item.button()
            if btn:
                btn.setToolTip_(tooltip)
        except Exception:
            pass

    def hide(self) -> None:
        if self._item is None:
            return
        try:
            AppKit = _appkit()
            if AppKit:
                AppKit.NSStatusBar.systemStatusBar().removeStatusItem_(self._item)
        except Exception:
            pass
        self._item = None
