"""Tab 2: Kanäle – integrierter Kanalbaum mit Nutzern (ab v1.10.1).

Layout: einzelner wx.TreeCtrl füllt den gesamten Tab.
Kanäle erscheinen als übergeordnete Knoten, Nutzer als deren Kinder.
Doppelklick/Enter auf Kanal → Kanal beitreten.
Kontextmenü auf Nutzer-Knoten (Rechtsklick / Shift+F10).
"""
from __future__ import annotations

from typing import Dict, List, Optional, TYPE_CHECKING

import wx

if TYPE_CHECKING:
    from app import MainFrame

# Knotentypen im Baum
_NODE_CHANNEL = "channel"
_NODE_USER = "user"


class ChannelsTab(wx.Panel):
    """Tab 2: Kanäle -- integrierter Kanalbaum mit Nutzerknoten."""

    def __init__(self, parent: wx.Window, frame: "MainFrame") -> None:
        super().__init__(parent)
        self.frame = frame
        self.SetName("Kanäle")

        # Interne Zustandsvariablen
        self._channel_items: Dict[int, wx.TreeItemId] = {}   # channel_id → TreeItemId
        self._user_items: Dict[int, wx.TreeItemId] = {}      # user_id → TreeItemId
        self._current_users: List = []   # Nutzer im eigenen Kanal (für Chat-Tab, Kontext-Menü)
        self._all_users: List = []       # Alle Server-Nutzer (für baumweite Anzeige)
        self._private_user_ids: List[int] = []
        self._selected_channel_id: Optional[int] = None
        self._selected_user_id: Optional[int] = None
        self._cached_channels: List = []

        # TreeCtrl direkt im Panel – kein StaticBox-Wrapper (verhindert Render-Probleme
        # wenn ChannelsTab in einem äußeren SplitterWindow sitzt)
        sizer = wx.BoxSizer(wx.VERTICAL)

        self.channel_tree = wx.TreeCtrl(
            self,
            style=wx.TR_HAS_BUTTONS | wx.TR_LINES_AT_ROOT | wx.TR_SINGLE,
        )
        self.channel_tree.SetName("Kanalliste")
        self.channel_tree.Bind(wx.EVT_TREE_SEL_CHANGED, self._on_tree_sel_changed)
        self.channel_tree.Bind(wx.EVT_TREE_ITEM_ACTIVATED, self._on_tree_activated)
        self.channel_tree.Bind(wx.EVT_RIGHT_DOWN, self._on_tree_right_click)
        self.channel_tree.Bind(wx.EVT_KEY_DOWN, self._on_tree_key)

        sizer.Add(self.channel_tree, 1, wx.ALL | wx.EXPAND, 4)

        # Beitreten-Button als barrierefreie Alternative zum Doppelklick/Enter
        self.join_btn = wx.Button(self, label="&Kanal beitreten")
        self.join_btn.SetName("Kanal beitreten")
        self.join_btn.Bind(wx.EVT_BUTTON, self._on_join_btn)
        sizer.Add(self.join_btn, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 4)

        self.SetSizer(sizer)

    # ------------------------------------------------------------------
    # Baum aufbauen
    # ------------------------------------------------------------------

    def refresh_channels_and_users(self) -> None:
        client = self.frame.client
        tt_str = self.frame.tt_str
        logger = self.frame.logger

        try:
            channels = list(client.get_server_channels() or [])
        except Exception as exc:
            logger.write(f"get_server_channels failed: {exc}")
            channels = []
        self._cached_channels = channels
        logger.write(f"Channels received: {len(channels)}")

        try:
            all_users = list(client.get_server_users() or [])
        except Exception as exc:
            logger.write(f"get_server_users failed: {exc}")
            all_users = []
        self._all_users = all_users

        # Nutzer nach Kanal gruppieren
        users_by_channel: Dict[int, List] = {}
        for u in all_users:
            try:
                cid = int(u.nChannelID)
                users_by_channel.setdefault(cid, []).append(u)
            except Exception:
                pass

        # Vorherige Auswahl merken (robust gegen ungültige Items)
        prev_type: Optional[str] = None
        prev_id: Optional[int] = None
        try:
            sel = self.channel_tree.GetSelection()
            if sel.IsOk():
                prev_type, prev_id = self._node_info_from_item(sel)
        except Exception:
            pass

        self.channel_tree.DeleteAllItems()
        self._channel_items.clear()
        self._user_items.clear()

        if not channels:
            return

        # Root-Kanal ermitteln
        try:
            root_id = int(client.get_root_channel_id() or 0)
        except Exception:
            root_id = 0
        channel_ids = {c.nChannelID for c in channels}
        parent_ids = {c.nParentID for c in channels}
        if root_id <= 0 or root_id not in channel_ids:
            if len(parent_ids) == 1:
                root_id = next(iter(parent_ids))
            elif 1 in parent_ids:
                root_id = 1
            elif parent_ids:
                root_id = min(parent_ids)

        root_channel = next((c for c in channels if c.nChannelID == root_id), None)
        root_name = tt_str(root_channel.szName) if root_channel else "Root"
        root_label = self._make_channel_label(root_name, root_channel, users_by_channel.get(root_id, []))
        root_item = self.channel_tree.AddRoot(root_label)
        try:
            self.channel_tree.SetItemData(root_item, {"type": _NODE_CHANNEL, "id": root_id})
        except Exception:
            pass
        self._channel_items[root_id] = root_item
        self._add_user_nodes(root_item, users_by_channel.get(root_id, []))

        # Unterkanäle iterativ einbauen
        pending = {c.nChannelID: c for c in channels if c.nChannelID != root_id}
        while pending:
            progressed = False
            for chan_id in list(pending.keys()):
                chan = pending[chan_id]
                parent_item = self._channel_items.get(chan.nParentID)
                if parent_item is None:
                    continue
                try:
                    name = tt_str(chan.szName)
                    label = self._make_channel_label(name, chan, users_by_channel.get(chan_id, []))
                    item = self.channel_tree.AppendItem(parent_item, label)
                    try:
                        self.channel_tree.SetItemData(item, {"type": _NODE_CHANNEL, "id": chan_id})
                    except Exception:
                        pass
                    self._channel_items[chan_id] = item
                    self._add_user_nodes(item, users_by_channel.get(chan_id, []))
                except Exception as exc:
                    logger.write(f"Fehler beim Einbauen von Kanal {chan_id}: {exc}")
                pending.pop(chan_id)
                progressed = True
            if not progressed:
                break

        try:
            self.channel_tree.ExpandAll()
        except Exception:
            pass

        # Eigenen Kanal und Nutzer aktualisieren
        try:
            my_ch = int(client.get_my_channel_id() or 0)
        except Exception:
            my_ch = 0
        if my_ch:
            self._selected_channel_id = my_ch
            my_users = users_by_channel.get(my_ch, [])
            self._current_users = my_users
            self._private_user_ids = [int(u.nUserID) for u in my_users]
            self._announce_channel_members(my_users, my_ch)
        chat_tab = self.frame.chat_tab
        if chat_tab and self._current_users is not None:
            try:
                chat_tab.refresh_private_user_choice(self._current_users)
            except Exception:
                pass

        # Vorherige Auswahl wiederherstellen
        restore_item = None
        if prev_type == _NODE_CHANNEL and prev_id is not None:
            restore_item = self._channel_items.get(prev_id)
        elif prev_type == _NODE_USER and prev_id is not None:
            restore_item = self._user_items.get(prev_id)
        try:
            if restore_item and restore_item.IsOk():
                self.channel_tree.SelectItem(restore_item)
            elif my_ch and my_ch in self._channel_items:
                self.channel_tree.SelectItem(self._channel_items[my_ch])
            elif root_item.IsOk():
                self.channel_tree.SelectItem(root_item)
        except Exception:
            pass

    def _make_channel_label(self, name: str, chan, users: List) -> str:
        parts = [name]
        if chan is not None and bool(getattr(chan, "bPassword", False)):
            parts.append("Passwort")
        n = len(users)
        if n == 1:
            parts.append("1 Nutzer")
        elif n > 1:
            parts.append(f"{n} Nutzer")
        return ", ".join(parts)

    def _add_user_nodes(self, parent_item: wx.TreeItemId, users: List) -> None:
        for user in users:
            try:
                label = self._format_user_label(user)
                item = self.channel_tree.AppendItem(parent_item, label)
                uid = int(user.nUserID)
                try:
                    self.channel_tree.SetItemData(item, {"type": _NODE_USER, "id": uid})
                except Exception:
                    pass
                self._user_items[uid] = item
            except Exception:
                pass

    def _format_user_label(self, user) -> str:
        try:
            name = self.frame.tt_str(user.szNickname) or self.frame.tt_str(user.szUsername) or "Benutzer"
        except Exception:
            name = "Benutzer"
        flags = []
        try:
            tt = self.frame.client.tt
            if user.uUserType & tt.UserType.USERTYPE_ADMIN:
                flags.append("Admin")
        except Exception:
            pass
        try:
            tt = self.frame.client.tt
            if user.uUserState & tt.UserState.USERSTATE_VOICE:
                flags.append("Spricht")
            elif user.uUserState & tt.UserState.USERSTATE_MUTE_VOICE:
                flags.append("Stumm")
        except Exception:
            pass
        if flags:
            return f"{name}, {', '.join(flags)}"
        return name

    # Rückwärtskompatibilität: alter Name wird weiter genutzt
    def _format_member_label(self, user) -> str:
        return self._format_user_label(user)

    # ------------------------------------------------------------------
    # Nutzer im eigenen Kanal aktualisieren
    # ------------------------------------------------------------------

    def refresh_users_for_channel(self, channel_id: int) -> None:
        """Aktualisiert _current_users für den angegebenen Kanal (für Chat-Tab)."""
        client = self.frame.client
        actual = channel_id or int(client.get_my_channel_id() or 0)
        users = list(client.get_channel_users(actual))
        self._current_users = users
        self._private_user_ids = [int(u.nUserID) for u in users]
        self._announce_channel_members(users, actual)
        chat_tab = self.frame.chat_tab
        if chat_tab:
            chat_tab.refresh_private_user_choice(users)

    def refresh_members_for_my_channel(self) -> None:
        my_ch = int(self.frame.client.get_my_channel_id() or 0)
        if my_ch:
            self._selected_channel_id = my_ch
        self.refresh_channels_and_users()

    # ------------------------------------------------------------------
    # Nutzerinfo-Ansage (Hotkey)
    # ------------------------------------------------------------------

    def announce_selected_user_info(self) -> None:
        """Liest Infos über den aktuell ausgewählten Nutzer via TTS vor."""
        if self._selected_user_id is None:
            self.frame.tts.speak("Kein Nutzer ausgewählt", kind="system")
            return
        user = self._find_user(self._selected_user_id)
        if user is None:
            self.frame.tts.speak("Nutzer nicht gefunden", kind="system")
            return
        tt = self.frame.client.tt
        name = self.frame.tt_str(user.szNickname) or self.frame.tt_str(user.szUsername) or "Unbekannt"
        parts = [name]
        try:
            if user.uUserType & tt.UserType.USERTYPE_ADMIN:
                parts.append("Administrator")
            else:
                parts.append("Normaler Nutzer")
        except Exception:
            pass
        try:
            if user.uUserState & tt.UserState.USERSTATE_VOICE:
                parts.append("spricht gerade")
            elif user.uUserState & tt.UserState.USERSTATE_MUTE_VOICE:
                parts.append("stummgeschaltet")
        except Exception:
            pass
        try:
            if user.nStatusMode != 0:
                parts.append("abwesend")
        except Exception:
            pass
        self.frame.tts.speak(", ".join(parts), kind="system")

    # ------------------------------------------------------------------
    # Hilfsmethoden
    # ------------------------------------------------------------------

    def _find_user(self, user_id: int):
        """Sucht Nutzer erst in _all_users, dann in _current_users."""
        for user in self._all_users:
            if int(user.nUserID) == user_id:
                return user
        for user in self._current_users:
            if int(user.nUserID) == user_id:
                return user
        try:
            return self.frame.client.get_user(int(user_id))
        except Exception:
            return None

    # Rückwärtskompatibilität
    def _get_user_by_id(self, user_id: int):
        return self._find_user(user_id)

    def _channel_id_from_item(self, item: wx.TreeItemId) -> Optional[int]:
        for cid, ti in self._channel_items.items():
            if ti == item:
                return cid
        return None

    def _node_info_from_item(self, item: wx.TreeItemId):
        """Gibt (node_type, node_id) zurück. Primär via GetItemData, Fallback via Dict-Lookup."""
        data = self.channel_tree.GetItemData(item)
        if isinstance(data, dict):
            return data.get("type"), data.get("id")
        # Fallback: Reverse-Lookup über die ID-Dicts
        for cid, ti in self._channel_items.items():
            if ti == item:
                return _NODE_CHANNEL, cid
        for uid, ti in self._user_items.items():
            if ti == item:
                return _NODE_USER, uid
        return None, None

    def _announce_channel_members(self, users: List, channel_id: int) -> None:
        names = [self._format_user_label(u) for u in users]
        self.frame.logger.write(f"Channel members update: channel_id={channel_id} count={len(names)}")
        try:
            channel = self.frame.client.get_channel(channel_id)
            ch_name = self.frame.tt_str(channel.szName)
        except Exception:
            ch_name = ""
        if not ch_name:
            ch_name = "aktuellen Kanal"
        if names:
            announce = f"Im Kanal {ch_name}: " + ", ".join(names)
        else:
            announce = f"Im Kanal {ch_name} ist niemand."
        self.frame.set_status(announce)

    # ------------------------------------------------------------------
    # Baum-Events
    # ------------------------------------------------------------------

    def _on_tree_sel_changed(self, event) -> None:
        item = event.GetItem()
        if not item.IsOk():
            item = self.channel_tree.GetSelection()
        if not item.IsOk():
            return
        node_type, node_id = self._node_info_from_item(item)
        if node_type == _NODE_CHANNEL and node_id is not None:
            self._selected_channel_id = node_id
            self._selected_user_id = None
            label = self.channel_tree.GetItemText(item)
            self.frame.tts.speak(label, kind="system")
            try:
                self.frame.chat_tab.update_chat_target()
            except Exception:
                pass
        elif node_type == _NODE_USER and node_id is not None:
            self._selected_user_id = node_id
            user = self._find_user(node_id)
            if user:
                self.frame.tts.speak(self._format_user_label(user), kind="system")
            for i, uid in enumerate(self._private_user_ids):
                if uid == node_id:
                    try:
                        self.frame.chat_tab.private_user.SetSelection(i)
                    except Exception:
                        pass
                    break
            try:
                self.frame.chat_tab.update_chat_target()
            except Exception:
                pass

    def _on_tree_activated(self, event) -> None:
        item = event.GetItem()
        if not item.IsOk():
            item = self.channel_tree.GetSelection()
        if not item.IsOk():
            return
        node_type, node_id = self._node_info_from_item(item)
        if node_type == _NODE_CHANNEL and node_id is not None:
            self.frame.join_channel(node_id)
        elif node_type == _NODE_USER:
            try:
                self.frame.notebook.SetSelection(2)
            except Exception:
                pass

    def _on_join_btn(self, _event) -> None:
        if self._selected_channel_id:
            self.frame.join_channel(self._selected_channel_id)
        else:
            self.frame.set_status("Bitte zuerst einen Kanal im Baum auswählen")

    def _on_tree_key(self, event) -> None:
        key = event.GetKeyCode()
        if key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            item = self.channel_tree.GetSelection()
            if item.IsOk():
                node_type, node_id = self._node_info_from_item(item)
                if node_type == _NODE_CHANNEL and node_id is not None:
                    self.frame.join_channel(node_id)
                elif node_type == _NODE_USER:
                    try:
                        self.frame.notebook.SetSelection(2)
                    except Exception:
                        pass
            return
        if key == wx.WXK_WINDOWS_MENU or (key == wx.WXK_F10 and event.ShiftDown()):
            item = self.channel_tree.GetSelection()
            if item.IsOk():
                node_type, node_id = self._node_info_from_item(item)
                if node_type == _NODE_USER and node_id is not None:
                    self._show_user_context_menu_for(node_id)
            return
        event.Skip()

    def _on_tree_right_click(self, event) -> None:
        pos = event.GetPosition()
        item, _flags = self.channel_tree.HitTest(pos)
        if item.IsOk():
            node_type, node_id = self._node_info_from_item(item)
            if node_type == _NODE_USER and node_id is not None:
                self.channel_tree.SelectItem(item)
                self._selected_user_id = node_id
                try:
                    self.frame.chat_tab.update_chat_target()
                except Exception:
                    pass
                self._show_user_context_menu_for(node_id)
        event.Skip()

    # ------------------------------------------------------------------
    # Nutzer-Kontextmenü
    # ------------------------------------------------------------------

    def _show_user_context_menu_for(self, user_id: int) -> None:
        user = self._find_user(user_id)
        if user is None:
            return
        tt = self.frame.client.tt

        menu = wx.Menu()

        user_state = int(getattr(user, "uUserState", 0) or 0)
        voice_muted = bool(user_state & int(tt.UserState.USERSTATE_MUTE_VOICE))
        media_muted = bool(user_state & int(tt.UserState.USERSTATE_MUTE_MEDIAFILE))

        info_item = menu.Append(wx.ID_ANY, "Benutzerinfo...")
        menu.AppendSeparator()

        vol_voice_item = menu.Append(wx.ID_ANY, "Lautstärke Stimme...")
        vol_media_item = menu.Append(wx.ID_ANY, "Lautstärke Mediendatei...")
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
            ("Rundnachricht", tt.Subscription.SUBSCRIBE_BROADCAST_MSG),
            ("Desktop", tt.Subscription.SUBSCRIBE_DESKTOP),
            ("Desktop-Steuerung", tt.Subscription.SUBSCRIBE_DESKTOPINPUT),
            ("Desktop abfangen", tt.Subscription.SUBSCRIBE_INTERCEPT_DESKTOP),
            ("Benutzernachrichten abfangen", tt.Subscription.SUBSCRIBE_INTERCEPT_USER_MSG),
            ("Kanalnachrichten abfangen", tt.Subscription.SUBSCRIBE_INTERCEPT_CHANNEL_MSG),
            ("Sprache abfangen", tt.Subscription.SUBSCRIBE_INTERCEPT_VOICE),
            ("Video abfangen", tt.Subscription.SUBSCRIBE_INTERCEPT_VIDEOCAPTURE),
            ("Mediendatei abfangen", tt.Subscription.SUBSCRIBE_INTERCEPT_MEDIAFILE),
            ("Benutzerdefiniert abfangen", tt.Subscription.SUBSCRIBE_INTERCEPT_CUSTOM_MSG),
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
        kick_item = menu.Append(wx.ID_ANY, "Kicken")
        kick_ban_item = menu.Append(wx.ID_ANY, "Kicken + Bannen")
        desktop_access_item = menu.Append(wx.ID_ANY, "Desktop-Zugriff erlauben")

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

    # ------------------------------------------------------------------
    # Kontextmenü-Handler
    # ------------------------------------------------------------------

    def _on_user_info(self, user_id: int) -> None:
        user = self._find_user(user_id)
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

    def _on_user_volume(self, user_id: int, stream_type: int, label: str) -> None:
        dlg = wx.NumberEntryDialog(self, "Lautstärke (0–32000)", "Lautstärke:", f"{label}-Lautstärke", 1000, 0, 32000)
        if dlg.ShowModal() == wx.ID_OK:
            vol = dlg.GetValue()
            self.frame.client.set_user_volume(user_id, stream_type, vol)
            self.frame.set_status(f"{label}-Lautstärke auf {vol} gesetzt")
        dlg.Destroy()

    def _on_user_mute(self, user_id: int, stream_type: int, checked: bool) -> None:
        self.frame.client.set_user_mute(user_id, stream_type, bool(checked))
        label = "Mediendatei" if stream_type == int(self.frame.client.tt.StreamType.STREAMTYPE_MEDIAFILE) else "Stimme"
        self.frame.set_status(f"{label} {'stummgeschaltet' if checked else 'entstummt'}")

    def _on_user_op(self, user_id: int, make_op: bool) -> None:
        my_ch = self.frame.client.get_my_channel_id()
        if my_ch:
            self.frame.client.do_channel_op(int(my_ch), user_id, make_op)
            self.frame.set_status("Operator gesetzt" if make_op else "Operator entzogen")

    def _on_user_kick(self, user_id: int) -> None:
        my_ch = self.frame.client.get_my_channel_id()
        if not my_ch:
            return
        dlg = wx.MessageDialog(
            self, "Benutzer wirklich kicken?",
            "Kicken", wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION,
        )
        dlg.SetYesNoLabels("Ja", "Nein")
        if dlg.ShowModal() != wx.ID_YES:
            dlg.Destroy()
            return
        dlg.Destroy()
        self.frame.client.do_kick_user(user_id, int(my_ch))
        self.frame.set_status("Benutzer gekickt")

    def _on_user_kick_ban(self, user_id: int) -> None:
        user = self._find_user(user_id)
        if not user:
            self.frame.set_status("Benutzer nicht gefunden")
            return
        ban_types = self._ask_ban_types(user)
        if ban_types is None:
            return
        dlg = wx.MessageDialog(
            self, "Benutzer wirklich kicken und bannen?",
            "Kicken + Bannen", wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION,
        )
        dlg.SetYesNoLabels("Ja", "Nein")
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

    def _on_user_subscribe_toggle(self, user_id: int, flag: int, checked: bool) -> None:
        if checked:
            self.frame.client.do_subscribe(user_id, flag)
            self.frame.set_status("Abonnement aktiviert")
        else:
            self.frame.client.do_unsubscribe(user_id, flag)
            self.frame.set_status("Abonnement deaktiviert")

    def _on_user_ban(self, user_id: int) -> None:
        user = self._find_user(user_id)
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
            choices.extend([
                "IP-Adresse (Kanal)",
                "Benutzername (Kanal)",
                "IP-Adresse (Server)",
                "Benutzername (Server)",
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
        accel = wx.AcceleratorTable([(wx.ACCEL_CMD, ord("W"), wx.ID_CLOSE)])
        dlg.SetAcceleratorTable(accel)
        dlg.Bind(wx.EVT_MENU, lambda e: dlg.EndModal(wx.ID_CANCEL), id=wx.ID_CLOSE)
        if dlg.ShowModal() != wx.ID_OK:
            dlg.Destroy()
            return None
        idx = dlg.GetSelection()
        dlg.Destroy()
        if idx == wx.NOT_FOUND:
            return None
        return types[idx]
