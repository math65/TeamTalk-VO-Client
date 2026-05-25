"""Privater Chat-Dialog — dediziertes Fenster pro Benutzer (wxPython)."""
from __future__ import annotations

import time
from typing import TYPE_CHECKING, Dict

import wx

from ui_wx.a11y import post_voiceover_announcement

if TYPE_CHECKING:
    from app_wx import App


# Registry of open dialogs: user_id → PrivateChatDialog instance
_open_dialogs: Dict[int, "PrivateChatDialog"] = {}


def open_private_chat(frame: "App", user_id: int, nick: str = "") -> "PrivateChatDialog":
    """Open or focus the private chat window for user_id."""
    if user_id in _open_dialogs and _open_dialogs[user_id]:
        dlg = _open_dialogs[user_id]
        if not dlg.IsBeingDeleted():
            dlg.Raise()
            dlg.SetFocus()
            dlg._input.SetFocus()
            return dlg
    dlg = PrivateChatDialog(frame, user_id, nick)
    _open_dialogs[user_id] = dlg
    dlg.Show()
    dlg.Raise()
    dlg._input.SetFocus()
    return dlg


class PrivateChatDialog(wx.Frame):
    """Nicht-modales Privat-Chat-Fenster mit einem Benutzer.

    Layout:
        ┌─────────────────────────────────────┐
        │  Chatverlauf (scrollbar, read-only) │
        ├─────────────────────────────────────┤
        │  Nachricht eingeben        [Senden] │
        │  [Verlauf laden] [Exportieren]      │
        └─────────────────────────────────────┘

    Tastatur:
        Enter       → Nachricht senden
        Cmd+W       → Fenster schließen
    """

    def __init__(self, frame: "App", user_id: int, nick: str = "") -> None:
        super().__init__(frame, title=f"Privat: {nick or f'User#{user_id}'}",
                         style=wx.DEFAULT_FRAME_STYLE)
        self.frame = frame
        self.user_id = user_id
        self._nick = nick or f"User#{user_id}"

        self.SetName(f"Privater Chat mit {self._nick}")
        self.SetSize(520, 420)

        self._build_ui()
        self._load_history()

        self._nick_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_nick_timer, self._nick_timer)
        self._nick_timer.Start(5000)

        self.Bind(wx.EVT_CLOSE, self._on_close)

        # Cmd+W closes
        accel = wx.AcceleratorTable([(wx.ACCEL_CMD, ord("W"), wx.ID_CLOSE)])
        self.SetAcceleratorTable(accel)
        self.Bind(wx.EVT_MENU, lambda _e: self.Close(), id=wx.ID_CLOSE)

    def _build_ui(self) -> None:
        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        # Status label
        self._status_label = wx.StaticText(panel, label=f"Chat mit {self._nick}")
        sizer.Add(self._status_label, 0, wx.ALL, 6)

        # Chat log (read-only)
        self._log = wx.TextCtrl(panel, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2)
        self._log.SetName(f"Verlauf des privaten Chats mit {self._nick}")
        sizer.Add(self._log, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)

        # Input row
        input_row = wx.BoxSizer(wx.HORIZONTAL)
        self._input = wx.TextCtrl(panel, style=wx.TE_PROCESS_ENTER)
        self._input.SetName(f"Nachricht an {self._nick}")
        self._input.Bind(wx.EVT_TEXT_ENTER, self._on_send)
        self._send_btn = wx.Button(panel, label="&Senden")
        self._send_btn.SetName("Nachricht senden")
        self._send_btn.Bind(wx.EVT_BUTTON, self._on_send)
        input_row.Add(self._input, 1, wx.EXPAND | wx.RIGHT, 6)
        input_row.Add(self._send_btn, 0)
        sizer.Add(input_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)

        # Action buttons
        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        load_btn = wx.Button(panel, label="Verlauf &laden")
        load_btn.SetName("Gespeicherten Verlauf laden")
        load_btn.Bind(wx.EVT_BUTTON, lambda _e: self._load_history())
        export_btn = wx.Button(panel, label="E&xportieren")
        export_btn.SetName("Verlauf exportieren")
        export_btn.Bind(wx.EVT_BUTTON, self._on_export)
        btn_row.Add(load_btn, 0, wx.RIGHT, 6)
        btn_row.Add(export_btn, 0)
        sizer.Add(btn_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)

        panel.SetSizer(sizer)

    def _get_partner_name(self) -> str:
        """Returns the partner name as stored in chat_history (usually nickname or id string)."""
        return self._nick or f"id{self.user_id}"

    def _load_history(self) -> None:
        self._log.Clear()
        try:
            server_key = self.frame._get_server_key() or ""
            if server_key and hasattr(self.frame, "_chat_history"):
                partner = self._get_partner_name()
                entries = self.frame._chat_history.load_private(server_key, partner)
                for e in entries:
                    ts = e.get("ts", "")
                    text = e.get("text", "")
                    line = f"[{ts}] {text}" if ts else text
                    self._log.AppendText(line + "\n")
        except Exception:
            pass

    def append_message(self, sender: str, text: str, own: bool = False) -> None:
        """Called when a private message is sent or received."""
        ts = time.strftime("%H:%M:%S")
        line = f"[{ts}] {sender}: {text}"
        wx.CallAfter(self._append_line, line)
        # Also persist via chat_history
        try:
            server_key = self.frame._get_server_key() or ""
            if server_key and hasattr(self.frame, "_chat_history"):
                partner = self._get_partner_name()
                self.frame._chat_history.append_private(
                    server_key, partner, f"{sender}: {text}", "private"
                )
        except Exception:
            pass

    def _append_line(self, line: str) -> None:
        self._log.AppendText(line + "\n")
        self._log.SetInsertionPointEnd()

    def _on_send(self, _event) -> None:
        text = self._input.GetValue().strip()
        if not text:
            return
        try:
            self.frame.client.send_user_message(self.user_id, text)
            my_nick = "Ich"
            try:
                my_id = self.frame.client.get_my_user_id()
                u = self.frame.client.get_user(my_id)
                if u:
                    my_nick = self.frame.tt_str(u.szNickname) or "Ich"
            except Exception:
                pass
            self.append_message(my_nick, text, own=True)
            self._input.Clear()
            self.frame._analytics.on_message_sent()
        except Exception as exc:
            wx.MessageBox(str(exc), "Fehler", wx.ICON_ERROR)

    def _on_export(self, _event) -> None:
        content = self._log.GetValue()
        if not content.strip():
            return
        dlg = wx.FileDialog(
            self, "Verlauf exportieren", wildcard="Textdateien (*.txt)|*.txt",
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
            defaultFile=f"privat_{self._nick}.txt",
        )
        if dlg.ShowModal() == wx.ID_OK:
            path = dlg.GetPath()
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(content)
                post_voiceover_announcement(f"Exportiert: {path}")
            except Exception as exc:
                wx.MessageBox(str(exc), "Fehler", wx.ICON_ERROR)
        dlg.Destroy()

    def _on_nick_timer(self, _event) -> None:
        try:
            u = self.frame.client.get_user(self.user_id)
            if u:
                nick = (
                    self.frame.tt_str(u.szNickname)
                    or self.frame.tt_str(u.szUsername)
                    or f"User#{self.user_id}"
                )
                if nick != self._nick:
                    self._nick = nick
                    wx.CallAfter(self.SetTitle, f"Privat: {nick}")
                    wx.CallAfter(self._status_label.SetLabel, f"Chat mit {nick}")
        except Exception:
            pass

    def _on_close(self, event) -> None:
        self._nick_timer.Stop()
        _open_dialogs.pop(self.user_id, None)
        event.Skip()
