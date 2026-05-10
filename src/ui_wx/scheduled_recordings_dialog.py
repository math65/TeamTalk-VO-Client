"""Dialog für geplante Aufnahmen."""
from __future__ import annotations

from typing import List, Optional, TYPE_CHECKING

import wx

from ui_wx.a11y import setup_list_accessible
from scheduled_recordings import ScheduledRecording, ScheduledRecordingManager

if TYPE_CHECKING:
    pass


class ScheduledRecordingsDialog(wx.Dialog):
    """Zeigt alle geplanten Aufnahmen und erlaubt Neu/Bearbeiten/Löschen."""

    def __init__(self, parent: wx.Window, manager: ScheduledRecordingManager) -> None:
        super().__init__(parent, title="Geplante Aufnahmen", size=(640, 440),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self._manager = manager

        sizer = wx.BoxSizer(wx.VERTICAL)

        lbl = wx.StaticText(self, label="Aufnahme, Wochentage, Uhrzeit, Dauer")
        lbl.SetName("Aufnahmeliste Kopfzeile")
        sizer.Add(lbl, 0, wx.LEFT | wx.RIGHT | wx.TOP, 8)

        self.list_box = wx.ListBox(self, style=wx.LB_SINGLE)
        self.list_box.SetName("Geplante Aufnahmen")
        setup_list_accessible(self.list_box)
        self.list_box.SetMinSize((-1, 200))
        sizer.Add(self.list_box, 1, wx.ALL | wx.EXPAND, 8)

        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        self.new_btn = wx.Button(self, label="&Neu")
        self.new_btn.SetName("Neue Aufnahme")
        self.new_btn.Bind(wx.EVT_BUTTON, self._on_new)
        self.edit_btn = wx.Button(self, label="&Bearbeiten")
        self.edit_btn.SetName("Aufnahme bearbeiten")
        self.edit_btn.Bind(wx.EVT_BUTTON, self._on_edit)
        self.delete_btn = wx.Button(self, label="&Löschen")
        self.delete_btn.SetName("Aufnahme löschen")
        self.delete_btn.Bind(wx.EVT_BUTTON, self._on_delete)
        self.toggle_btn = wx.Button(self, label="Ak&tivieren/Deaktivieren")
        self.toggle_btn.SetName("Aufnahme aktivieren oder deaktivieren")
        self.toggle_btn.Bind(wx.EVT_BUTTON, self._on_toggle)
        for btn in (self.new_btn, self.edit_btn, self.delete_btn, self.toggle_btn):
            btn_row.Add(btn, 0, wx.RIGHT, 8)
        sizer.Add(btn_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        close_btn = wx.Button(self, wx.ID_CLOSE, label="&Schließen")
        close_btn.Bind(wx.EVT_BUTTON, lambda _e: self.EndModal(wx.ID_CLOSE))
        sizer.Add(close_btn, 0, wx.ALL | wx.ALIGN_RIGHT, 8)

        self.SetSizer(sizer)
        self._refresh_list()
        self.Centre()

    def _refresh_list(self) -> None:
        sel = self.list_box.GetSelection()
        items = [self._manager.display_label(r) for r in self._manager.items()]
        self.list_box.Set(items)
        if sel != wx.NOT_FOUND and sel < len(items):
            self.list_box.SetSelection(sel)

    def _selected_idx(self) -> Optional[int]:
        idx = self.list_box.GetSelection()
        if idx == wx.NOT_FOUND:
            return None
        items = self._manager.items()
        if idx >= len(items):
            return None
        return idx

    def _on_new(self, _event) -> None:
        dlg = _EditRecordingDialog(self)
        if dlg.ShowModal() == wx.ID_OK:
            rec = dlg.get_result()
            if rec:
                self._manager.add(rec)
                self._refresh_list()
        dlg.Destroy()

    def _on_edit(self, _event) -> None:
        idx = self._selected_idx()
        if idx is None:
            wx.MessageBox("Bitte eine Aufnahme auswählen.", "Hinweis", wx.OK | wx.ICON_INFORMATION, self)
            return
        rec = self._manager.items()[idx]
        dlg = _EditRecordingDialog(self, rec)
        if dlg.ShowModal() == wx.ID_OK:
            updated = dlg.get_result()
            if updated:
                updated.id = rec.id
                self._manager.update(idx, updated)
                self._refresh_list()
        dlg.Destroy()

    def _on_delete(self, _event) -> None:
        idx = self._selected_idx()
        if idx is None:
            wx.MessageBox("Bitte eine Aufnahme auswählen.", "Hinweis", wx.OK | wx.ICON_INFORMATION, self)
            return
        rec = self._manager.items()[idx]
        dlg = wx.MessageDialog(
            self, f"Aufnahme '{rec.label}' wirklich löschen?",
            "Löschen bestätigen", wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION,
        )
        if dlg.ShowModal() == wx.ID_YES:
            self._manager.remove(idx)
            self._refresh_list()
        dlg.Destroy()

    def _on_toggle(self, _event) -> None:
        idx = self._selected_idx()
        if idx is None:
            wx.MessageBox("Bitte eine Aufnahme auswählen.", "Hinweis", wx.OK | wx.ICON_INFORMATION, self)
            return
        self._manager.toggle_enabled(idx)
        self._refresh_list()


class _EditRecordingDialog(wx.Dialog):
    """Eingabedialog zum Erstellen/Bearbeiten einer geplanten Aufnahme."""

    _WEEKDAY_LABELS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]

    def __init__(self, parent: wx.Window, rec: Optional[ScheduledRecording] = None) -> None:
        title = "Aufnahme bearbeiten" if rec else "Neue Aufnahme"
        super().__init__(parent, title=title, style=wx.DEFAULT_DIALOG_STYLE)
        self._result: Optional[ScheduledRecording] = None

        sizer = wx.BoxSizer(wx.VERTICAL)
        form = wx.FlexGridSizer(cols=2, vgap=8, hgap=12)
        form.AddGrowableCol(1)

        # Label
        form.Add(wx.StaticText(self, label="Bezeichnung"), 0, wx.ALIGN_CENTER_VERTICAL)
        self._label = wx.TextCtrl(self, value=rec.label if rec else "")
        self._label.SetName("Bezeichnung")
        form.Add(self._label, 1, wx.EXPAND)

        # Startzeit
        form.Add(wx.StaticText(self, label="Startzeit (HH:MM)"), 0, wx.ALIGN_CENTER_VERTICAL)
        self._start_time = wx.TextCtrl(self, value=rec.start_time if rec else "08:00")
        self._start_time.SetName("Startzeit")
        form.Add(self._start_time, 1, wx.EXPAND)

        # Dauer
        form.Add(wx.StaticText(self, label="Dauer (Minuten)"), 0, wx.ALIGN_CENTER_VERTICAL)
        self._duration = wx.SpinCtrl(self, min=1, max=1440, initial=rec.duration_min if rec else 60)
        self._duration.SetName("Dauer in Minuten")
        form.Add(self._duration, 0)

        sizer.Add(form, 0, wx.ALL | wx.EXPAND, 12)

        # Wochentage
        days_box = wx.StaticBox(self, label="Wochentage (leer = täglich)")
        days_sizer = wx.StaticBoxSizer(days_box, wx.VERTICAL)
        self._day_checks: List[wx.CheckBox] = []
        active_days = set(rec.weekdays) if rec else set()
        for i, day in enumerate(self._WEEKDAY_LABELS):
            cb = wx.CheckBox(days_box, label=day)
            cb.SetName(day)
            cb.SetValue(i in active_days)
            days_sizer.Add(cb, 0, wx.ALL, 4)
            self._day_checks.append(cb)
        sizer.Add(days_sizer, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)

        # Buttons
        btn_sizer = self.CreateButtonSizer(wx.OK | wx.CANCEL)
        sizer.Add(btn_sizer, 0, wx.ALL | wx.EXPAND, 8)

        self.SetSizer(sizer)
        self.Fit()
        self.Centre()
        self.Bind(wx.EVT_BUTTON, self._on_ok, id=wx.ID_OK)

    def _on_ok(self, _event) -> None:
        label = self._label.GetValue().strip()
        if not label:
            wx.MessageBox("Bitte eine Bezeichnung eingeben.", "Hinweis", wx.OK | wx.ICON_WARNING, self)
            return
        start = self._start_time.GetValue().strip()
        # Validate HH:MM
        parts = start.split(":")
        if len(parts) != 2:
            wx.MessageBox("Startzeit muss im Format HH:MM sein.", "Hinweis", wx.OK | wx.ICON_WARNING, self)
            return
        try:
            hh, mm = int(parts[0]), int(parts[1])
            if not (0 <= hh <= 23 and 0 <= mm <= 59):
                raise ValueError()
        except ValueError:
            wx.MessageBox("Ungültige Startzeit. Format: HH:MM (00:00–23:59).", "Hinweis", wx.OK | wx.ICON_WARNING, self)
            return
        weekdays = [i for i, cb in enumerate(self._day_checks) if cb.GetValue()]
        duration = self._duration.GetValue()
        self._result = ScheduledRecording.new(
            label=label,
            weekdays=weekdays,
            start_time=f"{hh:02d}:{mm:02d}",
            duration_min=duration,
        )
        self.EndModal(wx.ID_OK)

    def get_result(self) -> Optional[ScheduledRecording]:
        return self._result
