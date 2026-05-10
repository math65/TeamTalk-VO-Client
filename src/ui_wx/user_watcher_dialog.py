"""Nutzerwatcher: Benachrichtigung wenn bestimmte Nutzer den Server betreten."""
from __future__ import annotations

import wx


class UserWatcherDialog(wx.Dialog):
    def __init__(self, parent, settings_store):
        super().__init__(
            parent,
            title="Nutzerwatcher",
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self._store = settings_store
        self._names = list(getattr(settings_store.settings, "watched_users", []) or [])

        accel = wx.AcceleratorTable([(wx.ACCEL_CMD, ord("W"), wx.ID_CLOSE)])
        self.SetAcceleratorTable(accel)
        self.Bind(wx.EVT_MENU, lambda e: self.EndModal(wx.ID_CANCEL), id=wx.ID_CLOSE)

        root = wx.BoxSizer(wx.VERTICAL)

        root.Add(
            wx.StaticText(self, label="Beobachtete Nutzernamen (eine Benachrichtigung beim Beitreten):"),
            0, wx.ALL, 8,
        )

        self._lb = wx.ListBox(self, style=wx.LB_SINGLE)
        self._lb.SetName("Beobachtete Nutzer")
        self._lb.SetMinSize((350, 250))
        for n in self._names:
            self._lb.Append(n)
        root.Add(self._lb, 1, wx.LEFT | wx.RIGHT | wx.EXPAND, 8)

        add_row = wx.BoxSizer(wx.HORIZONTAL)
        self._name_field = wx.TextCtrl(self, size=(220, -1))
        self._name_field.SetName("Nutzername")
        add_btn = wx.Button(self, label="&Hinzufügen")
        add_row.Add(self._name_field, 1, wx.RIGHT, 4)
        add_row.Add(add_btn, 0)
        root.Add(add_row, 0, wx.ALL | wx.EXPAND, 8)

        remove_btn = wx.Button(self, label="&Entfernen")
        root.Add(remove_btn, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        save_btn = wx.Button(self, label="&Speichern")
        close_btn = wx.Button(self, wx.ID_CLOSE, label="&Schließen")
        btn_row.Add(save_btn, 0, wx.RIGHT, 4)
        btn_row.Add(close_btn, 0)
        root.Add(btn_row, 0, wx.ALL | wx.ALIGN_RIGHT, 8)

        self.SetSizer(root)
        self.Fit()
        self.CentreOnParent()

        add_btn.Bind(wx.EVT_BUTTON, self._on_add)
        self._name_field.Bind(wx.EVT_TEXT_ENTER, self._on_add)
        remove_btn.Bind(wx.EVT_BUTTON, self._on_remove)
        save_btn.Bind(wx.EVT_BUTTON, self._on_save)
        close_btn.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_CLOSE))

    def _on_add(self, _evt):
        name = self._name_field.GetValue().strip()
        if not name or name in self._names:
            return
        self._names.append(name)
        self._lb.Append(name)
        self._name_field.Clear()

    def _on_remove(self, _evt):
        idx = self._lb.GetSelection()
        if idx == wx.NOT_FOUND:
            return
        self._names.pop(idx)
        self._lb.Delete(idx)

    def _on_save(self, _evt):
        self._store.settings.watched_users = list(self._names)
        self._store.save()
        self.EndModal(wx.ID_OK)
