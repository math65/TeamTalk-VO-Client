from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QWidget, QHBoxLayout

from ui_qt.tabs.channels import ChannelsTab
from ui_qt.tabs.chat import ChatTab

if TYPE_CHECKING:
    from app_qt import MainWindow


class ChannelsChatTab(QWidget):
    """Tab 2+3: Kanäle und Chat nebeneinander."""

    def __init__(self, parent: QWidget, window: "MainWindow") -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.channels_tab = ChannelsTab(self, window)
        self.chat_tab = ChatTab(self, window)
        layout.addWidget(self.channels_tab, 1)
        layout.addWidget(self.chat_tab, 1)
