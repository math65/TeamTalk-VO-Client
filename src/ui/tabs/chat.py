from __future__ import annotations

from typing import TYPE_CHECKING

import wx

if TYPE_CHECKING:
    from app import MainFrame


class ChatTab(wx.Panel):
    """Tab 3: Chat -- target, private toggle, chat log, message input."""

    def __init__(self, parent: wx.Window, frame: MainFrame) -> None:
        super().__init__(parent)
        self.frame = frame
        self.SetName("Chat")

        sizer = wx.BoxSizer(wx.VERTICAL)

        target_box = wx.StaticBox(self, label="Chat-Ziel")
        target_sizer = wx.StaticBoxSizer(target_box, wx.VERTICAL)
        self.chat_target = wx.StaticText(target_box, label="Ziel: (kein)")
        self.chat_target.SetName("Chat-Ziel")
        target_sizer.Add(self.chat_target, 0, wx.ALL, 8)

        target_row = wx.BoxSizer(wx.HORIZONTAL)
        self.private_chat = wx.CheckBox(target_box, label="Privat")
        self.private_chat.SetName("Privat")
        self.private_chat.Bind(wx.EVT_CHECKBOX, lambda e: self.update_chat_target())
        # Label created immediately before control for NVDA
        lbl_private = wx.StaticText(target_box, label="Privat an:")
        self.private_user = wx.Choice(target_box)
        self.private_user.SetName("Privat an")
        target_row.Add(self.private_chat, 0, wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 8)
        target_row.Add(lbl_private, 0, wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 4)
        target_row.Add(self.private_user, 1, wx.EXPAND)
        target_sizer.Add(target_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)
        sizer.Add(target_sizer, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)

        lbl_log = wx.StaticText(self, label="Chatverlauf")
        sizer.Add(lbl_log, 0, wx.LEFT | wx.RIGHT, 8)
        self.chat_log = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2)
        self.chat_log.SetName("Chatverlauf")
        sizer.Add(self.chat_log, 1, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)

        input_row = wx.BoxSizer(wx.HORIZONTAL)
        lbl_msg = wx.StaticText(self, label="Nachricht eingeben")
        self.chat_input = wx.TextCtrl(self, style=wx.TE_PROCESS_ENTER)
        self.chat_input.SetName("Nachricht")
        self.chat_input.Bind(wx.EVT_TEXT_ENTER, self.on_chat_send)
        self.chat_send = wx.Button(self, label="Senden")
        self.chat_send.SetName("Nachricht senden")
        self.chat_send.Bind(wx.EVT_BUTTON, self.on_chat_send)
        input_row.Add(lbl_msg, 0, wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 4)
        input_row.Add(self.chat_input, 1, wx.RIGHT, 8)
        input_row.Add(self.chat_send, 0)
        sizer.Add(input_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)

        self.SetSizer(sizer)
        self._set_tab_order()

    def append_chat(self, text: str, kind: str = "chat", speak: bool = True) -> None:
        self.chat_log.AppendText(text + "\n")
        self.frame.logger.write(f"CHAT {text}")
        if speak:
            self.frame.tts.speak(text, kind=kind)

    def refresh_private_user_choice(self, users):
        labels = [self.frame.tt_str(u.szNickname) or self.frame.tt_str(u.szUsername) for u in users]
        self.private_user.Set(labels)

    def update_chat_target(self):
        channels_tab = self.frame.channels_tab
        if self.private_chat.GetValue() and channels_tab._selected_user_id is not None:
            user = next(
                (u for u in channels_tab._current_users if u.nUserID == channels_tab._selected_user_id),
                None,
            )
            label = f"Ziel: Benutzer {self.frame.tt_str(user.szNickname)}" if user else "Ziel: Benutzer"
        else:
            my_ch = self.frame.client.get_my_channel_id()
            if my_ch:
                ch = self.frame.client.get_channel(int(my_ch))
                label = f"Ziel: Kanal {self.frame.tt_str(ch.szName)}"
            elif channels_tab._selected_channel_id is not None:
                ch = self.frame.client.get_channel(channels_tab._selected_channel_id)
                label = f"Ziel: Kanal {self.frame.tt_str(ch.szName)}"
            else:
                label = "Ziel: (kein)"
        self.chat_target.SetLabel(label)

    def on_chat_send(self, _event):
        msg = self.chat_input.GetValue().strip()
        if not msg:
            return
        channels_tab = self.frame.channels_tab
        if self.private_chat.GetValue():
            if self.private_user.GetSelection() == wx.NOT_FOUND:
                self.frame.set_status("Bitte einen Benutzer fuer Privatnachricht waehlen")
                return
            user_id = channels_tab._private_user_ids[self.private_user.GetSelection()]
            ok = self.frame.client.send_user_message(user_id, msg)
        else:
            channel_id = self.frame.client.get_my_channel_id() or channels_tab._selected_channel_id
            if not channel_id or int(channel_id) <= 0:
                self.frame.set_status("Kein Kanal ausgewaehlt")
                return
            ok = self.frame.client.send_channel_message(int(channel_id), msg)
        if ok:
            self.append_chat(f"Ich: {msg}", kind="own")
            self.chat_input.SetValue("")
        else:
            self.frame.set_status("Senden fehlgeschlagen")

    def _set_tab_order(self):
        order = [
            self.private_chat, self.private_user, self.chat_log, self.chat_input, self.chat_send,
        ]
        for i in range(1, len(order)):
            order[i].MoveAfterInTabOrder(order[i - 1])
