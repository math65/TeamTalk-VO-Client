"""TTS-Mitschrift-Fenster: zeigt die letzten gesprochenen Texte."""
from __future__ import annotations

import wx


class TTSTranscriptDialog(wx.Dialog):
    def __init__(self, parent, tts_manager):
        super().__init__(
            parent,
            title="TTS-Mitschrift",
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self._tts = tts_manager

        accel = wx.AcceleratorTable([(wx.ACCEL_CMD, ord("W"), wx.ID_CLOSE)])
        self.SetAcceleratorTable(accel)
        self.Bind(wx.EVT_MENU, lambda e: self.EndModal(wx.ID_CANCEL), id=wx.ID_CLOSE)

        root = wx.BoxSizer(wx.VERTICAL)

        self._lb = wx.ListBox(self, style=wx.LB_SINGLE)
        self._lb.SetName("TTS-Mitschrift Liste")
        self._lb.SetMinSize((500, 350))
        root.Add(self._lb, 1, wx.EXPAND | wx.ALL, 8)

        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        refresh_btn = wx.Button(self, label="&Aktualisieren")
        clear_btn = wx.Button(self, label="&Leeren")
        close_btn = wx.Button(self, wx.ID_CLOSE, label="&Schließen")
        btn_row.Add(refresh_btn, 0, wx.RIGHT, 4)
        btn_row.Add(clear_btn, 0, wx.RIGHT, 4)
        btn_row.Add(close_btn, 0)
        root.Add(btn_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        self.SetSizer(root)
        self.Fit()
        self.CentreOnParent()

        self._fill()

        refresh_btn.Bind(wx.EVT_BUTTON, lambda _e: self._fill())
        clear_btn.Bind(wx.EVT_BUTTON, self._on_clear)
        close_btn.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_CLOSE))

    def _fill(self):
        self._lb.Clear()
        for ts, kind, text in list(self._tts._transcript):
            self._lb.Append(f"{ts}, {kind}: {text}")
        if self._lb.GetCount():
            self._lb.SetSelection(self._lb.GetCount() - 1)

    def _on_clear(self, _evt):
        self._tts._transcript.clear()
        self._lb.Clear()
