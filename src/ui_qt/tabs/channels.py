"""Tab 2: Kanäle – QListWidget mit Kanal/Nutzer-Einträgen."""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple, TYPE_CHECKING

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QPushButton, QMenu, QListWidgetItem,
    QInputDialog, QMessageBox, QApplication,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent, QFont, QColor

from i18n import _

if TYPE_CHECKING:
    from app_qt import MainWindow

_NODE_CHANNEL = "channel"
_NODE_USER = "user"


class ChannelsTab(QWidget):
    """Tab 2: Kanäle."""

    def __init__(self, parent: QWidget, window: "MainWindow") -> None:
        super().__init__(parent)
        self.window = window
        self._items: List[Tuple[str, int]] = []
        self._current_users: List = []
        self._all_users: List = []
        self._private_user_ids: List[int] = []
        self._selected_channel_id: Optional[int] = None
        self._selected_user_id: Optional[int] = None
        self._cached_channels: List = []
        self._all_labels: List[str] = []
        self._all_items: List[Tuple[str, int]] = []
        self._displayed_labels: List[str] = []
        # user notes are persisted in settings_store.settings.user_notes (keyed by username)

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)

        search_row = QHBoxLayout()
        search_row.addWidget(QLabel(_("Suche:")))
        self._channel_search = QLineEdit()
        self._channel_search.setAccessibleName(_("Kanal suchen"))
        self._channel_search.setAccessibleDescription(
            _("Eingabe filtert die Kanalliste. Leer lassen für alle Kanäle.")
        )
        self._channel_search.setPlaceholderText(_("Kanalnamen filtern …"))
        self._channel_search.textChanged.connect(self._on_channel_search)
        search_row.addWidget(self._channel_search)
        root.addLayout(search_row)

        self.channel_list = QListWidget()
        self.channel_list.setAccessibleName(_("Kanäle und Benutzer"))
        self.channel_list.setAccessibleDescription(
            _("Liste aller Kanäle und verbundenen Benutzer. "
              "Enter: Kanal beitreten oder privaten Chat öffnen. "
              "Shift+F10 oder Kontextmenü-Taste: Aktionen.")
        )
        self.channel_list.setStyleSheet(
            "QListWidget::item { padding: 3px 6px; }"
            "QListWidget::item:selected { font-weight: bold; }"
        )
        self.channel_list.currentRowChanged.connect(self._on_list_sel)
        self.channel_list.itemActivated.connect(self._on_list_activate)
        self.channel_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.channel_list.customContextMenuRequested.connect(self._on_list_right_click)
        self.channel_list.installEventFilter(self)
        root.addWidget(self.channel_list, 1)

        btn_row = QHBoxLayout()
        self.join_btn = QPushButton(_("&Kanal beitreten"))
        self.join_btn.setAccessibleName(_("Ausgewählten Kanal beitreten"))
        self.join_btn.clicked.connect(self._on_join_btn)
        btn_row.addWidget(self.join_btn, 1)

        self.refresh_btn = QPushButton(_("&Aktualisieren"))
        self.refresh_btn.setAccessibleName(_("Kanalliste aktualisieren"))
        self.refresh_btn.setToolTip(_("Kanal- und Nutzerliste neu laden"))
        self.refresh_btn.clicked.connect(self.refresh_channels_and_users)
        btn_row.addWidget(self.refresh_btn)
        root.addLayout(btn_row)

    # ------------------------------------------------------------------
    # Item styling helpers
    # ------------------------------------------------------------------

    def _make_list_item(self, label: str, node_type: str) -> QListWidgetItem:
        item = QListWidgetItem(label)
        self._apply_item_style(item, node_type)
        return item

    def _apply_item_style(self, item: QListWidgetItem, node_type: str) -> None:
        font = item.font()
        font.setBold(node_type == _NODE_CHANNEL)
        item.setFont(font)

    def eventFilter(self, obj, event) -> bool:
        if obj is self.channel_list and isinstance(event, QKeyEvent):
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._on_list_activate(self.channel_list.currentItem())
                return True
            if event.key() == Qt.Key.Key_F10 and (event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
                row = self.channel_list.currentRow()
                if 0 <= row < len(self._items):
                    node_type, node_id = self._items[row]
                    if node_type == _NODE_USER:
                        self._show_user_context_menu_for(node_id)
                    elif node_type == _NODE_CHANNEL:
                        self._show_channel_context_menu_for(node_id)
                return True
        return super().eventFilter(obj, event)

    # ------------------------------------------------------------------
    # List refresh
    # ------------------------------------------------------------------

    def refresh_channels_and_users(self) -> None:
        client = self.window.client
        tt_str = self.window.tt_str
        logger = self.window.logger

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

        prev_type: Optional[str] = None
        prev_id: Optional[int] = None
        cur_row = self.channel_list.currentRow()
        if 0 <= cur_row < len(self._items):
            prev_type, prev_id = self._items[cur_row]

        if not channels:
            self.channel_list.clear()
            self._items = []
            return

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
        labels, items = self._build_flat_list(
            root_id, root_channel, server_name, channels_by_id, users_by_channel
        )

        self._all_labels = list(labels)
        self._all_items = list(items)
        self._items = items

        search = self._channel_search.text().strip().lower()
        if search:
            filtered_labels, filtered_items = self._filter_by_search(labels, items, search)
            self.channel_list.clear()
            for lbl, (ntype, _nid) in zip(filtered_labels, filtered_items):
                self.channel_list.addItem(self._make_list_item(lbl, ntype))
            self._items = filtered_items
        else:
            self._diff_update_listwidget(labels)

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
        chat_tab = self.window.chat_tab
        if chat_tab and self._current_users is not None:
            try:
                chat_tab.refresh_private_user_choice(self._current_users)
            except Exception:
                pass

        restore_idx = -1
        if prev_type is not None and prev_id is not None:
            restore_idx = self._find_item_index(prev_type, prev_id)
        if restore_idx == -1 and my_ch:
            restore_idx = self._find_item_index(_NODE_CHANNEL, my_ch)
        if restore_idx == -1 and items:
            restore_idx = 0
        if restore_idx >= 0:
            self.channel_list.setCurrentRow(restore_idx)

    def _count_total_users(self, chan_id: int, users_by_channel: Dict, channels_by_id: Dict) -> int:
        total = len(users_by_channel.get(chan_id, []))
        for child in channels_by_id.values():
            if int(child.nParentID) == chan_id:
                total += self._count_total_users(child.nChannelID, users_by_channel, channels_by_id)
        return total

    def _build_flat_list(self, root_id, root_channel, server_name,
                         channels_by_id, users_by_channel,
                         depth=0) -> Tuple[List[str], List[Tuple[str, int]]]:
        labels: List[str] = []
        items: List[Tuple[str, int]] = []
        indent = "  " * depth
        ch = root_channel or channels_by_id.get(root_id)
        if ch is None:
            return labels, items
        tt_str = self.window.tt_str
        ch_name = server_name if depth == 0 else tt_str(ch.szName)
        user_count = len(users_by_channel.get(root_id, []))
        total_count = self._count_total_users(root_id, users_by_channel, channels_by_id)
        has_pw = bool(getattr(ch, "bPassword", False))
        braille = getattr(self.window, "braille", None)
        compact = braille and braille.verbosity == "compact"
        if compact:
            if total_count > user_count:
                count_txt = f" {user_count}/{total_count}N"
            elif user_count:
                count_txt = f" {user_count}N"
            else:
                count_txt = ""
            pw_txt = " [P]" if has_pw else ""
            labels.append(f"{indent}{ch_name}{pw_txt}{count_txt}")
        else:
            topic = ""
            try:
                t = tt_str(ch.szTopic)
                if t:
                    topic = f", {t}"
            except Exception:
                pass
            if total_count > user_count:
                count_txt = f" ({user_count}/{total_count})"
            elif user_count:
                count_txt = f" ({user_count})"
            else:
                count_txt = ""
            pw_txt = ", Passwort" if has_pw else ""
            labels.append(f"{indent}[{ch_name}{topic}{pw_txt}{count_txt}]")
        items.append((_NODE_CHANNEL, root_id))

        for u in sorted(users_by_channel.get(root_id, []),
                        key=lambda u: (tt_str(u.szNickname) or "").lower()):
            try:
                uname = tt_str(u.szNickname) or tt_str(u.szUsername) or f"User#{u.nUserID}"
                line = f"{indent}  {uname}"
                if not compact:
                    status_txt = tt_str(u.szStatusMsg)
                    if status_txt:
                        line += f", {status_txt}"
                labels.append(line)
                items.append((_NODE_USER, int(u.nUserID)))
            except Exception:
                pass

        for cid in sorted(
            [c.nChannelID for c in channels_by_id.values()
             if int(c.nParentID) == root_id and c.nChannelID != root_id],
            key=lambda cid: (tt_str(channels_by_id[cid].szName) or "").lower()
        ):
            sub_labels, sub_items = self._build_flat_list(
                cid, channels_by_id[cid], "", channels_by_id, users_by_channel, depth + 1
            )
            labels.extend(sub_labels)
            items.extend(sub_items)

        return labels, items

    def _diff_update_listwidget(self, new_labels: List[str]) -> None:
        old = self._displayed_labels
        if new_labels == old:
            return
        if len(new_labels) == len(old):
            for i, (new, old_lbl) in enumerate(zip(new_labels, old)):
                if new != old_lbl:
                    item = self.channel_list.item(i)
                    if item:
                        item.setText(new)
                        if i < len(self._items):
                            self._apply_item_style(item, self._items[i][0])
        else:
            self.channel_list.clear()
            for i, lbl in enumerate(new_labels):
                node_type = self._items[i][0] if i < len(self._items) else _NODE_CHANNEL
                self.channel_list.addItem(self._make_list_item(lbl, node_type))
        self._displayed_labels = list(new_labels)

    def _filter_by_search(self, labels, items, search):
        filtered_labels, filtered_items = [], []
        for lbl, item in zip(labels, items):
            if search in lbl.lower():
                filtered_labels.append(lbl)
                filtered_items.append(item)
        return filtered_labels, filtered_items

    def _find_item_index(self, node_type: str, node_id: int) -> int:
        for i, (t, nid) in enumerate(self._items):
            if t == node_type and nid == node_id:
                return i
        return -1

    def _announce_channel_members(self, users, channel_id: int) -> None:
        pass  # handled by app_qt event system

    def _find_user(self, user_id: int):
        for user in self._all_users:
            if int(user.nUserID) == user_id:
                return user
        for user in self._current_users:
            if int(user.nUserID) == user_id:
                return user
        try:
            return self.window.client.get_user(user_id)
        except Exception:
            return None

    def _format_user_label(self, user) -> str:
        tt_str = self.window.tt_str
        try:
            name = tt_str(user.szNickname) or tt_str(user.szUsername) or "Benutzer"
        except Exception:
            name = "Benutzer"
        flags = []
        try:
            tt = self.window.client.tt
            if user.uUserType & tt.UserType.USERTYPE_ADMIN:
                flags.append("Admin")
        except Exception:
            pass
        try:
            tt = self.window.client.tt
            if user.uUserState & tt.UserState.USERSTATE_VOICE:
                flags.append("Spricht")
            elif user.uUserState & tt.UserState.USERSTATE_MUTE_VOICE:
                flags.append("Stumm")
        except Exception:
            pass
        if flags:
            return f"{name}, {', '.join(flags)}"
        return name

    # ------------------------------------------------------------------
    # User info announcement (hotkey support)
    # ------------------------------------------------------------------

    def announce_selected_user_info(self) -> None:
        if self._selected_user_id is None:
            self.window.tts.speak("Kein Nutzer ausgewählt", kind="system")
            return
        user = self._find_user(self._selected_user_id)
        if user is None:
            self.window.tts.speak("Nutzer nicht gefunden", kind="system")
            return
        self.window.tts.speak(self._build_user_info_text(user), kind="system")

    def _build_user_info_text(self, user) -> str:
        tt_str = self.window.tt_str
        name = tt_str(user.szNickname) or tt_str(user.szUsername) or "Unbekannt"
        parts = [name]
        try:
            tt = self.window.client.tt
            if user.uUserType & tt.UserType.USERTYPE_ADMIN:
                parts.append("Administrator")
            else:
                parts.append("Normaler Nutzer")
        except Exception:
            pass
        try:
            tt = self.window.client.tt
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
        return ", ".join(parts)

    # ------------------------------------------------------------------
    # List events
    # ------------------------------------------------------------------

    def _on_list_sel(self, row: int) -> None:
        if row < 0 or row >= len(self._items):
            return
        node_type, node_id = self._items[row]
        if node_type == _NODE_CHANNEL:
            self._selected_channel_id = node_id
            self._selected_user_id = None
        else:
            self._selected_user_id = node_id
            self._selected_channel_id = None
            # Sync private user combobox in chat tab
            try:
                chat_tab = self.window.chat_tab
                if chat_tab and node_id in chat_tab._private_user_ids:
                    chat_tab.private_user.setCurrentIndex(
                        chat_tab._private_user_ids.index(node_id)
                    )
            except Exception:
                pass

    def _on_list_activate(self, item) -> None:
        row = self.channel_list.currentRow()
        if row < 0 or row >= len(self._items):
            return
        node_type, node_id = self._items[row]
        if node_type == _NODE_CHANNEL:
            self.window.join_channel(node_id)
        elif node_type == _NODE_USER:
            self._open_private_chat_for_user(node_id)

    def _on_list_right_click(self, pos) -> None:
        item = self.channel_list.itemAt(pos)
        if item is None:
            return
        row = self.channel_list.row(item)
        if row < 0 or row >= len(self._items):
            return
        self.channel_list.setCurrentRow(row)
        node_type, node_id = self._items[row]
        if node_type == _NODE_USER:
            self._selected_user_id = node_id
            self._show_user_context_menu_for(node_id)
        elif node_type == _NODE_CHANNEL:
            self._selected_channel_id = node_id
            self._show_channel_context_menu_for(node_id)

    # ------------------------------------------------------------------
    # Channel context menu
    # ------------------------------------------------------------------

    def _show_channel_context_menu_for(self, channel_id: int) -> None:
        menu = QMenu(self)

        join_action = menu.addAction(_("Kanal &beitreten"))
        leave_action = menu.addAction(_("Kanal &verlassen"))
        menu.addSeparator()
        create_action = menu.addAction(_("Kanal &erstellen..."))
        edit_action = menu.addAction(_("Kanal &bearbeiten..."))
        delete_action = menu.addAction(_("Kanal &löschen"))
        menu.addSeparator()
        info_action = menu.addAction(_("Kanal-&Info..."))
        url_action = menu.addAction(_("TT-URL &kopieren"))
        menu.addSeparator()
        speak_info_action = menu.addAction(_("Kanalinfo &sprechen"))
        menu.addSeparator()
        ban_list_action = menu.addAction(_("&Sperrliste anzeigen..."))

        action = menu.exec(self.channel_list.mapToGlobal(
            self.channel_list.visualItemRect(
                self.channel_list.item(self._find_item_index(_NODE_CHANNEL, channel_id))
            ).center()
        ))

        if action == join_action:
            self.window.join_channel(channel_id)
        elif action == leave_action:
            self.window.leave_channel()
        elif action == create_action:
            self.window.on_menu_create_channel()
        elif action == edit_action:
            self.window.on_menu_edit_channel()
        elif action == delete_action:
            self.window.on_menu_delete_channel()
        elif action == info_action:
            self._show_channel_info(channel_id)
        elif action == url_action:
            self._copy_tt_url_for_channel(channel_id)
        elif action == speak_info_action:
            self._speak_channel_info(channel_id)
        elif action == ban_list_action:
            self.window.on_menu_channel_bans()

    def _show_channel_info(self, channel_id: int) -> None:
        tt_str = self.window.tt_str
        ch = None
        for c in self._cached_channels:
            if c.nChannelID == channel_id:
                ch = c
                break
        if ch is None:
            QMessageBox.information(self, _("Kanal-Info"), _("Kanal nicht gefunden"))
            return
        name = tt_str(ch.szName)
        topic = tt_str(ch.szTopic)
        has_pw = bool(getattr(ch, "bPassword", False))
        user_count = sum(
            1 for (t, nid) in self._items
            if t == _NODE_USER and self._channel_of_user(nid) == channel_id
        )
        lines = [
            f"Name: {name}",
            f"Thema: {topic or '(kein)'}",
            f"Passwort: {'Ja' if has_pw else 'Nein'}",
            f"Nutzer: {user_count}",
            f"ID: {channel_id}",
        ]
        QMessageBox.information(self, _("Kanal-Info"), "\n".join(lines))

    def _channel_of_user(self, user_id: int) -> int:
        for u in self._all_users:
            try:
                if int(u.nUserID) == user_id:
                    return int(u.nChannelID)
            except Exception:
                pass
        return 0

    def _copy_tt_url_for_channel(self, channel_id: int) -> None:
        try:
            profile = getattr(self.window, "_current_profile", None)
            if profile is not None:
                from ui.tt_file_parser import build_teamtalk_url
                url = build_teamtalk_url(profile)
            else:
                url = ""
            if url:
                QApplication.clipboard().setText(url)
                self.window.set_status(f"TT-URL kopiert: {url}")
            else:
                self.window.set_status("Keine TT-URL verfügbar")
        except Exception as exc:
            self.window.set_status(f"URL kopieren fehlgeschlagen: {exc}")

    def _speak_channel_info(self, channel_id: int) -> None:
        tt_str = self.window.tt_str
        ch = None
        for c in self._cached_channels:
            if c.nChannelID == channel_id:
                ch = c
                break
        if ch is None:
            self.window.tts.speak("Kanal nicht gefunden", kind="system")
            return
        name = tt_str(ch.szName)
        topic = tt_str(ch.szTopic)
        users = [u for u in self._all_users if int(u.nChannelID) == channel_id]
        user_count = len(users)
        parts = [name]
        if topic:
            parts.append(f"Thema: {topic}")
        parts.append(f"{user_count} Nutzer")
        self.window.tts.speak(", ".join(parts), kind="system")

    # ------------------------------------------------------------------
    # User context menu
    # ------------------------------------------------------------------

    def _show_user_context_menu_for(self, user_id: int) -> None:
        user = self._find_user(user_id)
        if user is None:
            return

        try:
            tt = self.window.client.tt
        except Exception:
            tt = None

        menu = QMenu(self)

        info_action = menu.addAction(_("Benutzerinfo &sprechen"))
        pm_action = menu.addAction(_("&Private Nachricht..."))
        menu.addSeparator()
        vol_action = menu.addAction(_("&Lautstärke..."))

        # Mute state
        voice_muted = False
        try:
            if tt:
                voice_muted = bool(user.uUserState & tt.UserState.USERSTATE_MUTE_VOICE)
        except Exception:
            pass
        mute_label = _("Mikrofon &entstummen") if voice_muted else _("Mikrofon &stummschalten")
        mute_action = menu.addAction(mute_label)

        # Media mute state
        media_muted = False
        try:
            if tt:
                media_muted = bool(user.uUserState & tt.UserState.USERSTATE_MUTE_MEDIAFILE)
        except Exception:
            media_muted = self.window._user_media_muted.get(user_id, False)
        media_mute_label = _("Medienstream &entstummen") if media_muted else _("Medienstream &stummschalten")
        media_mute_action = menu.addAction(media_mute_label)
        media_vol_action = menu.addAction(_("Medienstream-&Lautstärke..."))
        menu.addSeparator()

        # Subscription submenu
        sub_menu = menu.addMenu(_("&Abonnements"))
        sub_actions = []
        if tt:
            sub_flags = [
                (_("Sprache"), "SUBSCRIBE_VOICE"),
                (_("Video"), "SUBSCRIBE_VIDEOCAPTURE"),
                (_("Mediendatei"), "SUBSCRIBE_MEDIAFILE"),
                (_("Benutzernachrichten"), "SUBSCRIBE_USER_MSG"),
                (_("Kanalnachrichten"), "SUBSCRIBE_CHANNEL_MSG"),
                (_("Sprache abfangen"), "SUBSCRIBE_INTERCEPT_VOICE"),
                (_("Mediendatei abfangen"), "SUBSCRIBE_INTERCEPT_MEDIAFILE"),
            ]
            current_subs = int(getattr(user, "uLocalSubscriptions", 0) or 0)
            for label, flag_name in sub_flags:
                try:
                    flag_val = int(getattr(tt.Subscription, flag_name))
                    checked = bool(current_subs & flag_val)
                    act = sub_menu.addAction(label)
                    act.setCheckable(True)
                    act.setChecked(checked)
                    sub_actions.append((act, flag_val, checked))
                except Exception:
                    pass

        menu.addSeparator()

        # Operator
        my_ch = 0
        is_op = False
        try:
            my_ch = int(self.window.client.get_my_channel_id() or 0)
            is_op = bool(self.window.client.is_channel_operator(my_ch, user_id)) if my_ch else False
        except Exception:
            pass
        op_label = _("Operator &entfernen") if is_op else _("Zum &Operator machen")
        op_action = menu.addAction(op_label)
        menu.addSeparator()

        move_action = menu.addAction(_("Benutzer &verschieben..."))
        menu.addSeparator()
        kick_action = menu.addAction(_("Aus Kanal &kicken..."))
        kick_ban_action = menu.addAction(_("Aus Kanal kicken + &Bannen..."))
        kick_server_action = menu.addAction(_("Vom &Server kicken..."))
        menu.addSeparator()

        note_action = menu.addAction(_("&Notiz bearbeiten..."))

        action = menu.exec(self.channel_list.mapToGlobal(
            self.channel_list.visualItemRect(
                self.channel_list.currentItem()
            ).center()
        ))

        if action is None:
            return

        if action == info_action:
            self.window.tts.speak(self._build_user_info_text(user), kind="system")

        elif action == pm_action:
            self._send_private_message_dialog(user_id)

        elif action == vol_action:
            self._set_user_volume_dialog(user_id)

        elif action == mute_action:
            self._toggle_user_mute(user_id, not voice_muted)

        elif action == media_mute_action:
            self._toggle_media_mute(user_id, not media_muted)

        elif action == media_vol_action:
            self._set_media_volume_dialog(user_id)

        elif action == op_action:
            self._toggle_channel_op(user_id, my_ch, not is_op)

        elif action == move_action:
            self.window.on_menu_move_user()

        elif action == kick_action:
            self._kick_user_from_channel(user_id, my_ch)

        elif action == kick_ban_action:
            self._kick_ban_user(user_id)

        elif action == kick_server_action:
            self._kick_user_from_server(user_id)

        elif action == note_action:
            self._edit_user_note(user_id)

        else:
            # Check subscription toggle actions
            for act, flag_val, was_checked in sub_actions:
                if action == act:
                    now_checked = act.isChecked()
                    try:
                        if now_checked:
                            self.window.client.do_subscribe(user_id, flag_val)
                            self.window.set_status(_("Abonnement aktiviert"))
                        else:
                            self.window.client.do_unsubscribe(user_id, flag_val)
                            self.window.set_status(_("Abonnement deaktiviert"))
                    except Exception as exc:
                        self.window.set_status(f"Abonnement fehlgeschlagen: {exc}")
                    break

    # ------------------------------------------------------------------
    # User context menu handlers
    # ------------------------------------------------------------------

    def _send_private_message_dialog(self, user_id: int) -> None:
        user = self._find_user(user_id)
        name = ""
        if user:
            tt_str = self.window.tt_str
            name = tt_str(user.szNickname) or tt_str(user.szUsername) or f"User#{user_id}"
        msg, ok = QInputDialog.getText(
            self, _("Private Nachricht"), f"Nachricht an {name}:"
        )
        if ok and msg.strip():
            self.window.send_chat_message(msg.strip(), private=True, target_id=user_id)

    def _set_user_volume_dialog(self, user_id: int) -> None:
        try:
            tt = self.window.client.tt
            stream_type = int(tt.StreamType.STREAMTYPE_VOICE)
        except Exception:
            self.window.set_status(_("Lautstärke: SDK nicht verfügbar"))
            return
        current = self.window._user_volume_levels.get(user_id, 16384)
        vol, ok = QInputDialog.getInt(
            self, _("Lautstärke"), _("Lautstärke (0–32000):"), current, 0, 32000, 100
        )
        if ok:
            try:
                self.window.client.set_user_volume(user_id, stream_type, vol)
                self.window._user_volume_levels[user_id] = vol
                self.window.set_status(f"Lautstärke auf {vol} gesetzt")
            except Exception as exc:
                self.window.set_status(f"Lautstärke fehlgeschlagen: {exc}")

    def _toggle_user_mute(self, user_id: int, mute: bool) -> None:
        try:
            tt = self.window.client.tt
            stream_type = int(tt.StreamType.STREAMTYPE_VOICE)
            self.window.client.set_user_mute(user_id, stream_type, mute)
            self.window.set_status(_("Stummgeschaltet") if mute else _("Entstummt"))
        except Exception as exc:
            self.window.set_status(f"Stummschalten fehlgeschlagen: {exc}")

    def _toggle_media_mute(self, user_id: int, mute: bool) -> None:
        try:
            tt = self.window.client.tt
            stream_type = int(tt.StreamType.STREAMTYPE_MEDIAFILE_AUDIO)
            self.window.client.set_user_mute(user_id, stream_type, mute)
            self.window._user_media_muted[user_id] = mute
            self.window.set_status(_("Medienstream stummgeschaltet") if mute else _("Medienstream entstummt"))
        except Exception as exc:
            self.window.set_status(f"Medien-Stummschalten fehlgeschlagen: {exc}")

    def _set_media_volume_dialog(self, user_id: int) -> None:
        try:
            tt = self.window.client.tt
            stream_type = int(tt.StreamType.STREAMTYPE_MEDIAFILE_AUDIO)
        except Exception:
            self.window.set_status(_("Medien-Lautstärke: SDK nicht verfügbar"))
            return
        current = self.window._user_media_volumes.get(user_id, 16384)
        vol, ok = QInputDialog.getInt(
            self, _("Medienstream-Lautstärke"), _("Lautstärke (0–32000):"), current, 0, 32000, 500
        )
        if ok:
            try:
                self.window.client.set_user_volume(user_id, stream_type, vol)
                self.window._user_media_volumes[user_id] = vol
                self.window.set_status(f"Medien-Lautstärke auf {vol} gesetzt")
            except Exception as exc:
                self.window.set_status(f"Medien-Lautstärke fehlgeschlagen: {exc}")

    def _toggle_channel_op(self, user_id: int, channel_id: int, make_op: bool) -> None:
        if not channel_id:
            self.window.set_status(_("Kein eigener Kanal"))
            return
        try:
            self.window.client.do_channel_op(channel_id, user_id, make_op)
            self.window.set_status(_("Operator gesetzt") if make_op else _("Operator entzogen"))
        except Exception as exc:
            self.window.set_status(f"Operator fehlgeschlagen: {exc}")

    def _kick_user_from_channel(self, user_id: int, channel_id: int) -> None:
        if not channel_id:
            self.window.set_status(_("Kein eigener Kanal"))
            return
        reply = QMessageBox.question(
            self, _("Kicken"), _("Benutzer wirklich aus dem Kanal kicken?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            try:
                self.window.client.do_kick_user(user_id, channel_id)
                self.window.set_status(_("Benutzer gekickt"))
            except Exception as exc:
                self.window.set_status(f"Kick fehlgeschlagen: {exc}")

    def _kick_ban_user(self, user_id: int) -> None:
        user = self._find_user(user_id)
        reply = QMessageBox.question(
            self, _("Kicken + Bannen"), _("Benutzer wirklich kicken und bannen?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            tt = self.window.client.tt
            ban_types = int(tt.BanType.BANTYPE_USERNAME)
            self.window.client.do_ban_user_ex(user_id, ban_types)
            ch_id = int(getattr(user, "nChannelID", 0) or 0) if user else 0
            if ch_id > 0:
                self.window.client.do_kick_user(user_id, ch_id)
            self.window.set_status(_("Benutzer gekickt und gebannt"))
        except Exception as exc:
            self.window.set_status(f"Kick+Bann fehlgeschlagen: {exc}")

    def _kick_user_from_server(self, user_id: int) -> None:
        reply = QMessageBox.question(
            self, _("Vom Server kicken"), _("Benutzer wirklich vom Server kicken?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            try:
                self.window.client.do_kick_user(user_id, 0)
                self.window.set_status(_("Benutzer vom Server gekickt"))
            except Exception as exc:
                self.window.set_status(f"Server-Kick fehlgeschlagen: {exc}")

    def _edit_user_note(self, user_id: int) -> None:
        user = self._find_user(user_id)
        tt_str = self.window.tt_str
        name = ""
        username = f"User#{user_id}"
        if user:
            name = tt_str(user.szNickname) or tt_str(user.szUsername) or f"User#{user_id}"
            username = tt_str(user.szUsername) or f"User#{user_id}"
        notes = getattr(self.window.settings_store.settings, "user_notes", {}) or {}
        current_note = notes.get(username, "")
        note, ok = QInputDialog.getText(
            self, _("Notiz bearbeiten"), f"Notiz für {name}:", text=current_note
        )
        if ok:
            if not isinstance(getattr(self.window.settings_store.settings, "user_notes", None), dict):
                self.window.settings_store.settings.user_notes = {}
            if note.strip():
                self.window.settings_store.settings.user_notes[username] = note.strip()
            else:
                self.window.settings_store.settings.user_notes.pop(username, None)
            self.window.settings_store.save()
            self.window.set_status(_("Notiz gespeichert"))

    # ------------------------------------------------------------------
    # Navigation helpers
    # ------------------------------------------------------------------

    def _open_private_chat_for_user(self, user_id: int) -> None:
        self.window.open_private_chat(user_id)

    def _on_join_btn(self) -> None:
        row = self.channel_list.currentRow()
        if row < 0 or row >= len(self._items):
            self.window.set_status(_("Bitte zuerst einen Kanal in der Liste auswählen"))
            return
        node_type, node_id = self._items[row]
        if node_type == _NODE_CHANNEL:
            self.window.join_channel(node_id)
        else:
            self.window.set_status(_("Bitte einen Kanal (nicht Nutzer) auswählen"))

    def _on_channel_search(self, text: str) -> None:
        search = text.strip().lower()
        if not search:
            self._items = list(self._all_items)
            self._diff_update_listwidget(self._all_labels)
        else:
            filtered_labels, filtered_items = self._filter_by_search(
                self._all_labels, self._all_items, search
            )
            self.channel_list.clear()
            for lbl, (ntype, _nid) in zip(filtered_labels, filtered_items):
                self.channel_list.addItem(self._make_list_item(lbl, ntype))
            self._items = filtered_items

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_selected_user_id(self) -> Optional[int]:
        return self._selected_user_id

    def get_selected_channel_id(self) -> Optional[int]:
        return self._selected_channel_id

    def refresh_users_for_channel(self, channel_id: int) -> None:
        client = self.window.client
        actual = channel_id or int(client.get_my_channel_id() or 0)
        try:
            users = list(client.get_channel_users(actual))
        except Exception:
            users = []
        self._current_users = users
        self._private_user_ids = [int(u.nUserID) for u in users]
        chat_tab = self.window.chat_tab
        if chat_tab:
            try:
                chat_tab.refresh_private_user_choice(users)
            except Exception:
                pass
