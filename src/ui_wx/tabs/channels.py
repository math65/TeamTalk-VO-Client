"""Tab 2: Kanäle – flache ListBox mit Kanal/Nutzer-Einträgen (VoiceOver-zugänglich).

Layout: wx.ListBox füllt den gesamten Tab (VoiceOver-zuverlässiger als wx.TreeCtrl).
Tiefe wird durch Leerzeichen-Einrückung dargestellt (gut für Braillezeile).
Doppelklick/Enter auf Kanal → Kanal beitreten.
Kontextmenü auf Nutzer-Einträge (Rechtsklick / Shift+F10).
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple, TYPE_CHECKING

import wx

from ui_wx.a11y import setup_list_accessible

if TYPE_CHECKING:
    from app import MainFrame

_NODE_CHANNEL = "channel"
_NODE_USER = "user"


class ChannelsTab(wx.Panel):
    """Tab 2: Kanäle – flache ListBox, VoiceOver-zugänglich."""

    def __init__(self, parent: wx.Window, frame: "MainFrame") -> None:
        super().__init__(parent)
        self.frame = frame
        self.SetName("Kanäle")

        # Interne Zustandsvariablen
        self._items: List[Tuple[str, int]] = []   # [(node_type, node_id), ...]
        self._current_users: List = []
        self._all_users: List = []
        self._private_user_ids: List[int] = []
        self._selected_channel_id: Optional[int] = None
        self._selected_user_id: Optional[int] = None
        self._cached_channels: List = []
        # v2.4.0 – Schnellsuche: alle Labels/Items vor Filterung
        self._all_labels: List[str] = []
        self._all_items: List[Tuple[str, int]] = []
        # v4.6.0 – Diff-Cache: zuletzt angezeigte Labels für diff-basiertes Update
        self._displayed_labels: List[str] = []

        sizer = wx.BoxSizer(wx.VERTICAL)

        # v2.4.0 – Schnellsuche
        search_row = wx.BoxSizer(wx.HORIZONTAL)
        search_row.Add(wx.StaticText(self, label="Suche:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        self._channel_search = wx.TextCtrl(self)
        self._channel_search.SetName("Kanal suchen")
        self._channel_search.SetHelpText("Kanalnamen filtern (Eingabe filtert die Liste)")
        self._channel_search.Bind(wx.EVT_TEXT, self._on_channel_search)
        search_row.Add(self._channel_search, 1)
        sizer.Add(search_row, 0, wx.ALL | wx.EXPAND, 4)

        self.channel_list = wx.ListBox(self, style=wx.LB_SINGLE)
        self.channel_list.SetName("Kanalliste")
        setup_list_accessible(self.channel_list)
        self.channel_list.Bind(wx.EVT_LISTBOX, self._on_list_sel)
        self.channel_list.Bind(wx.EVT_LISTBOX_DCLICK, self._on_list_activate)
        self.channel_list.Bind(wx.EVT_KEY_DOWN, self._on_list_key)
        self.channel_list.Bind(wx.EVT_RIGHT_DOWN, self._on_list_right_click)
        sizer.Add(self.channel_list, 1, wx.ALL | wx.EXPAND, 4)

        self.join_btn = wx.Button(self, label="&Kanal beitreten")
        self.join_btn.SetName("Kanal beitreten")
        self.join_btn.Bind(wx.EVT_BUTTON, self._on_join_btn)
        sizer.Add(self.join_btn, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 4)

        self.SetSizer(sizer)

    # ------------------------------------------------------------------
    # Liste aufbauen
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

        try:
            all_users = list(client.get_server_users() or [])
        except Exception as exc:
            logger.write(f"get_server_users failed: {exc}")
            all_users = []
        self._all_users = all_users

        users_by_channel: Dict[int, List] = {}
        for u in all_users:
            try:
                cid = int(u.nChannelID)
                users_by_channel.setdefault(cid, []).append(u)
            except Exception:
                pass

        # Vorherige Auswahl merken
        prev_type: Optional[str] = None
        prev_id: Optional[int] = None
        sel_idx = self.channel_list.GetSelection()
        if sel_idx != wx.NOT_FOUND and sel_idx < len(self._items):
            prev_type, prev_id = self._items[sel_idx]

        if not channels:
            self.channel_list.Clear()
            self._items = []
            return

        # Root-Kanal ermitteln
        try:
            root_id = int(client.get_root_channel_id() or 0)
        except Exception:
            root_id = 0
        channel_ids = {c.nChannelID for c in channels}
        parent_ids = {c.nParentID for c in channels}
        if root_id <= 0 or root_id not in channel_ids:
            if 1 in parent_ids:
                root_id = 1
            elif parent_ids:
                root_id = min(parent_ids - {0})

        # Servernamen für Root-Kanal (Bearware Qt-Referenz)
        try:
            server_props = client.get_server_properties()
            server_name = tt_str(server_props.szServerName)
        except Exception:
            server_name = ""
        root_channel = next((c for c in channels if c.nChannelID == root_id), None)
        if not server_name and root_channel:
            server_name = tt_str(root_channel.szName)
        if not server_name:
            server_name = "Server"

        channels_by_id = {c.nChannelID: c for c in channels}

        # Flache Liste per DFS aufbauen
        labels, items = self._build_flat_list(
            root_id, root_channel, server_name, channels_by_id, users_by_channel
        )

        # v2.4.0 – Vollständige Liste für Schnellsuche merken
        self._all_labels = list(labels)
        self._all_items = list(items)

        self._items = items
        # v4.6.0 – Diff-basiertes Update: nur geänderte Labels ersetzen
        search = self._channel_search.GetValue().strip().lower() if hasattr(self, "_channel_search") else ""
        if search:
            filtered_labels, filtered_items = self._filter_by_search(labels, items, search)
            # Bei aktivem Filter immer vollständig neu aufbauen
            self.channel_list.Clear()
            if filtered_labels:
                self.channel_list.InsertItems(filtered_labels, 0)
            self._items = filtered_items
        else:
            self._diff_update_listbox(labels)

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
        restore_idx = -1
        if prev_type is not None and prev_id is not None:
            restore_idx = self._find_item_index(prev_type, prev_id)
        if restore_idx == -1 and my_ch:
            restore_idx = self._find_item_index(_NODE_CHANNEL, my_ch)
        if restore_idx == -1 and items:
            restore_idx = 0
        if restore_idx >= 0:
            self.channel_list.SetSelection(restore_idx)

    def _build_flat_list(
        self,
        root_id: int,
        root_channel,
        server_name: str,
        channels_by_id: Dict[int, object],
        users_by_channel: Dict[int, List],
    ) -> Tuple[List[str], List[Tuple[str, int]]]:
        labels: List[str] = []
        items: List[Tuple[str, int]] = []

        def visit(chan_id: int, depth: int) -> None:
            indent = "  " * depth
            chan = channels_by_id.get(chan_id)
            if chan_id == root_id:
                name = server_name
            else:
                name = self.frame.tt_str(chan.szName) if chan else str(chan_id)

            users = users_by_channel.get(chan_id, [])
            label = indent + self._make_channel_label(name, chan if chan_id != root_id else None, users)
            labels.append(label)
            items.append((_NODE_CHANNEL, chan_id))

            # Nutzer alphabetisch
            for user in sorted(users, key=lambda u: (self.frame.tt_str(u.szNickname) or "").lower()):
                user_indent = "  " * (depth + 1)
                labels.append(user_indent + self._format_user_label(user))
                items.append((_NODE_USER, int(user.nUserID)))

            # Unterkanäle alphabetisch
            children = sorted(
                [c for c in channels_by_id.values() if c.nParentID == chan_id],
                key=lambda c: (self.frame.tt_str(c.szName) or "").lower(),
            )
            for child in children:
                visit(child.nChannelID, depth + 1)

        visit(root_id, 0)
        return labels, items

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

    # Rückwärtskompatibilität
    def _format_member_label(self, user) -> str:
        return self._format_user_label(user)

    # ------------------------------------------------------------------
    # Hilfsmethoden
    # ------------------------------------------------------------------

    def _find_item_index(self, node_type: str, node_id: int) -> int:
        for i, (t, n) in enumerate(self._items):
            if t == node_type and n == node_id:
                return i
        return -1

    def _diff_update_listbox(self, new_labels: List[str]) -> bool:
        """v4.6.0 – Diff-basiertes Update: ersetzt nur geänderte Labels.

        Gibt True zurück wenn ein Diff-Update angewendet wurde (keine Full-Clear nötig).
        Fällt auf False zurück wenn Listen-Länge unterschiedlich ist.
        """
        old = self._displayed_labels
        if len(old) != len(new_labels):
            # Größenänderung → vollständiger Rebuild notwendig
            self.channel_list.Clear()
            if new_labels:
                self.channel_list.InsertItems(new_labels, 0)
            self._displayed_labels = list(new_labels)
            return True
        # Selektive Updates: nur geänderte Labels ersetzen
        changed = False
        for i, (old_lbl, new_lbl) in enumerate(zip(old, new_labels)):
            if old_lbl != new_lbl:
                self.channel_list.SetString(i, new_lbl)
                changed = True
        self._displayed_labels = list(new_labels)
        return True  # immer True wenn gleiche Länge

    def _filter_by_search(
        self,
        labels: List[str],
        items: List[Tuple[str, int]],
        search: str,
    ) -> Tuple[List[str], List[Tuple[str, int]]]:
        """Returns labels/items whose stripped text contains the search string."""
        filtered_labels: List[str] = []
        filtered_items: List[Tuple[str, int]] = []
        for label, item in zip(labels, items):
            if search in label.strip().lower():
                filtered_labels.append(label)
                filtered_items.append(item)
        return filtered_labels, filtered_items

    def _on_channel_search(self, _event) -> None:
        """v2.4.0 – Filters the channel list based on the search text."""
        search = self._channel_search.GetValue().strip().lower()
        if not search:
            # Restore full list
            self._items = list(self._all_items)
            self.channel_list.Clear()
            if self._all_labels:
                self.channel_list.InsertItems(self._all_labels, 0)
            # Try to restore selection to current channel
            try:
                my_ch = int(self.frame.client.get_my_channel_id() or 0)
                if my_ch:
                    idx = self._find_item_index(_NODE_CHANNEL, my_ch)
                    if idx >= 0:
                        self.channel_list.SetSelection(idx)
            except Exception:
                pass
            return
        filtered_labels, filtered_items = self._filter_by_search(
            self._all_labels, self._all_items, search
        )
        self._items = filtered_items
        self.channel_list.Clear()
        if filtered_labels:
            self.channel_list.InsertItems(filtered_labels, 0)

    def _find_user(self, user_id: int):
        for user in self._all_users:
            if int(user.nUserID) == user_id:
                return user
        for user in self._current_users:
            if int(user.nUserID) == user_id:
                return user
        try:
            return self.frame.client.get_user(user_id)
        except Exception:
            return None

    # Rückwärtskompatibilität
    def _get_user_by_id(self, user_id: int):
        return self._find_user(user_id)

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
    # Nutzer im eigenen Kanal aktualisieren
    # ------------------------------------------------------------------

    def refresh_users_for_channel(self, channel_id: int) -> None:
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
    # Listen-Events
    # ------------------------------------------------------------------

    def _on_list_sel(self, event) -> None:
        try:
            idx = self.channel_list.GetSelection()
            if idx == wx.NOT_FOUND or idx >= len(self._items):
                return
            node_type, node_id = self._items[idx]
            if node_type == _NODE_CHANNEL:
                self._selected_channel_id = node_id
                self._selected_user_id = None
                label = self.channel_list.GetString(idx).strip()
                self.frame.tts.speak(label, kind="system")
                try:
                    self.frame.chat_tab.update_chat_target()
                except Exception:
                    pass
            elif node_type == _NODE_USER:
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
        except Exception:
            pass

    def _on_list_activate(self, event) -> None:
        try:
            idx = self.channel_list.GetSelection()
            if idx == wx.NOT_FOUND or idx >= len(self._items):
                return
            node_type, node_id = self._items[idx]
            if node_type == _NODE_CHANNEL:
                self.frame.join_channel(node_id)
            elif node_type == _NODE_USER:
                try:
                    self.frame.notebook.SetSelection(2)
                except Exception:
                    pass
        except Exception:
            pass

    def _on_join_btn(self, _event) -> None:
        if self._selected_channel_id:
            self.frame.join_channel(self._selected_channel_id)
        else:
            self.frame.set_status("Bitte zuerst einen Kanal in der Liste auswählen")

    def _on_list_key(self, event) -> None:
        key = event.GetKeyCode()
        if key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            idx = self.channel_list.GetSelection()
            if idx != wx.NOT_FOUND and idx < len(self._items):
                node_type, node_id = self._items[idx]
                if node_type == _NODE_CHANNEL:
                    self.frame.join_channel(node_id)
                elif node_type == _NODE_USER:
                    try:
                        self.frame.notebook.SetSelection(2)
                    except Exception:
                        pass
            return
        if key == wx.WXK_WINDOWS_MENU or (key == wx.WXK_F10 and event.ShiftDown()):
            idx = self.channel_list.GetSelection()
            if idx != wx.NOT_FOUND and idx < len(self._items):
                node_type, node_id = self._items[idx]
                if node_type == _NODE_USER:
                    self._show_user_context_menu_for(node_id)
            return
        event.Skip()

    def _on_list_right_click(self, event) -> None:
        try:
            pos = event.GetPosition()
            idx = self.channel_list.HitTest(pos)
            if idx != wx.NOT_FOUND and idx < len(self._items):
                node_type, node_id = self._items[idx]
                self.channel_list.SetSelection(idx)
                if node_type == _NODE_USER:
                    self._selected_user_id = node_id
                    try:
                        self.frame.chat_tab.update_chat_target()
                    except Exception:
                        pass
                    self._show_user_context_menu_for(node_id)
                elif node_type == _NODE_CHANNEL:
                    self._selected_channel_id = node_id
                    self._show_channel_context_menu_for(node_id)
        except Exception:
            pass
        event.Skip()

    def _show_channel_context_menu_for(self, channel_id: int) -> None:
        """Kontextmenü für einen Kanal-Eintrag."""
        menu = wx.Menu()
        join_item = menu.Append(wx.ID_ANY, _("Kanal &beitreten"))
        menu.AppendSeparator()

        # Kanal-Notiz: zeige ob eine Notiz existiert
        server_key = getattr(self.frame, "_current_server_key", "")
        has_note = False
        try:
            has_note = self.frame._channel_notes.has_note(server_key, channel_id)
        except Exception:
            pass
        note_label = _("Notiz bearbeiten... [✓]") if has_note else _("Notiz bearbeiten...")
        note_item = menu.Append(wx.ID_ANY, note_label)

        def _join(_e):
            self.frame.join_channel(channel_id)

        def _note(_e):
            self.frame.on_menu_channel_note(None)

        menu.Bind(wx.EVT_MENU, _join, join_item)
        menu.Bind(wx.EVT_MENU, _note, note_item)
        self.PopupMenu(menu)
        menu.Destroy()

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

        info_item = menu.Append(wx.ID_ANY, _("Benutzerinfo..."))
        menu.AppendSeparator()

        vol_voice_item = menu.Append(wx.ID_ANY, _("Lautstärke Stimme..."))
        vol_media_item = menu.Append(wx.ID_ANY, _("Lautstärke Mediendatei..."))
        mute_voice_item = menu.AppendCheckItem(wx.ID_ANY, _("Stimme stummschalten"))
        mute_media_item = menu.AppendCheckItem(wx.ID_ANY, _("Mediendatei stummschalten"))
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
        menu.AppendSubMenu(sub_menu, _("Abonnements"))

        my_ch = self.frame.client.get_my_channel_id()
        is_op = self.frame.client.is_channel_operator(int(my_ch), user_id) if my_ch else False
        op_label = _("Operator entziehen") if is_op else _("Zum Operator machen")
        op_item = menu.Append(wx.ID_ANY, op_label)

        ban_item = menu.Append(wx.ID_ANY, _("Bannen..."))
        move_item = menu.Append(wx.ID_ANY, _("Benutzer verschieben..."))
        kick_item = menu.Append(wx.ID_ANY, _("Kicken"))
        kick_ban_item = menu.Append(wx.ID_ANY, _("Kicken + Bannen"))
        desktop_access_item = menu.Append(wx.ID_ANY, _("Desktop-Zugriff erlauben"))

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
