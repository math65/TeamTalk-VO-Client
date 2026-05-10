"""Per-Server-Audioprofil: Audioprofil für einen Server festlegen."""
from __future__ import annotations

import wx


class ServerAudioProfileDialog(wx.Dialog):
    """Ordnet Audioprofilen bestimmte Server zu."""

    def __init__(self, parent, settings_store):
        super().__init__(
            parent,
            title="Per-Server-Audioprofile",
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self._store = settings_store
        s = settings_store.settings
        self._mapping = dict(getattr(s, "server_audio_profiles", {}) or {})
        profiles = list(getattr(s, "sound_profiles", []) or [])
        self._profile_names = ["(kein)"] + [p.get("name", "?") for p in profiles if isinstance(p, dict)]

        accel = wx.AcceleratorTable([(wx.ACCEL_CMD, ord("W"), wx.ID_CLOSE)])
        self.SetAcceleratorTable(accel)
        self.Bind(wx.EVT_MENU, lambda e: self.EndModal(wx.ID_CANCEL), id=wx.ID_CLOSE)

        root = wx.BoxSizer(wx.VERTICAL)
        root.Add(
            wx.StaticText(self, label="Server-Schlüssel → Audioprofil (automatisch beim Verbinden angewendet):"),
            0, wx.ALL, 8,
        )

        self._lb = wx.ListBox(self, style=wx.LB_SINGLE)
        self._lb.SetName("Server-Audioprofil-Zuordnungen")
        self._lb.SetMinSize((450, 220))
        self._refresh_lb()
        root.Add(self._lb, 1, wx.LEFT | wx.RIGHT | wx.EXPAND, 8)

        add_box = wx.StaticBoxSizer(wx.StaticBox(self, label="Zuordnung hinzufügen"), wx.VERTICAL)
        row1 = wx.BoxSizer(wx.HORIZONTAL)
        row1.Add(wx.StaticText(self, label="Server:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self._server_field = wx.TextCtrl(self, size=(200, -1))
        self._server_field.SetName("Server-Schlüssel")
        row1.Add(self._server_field, 1)
        add_box.Add(row1, 0, wx.ALL | wx.EXPAND, 4)

        row2 = wx.BoxSizer(wx.HORIZONTAL)
        row2.Add(wx.StaticText(self, label="Profil:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self._profile_choice = wx.Choice(self, choices=self._profile_names)
        self._profile_choice.SetSelection(0)
        self._profile_choice.SetName("Audioprofil")
        row2.Add(self._profile_choice, 1)
        add_box.Add(row2, 0, wx.ALL | wx.EXPAND, 4)

        add_btn = wx.Button(self, label="&Hinzufügen / Aktualisieren")
        add_box.Add(add_btn, 0, wx.ALL, 4)
        root.Add(add_box, 0, wx.ALL | wx.EXPAND, 8)

        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        remove_btn = wx.Button(self, label="Auswahl &entfernen")
        save_btn = wx.Button(self, label="&Speichern")
        close_btn = wx.Button(self, wx.ID_CLOSE, label="&Schließen")
        btn_row.Add(remove_btn, 0, wx.RIGHT, 4)
        btn_row.Add(save_btn, 0, wx.RIGHT, 4)
        btn_row.Add(close_btn, 0)
        root.Add(btn_row, 0, wx.ALL | wx.ALIGN_RIGHT, 8)

        self.SetSizer(root)
        self.Fit()
        self.CentreOnParent()

        add_btn.Bind(wx.EVT_BUTTON, self._on_add)
        remove_btn.Bind(wx.EVT_BUTTON, self._on_remove)
        save_btn.Bind(wx.EVT_BUTTON, self._on_save)
        close_btn.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_CLOSE))

    def _refresh_lb(self):
        self._lb.Clear()
        for k, v in self._mapping.items():
            self._lb.Append(f"{k} → {v or '(kein)'}")

    def _on_add(self, _evt):
        server = self._server_field.GetValue().strip()
        if not server:
            return
        idx = self._profile_choice.GetSelection()
        profile = "" if idx <= 0 else self._profile_names[idx]
        if profile:
            self._mapping[server] = profile
        elif server in self._mapping:
            del self._mapping[server]
        self._refresh_lb()
        self._server_field.Clear()

    def _on_remove(self, _evt):
        idx = self._lb.GetSelection()
        if idx == wx.NOT_FOUND:
            return
        keys = list(self._mapping.keys())
        if idx < len(keys):
            del self._mapping[keys[idx]]
        self._refresh_lb()

    def _on_save(self, _evt):
        self._store.settings.server_audio_profiles = dict(self._mapping)
        self._store.save()
        self.EndModal(wx.ID_OK)
