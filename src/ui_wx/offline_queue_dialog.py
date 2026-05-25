"""Offline-Warteschlangen-Verwaltung: zeigt und verwaltet gepufferte Nachrichten."""
from __future__ import annotations

from typing import TYPE_CHECKING

import wx

from ui_wx.a11y import post_voiceover_announcement, setup_list_accessible

if TYPE_CHECKING:
    from app_wx import MainFrame


class OfflineQueueDialog(wx.Dialog):
    def __init__(self, parent: "MainFrame", offline_queue) -> None:
        super().__init__(
            parent,
            title="Offline-Warteschlange",
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self._oq = offline_queue
        self._frame = parent

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
        self._lb.SetMinSize((520, 260))
        setup_list_accessible(self._lb)
        root.Add(self._lb, 1, wx.LEFT | wx.RIGHT | wx.EXPAND, 8)

        self._info = wx.StaticText(self, label="")
        self._info.SetName("Anzahl ausstehender Nachrichten")
        root.Add(self._info, 0, wx.LEFT | wx.TOP, 8)

        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        self._send_btn   = wx.Button(self, label="Alle &jetzt senden")
        self._send_btn.SetName("Alle Nachrichten jetzt senden")
        self._remove_btn = wx.Button(self, label="Eintrag &entfernen")
        self._remove_btn.SetName("Ausgewählten Eintrag entfernen")
        clear_btn        = wx.Button(self, label="&Alle verwerfen")
        clear_btn.SetName("Alle Nachrichten verwerfen")
        close_btn        = wx.Button(self, wx.ID_CLOSE, label="&Schließen")

        btn_row.Add(self._send_btn,   0, wx.RIGHT, 4)
        btn_row.Add(self._remove_btn, 0, wx.RIGHT, 4)
        btn_row.Add(clear_btn,        0, wx.RIGHT, 4)
        btn_row.Add(close_btn,        0)
        root.Add(btn_row, 0, wx.ALL | wx.ALIGN_RIGHT, 8)

        self.SetSizer(root)
        self.Fit()
        self.CentreOnParent()

        self._fill()

        self._send_btn.Bind(wx.EVT_BUTTON,   self._on_send_all)
        self._remove_btn.Bind(wx.EVT_BUTTON, self._on_remove)
        clear_btn.Bind(wx.EVT_BUTTON,        self._on_clear)
        close_btn.Bind(wx.EVT_BUTTON,        lambda e: self.EndModal(wx.ID_CLOSE))

    # ------------------------------------------------------------------

    def _fill(self) -> None:
        self._lb.Clear()
        items = self._oq.peek()
        for m in items:
            target      = m.target_name or str(m.target_id)
            kind_label  = "Privat" if m.target_type == "private" else "Kanal"
            preview     = m.text[:60] + ("…" if len(m.text) > 60 else "")
            self._lb.Append(f"[{m.age_str} alt, {kind_label} → {target}] {preview}")
        count = len(items)
        self._info.SetLabel(f"{count} Nachricht(en) ausstehend")
        connected = self._frame.client.is_connected()
        self._send_btn.Enable(connected and count > 0)
        self._remove_btn.Enable(count > 0)

    def _on_send_all(self, _evt) -> None:
        client = self._frame.client
        if not client.is_connected():
            wx.MessageBox("Nicht verbunden – Nachrichten können nicht gesendet werden.",
                          "Nicht verbunden", wx.OK | wx.ICON_INFORMATION, self)
            return
        msgs = self._oq.dequeue_all()
        sent = 0
        for m in msgs:
            try:
                if m.target_type == "private":
                    ok = client.send_user_message(int(m.target_id), m.text)
                else:
                    ok = client.send_channel_message(int(m.target_id), m.text)
                if ok:
                    sent += 1
            except Exception:
                pass
        self._fill()
        msg = f"{sent} von {len(msgs)} Nachricht(en) gesendet"
        self._info.SetLabel(msg)
        post_voiceover_announcement(msg)

    def _on_remove(self, _evt) -> None:
        idx = self._lb.GetSelection()
        if idx == wx.NOT_FOUND:
            wx.MessageBox("Bitte zuerst einen Eintrag auswählen.",
                          "Kein Eintrag gewählt", wx.OK | wx.ICON_INFORMATION, self)
            return
        self._oq.remove_at(idx)
        self._fill()
        count = self._lb.GetCount()
        if count > 0:
            self._lb.SetSelection(min(idx, count - 1))
        post_voiceover_announcement("Eintrag entfernt")

    def _on_clear(self, _evt) -> None:
        if self._lb.GetCount() == 0:
            return
        dlg = wx.MessageDialog(
            self,
            "Alle Nachrichten in der Warteschlange verwerfen?",
            "Alle verwerfen",
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION,
        )
        result = dlg.ShowModal()
        dlg.Destroy()
        if result != wx.ID_YES:
            return
        self._oq.clear()
        self._fill()
        post_voiceover_announcement("Warteschlange geleert")
