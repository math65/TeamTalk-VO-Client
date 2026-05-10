"""Tab 2: Kanäle – QListWidget mit Kanal/Nutzer-Einträgen."""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple, TYPE_CHECKING

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QPushButton, QMenu, QListWidgetItem,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent

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

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)

        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("Suche:"))
        self._channel_search = QLineEdit()
        self._channel_search.setObjectName("Kanal suchen")
        self._channel_search.textChanged.connect(self._on_channel_search)
        search_row.addWidget(self._channel_search)
        root.addLayout(search_row)

        self.channel_list = QListWidget()
        self.channel_list.setObjectName("Kanalliste")
        self.channel_list.currentRowChanged.connect(self._on_list_sel)
        self.channel_list.itemActivated.connect(self._on_list_activate)
        self.channel_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.channel_list.customContextMenuRequested.connect(self._on_list_right_click)
        self.channel_list.installEventFilter(self)
        root.addWidget(self.channel_list, 1)

        self.join_btn = QPushButton("&Kanal beitreten")
        self.join_btn.clicked.connect(self._on_join_btn)
        root.addWidget(self.join_btn)

    def eventFilter(self, obj, event) -> bool:
        if obj is self.channel_list and isinstance(event, QKeyEvent):
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._on_list_activate(self.channel_list.currentItem())
                return True
        return super().eventFilter(obj, event)

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
            for lbl in filtered_labels:
                self.channel_list.addItem(lbl)
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
        topic = ""
        try:
            t = tt_str(ch.szTopic)
            if t:
                topic = f", {t}"
        except Exception:
            pass
        user_count = len(users_by_channel.get(root_id, []))
        count_txt = f" ({user_count})" if user_count else ""
        labels.append(f"{indent}[{ch_name}{topic}{count_txt}]")
        items.append((_NODE_CHANNEL, root_id))

        for u in users_by_channel.get(root_id, []):
            try:
                uname = tt_str(u.szNickname) or tt_str(u.szUsername) or f"User#{u.nUserID}"
                status_txt = tt_str(u.szStatusMsg)
                line = f"{indent}  {uname}"
                if status_txt:
                    line += f", {status_txt}"
                labels.append(line)
                items.append((_NODE_USER, int(u.nUserID)))
            except Exception:
                pass

        for cid, c in channels_by_id.items():
            try:
                if int(c.nParentID) == root_id and cid != root_id:
                    sub_labels, sub_items = self._build_flat_list(
                        cid, c, "", channels_by_id, users_by_channel, depth + 1
                    )
                    labels.extend(sub_labels)
                    items.extend(sub_items)
            except Exception:
                pass
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
        else:
            self.channel_list.clear()
            for lbl in new_labels:
                self.channel_list.addItem(lbl)
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
        row = self.channel_list.currentRow()
        if row < 0 or row >= len(self._items):
            return
        node_type, node_id = self._items[row]
        if node_type != _NODE_USER:
            return
        menu = QMenu(self)
        kick_action = menu.addAction("Nutzer kicken")
        mute_action = menu.addAction("Nutzer stummschalten")
        pm_action = menu.addAction("Privatnachricht senden")
        action = menu.exec(self.channel_list.mapToGlobal(pos))
        if action == kick_action:
            self.window.kick_user(node_id)
        elif action == mute_action:
            self.window.mute_user(node_id)
        elif action == pm_action:
            self._open_private_chat_for_user(node_id)

    def _open_private_chat_for_user(self, user_id: int) -> None:
        self.window.open_private_chat(user_id)

    def _on_join_btn(self) -> None:
        row = self.channel_list.currentRow()
        if row < 0 or row >= len(self._items):
            return
        node_type, node_id = self._items[row]
        if node_type == _NODE_CHANNEL:
            self.window.join_channel(node_id)

    def _on_channel_search(self, text: str) -> None:
        search = text.strip().lower()
        if not search:
            self._diff_update_listwidget(self._all_labels)
            self._items = list(self._all_items)
        else:
            filtered_labels, filtered_items = self._filter_by_search(
                self._all_labels, self._all_items, search
            )
            self.channel_list.clear()
            for lbl in filtered_labels:
                self.channel_list.addItem(lbl)
            self._items = filtered_items

    def get_selected_user_id(self) -> Optional[int]:
        return self._selected_user_id

    def get_selected_channel_id(self) -> Optional[int]:
        return self._selected_channel_id
