from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGroupBox,
    QListWidget, QPushButton, QInputDialog, QMessageBox, QDialogButtonBox,
)

if TYPE_CHECKING:
    from app_qt import MainWindow


class ServerGroupsDialog(QDialog):
    """Server-Gruppen verwalten (Server in benannte Gruppen einteilen)."""

    def __init__(self, parent: "MainWindow") -> None:
        super().__init__(parent)
        self._window = parent
        self.setWindowTitle("Server-Gruppen verwalten")
        self.setMinimumWidth(600)
        self.resize(640, 460)

        self._groups: dict = dict(
            getattr(parent.settings_store.settings, "server_groups", {}) or {}
        )

        layout = QVBoxLayout(self)
        top_row = QHBoxLayout()

        # Left: group list
        grp_box = QGroupBox("Gruppen")
        grp_v = QVBoxLayout(grp_box)
        self._grp_list = QListWidget()
        self._grp_list.setAccessibleName("Gruppen-Liste")
        self._grp_list.currentRowChanged.connect(self._on_group_selected)
        grp_v.addWidget(self._grp_list, 1)
        grp_btn_row = QHBoxLayout()
        add_grp_btn = QPushButton("&Neu")
        add_grp_btn.setAccessibleName("Neue Gruppe erstellen")
        add_grp_btn.clicked.connect(self._on_add_group)
        del_grp_btn = QPushButton("&Löschen")
        del_grp_btn.setAccessibleName("Ausgewählte Gruppe löschen")
        del_grp_btn.clicked.connect(self._on_del_group)
        grp_btn_row.addWidget(add_grp_btn)
        grp_btn_row.addWidget(del_grp_btn)
        grp_btn_row.addStretch()
        grp_v.addLayout(grp_btn_row)
        top_row.addWidget(grp_box, 1)

        # Right: server list for selected group
        srv_box = QGroupBox("Server in Gruppe")
        srv_v = QVBoxLayout(srv_box)
        self._srv_list = QListWidget()
        self._srv_list.setAccessibleName("Server in Gruppe")
        srv_v.addWidget(self._srv_list, 1)
        srv_btn_row = QHBoxLayout()
        add_srv_btn = QPushButton("Server &hinzufügen")
        add_srv_btn.setAccessibleName("Server zur Gruppe hinzufügen")
        add_srv_btn.clicked.connect(self._on_add_server)
        rem_srv_btn = QPushButton("Server &entfernen")
        rem_srv_btn.setAccessibleName("Server aus Gruppe entfernen")
        rem_srv_btn.clicked.connect(self._on_rem_server)
        srv_btn_row.addWidget(add_srv_btn)
        srv_btn_row.addWidget(rem_srv_btn)
        srv_btn_row.addStretch()
        srv_v.addLayout(srv_btn_row)
        top_row.addWidget(srv_box, 1)

        layout.addLayout(top_row, 1)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(self.reject)
        layout.addWidget(bb)

        self._refresh_groups()

    def _refresh_groups(self) -> None:
        self._grp_list.clear()
        for name in sorted(self._groups.keys()):
            self._grp_list.addItem(name)
        self._srv_list.clear()

    def _current_group(self) -> Optional[str]:
        item = self._grp_list.currentItem()
        return item.text() if item else None

    def _on_group_selected(self, row: int) -> None:
        grp = self._current_group()
        self._srv_list.clear()
        if grp is not None:
            for srv in self._groups.get(grp, []):
                self._srv_list.addItem(srv)

    def _on_add_group(self) -> None:
        name, ok = QInputDialog.getText(self, "Gruppe erstellen", "Name der neuen Gruppe:")
        if not ok or not name.strip():
            return
        name = name.strip()
        if name in self._groups:
            QMessageBox.information(self, "Hinweis", "Gruppe existiert bereits.")
            return
        self._groups[name] = []
        self._save()
        self._refresh_groups()

    def _on_del_group(self) -> None:
        grp = self._current_group()
        if grp is None:
            return
        self._groups.pop(grp, None)
        self._save()
        self._refresh_groups()

    def _on_add_server(self) -> None:
        grp = self._current_group()
        if grp is None:
            QMessageBox.information(self, "Hinweis", "Erst eine Gruppe auswählen.")
            return
        servers = [p.name for p in self._window.server_store.items()]
        if not servers:
            QMessageBox.information(self, "Hinweis", "Keine Server in der Serverliste.")
            return
        srv, ok = QInputDialog.getItem(self, "Server hinzufügen", "Server auswählen:", servers, 0, False)
        if not ok or not srv:
            return
        if srv not in self._groups[grp]:
            self._groups[grp].append(srv)
            self._save()
            self._on_group_selected(self._grp_list.currentRow())

    def _on_rem_server(self) -> None:
        grp = self._current_group()
        if grp is None:
            return
        item = self._srv_list.currentItem()
        if item is None:
            return
        srv = item.text()
        members = self._groups.get(grp, [])
        if srv in members:
            members.remove(srv)
            self._groups[grp] = members
            self._save()
            self._on_group_selected(self._grp_list.currentRow())

    def _save(self) -> None:
        self._window.settings_store.settings.server_groups = dict(self._groups)
        self._window.settings_store.save()
