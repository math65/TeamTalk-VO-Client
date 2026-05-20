from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QWidget, QVBoxLayout, QSplitter
from PySide6.QtCore import Qt

from ui_qt.tabs.channels import ChannelsTab
from ui_qt.tabs.chat import ChatTab

if TYPE_CHECKING:
    from app_qt import MainWindow


class ChannelsChatTab(QWidget):
    """Tab 2+3: Kanäle und Chat nebeneinander (mit ziehbarem Splitter)."""

    def __init__(self, parent: QWidget, window: "MainWindow") -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        self.channels_tab = ChannelsTab(splitter, window)
        self.chat_tab = ChatTab(splitter, window)
        splitter.addWidget(self.channels_tab)
        splitter.addWidget(self.chat_tab)
        splitter.setSizes([380, 620])
        layout.addWidget(splitter)
