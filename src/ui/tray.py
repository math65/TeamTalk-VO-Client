from __future__ import annotations

import wx
import wx.adv


class TrayIcon(wx.adv.TaskBarIcon):
    def __init__(self, frame: wx.Frame) -> None:
        super().__init__()
        self.frame = frame
        self._icon = wx.Icon(wx.ArtProvider.GetBitmap(wx.ART_INFORMATION, wx.ART_OTHER, (16, 16)))
        self.SetIcon(self._icon, "TeamTalk VoiceOver Client")
        self.Bind(wx.adv.EVT_TASKBAR_LEFT_DCLICK, self.on_show)

    def CreatePopupMenu(self):
        menu = wx.Menu()
        show = menu.Append(wx.ID_ANY, "Anzeigen")
        quit_item = menu.Append(wx.ID_ANY, "Beenden")
        self.Bind(wx.EVT_MENU, self.on_show, show)
        self.Bind(wx.EVT_MENU, self.on_quit, quit_item)
        return menu

    def on_show(self, _event):
        self.frame.Show()
        self.frame.Raise()

    def on_quit(self, _event):
        self.frame.force_close()
