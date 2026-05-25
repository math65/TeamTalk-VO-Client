"""Privatnachrichten-Verlauf-Browser (wxPython)."""
from __future__ import annotations
import wx
from ui_wx.a11y import setup_list_accessible, post_voiceover_announcement
from typing import TYPE_CHECKING, List
if TYPE_CHECKING:
    from app_wx import App
    from chat_history import ChatHistoryManager


class PMHistoryDialog(wx.Dialog):
    """Dialog zum Durchsuchen gespeicherter Privatnachrichten-Verläufe."""

    def __init__(self, parent: wx.Window, chat_history: "ChatHistoryManager", server_key: str) -> None:
        super().__init__(parent, title="Privatnachrichten-Verlauf",
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.SetName("Privatnachrichten-Verlauf")
        self._history = chat_history
        self._server_key = server_key
        self._partners: List[str] = []

        accel = wx.AcceleratorTable([(wx.ACCEL_CMD, ord("W"), wx.ID_CLOSE)])
        self.SetAcceleratorTable(accel)
        self.Bind(wx.EVT_MENU, lambda _e: self.Close(), id=wx.ID_CLOSE)

        self._build_ui()
        self._load_partners()
        self.SetSize(700, 500)
        self.CenterOnParent()

    def _build_ui(self) -> None:
        sizer = wx.BoxSizer(wx.VERTICAL)

        # Filter row
        filter_row = wx.BoxSizer(wx.HORIZONTAL)
        filter_row.Add(wx.StaticText(self, label="Suche"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self._filter = wx.TextCtrl(self)
        self._filter.SetName("Partner suchen")
        self._filter.Bind(wx.EVT_TEXT, self._on_filter)
        filter_row.Add(self._filter, 1, wx.EXPAND)
        sizer.Add(filter_row, 0, wx.ALL | wx.EXPAND, 8)

        # Splitter: left=partners, right=messages
        splitter = wx.SplitterWindow(self, style=wx.SP_LIVE_UPDATE)
        splitter.SetMinimumPaneSize(150)

        left = wx.Panel(splitter)
        left_sizer = wx.BoxSizer(wx.VERTICAL)
        left_sizer.Add(wx.StaticText(left, label="Gesprächspartner"), 0, wx.ALL, 4)
        self._partner_lb = wx.ListBox(left)
        self._partner_lb.SetName("Gesprächspartner-Liste")
        setup_list_accessible(self._partner_lb)
        self._partner_lb.Bind(wx.EVT_LISTBOX, self._on_partner_selected)
        left_sizer.Add(self._partner_lb, 1, wx.EXPAND | wx.ALL, 4)
        left.SetSizer(left_sizer)

        right = wx.Panel(splitter)
        right_sizer = wx.BoxSizer(wx.VERTICAL)
        self._partner_label = wx.StaticText(right, label="Kein Gesprächspartner gewählt")
        right_sizer.Add(self._partner_label, 0, wx.ALL, 4)
        self._msg_list = wx.ListBox(right)
        self._msg_list.SetName("Nachrichten")
        setup_list_accessible(self._msg_list)
        right_sizer.Add(self._msg_list, 1, wx.EXPAND | wx.ALL, 4)

        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        self._export_btn = wx.Button(right, label="Ex&portieren")
        self._export_btn.SetName("Verlauf exportieren")
        self._export_btn.Enable(False)
        self._export_btn.Bind(wx.EVT_BUTTON, self._on_export)
        btn_row.Add(self._export_btn, 0, wx.RIGHT, 8)
        right_sizer.Add(btn_row, 0, wx.ALL, 4)
        right.SetSizer(right_sizer)

        splitter.SplitVertically(left, right, 200)
        sizer.Add(splitter, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        close_btn = wx.Button(self, wx.ID_CLOSE, label="Schließen")
        close_btn.Bind(wx.EVT_BUTTON, lambda _e: self.Close())
        sizer.Add(close_btn, 0, wx.ALIGN_RIGHT | wx.ALL, 8)

        self.SetSizer(sizer)

    def _load_partners(self) -> None:
        try:
            partners = self._history.list_private_partners(self._server_key)
        except Exception:
            partners = []
        self._partners = sorted(partners)
        self._partner_lb.Set(self._partners)
        self._msg_list.Clear()
        if self._partners:
            self._partner_lb.SetSelection(0)
            self._on_partner_selected(None)

    def _on_filter(self, _event) -> None:
        query = self._filter.GetValue().strip().lower()
        try:
            all_partners = self._history.list_private_partners(self._server_key)
        except Exception:
            all_partners = []
        filtered = sorted(p for p in all_partners if not query or query in p.lower())
        self._partners = filtered
        self._partner_lb.Set(filtered)
        self._msg_list.Clear()
        self._partner_label.SetLabel("Kein Gesprächspartner gewählt")
        self._export_btn.Enable(False)

    def _on_partner_selected(self, _event) -> None:
        idx = self._partner_lb.GetSelection()
        if idx == wx.NOT_FOUND or idx >= len(self._partners):
            return
        partner = self._partners[idx]
        self._partner_label.SetLabel(f"Verlauf mit {partner}")
        try:
            entries = self._history.load_private(self._server_key, partner)
        except Exception:
            entries = []
        lines = []
        for e in entries:
            ts = e.get("ts", "")
            text = e.get("text", "")
            lines.append(f"[{ts}] {text}" if ts else text)
        self._msg_list.Set(lines)
        self._export_btn.Enable(bool(lines))
        if lines:
            self._msg_list.SetSelection(len(lines) - 1)
        count_text = f"{len(lines)} Nachrichten mit {partner}"
        post_voiceover_announcement(count_text)

    def _on_export(self, _event) -> None:
        idx = self._partner_lb.GetSelection()
        if idx == wx.NOT_FOUND or idx >= len(self._partners):
            return
        partner = self._partners[idx]
        dlg = wx.FileDialog(
            self, "Verlauf exportieren", wildcard="Textdateien (*.txt)|*.txt",
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
            defaultFile=f"privat_{partner}.txt",
        )
        if dlg.ShowModal() == wx.ID_OK:
            path = dlg.GetPath()
            try:
                entries = self._history.load_private(self._server_key, partner)
                lines = []
                for e in entries:
                    ts = e.get("ts", "")
                    text = e.get("text", "")
                    lines.append(f"[{ts}] {text}" if ts else text)
                with open(path, "w", encoding="utf-8") as f:
                    f.write("\n".join(lines))
                post_voiceover_announcement(f"Exportiert: {path}")
            except Exception as ex:
                wx.MessageBox(str(ex), "Fehler", wx.ICON_ERROR)
        dlg.Destroy()
