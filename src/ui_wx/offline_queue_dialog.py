"""Offline-Warteschlangen-Verwaltung: zeigt und verwaltet gepufferte Nachrichten."""
from __future__ import annotations

import wx


class OfflineQueueDialog(wx.Dialog):
    def __init__(self, parent, offline_queue):
        super().__init__(
            parent,
            title="Offline-Warteschlange",
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self._oq = offline_queue

        accel = wx.AcceleratorTable([(wx.ACCEL_CMD, ord("W"), wx.ID_CLOSE)])
        self.SetAcceleratorTable(accel)
        self.Bind(wx.EVT_MENU, lambda e: self.EndModal(wx.ID_CANCEL), id=wx.ID_CLOSE)

        root = wx.BoxSizer(wx.VERTICAL)

        root.Add(
            wx.StaticText(self, label="Nachrichten, die im Offline-Modus gepuffert wurden:"),
            0, wx.ALL, 8,
        )

        self._lb = wx.ListBox(self, style=wx.LB_SINGLE)
        self._lb.SetName("Offline-Warteschlange")
        self._lb.SetMinSize((480, 280))
        root.Add(self._lb, 1, wx.LEFT | wx.RIGHT | wx.EXPAND, 8)

        self._info = wx.StaticText(self, label="")
        root.Add(self._info, 0, wx.LEFT | wx.TOP, 8)

        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        clear_btn = wx.Button(self, label="&Alle verwerfen")
        close_btn = wx.Button(self, wx.ID_CLOSE, label="&Schließen")
        btn_row.Add(clear_btn, 0, wx.RIGHT, 4)
        btn_row.Add(close_btn, 0)
        root.Add(btn_row, 0, wx.ALL | wx.ALIGN_RIGHT, 8)

        self.SetSizer(root)
        self.Fit()
        self.CentreOnParent()

        self._fill()

        clear_btn.Bind(wx.EVT_BUTTON, self._on_clear)
        close_btn.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_CLOSE))

    def _fill(self):
        self._lb.Clear()
        items = self._oq.peek()
        for m in items:
            target = m.target_name or str(m.target_id)
            self._lb.Append(f"[{m.age_str} alt] → {target} ({m.target_type}): {m.text}")
        self._info.SetLabel(f"{len(items)} Nachrichten ausstehend")

    def _on_clear(self, _evt):
        self._oq.clear()
        self._lb.Clear()
        self._info.SetLabel("Warteschlange geleert")
