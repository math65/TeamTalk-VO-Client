"""Gespeicherte-Nachrichten-Dialog (wxPython / macOS)."""
from __future__ import annotations

from typing import TYPE_CHECKING, List

import wx

from ui_wx.a11y import post_voiceover_announcement, setup_list_accessible

if TYPE_CHECKING:
    from app_wx import MainFrame
    from saved_messages import SavedMessageManager


class SavedMessagesDialog(wx.Dialog):
    """Zeigt gespeicherte Chat-Nachrichten mit Such-, Kopier- und Löschfunktionen."""

    def __init__(self, parent: "MainFrame", manager: "SavedMessageManager") -> None:
        super().__init__(
            parent,
            title="Gespeicherte Nachrichten",
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self._manager = manager
        self._frame = parent
        # Parallele Index-Liste: mappt Listbox-Position → Original-Index in manager
        self._filtered_indices: List[int] = []

        accel = wx.AcceleratorTable([(wx.ACCEL_CMD, ord("W"), wx.ID_CLOSE)])
        self.SetAcceleratorTable(accel)
        self.Bind(wx.EVT_MENU, lambda e: self.EndModal(wx.ID_CANCEL), id=wx.ID_CLOSE)

        self.SetMinSize((680, 460))

        root = wx.BoxSizer(wx.VERTICAL)

        # Suchfeld
        search_row = wx.BoxSizer(wx.HORIZONTAL)
        search_lbl = wx.StaticText(self, label="&Suche:")
        self._search = wx.TextCtrl(self)
        self._search.SetName("Suchfeld")
        search_row.Add(search_lbl, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        search_row.Add(self._search, 1, wx.EXPAND)
        root.Add(search_row, 0, wx.ALL | wx.EXPAND, 8)

        # Zähler-Label
        self._count_lbl = wx.StaticText(self, label="")
        self._count_lbl.SetName("Anzahl Nachrichten")
        root.Add(self._count_lbl, 0, wx.LEFT | wx.BOTTOM, 8)

        # Nachrichten-Liste
        self._lb = wx.ListBox(self, style=wx.LB_SINGLE)
        self._lb.SetName("Gespeicherte Nachrichten")
        self._lb.SetMinSize((-1, 280))
        setup_list_accessible(self._lb)
        root.Add(self._lb, 1, wx.LEFT | wx.RIGHT | wx.EXPAND, 8)

        # Volltext-Anzeige (nicht editierbar)
        self._detail = wx.TextCtrl(
            self,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_WORDWRAP,
        )
        self._detail.SetName("Vollständiger Nachrichtentext")
        self._detail.SetMinSize((-1, 80))
        root.Add(self._detail, 0, wx.LEFT | wx.RIGHT | wx.TOP | wx.EXPAND, 8)

        # Buttons
        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        self._copy_btn  = wx.Button(self, label="&Kopieren")
        self._copy_btn.SetName("Nachricht kopieren")
        self._del_btn   = wx.Button(self, label="&Löschen")
        self._del_btn.SetName("Ausgewählte Nachricht löschen")
        self._clear_btn = wx.Button(self, label="&Alle löschen")
        self._clear_btn.SetName("Alle gespeicherten Nachrichten löschen")
        close_btn       = wx.Button(self, wx.ID_CLOSE, label="S&chließen")

        btn_row.Add(self._copy_btn,  0, wx.RIGHT, 6)
        btn_row.Add(self._del_btn,   0, wx.RIGHT, 6)
        btn_row.Add(self._clear_btn, 0, wx.RIGHT, 6)
        btn_row.Add(close_btn,       0)
        root.Add(btn_row, 0, wx.ALL | wx.ALIGN_RIGHT, 8)

        self.SetSizer(root)
        self.Fit()
        self.CentreOnParent()

        # Initialbefüllung
        self._fill("")

        # Events
        self._search.Bind(wx.EVT_TEXT, self._on_search)
        self._lb.Bind(wx.EVT_LISTBOX, self._on_select)
        self._copy_btn.Bind(wx.EVT_BUTTON,  self._on_copy)
        self._del_btn.Bind(wx.EVT_BUTTON,   self._on_delete)
        self._clear_btn.Bind(wx.EVT_BUTTON, self._on_clear)
        close_btn.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_CLOSE))

    # ------------------------------------------------------------------
    # Hilfsmethoden

    def _entry_label(self, m) -> str:
        srv = f" [{m.server}]" if m.server else ""
        preview = m.text[:100] + ("…" if len(m.text) > 100 else "")
        return f"{m.time_str}{srv}: {preview}"

    def _fill(self, query: str) -> None:
        """Befüllt die ListBox entsprechend dem Suchbegriff."""
        query = query.strip().lower()
        all_items = self._manager.items()

        self._lb.Clear()
        self._filtered_indices = []
        self._detail.SetValue("")

        for orig_idx, m in enumerate(all_items):
            label = self._entry_label(m)
            if query and query not in label.lower() and query not in m.text.lower():
                continue
            self._lb.Append(label)
            self._filtered_indices.append(orig_idx)

        count = self._lb.GetCount()
        total = len(all_items)
        if query:
            self._count_lbl.SetLabel(f"{count} von {total} Nachricht(en)")
        else:
            self._count_lbl.SetLabel(f"{total} Nachricht(en)")

        self._update_buttons()

    def _update_buttons(self) -> None:
        has_items = self._lb.GetCount() > 0
        has_sel   = self._lb.GetSelection() != wx.NOT_FOUND
        self._copy_btn.Enable(has_sel)
        self._del_btn.Enable(has_sel)
        self._clear_btn.Enable(has_items)

    def _orig_index(self, lb_pos: int) -> int:
        """Gibt den Original-Index im Manager zurück."""
        if 0 <= lb_pos < len(self._filtered_indices):
            return self._filtered_indices[lb_pos]
        return -1

    # ------------------------------------------------------------------
    # Event-Handler

    def _on_search(self, _evt) -> None:
        self._fill(self._search.GetValue())

    def _on_select(self, _evt) -> None:
        idx = self._lb.GetSelection()
        if idx == wx.NOT_FOUND:
            self._detail.SetValue("")
            self._update_buttons()
            return
        orig = self._orig_index(idx)
        items = self._manager.items()
        if 0 <= orig < len(items):
            self._detail.SetValue(items[orig].text)
        self._update_buttons()

    def _on_copy(self, _evt) -> None:
        idx = self._lb.GetSelection()
        if idx == wx.NOT_FOUND:
            return
        orig = self._orig_index(idx)
        items = self._manager.items()
        if 0 <= orig < len(items):
            text = items[orig].text
            if wx.TheClipboard.Open():
                wx.TheClipboard.SetData(wx.TextDataObject(text))
                wx.TheClipboard.Close()
            try:
                self._frame.set_status("Nachricht in Zwischenablage kopiert")
            except Exception:
                pass
            post_voiceover_announcement("Nachricht kopiert")

    def _on_delete(self, _evt) -> None:
        idx = self._lb.GetSelection()
        if idx == wx.NOT_FOUND:
            wx.MessageBox(
                "Bitte zuerst einen Eintrag auswählen.",
                "Kein Eintrag gewählt",
                wx.OK | wx.ICON_INFORMATION,
                self,
            )
            return
        orig = self._orig_index(idx)
        self._manager.remove(orig)
        # Liste neu aufbauen (Indizes haben sich verschoben)
        query = self._search.GetValue()
        self._fill(query)
        count = self._lb.GetCount()
        if count > 0:
            new_sel = min(idx, count - 1)
            self._lb.SetSelection(new_sel)
            # Detail aktualisieren
            new_orig = self._orig_index(new_sel)
            items = self._manager.items()
            if 0 <= new_orig < len(items):
                self._detail.SetValue(items[new_orig].text)
        self._update_buttons()
        post_voiceover_announcement("Nachricht gelöscht")

    def _on_clear(self, _evt) -> None:
        if self._lb.GetCount() == 0:
            return
        dlg = wx.MessageDialog(
            self,
            "Alle gespeicherten Nachrichten wirklich löschen?",
            "Alle löschen",
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION,
        )
        result = dlg.ShowModal()
        dlg.Destroy()
        if result != wx.ID_YES:
            return
        self._manager.clear()
        self._fill(self._search.GetValue())
        post_voiceover_announcement("Alle gespeicherten Nachrichten gelöscht")
