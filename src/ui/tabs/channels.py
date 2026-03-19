from __future__ import annotations

from typing import Dict, List, Optional, TYPE_CHECKING

import wx

if TYPE_CHECKING:
    from app import MainFrame


class ChannelsTab(wx.Panel):
    """Tab 2: Kanaele -- channel tree, user list, members, context menu."""

    def __init__(self, parent: wx.Window, frame: MainFrame) -> None:
        super().__init__(parent)
        self.frame = frame
        self.SetName("Kanaele")

        self._channel_items: Dict[int, wx.TreeItemId] = {}
        self._current_users: List = []
        self._selected_channel_id: Optional[int] = None
        self._selected_user_id: Optional[int] = None
        self._channel_list_ids: List[int] = []
        self._private_user_ids: List[int] = []

        sizer = wx.BoxSizer(wx.VERTICAL)

        # --- Splitter: tree + user list ---
        main_box = wx.StaticBox(self, label="Kanalstruktur und Nutzer")
        main_sizer = wx.StaticBoxSizer(main_box, wx.VERTICAL)
        splitter = wx.SplitterWindow(main_box, style=wx.SP_LIVE_UPDATE)
        self.channel_tree = wx.TreeCtrl(splitter, style=wx.TR_HAS_BUTTONS | wx.TR_LINES_AT_ROOT)
        self.channel_tree.SetName("Kanalliste")
        self.channel_tree.Bind(wx.EVT_TREE_SEL_CHANGED, self.on_channel_selected)
        self.channel_tree.Bind(wx.EVT_TREE_ITEM_ACTIVATED, self.on_channel_activated)

        self.user_list = wx.ListCtrl(splitter, style=wx.LC_REPORT | wx.BORDER_SUNKEN)
        self.user_list.SetName("Nutzerliste im Kanal")
        self.user_list.InsertColumn(0, "Nickname")
        self.user_list.InsertColumn(1, "Benutzername")
        self.user_list.InsertColumn(2, "Status")
        self.user_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_user_selected)
        self.user_list.Bind(wx.EVT_LIST_ITEM_DESELECTED, self.on_user_deselected)
        self.user_list.Bind(wx.EVT_LIST_ITEM_RIGHT_CLICK, self.on_user_right_click)
        self.user_list.Bind(wx.EVT_KEY_DOWN, self._on_user_list_key)

        splitter.SplitVertically(self.channel_tree, self.user_list, sashPosition=260)
        splitter.SetMinimumPaneSize(180)
        splitter.SetSashGravity(0.5)

        main_sizer.Add(splitter, 1, wx.ALL | wx.EXPAND, 8)
        sizer.Add(main_sizer, 1, wx.ALL | wx.EXPAND, 8)

        # --- Channel list (flat) ---
        list_box = wx.StaticBox(self, label="Kanal-Übersicht (Schnellbeitritt)")
        list_sizer = wx.StaticBoxSizer(list_box, wx.VERTICAL)
        ch_row = wx.BoxSizer(wx.HORIZONTAL)
        self.channel_list = wx.ListBox(list_box)
        self.channel_list.SetName("Kanal-Liste")
        self.channel_list.SetMinSize((-1, 140))
        self.channel_list.Bind(wx.EVT_LISTBOX_DCLICK, self.on_channel_list_join)
        self.channel_join_btn = wx.Button(list_box, label="Kanal beitreten")
        self.channel_join_btn.SetName("Kanal beitreten")
        self.channel_join_btn.Bind(wx.EVT_BUTTON, self.on_channel_list_join)
        ch_row.Add(self.channel_list, 1, wx.RIGHT | wx.EXPAND, 8)
        ch_row.Add(self.channel_join_btn, 0)
        list_sizer.Add(ch_row, 0, wx.ALL | wx.EXPAND, 8)
        sizer.Add(list_sizer, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)

        # --- Members ---
        members_box = wx.StaticBox(self, label="Mitglieder im aktuellen Kanal")
        members_sizer = wx.StaticBoxSizer(members_box, wx.VERTICAL)
        self.channel_members = wx.ListBox(members_box)
        self.channel_members.SetName("Kanal-Mitglieder")
        self.channel_members.SetMinSize((-1, 120))
        members_sizer.Add(self.channel_members, 1, wx.ALL | wx.EXPAND, 8)
        sizer.Add(members_sizer, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)

        self.SetSizer(sizer)


    def refresh_channels_and_users(self):
        client = self.frame.client
        tt_str = self.frame.tt_str
        logger = self.frame.logger

        channels = list(client.get_server_channels())
        logger.write(f"Channels received: {len(channels)}")
        users_by_channel = self._count_users_by_channel()
        self.channel_tree.DeleteAllItems()
        self._channel_items.clear()
        self._channel_list_ids = []

        root_id = client.get_root_channel_id()
        channel_ids = {c.nChannelID for c in channels}
        parent_ids = {c.nParentID for c in channels}
        if root_id <= 0 or root_id not in channel_ids:
            inferred_root = None
            if len(parent_ids) == 1:
                inferred_root = next(iter(parent_ids))
            elif 1 in parent_ids:
                inferred_root = 1
            elif parent_ids:
                inferred_root = min(parent_ids)
            if inferred_root is not None:
                logger.write(f"Inferred root channel id: {inferred_root} (was {root_id})")
                root_id = inferred_root

        root_channel = next((c for c in channels if c.nChannelID == root_id), None)
        root_label = tt_str(root_channel.szName) if root_channel else "Root"
        root_item = self.channel_tree.AddRoot(root_label)
        self._channel_items[root_id] = root_item

        pending = {c.nChannelID: c for c in channels if c.nChannelID != root_id}
        while pending:
            progressed = False
            for chan_id in list(pending.keys()):
                chan = pending[chan_id]
                parent = self._channel_items.get(chan.nParentID)
                if parent is None:
                    continue
                label = tt_str(chan.szName)
                item = self.channel_tree.AppendItem(parent, label)
                self._channel_items[chan.nChannelID] = item
                try:
                    path = tt_str(client.get_channel_path(chan.nChannelID))
                    logger.write(f"Channel: id={chan.nChannelID} parent={chan.nParentID} path={path}")
                except Exception:
                    pass
                pending.pop(chan_id)
                progressed = True
            if not progressed:
                break

        self.channel_tree.ExpandAll()
        self.channel_tree.SelectItem(root_item)
        self._selected_channel_id = root_id
        self.refresh_users_for_channel(root_id)
        self._refresh_channel_list(channels, users_by_channel)

    def _refresh_channel_list(self, channels, users_by_channel: Dict[int, int]):
        tt_str = self.frame.tt_str
        client = self.frame.client
        display = []
        for chan in channels:
            try:
                path = tt_str(client.get_channel_path(chan.nChannelID))
            except Exception:
                path = tt_str(chan.szName)
            if not path:
                path = tt_str(chan.szName)
            count = users_by_channel.get(int(chan.nChannelID), 0)
            has_pw = bool(chan.bPassword)
            label = f"{path}  | Nutzer: {count}  | Passwort: {'Ja' if has_pw else 'Nein'}"
            display.append((label, int(chan.nChannelID)))
        combined = sorted(display, key=lambda x: x[0].lower())
        self._channel_list_ids = [i for _, i in combined]
        self.channel_list.Set([d for d, _ in combined])

    def _count_users_by_channel(self) -> Dict[int, int]:
        users = list(self.frame.client.get_server_users())
        by_ch: Dict[int, int] = {}
        for u in users:
            cid = int(u.nChannelID)
            by_ch[cid] = by_ch.get(cid, 0) + 1
        return by_ch

    # ------------------------------------------------------------------
    # Users
    # ------------------------------------------------------------------

    def refresh_users_for_channel(self, channel_id: int):
        client = self.frame.client
        tt_str = self.frame.tt_str
        actual = channel_id or client.get_my_channel_id()
        self.user_list.DeleteAllItems()
        users = list(client.get_channel_users(actual))
        self._current_users = users
        self._private_user_ids = []
        for user in users:
            idx = self.user_list.InsertItem(self.user_list.GetItemCount(), tt_str(user.szNickname))
            self.user_list.SetItem(idx, 1, tt_str(user.szUsername))
            self.user_list.SetItem(idx, 2, str(user.nStatusMode))
            self._private_user_ids.append(int(user.nUserID))
        self._refresh_channel_list(list(client.get_server_channels()), self._count_users_by_channel())
        self._update_channel_members(users, actual)
        # Sync private user choice in chat tab
        chat_tab = self.frame.chat_tab
        if chat_tab:
            chat_tab.refresh_private_user_choice(users)

    def refresh_members_for_my_channel(self):
        my_ch = self.frame.client.get_my_channel_id()
        if my_ch:
            self._selected_channel_id = int(my_ch)
            self.refresh_users_for_channel(int(my_ch))

    def _format_member_label(self, user) -> str:
        tt = self.frame.client.tt
        name = self.frame.tt_str(user.szNickname) or self.frame.tt_str(user.szUsername)
        flags = []
        if user.uUserType & tt.UserType.USERTYPE_ADMIN:
            flags.append("ADMIN")
        if user.uUserState & tt.UserState.USERSTATE_MUTE_VOICE:
            flags.append("MUTED")
        if user.uUserState & tt.UserState.USERSTATE_VOICE:
            flags.append("VOICE")
        if flags:
            return f"{name} ({', '.join(flags)})"
        return name

    def _update_channel_members(self, users, channel_id: int):
        names = [self._format_member_label(u) for u in users]
        self.frame.logger.write(f"Channel members update: channel_id={channel_id} count={len(names)}")
        self.channel_members.Set(names)
        try:
            channel = self.frame.client.get_channel(channel_id)
            ch_name = self.frame.tt_str(channel.szName)
        except Exception:
            ch_name = ""
        if not ch_name:
            ch_name = "aktuellen Channel"
        if names:
            announce = f"Im Channel {ch_name}: " + ", ".join(names)
        else:
            announce = f"Im Channel {ch_name} ist niemand."
        self.frame.set_status(announce)

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def on_channel_selected(self, _event):
        item = self.channel_tree.GetSelection()
        if not item.IsOk():
            return
        channel_id = self._channel_id_from_item(item)
        if channel_id is None:
            return
        self._selected_channel_id = channel_id
        self.refresh_users_for_channel(channel_id)
        self.frame.chat_tab.update_chat_target()

    def on_channel_activated(self, _event):
        item = self.channel_tree.GetSelection()
        if not item.IsOk():
            return
        channel_id = self._channel_id_from_item(item)
        if channel_id is not None:
            self.frame.join_channel(channel_id)

    def on_channel_list_join(self, _event):
        idx = self.channel_list.GetSelection()
        if idx == wx.NOT_FOUND:
            self.frame.set_status("Bitte einen Channel auswaehlen")
            return
        if idx >= len(self._channel_list_ids):
            self.frame.set_status("Ungueltige Channel-Auswahl")
            return
        self.frame.join_channel(self._channel_list_ids[idx])

    def on_user_selected(self, event):
        idx = event.GetIndex()
        if idx < 0 or idx >= len(self._current_users):
            return
        self._selected_user_id = int(self._current_users[idx].nUserID)
        self.frame.chat_tab.update_chat_target()
        for i, uid in enumerate(self._private_user_ids):
            if uid == self._selected_user_id:
                self.frame.chat_tab.private_user.SetSelection(i)
                break

    def on_user_deselected(self, _event):
        self._selected_user_id = None
        self.frame.chat_tab.update_chat_target()

    def _get_user_by_id(self, user_id: int):
        for user in self._current_users:
            if int(user.nUserID) == user_id:
                return user
        return None

    def _channel_id_from_item(self, item: wx.TreeItemId) -> Optional[int]:
        for cid, ti in self._channel_items.items():
            if ti == item:
                return cid
        return None

    # ------------------------------------------------------------------
    # User context menu (right-click)
    # ------------------------------------------------------------------

    def _on_user_list_key(self, event):
        key = event.GetKeyCode()
        if key == wx.WXK_WINDOWS_MENU or (key == wx.WXK_F10 and event.ShiftDown()):
            idx = self.user_list.GetFirstSelected()
            if idx >= 0:
                class _FakeEvent:
                    def GetIndex(self):
                        return idx
                self.on_user_right_click(_FakeEvent())
                return
        event.Skip()

    def on_user_right_click(self, event):
        idx = event.GetIndex()
        if idx < 0 or idx >= len(self._current_users):
            return
        user = self._current_users[idx]
        user_id = int(user.nUserID)
        tt = self.frame.client.tt

        menu = wx.Menu()

        self.user_list.Select(idx)
        self._selected_user_id = user_id
        self.frame.chat_tab.update_chat_target()

        user_state = int(getattr(user, "uUserState", 0) or 0)
        voice_muted = bool(user_state & int(tt.UserState.USERSTATE_MUTE_VOICE))
        media_muted = bool(user_state & int(tt.UserState.USERSTATE_MUTE_MEDIAFILE))

        info_item = menu.Append(wx.ID_ANY, "Benutzerinfo...")
        menu.AppendSeparator()

        vol_voice_item = menu.Append(wx.ID_ANY, "Lautstaerke Stimme...")
        vol_media_item = menu.Append(wx.ID_ANY, "Lautstaerke Mediendatei...")
        mute_voice_item = menu.AppendCheckItem(wx.ID_ANY, "Stimme stummschalten")
        mute_media_item = menu.AppendCheckItem(wx.ID_ANY, "Mediendatei stummschalten")
        mute_voice_item.Check(voice_muted)
        mute_media_item.Check(media_muted)

        sub_menu = wx.Menu()
        sub_flags = [
            ("Sprache", tt.Subscription.SUBSCRIBE_VOICE),
            ("Video", tt.Subscription.SUBSCRIBE_VIDEOCAPTURE),
            ("Mediendatei", tt.Subscription.SUBSCRIBE_MEDIAFILE),
            ("Benutzernachrichten", tt.Subscription.SUBSCRIBE_USER_MSG),
            ("Kanalnachrichten", tt.Subscription.SUBSCRIBE_CHANNEL_MSG),
            ("Broadcast", tt.Subscription.SUBSCRIBE_BROADCAST_MSG),
            ("Desktop", tt.Subscription.SUBSCRIBE_DESKTOP),
            ("Desktop-Steuerung", tt.Subscription.SUBSCRIBE_DESKTOPINPUT),
            ("Desktop-Intercept", tt.Subscription.SUBSCRIBE_INTERCEPT_DESKTOP),
            ("Intercept Benutzer-Msg", tt.Subscription.SUBSCRIBE_INTERCEPT_USER_MSG),
            ("Intercept Kanal-Msg", tt.Subscription.SUBSCRIBE_INTERCEPT_CHANNEL_MSG),
            ("Intercept Voice", tt.Subscription.SUBSCRIBE_INTERCEPT_VOICE),
            ("Intercept Video", tt.Subscription.SUBSCRIBE_INTERCEPT_VIDEOCAPTURE),
            ("Intercept Mediafile", tt.Subscription.SUBSCRIBE_INTERCEPT_MEDIAFILE),
            ("Intercept Custom", tt.Subscription.SUBSCRIBE_INTERCEPT_CUSTOM_MSG),
        ]
        sub_items = []
        current_subs = int(getattr(user, "uLocalSubscriptions", 0) or 0)
        for label, flag in sub_flags:
            mi = sub_menu.AppendCheckItem(wx.ID_ANY, label)
            mi.Check(bool(current_subs & int(flag)))
            sub_items.append((mi, flag))
        menu.AppendSubMenu(sub_menu, "Abonnements")

        my_ch = self.frame.client.get_my_channel_id()
        is_op = self.frame.client.is_channel_operator(int(my_ch), user_id) if my_ch else False
        op_label = "Operator entziehen" if is_op else "Zum Operator machen"
        op_item = menu.Append(wx.ID_ANY, op_label)

        ban_item = menu.Append(wx.ID_ANY, "Bannen...")
        move_item = menu.Append(wx.ID_ANY, "Benutzer verschieben...")
        kick_item = menu.Append(wx.ID_ANY, "Kick")
        kick_ban_item = menu.Append(wx.ID_ANY, "Kick + Ban")
        desktop_access_item = menu.Append(wx.ID_ANY, "Desktop-Zugriff erlauben")

        # Bind handlers
        self.Bind(wx.EVT_MENU, lambda e: self._on_user_info(user_id), info_item)
        self.Bind(wx.EVT_MENU, lambda e: self._on_user_volume(user_id, int(tt.StreamType.STREAMTYPE_VOICE), "Stimme"), vol_voice_item)
        self.Bind(wx.EVT_MENU, lambda e: self._on_user_volume(user_id, int(tt.StreamType.STREAMTYPE_MEDIAFILE), "Mediendatei"), vol_media_item)
        self.Bind(wx.EVT_MENU, lambda e: self._on_user_mute(user_id, int(tt.StreamType.STREAMTYPE_VOICE), e.IsChecked()), mute_voice_item)
        self.Bind(wx.EVT_MENU, lambda e: self._on_user_mute(user_id, int(tt.StreamType.STREAMTYPE_MEDIAFILE), e.IsChecked()), mute_media_item)
        self.Bind(wx.EVT_MENU, lambda e: self._on_user_op(user_id, not is_op), op_item)
        self.Bind(wx.EVT_MENU, lambda e: self._on_user_ban(user_id), ban_item)
        self.Bind(wx.EVT_MENU, lambda e: self.frame.on_menu_user_move(None), move_item)
        self.Bind(wx.EVT_MENU, lambda e: self._on_user_kick(user_id), kick_item)
        self.Bind(wx.EVT_MENU, lambda e: self._on_user_kick_ban(user_id), kick_ban_item)
        self.Bind(wx.EVT_MENU, lambda e: self.frame.on_menu_user_allow_desktop_access(None), desktop_access_item)
        for mi, flag in sub_items:
            self.Bind(wx.EVT_MENU, lambda e, f=flag: self._on_user_subscribe_toggle(user_id, f, e.IsChecked()), mi)

        self.PopupMenu(menu)
        menu.Destroy()

    def _on_user_info(self, user_id: int):
        user = self._get_user_by_id(user_id)
        if not user:
            self.frame.set_status("Benutzer nicht gefunden")
            return
        details = [
            f"Nickname: {self.frame.tt_str(user.szNickname)}",
            f"Benutzername: {self.frame.tt_str(user.szUsername)}",
            f"ID: {int(user.nUserID)}",
            f"Kanal: {int(user.nChannelID)}",
            f"Status: {int(user.nStatusMode)}",
        ]
        dlg = wx.MessageDialog(self, "\n".join(details), "Benutzerinfo", wx.OK | wx.ICON_INFORMATION)
        dlg.ShowModal()
        dlg.Destroy()

    def _on_user_volume(self, user_id: int, stream_type: int, label: str):
        dlg = wx.NumberEntryDialog(self, "Lautstaerke (0-32000)", "Lautstaerke:", f"{label}-Lautstaerke", 1000, 0, 32000)
        if dlg.ShowModal() == wx.ID_OK:
            vol = dlg.GetValue()
            self.frame.client.set_user_volume(user_id, stream_type, vol)
            self.frame.set_status(f"{label}-Lautstaerke auf {vol} gesetzt")
        dlg.Destroy()

    def _on_user_mute(self, user_id: int, stream_type: int, checked: bool):
        self.frame.client.set_user_mute(user_id, stream_type, bool(checked))
        if stream_type == int(self.frame.client.tt.StreamType.STREAMTYPE_MEDIAFILE):
            label = "Mediendatei"
        else:
            label = "Stimme"
        self.frame.set_status(f"{label} {'stummgeschaltet' if checked else 'entstummt'}")

    def _on_user_op(self, user_id: int, make_op: bool):
        my_ch = self.frame.client.get_my_channel_id()
        if my_ch:
            self.frame.client.do_channel_op(int(my_ch), user_id, make_op)
            self.frame.set_status("Operator gesetzt" if make_op else "Operator entzogen")

    def _on_user_kick(self, user_id: int):
        my_ch = self.frame.client.get_my_channel_id()
        if not my_ch:
            return
        dlg = wx.MessageDialog(
            self, "Benutzer wirklich kicken?",
            "Kick", wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION,
        )
        if dlg.ShowModal() != wx.ID_YES:
            dlg.Destroy()
            return
        dlg.Destroy()
        self.frame.client.do_kick_user(user_id, int(my_ch))
        self.frame.set_status("Benutzer gekickt")

    def _on_user_kick_ban(self, user_id: int):
        user = self._get_user_by_id(user_id)
        if not user:
            self.frame.set_status("Benutzer nicht gefunden")
            return
        ban_types = self._ask_ban_types(user)
        if ban_types is None:
            return
        dlg = wx.MessageDialog(
            self, "Benutzer wirklich kicken und bannen?",
            "Kick + Ban", wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION,
        )
        if dlg.ShowModal() != wx.ID_YES:
            dlg.Destroy()
            return
        dlg.Destroy()
        self.frame.client.do_ban_user_ex(user_id, ban_types)
        if int(getattr(user, "nChannelID", 0) or 0) > 0:
            self.frame.client.do_kick_user(user_id, int(user.nChannelID))
            self.frame.set_status("Benutzer gekickt und gebannt")
        else:
            self.frame.set_status("Benutzer gebannt")

    def _on_user_subscribe_toggle(self, user_id: int, flag: int, checked: bool):
        if checked:
            self.frame.client.do_subscribe(user_id, flag)
            self.frame.set_status("Abonnement aktiviert")
        else:
            self.frame.client.do_unsubscribe(user_id, flag)
            self.frame.set_status("Abonnement deaktiviert")

    def _on_user_ban(self, user_id: int):
        user = self._get_user_by_id(user_id)
        if not user:
            self.frame.set_status("Benutzer nicht gefunden")
            return
        ban_types = self._ask_ban_types(user)
        if ban_types is None:
            return
        self.frame.client.do_ban_user_ex(user_id, ban_types)
        self.frame.set_status("Benutzer gebannt")

    def _ask_ban_types(self, user) -> Optional[int]:
        tt = self.frame.client.tt
        in_channel = int(getattr(user, "nChannelID", 0) or 0) > 0
        choices = []
        types = []
        if in_channel:
            choices.extend(
                [
                    "IP-Adresse (Kanal)",
                    "Benutzername (Kanal)",
                    "IP-Adresse (Server)",
                    "Benutzername (Server)",
                ]
            )
            types.extend(
                [
                    int(tt.BanType.BANTYPE_CHANNEL | tt.BanType.BANTYPE_IPADDR),
                    int(tt.BanType.BANTYPE_CHANNEL | tt.BanType.BANTYPE_USERNAME),
                    int(tt.BanType.BANTYPE_IPADDR),
                    int(tt.BanType.BANTYPE_USERNAME),
                ]
            )
        else:
            choices.extend(["IP-Adresse (Server)", "Benutzername (Server)"])
            types.extend(
                [
                    int(tt.BanType.BANTYPE_IPADDR),
                    int(tt.BanType.BANTYPE_USERNAME),
                ]
            )
        dlg = wx.SingleChoiceDialog(self, "Ban-Typ auswaehlen", "Bannen", choices)
        if dlg.ShowModal() != wx.ID_OK:
            dlg.Destroy()
            return None
        idx = dlg.GetSelection()
        dlg.Destroy()
        if idx == wx.NOT_FOUND:
            return None
        return types[idx]
