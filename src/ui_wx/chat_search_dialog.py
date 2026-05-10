"""Chat-Verlaufssuche: Durchsucht gespeicherte Chat-Nachrichten."""
from __future__ import annotations

import wx


class ChatSearchDialog(wx.Dialog):
    def __init__(self, parent, chat_history_manager, server_key: str):
        super().__init__(
            parent,
            title="Chat-Verlauf durchsuchen",
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self._chm = chat_history_manager
        self._server_key = server_key
        self._all_entries = []

        accel = wx.AcceleratorTable([(wx.ACCEL_CMD, ord("W"), wx.ID_CLOSE)])
        self.SetAcceleratorTable(accel)
        self.Bind(wx.EVT_MENU, lambda e: self.EndModal(wx.ID_CANCEL), id=wx.ID_CLOSE)

        root = wx.BoxSizer(wx.VERTICAL)

        search_row = wx.BoxSizer(wx.HORIZONTAL)
        search_row.Add(wx.StaticText(self, label="Suche:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self._search_field = wx.TextCtrl(self, size=(300, -1))
        self._search_field.SetName("Suchbegriff")
        search_row.Add(self._search_field, 1, wx.RIGHT, 4)
        search_btn = wx.Button(self, label="&Suchen")
        search_row.Add(search_btn, 0)
        root.Add(search_row, 0, wx.ALL | wx.EXPAND, 8)

        self._lb = wx.ListBox(self, style=wx.LB_SINGLE)
        self._lb.SetName("Suchergebnisse")
        self._lb.SetMinSize((550, 350))
        root.Add(self._lb, 1, wx.LEFT | wx.RIGHT | wx.EXPAND, 8)

        self._result_label = wx.StaticText(self, label="")
        root.Add(self._result_label, 0, wx.LEFT | wx.TOP, 8)

        close_btn = wx.Button(self, wx.ID_CLOSE, label="&Schließen")
        root.Add(close_btn, 0, wx.ALL | wx.ALIGN_RIGHT, 8)

        self.SetSizer(root)
        self.Fit()
        self.CentreOnParent()

        self._load_all()

        search_btn.Bind(wx.EVT_BUTTON, self._on_search)
        self._search_field.Bind(wx.EVT_TEXT_ENTER, self._on_search)
        close_btn.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_CLOSE))

        self._search_field.SetFocus()

    def _load_all(self):
        self._all_entries = self._chm.load(self._server_key)
        self._result_label.SetLabel(f"{len(self._all_entries)} Nachrichten im Verlauf")

    def _on_search(self, _evt):
        query = self._search_field.GetValue().strip().lower()
        self._lb.Clear()
        if not query:
            self._result_label.SetLabel(f"{len(self._all_entries)} Nachrichten im Verlauf")
            return
        hits = [
            e for e in self._all_entries
            if query in e.get("text", "").lower()
        ]
        for e in hits:
            ts = e.get("ts", "")
            text = e.get("text", "")
            self._lb.Append(f"{ts}: {text}")
        self._result_label.SetLabel(f"{len(hits)} Treffer")
        if hits:
            self._lb.SetSelection(0)
