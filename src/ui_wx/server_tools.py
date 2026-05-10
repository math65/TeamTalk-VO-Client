from __future__ import annotations

from typing import TYPE_CHECKING, List

import wx

from ui_wx.a11y import setup_list_accessible

if TYPE_CHECKING:
    from app import MainFrame


class BroadcastMessageDialog(wx.Dialog):
    def __init__(self, parent: wx.Window) -> None:
        super().__init__(parent, title="Servernachricht senden", style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.SetName("Servernachricht senden")

        accel = wx.AcceleratorTable([(wx.ACCEL_CMD, ord("W"), wx.ID_CLOSE)])
        self.SetAcceleratorTable(accel)
        self.Bind(wx.EVT_MENU, lambda _e: self.Close(), id=wx.ID_CLOSE)

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(wx.StaticText(self, label="Nachricht an alle verbundenen Nutzer senden:"), 0, wx.ALL, 8)

        self.message = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_RICH2)
        self.message.SetName("Rundnachricht")
        self.message.SetMinSize((520, 180))
        sizer.Add(self.message, 1, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)

        btns = self.CreateSeparatedButtonSizer(wx.OK | wx.CANCEL)
        if btns:
            sizer.Add(btns, 0, wx.ALL | wx.EXPAND, 8)

        self.SetSizerAndFit(sizer)

    def get_message(self) -> str:
        return self.message.GetValue().strip()


