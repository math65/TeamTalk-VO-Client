from __future__ import annotations

import wx


class ChangeStatusDialog(wx.Dialog):
    def __init__(self, parent: wx.Window) -> None:
        super().__init__(parent, title="Status setzen", style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.SetName("Status setzen")

        accel = wx.AcceleratorTable([(wx.ACCEL_CMD, ord("W"), wx.ID_CLOSE)])
        self.SetAcceleratorTable(accel)
        self.Bind(wx.EVT_MENU, lambda _e: self.Close(), id=wx.ID_CLOSE)

        sizer = wx.BoxSizer(wx.VERTICAL)

        row = wx.BoxSizer(wx.HORIZONTAL)
        row.Add(wx.StaticText(self, label="Status"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.status_choice = wx.Choice(self, choices=["Verfügbar", "Abwesend", "Frage"])
        self.status_choice.SetName("Status Auswahl")
        self.status_choice.SetSelection(0)
        row.Add(self.status_choice, 1, wx.EXPAND)
        sizer.Add(row, 0, wx.ALL | wx.EXPAND, 8)

        sizer.Add(wx.StaticText(self, label="Status-Nachricht"), 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        self.status_message = wx.TextCtrl(self)
        self.status_message.SetName("Status Nachricht")
        sizer.Add(self.status_message, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)

        btns = self.CreateSeparatedButtonSizer(wx.OK | wx.CANCEL)
        if btns:
            sizer.Add(btns, 0, wx.ALL | wx.EXPAND, 8)

        self.SetSizerAndFit(sizer)

    def get_values(self) -> tuple[int, str]:
        return self.status_choice.GetSelection(), self.status_message.GetValue().strip()
