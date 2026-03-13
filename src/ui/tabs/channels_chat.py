from __future__ import annotations

from typing import TYPE_CHECKING

import wx

from ui.tabs.channels import ChannelsTab
from ui.tabs.chat import ChatTab

if TYPE_CHECKING:
    from app import MainFrame


class ChannelsChatTab(wx.Panel):
    """Combined tab: channels + chat."""

    def __init__(self, parent: wx.Window, frame: MainFrame) -> None:
        super().__init__(parent)
        self.frame = frame
        self.SetName("Kanäle und Chat")

        sizer = wx.BoxSizer(wx.VERTICAL)

        splitter = wx.SplitterWindow(self, style=wx.SP_LIVE_UPDATE)
        self.channels_tab = ChannelsTab(splitter, frame)
        self.chat_tab = ChatTab(splitter, frame)

        splitter.SplitHorizontally(self.channels_tab, self.chat_tab, sashPosition=420)
        splitter.SetMinimumPaneSize(160)
        splitter.SetSashGravity(0.6)

        sizer.Add(splitter, 1, wx.ALL | wx.EXPAND, 8)
        self.SetSizer(sizer)

        def _apply_default_sash():
            size = self.GetClientSize()
            if size.height > 0:
                splitter.SetSashPosition(int(size.height * 0.6))

        wx.CallAfter(_apply_default_sash)
