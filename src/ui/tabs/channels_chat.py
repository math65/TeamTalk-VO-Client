from __future__ import annotations

from typing import TYPE_CHECKING

import wx

from ui.tabs.channels import ChannelsTab
from ui.tabs.chat import ChatTab

if TYPE_CHECKING:
    from app import MainFrame


class ChannelsChatTab(wx.Panel):
    """Combined tab: channels (tree, always visible) + chat below."""

    def __init__(self, parent: wx.Window, frame: MainFrame) -> None:
        super().__init__(parent)
        self.frame = frame
        self.SetName("Kanäle und Chat")

        sizer = wx.BoxSizer(wx.VERTICAL)

        # Kanalbaum – nimmt 60 % der verfügbaren Höhe (proportion=3)
        self.channels_tab = ChannelsTab(self, frame)
        sizer.Add(self.channels_tab, 3, wx.LEFT | wx.RIGHT | wx.TOP | wx.EXPAND, 8)

        # Trennlinie
        sizer.Add(wx.StaticLine(self), 0, wx.LEFT | wx.RIGHT | wx.EXPAND, 8)

        # Chat – nimmt 40 % der verfügbaren Höhe (proportion=2)
        self.chat_tab = ChatTab(self, frame)
        sizer.Add(self.chat_tab, 2, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)

        self.SetSizer(sizer)
