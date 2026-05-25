from __future__ import annotations
import wx
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from ui.models import SettingsStore


class ChangeStatusDialog(wx.Dialog):
    def __init__(self, parent: wx.Window, settings_store: "SettingsStore" = None) -> None:
        super().__init__(parent, title="Status setzen", style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.SetName("Status setzen")
        self._settings_store = settings_store

        accel = wx.AcceleratorTable([(wx.ACCEL_CMD, ord("W"), wx.ID_CLOSE)])
        self.SetAcceleratorTable(accel)
        self.Bind(wx.EVT_MENU, lambda _e: self.Close(), id=wx.ID_CLOSE)

        sizer = wx.BoxSizer(wx.VERTICAL)

        # Status mode
        row = wx.BoxSizer(wx.HORIZONTAL)
        row.Add(wx.StaticText(self, label="Status"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.status_choice = wx.Choice(self, choices=["Verfügbar", "Abwesend", "Frage"])
        self.status_choice.SetName("Status Auswahl")
        self.status_choice.SetSelection(0)
        row.Add(self.status_choice, 1, wx.EXPAND)
        sizer.Add(row, 0, wx.ALL | wx.EXPAND, 8)

        # Saved statuses list
        saved = list(getattr(settings_store.settings if settings_store else None, "saved_statuses", []) or []) if settings_store else []
        if saved:
            sizer.Add(wx.StaticText(self, label="Gespeicherte Nachrichten (Doppelklick zum Übernehmen)"), 0, wx.LEFT | wx.RIGHT, 8)
            self._saved_lb = wx.ListBox(self, choices=saved, style=wx.LB_SINGLE)
            self._saved_lb.SetName("Gespeicherte Status-Nachrichten")
            self._saved_lb.SetMaxSize((-1, 100))
            self._saved_lb.Bind(wx.EVT_LISTBOX_DCLICK, self._on_preset_select)
            self._saved_lb.Bind(wx.EVT_LISTBOX, self._on_preset_select)
            sizer.Add(self._saved_lb, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)
        else:
            self._saved_lb = None

        # Message input
        sizer.Add(wx.StaticText(self, label="Status-Nachricht"), 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        self.status_message = wx.TextCtrl(self)
        self.status_message.SetName("Status Nachricht")
        sizer.Add(self.status_message, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)

        # Save as preset button
        self._save_btn = wx.Button(self, label="Als &Favorit speichern")
        self._save_btn.SetName("Als Favorit speichern")
        self._save_btn.Bind(wx.EVT_BUTTON, self._on_save_preset)
        sizer.Add(self._save_btn, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        btns = self.CreateSeparatedButtonSizer(wx.OK | wx.CANCEL)
        if btns:
            sizer.Add(btns, 0, wx.ALL | wx.EXPAND, 8)

        self.SetSizerAndFit(sizer)

    def _on_preset_select(self, _event) -> None:
        if self._saved_lb is None:
            return
        idx = self._saved_lb.GetSelection()
        if idx != wx.NOT_FOUND:
            self.status_message.SetValue(self._saved_lb.GetString(idx))

    def _on_save_preset(self, _event) -> None:
        text = self.status_message.GetValue().strip()
        if not text or not self._settings_store:
            return
        saved = list(getattr(self._settings_store.settings, "saved_statuses", []) or [])
        if text not in saved:
            saved.append(text)
            self._settings_store.settings.saved_statuses = saved
            try:
                self._settings_store.save()
            except Exception:
                pass
            wx.MessageBox(f'"{text}" gespeichert.', "Favorit gespeichert", wx.ICON_INFORMATION)

    def get_values(self) -> tuple[int, str]:
        return self.status_choice.GetSelection(), self.status_message.GetValue().strip()
