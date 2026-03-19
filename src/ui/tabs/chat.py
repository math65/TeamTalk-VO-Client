from __future__ import annotations

from typing import TYPE_CHECKING, List

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

    def append_chat(self, text: str, kind: str = "chat", speak: bool = True) -> None:
        if not text:
            return
        if self.chat_log.GetLastPosition() > 0:
            self.chat_log.AppendText("\n")
        if kind == "system":
            self.chat_log.SetDefaultStyle(wx.TextAttr(wx.Colour(128, 128, 128)))  # Gray
        elif kind == "private":
            self.chat_log.SetDefaultStyle(wx.TextAttr(wx.Colour(0, 0, 192)))  # Blue
        elif kind == "own":
            self.chat_log.SetDefaultStyle(wx.TextAttr(wx.Colour(0, 128, 0)))  # Green
        else:
            self.chat_log.SetDefaultStyle(wx.TextAttr(wx.BLACK))  # Black
        self.chat_log.AppendText(text)
        self.chat_log.SetDefaultStyle(wx.TextAttr(wx.BLACK)) # Reset for next messages
        self.chat_log.ShowPosition(self.chat_log.GetLastPosition()) # Scroll to bottom
        if speak:
            self.frame.tts.speak(text, kind=kind)

    def on_chat_send(self, _event):
        msg = self.chat_input.GetValue().strip()
        if not msg:
            return

        client = self.frame.client
        if not client.is_connected():
            self.frame.set_status("Nicht verbunden")
            return

        is_private = self.private_chat.GetValue()
        if is_private:
            user_idx = self.private_user.GetSelection()
            if user_idx == wx.NOT_FOUND:
                self.frame.set_status("Privater Chat: Bitte Benutzer waehlen")
                return
            target_user_id = self.private_user.GetClientData(user_idx)
            if client.send_user_message(target_user_id, msg):
                self.append_chat(f"An {self.private_user.GetString(user_idx)}: {msg}", kind="own")
            else:
                self.frame.set_status("Nachricht konnte nicht gesendet werden")
        else:
            channel_id = client.get_my_channel_id()
            if not channel_id:
                self.frame.set_status("Kanal-Chat: Nicht in einem Kanal")
                return
            if client.send_channel_message(channel_id, msg):
                self.append_chat(f"Ich: {msg}", kind="own")
            else:
                self.frame.set_status("Nachricht konnte nicht gesendet werden")

        self.chat_input.Clear()

    def update_chat_target(self):
        is_private = self.private_chat.GetValue()
        self.private_user.Enable(is_private)
        if is_private:
            user_idx = self.private_user.GetSelection()
            if user_idx != wx.NOT_FOUND:
                self.chat_target.SetLabel(f"Ziel: Privat an {self.private_user.GetString(user_idx)}")
            else:
                self.chat_target.SetLabel("Ziel: Privat an (keinen Benutzer)")
        else:
            channel_id = self.frame.client.get_my_channel_id()
            if channel_id:
                channel = self.frame.client.get_channel(channel_id)
                if channel:
                    self.chat_target.SetLabel(f"Ziel: Kanal {self.frame.tt_str(channel.szName)}")
                else:
                    self.chat_target.SetLabel("Ziel: Aktueller Kanal")
            else:
                self.chat_target.SetLabel("Ziel: (kein)")

    def refresh_private_user_choice(self, users: List) -> None:
        self.private_user.Clear()
        if not users:
            self.private_user.Disable()
            return
        
        self.private_user.Enable()
        items = []
        for user in users:
            nickname = self.frame.tt_str(user.szNickname)
            username = self.frame.tt_str(user.szUsername)
            label = nickname or username
            if nickname and username and nickname != username:
                label = f"{nickname} ({username})"
            elif not label:
                label = f"Unbekannt ({int(user.nUserID)})"
            items.append((label, int(user.nUserID)))

        # Sort alphabetically by label
        items.sort(key=lambda x: x[0].lower())
        
        for label, user_id in items:
            self.private_user.Append(label, clientData=user_id)
        
        if items:
            self.private_user.SetSelection(0)
        self.update_chat_target()

