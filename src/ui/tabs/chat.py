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
        self.private_chat = wx.CheckBox(target_box, label="&Privat")
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

        # Chat history action buttons
        history_row = wx.BoxSizer(wx.HORIZONTAL)
        self.export_btn = wx.Button(self, label="Verlauf &exportieren")
        self.export_btn.SetName("Verlauf exportieren")
        self.export_btn.Bind(wx.EVT_BUTTON, self._on_export_history)
        self.clear_btn = wx.Button(self, label="Verlauf &leeren")
        self.clear_btn.SetName("Verlauf leeren")
        self.clear_btn.Bind(wx.EVT_BUTTON, self._on_clear_history)
        history_row.Add(self.export_btn, 0, wx.RIGHT, 8)
        history_row.Add(self.clear_btn, 0)
        sizer.Add(history_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        input_row = wx.BoxSizer(wx.HORIZONTAL)
        lbl_msg = wx.StaticText(self, label="Nachricht eingeben")
        self.chat_input = wx.TextCtrl(self, style=wx.TE_PROCESS_ENTER)
        self.chat_input.SetName("Nachricht")
        self.chat_input.Bind(wx.EVT_TEXT_ENTER, self.on_chat_send)
        self.chat_send = wx.Button(self, label="&Senden")
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
        if self.frame.settings_store.settings.save_chat_history:
            self.frame.save_chat_message(text, kind)

    def _on_export_history(self, _event) -> None:
        content = self.chat_log.GetValue()
        if not content.strip():
            self.frame.set_status("Kein Chat-Verlauf zum Exportieren")
            return
        import time
        default_name = f"chatverlauf_{time.strftime('%Y%m%d_%H%M%S')}.txt"
        with wx.FileDialog(
            self,
            "Chat-Verlauf exportieren",
            wildcard="Textdateien (*.txt)|*.txt|Alle Dateien|*.*",
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
            defaultFile=default_name,
        ) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            path = dlg.GetPath()
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            self.frame.set_status(f"Chat-Verlauf exportiert: {path}")
        except Exception as exc:
            self.frame.set_status(f"Export fehlgeschlagen: {exc}")

    def _on_clear_history(self, _event) -> None:
        dlg = wx.MessageDialog(
            self,
            "Chat-Verlauf wirklich leeren?\n\nDies löscht den angezeigten Verlauf und – falls aktiviert – auch die gespeicherte Verlaufsdatei für diesen Server.",
            "Verlauf leeren",
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION,
        )
        result = dlg.ShowModal()
        dlg.Destroy()
        if result != wx.ID_YES:
            return
        self.chat_log.Clear()
        # Also clear the persisted file if chat history saving is enabled
        if self.frame.settings_store.settings.save_chat_history:
            try:
                key = self.frame._get_server_key()
                if key:
                    self.frame._chat_history.clear(key)
            except Exception:
                pass
        self.frame.set_status("Chat-Verlauf geleert")

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
                self.frame.set_status("Privater Chat: Bitte Benutzer wählen")
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
