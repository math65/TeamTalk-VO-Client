from __future__ import annotations

from PySide6.QtWidgets import QSystemTrayIcon, QMenu
from PySide6.QtGui import QIcon
from PySide6.QtCore import QObject

from i18n import _


class TrayIcon(QObject):
    def __init__(self, window) -> None:
        super().__init__()
        self._window = window
        self._tray = QSystemTrayIcon()
        self._tray.setIcon(QIcon.fromTheme("dialog-information"))
        self._tray.setToolTip("TeamTalk VoiceOver Client")

        menu = QMenu()
        show_action = menu.addAction(_("Anzeigen"))
        quit_action = menu.addAction(_("Beenden"))
        show_action.triggered.connect(self._on_show)
        quit_action.triggered.connect(self._on_quit)
        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._on_activated)
        self._tray.show()

    def _on_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._on_show()

    def _on_show(self):
        self._window.show()
        self._window.raise_()
        self._window.activateWindow()

    def _on_quit(self):
        self._window.force_close()

    def hide(self):
        self._tray.hide()