class OnlineUsersDialog(wx.Dialog):
    def __init__(self, parent: wx.Window, frame: MainFrame) -> None:
        super().__init__(parent, title="Online-Benutzer", style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.frame = frame
        self.SetName("Online-Benutzer")
        self._users: List = []

        accel = wx.AcceleratorTable([(wx.ACCEL_CMD, ord("W"), wx.ID_CLOSE)])
        self.SetAcceleratorTable(accel)
        self.Bind(wx.EVT_MENU, lambda _e: self.Close(), id=wx.ID_CLOSE)

        sizer = wx.BoxSizer(wx.VERTICAL)

        header = wx.StaticText(self, label="Nickname, Benutzername, Kanal")
        header.SetName("Online-Benutzer Kopfzeile")
        sizer.Add(header, 0, wx.ALL, 8)

        self.user_list = wx.ListBox(self)
        self.user_list.SetName("Online-Benutzer Liste")
        setup_list_accessible(self.user_list)
        self.user_list.SetMinSize((520, 300))
        self.user_list.Bind(wx.EVT_RIGHT_DOWN, self._on_right_click)
        self.user_list.Bind(wx.EVT_KEY_DOWN, self._on_key_down)
        self.user_list.Bind(wx.EVT_LISTBOX_DCLICK, self._on_dbl_click)
        sizer.Add(self.user_list, 1, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)

        self.count_label = wx.StaticText(self, label="")
        self.count_label.SetName("Online-Benutzer Anzahl")
        sizer.Add(self.count_label, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        search_row = wx.BoxSizer(wx.HORIZONTAL)
        search_lbl = wx.StaticText(self, label="Suche nach Benutzername:")
        search_lbl.SetName("Suche nach Benutzername")
        self.search_ctrl = wx.TextCtrl(self, style=wx.TE_PROCESS_ENTER)
        self.search_ctrl.SetName("Benutzername Suchfeld")
        self.search_ctrl.Bind(wx.EVT_TEXT_ENTER, self._on_search)
        self.search_btn = wx.Button(self, label="&Suchen")
        self.search_btn.SetName("Benutzer suchen")
        self.search_btn.Bind(wx.EVT_BUTTON, self._on_search)
        search_row.Add(search_lbl, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        search_row.Add(self.search_ctrl, 1, wx.EXPAND | wx.RIGHT, 4)
        search_row.Add(self.search_btn, 0)
        sizer.Add(search_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)

        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        self.refresh_btn = wx.Button(self, label="&Aktualisieren")
        self.refresh_btn.SetName("Online-Benutzer aktualisieren")
        self.refresh_btn.Bind(wx.EVT_BUTTON, self.on_refresh)
        self.pm_btn = wx.Button(self, label="&Privatnachricht")
        self.pm_btn.SetName("Privatnachricht an ausgewählten Benutzer")
        self.pm_btn.Bind(wx.EVT_BUTTON, lambda _e: self._do_private_message())
        close_btn = wx.Button(self, id=wx.ID_CLOSE, label="Sc&hließen")
        close_btn.SetName("Online-Benutzer schließen")
        close_btn.Bind(wx.EVT_BUTTON, lambda _evt: self.Close())
        btn_row.Add(self.refresh_btn, 0, wx.RIGHT, 8)
        btn_row.Add(self.pm_btn, 0, wx.RIGHT, 8)
        btn_row.Add(close_btn, 0)
        sizer.Add(btn_row, 0, wx.ALL, 8)

        self.SetSizerAndFit(sizer)

    def on_refresh(self, _event) -> None:
        self.refresh()

    def _on_search(self, _event) -> None:
        username = self.search_ctrl.GetValue().strip()
        if not username:
            return
        user = self.frame.client.get_user_by_username(username)
        user_id = int(getattr(user, "nUserID", 0) or 0)
        if not user_id:
            wx.MessageBox(
                f"Kein verbundener Benutzer mit dem Benutzernamen '{username}' gefunden.",
                "Suche", wx.OK | wx.ICON_INFORMATION, self,
            )
            return
        for idx, u in enumerate(self._users):
            if int(u.nUserID) == user_id:
                self.user_list.SetSelection(idx)
                self.user_list.EnsureVisible(idx)
                return
        # Nutzer ist verbunden aber noch nicht in der Liste – neu laden
        self.refresh()
        for idx, u in enumerate(self._users):
            if int(u.nUserID) == user_id:
                self.user_list.SetSelection(idx)
                self.user_list.EnsureVisible(idx)
                return

    def refresh(self) -> None:
        users = list(self.frame.client.get_server_users())
        self._users = users
        items: List[str] = []
        tt_str = self.frame.tt_str
        for user in users:
            nickname = tt_str(user.szNickname) or "-"
            username = tt_str(user.szUsername) or "-"
            ch_id = int(getattr(user, "nChannelID", 0) or 0)
            channel = "-"
            if ch_id:
                ch = self.frame.client.get_channel(ch_id)
                if ch is not None:
                    channel = tt_str(ch.szName) or f"#{ch_id}"
            items.append(f"{nickname}, {username}, {channel}")
        self.user_list.Set(items)
        self.count_label.SetLabel(f"{len(items)} Benutzer online")

    # ------------------------------------------------------------------
    # Input events
    # ------------------------------------------------------------------

    def _on_key_down(self, event):
        key = event.GetKeyCode()
        if key == wx.WXK_WINDOWS_MENU or (key == wx.WXK_F10 and event.ShiftDown()):
            idx = self.user_list.GetSelection()
            if idx != wx.NOT_FOUND:
                self._show_context_menu(idx)
            return
        event.Skip()

    def _on_right_click(self, event):
        idx = self.user_list.HitTest(event.GetPosition())
        if idx != wx.NOT_FOUND:
            self.user_list.SetSelection(idx)
            self._show_context_menu(idx)
        event.Skip()

    def _on_dbl_click(self, _event):
        self._do_private_message()

    # ------------------------------------------------------------------
    # Context menu
    # ------------------------------------------------------------------

    def _get_selected_user(self):
        idx = self.user_list.GetSelection()
        if idx == wx.NOT_FOUND or idx >= len(self._users):
            return None
        return self._users[idx]

    def _show_context_menu(self, idx: int):
        if idx < 0 or idx >= len(self._users):
            return
        user = self._users[idx]

        menu = wx.Menu()
        info_item = menu.Append(wx.ID_ANY, _("Benutzerinfo..."))
        menu.AppendSeparator()
        pm_item = menu.Append(wx.ID_ANY, _("Privatnachricht senden..."))
        menu.AppendSeparator()
        move_item = menu.Append(wx.ID_ANY, _("Benutzer verschieben..."))
        kick_ch_item = menu.Append(wx.ID_ANY, _("Aus Kanal kicken"))
        kick_srv_item = menu.Append(wx.ID_ANY, _("Vom Server kicken"))
        ban_item = menu.Append(wx.ID_ANY, _("Bannen..."))
        kick_ban_item = menu.Append(wx.ID_ANY, _("Kicken + Bannen"))

        user_id = int(user.nUserID)
        self.Bind(wx.EVT_MENU, lambda e: self._do_user_info(user_id), info_item)
        self.Bind(wx.EVT_MENU, lambda e: self._do_private_message(), pm_item)
        self.Bind(wx.EVT_MENU, lambda e: self._do_move(user_id), move_item)
        self.Bind(wx.EVT_MENU, lambda e: self._do_kick_channel(user), kick_ch_item)
        self.Bind(wx.EVT_MENU, lambda e: self._do_kick_server(user_id), kick_srv_item)
        self.Bind(wx.EVT_MENU, lambda e: self._do_ban(user), ban_item)
        self.Bind(wx.EVT_MENU, lambda e: self._do_kick_ban(user), kick_ban_item)

        self.PopupMenu(menu)
        menu.Destroy()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _do_user_info(self, user_id: int):
        user = next((u for u in self._users if int(u.nUserID) == user_id), None)
        if not user:
            return
        tt_str = self.frame.tt_str
        ch_id = int(getattr(user, "nChannelID", 0) or 0)
        channel = "-"
        if ch_id:
            ch = self.frame.client.get_channel(ch_id)
            if ch is not None:
                channel = tt_str(ch.szName) or f"#{ch_id}"
        details = [
            f"Nickname: {tt_str(user.szNickname)}",
            f"Benutzername: {tt_str(user.szUsername)}",
            f"ID: {user_id}",
            f"Kanal: {channel}",
            f"Status: {int(user.nStatusMode)}",
        ]
        dlg = wx.MessageDialog(self, "\n".join(details), "Benutzerinfo", wx.OK | wx.ICON_INFORMATION)
        dlg.ShowModal()
        dlg.Destroy()

    def _do_private_message(self):
        user = self._get_selected_user()
        if not user:
            return
        tt_str = self.frame.tt_str
        nick = tt_str(user.szNickname) or tt_str(user.szUsername) or "Benutzer"
        dlg = wx.TextEntryDialog(self, f"Nachricht an {nick}:", "Privatnachricht senden")
        if dlg.ShowModal() == wx.ID_OK:
            msg = dlg.GetValue().strip()
            if msg:
                if self.frame.client.send_user_message(int(user.nUserID), msg):
                    self.frame.chat_tab.append_chat(f"An {nick}: {msg}", kind="own")
                else:
                    wx.MessageBox(
                        "Nachricht konnte nicht gesendet werden", "Fehler",
                        wx.OK | wx.ICON_ERROR, self,
                    )
        dlg.Destroy()

    def _do_move(self, user_id: int):
        channels = list(self.frame.client.get_server_channels())
        if not channels:
            return
        options = []
        ids = []
        for ch in channels:
            cid = int(ch.nChannelID)
            try:
                path = self.frame.tt_str(self.frame.client.get_channel_path(cid))
            except Exception:
                path = ""
            label = path or self.frame.tt_str(ch.szName) or f"Kanal {cid}"
            options.append(label)
            ids.append(cid)
        dlg = wx.SingleChoiceDialog(self, "Zielkanal wählen", "Benutzer verschieben", options)
        if dlg.ShowModal() == wx.ID_OK:
            idx = dlg.GetSelection()
            if idx != wx.NOT_FOUND:
                self.frame.client.do_move_user(user_id, ids[idx])
        dlg.Destroy()

    def _do_kick_channel(self, user):
        ch_id = int(getattr(user, "nChannelID", 0) or 0)
        if not ch_id:
            wx.MessageBox("Benutzer ist in keinem Kanal.", "Kicken", wx.OK | wx.ICON_INFORMATION, self)
            return
        dlg = wx.MessageDialog(
            self, "Benutzer wirklich aus dem Kanal kicken?",
            "Kicken", wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION,
        )
        dlg.SetYesNoLabels("Ja", "Nein")
        if dlg.ShowModal() == wx.ID_YES:
            self.frame.client.do_kick_user(int(user.nUserID), ch_id)
        dlg.Destroy()

    def _do_kick_server(self, user_id: int):
        dlg = wx.MessageDialog(
            self, "Benutzer wirklich vom Server kicken?",
            "Vom Server kicken", wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION,
        )
        dlg.SetYesNoLabels("Ja", "Nein")
        if dlg.ShowModal() == wx.ID_YES:
            self.frame.client.do_kick_user(user_id, 0)
        dlg.Destroy()

    def _do_ban(self, user):
        ban_types = self._ask_ban_types(user)
        if ban_types is None:
            return
        self.frame.client.do_ban_user_ex(int(user.nUserID), ban_types)

    def _do_kick_ban(self, user):
        ban_types = self._ask_ban_types(user)
        if ban_types is None:
            return
        self.frame.client.do_ban_user_ex(int(user.nUserID), ban_types)
        ch_id = int(getattr(user, "nChannelID", 0) or 0)
        if ch_id:
            self.frame.client.do_kick_user(int(user.nUserID), ch_id)

    def _ask_ban_types(self, user):
        tt = self.frame.client.tt
        in_channel = int(getattr(user, "nChannelID", 0) or 0) > 0
        choices = []
        types = []
        if in_channel:
            choices.extend([
                "IP-Adresse (Kanal)", "Benutzername (Kanal)",
                "IP-Adresse (Server)", "Benutzername (Server)",
            ])
            types.extend([
                int(tt.BanType.BANTYPE_CHANNEL | tt.BanType.BANTYPE_IPADDR),
                int(tt.BanType.BANTYPE_CHANNEL | tt.BanType.BANTYPE_USERNAME),
                int(tt.BanType.BANTYPE_IPADDR),
                int(tt.BanType.BANTYPE_USERNAME),
            ])
        else:
            choices.extend(["IP-Adresse (Server)", "Benutzername (Server)"])
            types.extend([int(tt.BanType.BANTYPE_IPADDR), int(tt.BanType.BANTYPE_USERNAME)])
        dlg = wx.SingleChoiceDialog(self, "Ban-Art auswählen", "Bannen", choices)
        if dlg.ShowModal() != wx.ID_OK:
            dlg.Destroy()
            return None
        idx = dlg.GetSelection()
        dlg.Destroy()
        return types[idx] if idx != wx.NOT_FOUND else None


class ServerStatisticsDialog(wx.Dialog):
    def __init__(self, parent: wx.Window, frame: MainFrame) -> None:
        super().__init__(parent, title="Serverstatistiken", style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.frame = frame
        self.SetName("Serverstatistiken")
        self._last_stats = None

        accel = wx.AcceleratorTable([(wx.ACCEL_CMD, ord("W"), wx.ID_CLOSE)])
        self.SetAcceleratorTable(accel)
        self.Bind(wx.EVT_MENU, lambda _e: self.Close(), id=wx.ID_CLOSE)

        sizer = wx.BoxSizer(wx.VERTICAL)

        self.stats_list = wx.ListBox(self)
        self.stats_list.SetName("Serverstatistiken Liste")
        setup_list_accessible(self.stats_list)
        self.stats_list.SetMinSize((520, 260))
        sizer.Add(self.stats_list, 1, wx.ALL | wx.EXPAND, 8)

        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        self.refresh_btn = wx.Button(self, label="&Aktualisieren")
        self.refresh_btn.SetName("Serverstatistiken aktualisieren")
        self.refresh_btn.Bind(wx.EVT_BUTTON, self.on_refresh)
        close_btn = wx.Button(self, id=wx.ID_CLOSE, label="&Schließen")
        close_btn.SetName("Serverstatistiken schließen")
        close_btn.Bind(wx.EVT_BUTTON, lambda _evt: self.Close())
        btn_row.Add(self.refresh_btn, 0, wx.RIGHT, 8)
        btn_row.Add(close_btn, 0)
        sizer.Add(btn_row, 0, wx.ALL, 8)

        self.SetSizerAndFit(sizer)
        self.set_status("Lade Serverstatistiken...")

    def on_refresh(self, _event) -> None:
        self.refresh()

    def refresh(self) -> None:
        self.set_status("Lade Serverstatistiken...")
        self.frame.client.do_query_server_stats()

    def set_status(self, text: str) -> None:
        self.stats_list.Set([text])

    def update_stats(self, stats) -> None:
        self._last_stats = stats
        items = [
            f"Uptime: {self._format_uptime(getattr(stats, 'nUptimeMSec', 0))}",
            f"Benutzer gesamt: {getattr(stats, 'nUsersServed', 0)}",
            f"Benutzer Peak: {getattr(stats, 'nUsersPeak', 0)}",
            f"Gesamt TX: {self._format_bytes(getattr(stats, 'nTotalBytesTX', 0))}",
            f"Gesamt RX: {self._format_bytes(getattr(stats, 'nTotalBytesRX', 0))}",
            f"Voice TX: {self._format_bytes(getattr(stats, 'nVoiceBytesTX', 0))}",
            f"Voice RX: {self._format_bytes(getattr(stats, 'nVoiceBytesRX', 0))}",
            f"Video TX: {self._format_bytes(getattr(stats, 'nVideoCaptureBytesTX', 0))}",
            f"Video RX: {self._format_bytes(getattr(stats, 'nVideoCaptureBytesRX', 0))}",
            f"Mediafile TX: {self._format_bytes(getattr(stats, 'nMediaFileBytesTX', 0))}",
            f"Mediafile RX: {self._format_bytes(getattr(stats, 'nMediaFileBytesRX', 0))}",
            f"Desktop TX: {self._format_bytes(getattr(stats, 'nDesktopBytesTX', 0))}",
            f"Desktop RX: {self._format_bytes(getattr(stats, 'nDesktopBytesRX', 0))}",
            f"Dateien TX: {self._format_bytes(getattr(stats, 'nFilesTx', 0))}",
            f"Dateien RX: {self._format_bytes(getattr(stats, 'nFilesRx', 0))}",
        ]
        self.stats_list.Set(items)

    def _format_bytes(self, value: int) -> str:
        try:
            size = int(value)
        except Exception:
            size = 0
        if size < 1024:
            return f"{size} B"
        if size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        if size < 1024 * 1024 * 1024:
            return f"{size / (1024 * 1024):.1f} MB"
        return f"{size / (1024 * 1024 * 1024):.1f} GB"

    def _format_uptime(self, ms: int) -> str:
        try:
            total = int(ms) // 1000
        except Exception:
            total = 0
        seconds = total % 60
        minutes = (total // 60) % 60
        hours = (total // 3600) % 24
        days = total // (3600 * 24)
        if days:
            return f"{days}d {hours}h {minutes}m"
        if hours:
            return f"{hours}h {minutes}m"
        if minutes:
            return f"{minutes}m {seconds}s"
        return f"{seconds}s"


class BanListDialog(wx.Dialog):
    def __init__(self, parent: wx.Window, frame: MainFrame, title: str) -> None:
        super().__init__(parent, title=title, style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.frame = frame
        self.SetName("Sperrliste")
        self._bans: List = []

        accel = wx.AcceleratorTable([(wx.ACCEL_CMD, ord("W"), wx.ID_CLOSE)])
        self.SetAcceleratorTable(accel)
        self.Bind(wx.EVT_MENU, lambda _e: self.Close(), id=wx.ID_CLOSE)

        sizer = wx.BoxSizer(wx.VERTICAL)

        header = wx.StaticText(self, label="IP, Benutzername, Zeitpunkt")
        header.SetName("Sperrliste Kopfzeile")
        sizer.Add(header, 0, wx.ALL, 8)

        self.list_box = wx.ListBox(self)
        self.list_box.SetName("Sperrliste Liste")
        setup_list_accessible(self.list_box)
        self.list_box.SetMinSize((520, 260))
        sizer.Add(self.list_box, 1, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)

        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        self.refresh_btn = wx.Button(self, label="&Sperren laden")
        self.refresh_btn.SetName("Sperren laden")
        self.refresh_btn.Bind(wx.EVT_BUTTON, self.on_refresh)
        close_btn = wx.Button(self, id=wx.ID_CLOSE, label="Sc&hließen")
        close_btn.SetName("Sperrliste schließen")
        close_btn.Bind(wx.EVT_BUTTON, lambda _evt: self.Close())
        btn_row.Add(self.refresh_btn, 0, wx.RIGHT, 8)
        btn_row.Add(close_btn, 0)
        sizer.Add(btn_row, 0, wx.ALL, 8)

        self.SetSizerAndFit(sizer)

    def on_refresh(self, _event) -> None:
        self.refresh()

    def refresh(self) -> None:
        self.list_box.Set(["Sperren werden geladen..."])

    def clear(self) -> None:
        self._bans = []
        self.list_box.Set([])

    def add_ban(self, ban) -> None:
        tt_str = self.frame.tt_str
        self._bans.append(ban)
        label = f"{tt_str(ban.szIPAddress)}, {tt_str(ban.szUsername)}, {tt_str(ban.szBanTime)}"
        self.list_box.Append(label)
