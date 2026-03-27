from __future__ import annotations

from typing import TYPE_CHECKING, List

import wx

from ui.a11y import setup_list_accessible

if TYPE_CHECKING:
    from app import MainFrame


class ChatTab(wx.Panel):
    """Tab 3: Chat -- target, private toggle, chat log, message input."""

    def __init__(self, parent: wx.Window, frame: MainFrame) -> None:
        super().__init__(parent)
        self.frame = frame
        self.SetName("Chat")
        self._search_positions: List[int] = []

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

        # Search box
        search_box = wx.StaticBox(self, label="Verlauf durchsuchen")
        search_sizer = wx.StaticBoxSizer(search_box, wx.VERTICAL)
        search_row = wx.BoxSizer(wx.HORIZONTAL)
        self.search_input = wx.TextCtrl(search_box, style=wx.TE_PROCESS_ENTER)
        self.search_input.SetName("Suchbegriff")
        self.search_input.Bind(wx.EVT_TEXT_ENTER, self._on_search)
        self.search_btn = wx.Button(search_box, label="&Suchen")
        self.search_btn.SetName("Im Verlauf suchen")
        self.search_btn.Bind(wx.EVT_BUTTON, self._on_search)
        self.search_count = wx.StaticText(search_box, label="0 Treffer")
        self.search_count.SetName("Suchergebnis Anzahl")
        search_row.Add(self.search_input, 1, wx.RIGHT, 8)
        search_row.Add(self.search_btn, 0, wx.RIGHT, 8)
        search_row.Add(self.search_count, 0, wx.ALIGN_CENTER_VERTICAL)
        search_sizer.Add(search_row, 0, wx.ALL | wx.EXPAND, 8)
        self.search_results = wx.ListBox(search_box)
        self.search_results.SetName("Suchergebnisse")
        self.search_results.SetMinSize((-1, 100))
        setup_list_accessible(self.search_results)
        self.search_results.Bind(wx.EVT_LISTBOX, self._on_search_result_selected)
        search_sizer.Add(self.search_results, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)
        sizer.Add(search_sizer, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)

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

    def _is_muted_sender(self, text: str) -> bool:
        """Gibt True zurück, wenn der Absender in der Stummschalten-Liste ist."""
        s = self.frame.settings_store.settings
        raw = (s.chat_muted_users or "").strip()
        if not raw:
            return False
        muted = [u.strip().lower() for u in raw.split(",") if u.strip()]
        if not muted:
            return False
        # Format: "Username: Nachricht" oder "* Username hat ..."
        lower = text.lower()
        for name in muted:
            if lower.startswith(name + ":") or lower.startswith("* " + name + " "):
                return True
        return False

    def _has_highlight_keyword(self, text: str) -> bool:
        """Gibt True zurück, wenn ein Stichwort im Text vorkommt."""
        s = self.frame.settings_store.settings
        raw = (s.chat_highlight_keywords or "").strip()
        if not raw:
            return False
        keywords = [k.strip().lower() for k in raw.split(",") if k.strip()]
        lower = text.lower()
        return any(k in lower for k in keywords)

    def append_chat(self, text: str, kind: str = "chat", speak: bool = True) -> None:
        if not text:
            return
        # Muted users filter (system/own messages are never filtered)
        if kind not in ("system", "own") and self._is_muted_sender(text):
            return
        # Keyword highlight marker
        if kind not in ("system", "own") and self._has_highlight_keyword(text):
            text = "[!] " + text
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
        self.chat_log.SetDefaultStyle(wx.TextAttr(wx.BLACK))  # Reset for next messages
        self.chat_log.ShowPosition(self.chat_log.GetLastPosition())  # Scroll to bottom
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
            if target_user_id is None:
                self.frame.set_status("Benutzer-ID nicht verfügbar")
                return
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

    def _on_search(self, _event=None) -> None:
        """Durchsucht den aktuellen Chat-Verlauf nach dem Suchbegriff."""
        query = self.search_input.GetValue().strip().lower()
        self.search_results.Clear()
        self._search_positions = []
        if not query:
            self.search_count.SetLabel("0 Treffer")
            return
        text = self.chat_log.GetValue()
        lines = text.split("\n")
        hits = []
        pos = 0
        for line in lines:
            if query in line.lower():
                hits.append((line, pos))
            pos += len(line) + 1
        display_hits = hits[:100]
        for label, _ in display_hits:
            self.search_results.Append(label[:150] if len(label) > 150 else label)
        self._search_positions = [p for _, p in display_hits]
        total = len(hits)
        shown = len(display_hits)
        if total > shown:
            self.search_count.SetLabel(f"{total} Treffer (zeige {shown})")
        else:
            self.search_count.SetLabel(f"{total} Treffer")
        if display_hits:
            self.search_results.SetSelection(0)

    def _on_search_result_selected(self, _event) -> None:
        """Springt zur ausgewählten Fundstelle im Chat-Verlauf."""
        idx = self.search_results.GetSelection()
        if idx == wx.NOT_FOUND or idx >= len(self._search_positions):
            return
        pos = self._search_positions[idx]
        self.chat_log.SetInsertionPoint(pos)
        self.chat_log.ShowPosition(pos)
        self.chat_log.SetFocus()

    def select_private_recipient(self, user_id: int) -> None:
        """Wählt den Nutzer im Privat-Chat-Dropdown aus (für Antwort-Hotkey)."""
        for i in range(self.private_user.GetCount()):
            if self.private_user.GetClientData(i) == user_id:
                self.private_chat.SetValue(True)
                self.private_user.SetSelection(i)
                self.update_chat_target()
                self.private_user.Enable(True)
                return

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
