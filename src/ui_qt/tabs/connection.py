from __future__ import annotations

import socket
import threading
from typing import Dict, List, Optional, TYPE_CHECKING

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QFormLayout,
    QLabel, QLineEdit, QCheckBox, QListWidget, QPushButton,
    QComboBox, QFileDialog, QApplication,
)
from PySide6.QtCore import QTimer

from ui.models import ServerProfile
from tls_verify import get_cert_fingerprint

if TYPE_CHECKING:
    from app_qt import MainWindow


class ConnectionTab(QWidget):
    """Tab 1: Verbindung."""

    def __init__(self, parent: QWidget, window: "MainWindow") -> None:
        super().__init__(parent)
        self.window = window
        self._all_server_names: List[str] = [p.name for p in window.store.items()]
        self._filtered_indices: List[int] = list(range(len(self._all_server_names)))
        self._server_status: Dict[int, Optional[bool]] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        server_group = QGroupBox("Server")
        server_layout = QVBoxLayout(server_group)

        # Group filter
        group_row = QHBoxLayout()
        group_row.addWidget(QLabel("Gruppe:"))
        self.server_group_choice = QComboBox()
        self.server_group_choice.addItem("(Alle)")
        self.server_group_choice.currentIndexChanged.connect(self._on_group_filter_changed)
        manage_groups_btn = QPushButton("Gruppe &verwalten...")
        manage_groups_btn.clicked.connect(self._on_manage_groups)
        group_row.addWidget(self.server_group_choice, 1)
        group_row.addWidget(manage_groups_btn)
        server_layout.addLayout(group_row)

        # Filter
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Filter:"))
        self.server_filter = QLineEdit()
        self.server_filter.setObjectName("Serverfilter")
        self.server_filter.textChanged.connect(self._on_filter_changed)
        filter_row.addWidget(self.server_filter, 1)
        server_layout.addLayout(filter_row)

        # Server list
        self.server_list = QListWidget()
        self.server_list.setObjectName("Serverliste")
        self.server_list.currentRowChanged.connect(self.on_server_selected)
        self.server_list.itemActivated.connect(self.on_server_dclick)
        self.server_list.setContextMenuPolicy(
            __import__('PySide6.QtCore', fromlist=['Qt']).Qt.ContextMenuPolicy.CustomContextMenu
        )
        self.server_list.customContextMenuRequested.connect(self.on_server_list_context)
        server_layout.addWidget(self.server_list)

        btn_row = QHBoxLayout()
        self.server_add = QPushButton("&Neu")
        self.server_add.clicked.connect(self.on_server_add)
        self.server_edit = QPushButton("&Bearbeiten")
        self.server_edit.clicked.connect(self.on_server_edit)
        self.server_remove = QPushButton("&Entfernen")
        self.server_remove.clicked.connect(self.on_server_remove)
        self.join_code_btn = QPushButton("Bei&trittscode eingeben")
        self.join_code_btn.clicked.connect(self.on_enter_join_code)
        self.public_servers_btn = QPushButton("Öffentliche &Server…")
        self.public_servers_btn.clicked.connect(self.on_open_server_browser)
        self.status_check_btn = QPushButton("Status &prüfen")
        self.status_check_btn.clicked.connect(self._on_check_server_status)
        self.import_tt_btn = QPushButton(".tt &importieren")
        self.import_tt_btn.clicked.connect(self._on_import_tt_file)
        self.export_tt_btn = QPushButton(".tt &exportieren")
        self.export_tt_btn.clicked.connect(self._on_export_selected_tt)
        for btn in (self.server_add, self.server_edit, self.server_remove,
                    self.join_code_btn, self.public_servers_btn,
                    self.status_check_btn, self.import_tt_btn, self.export_tt_btn):
            btn_row.addWidget(btn)
        btn_row.addStretch()
        server_layout.addLayout(btn_row)

        # Connection form
        form_group = QGroupBox("Verbindungsdaten")
        form = QFormLayout(form_group)
        self.display_name = QLineEdit()
        self.host = QLineEdit("127.0.0.1")
        self.tcp_port = QLineEdit("10333")
        self.udp_port = QLineEdit("10333")
        self.nickname = QLineEdit("VoiceOverUser")
        self.username = QLineEdit("guest")
        self.password = QLineEdit("guest")
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.client_name = QLineEdit("TeamTalk VO")
        self.encrypted = QCheckBox("Versc&hlüsselt (Encrypted)")
        form.addRow("Profilname", self.display_name)
        form.addRow("Server", self.host)
        form.addRow("TCP Port", self.tcp_port)
        form.addRow("UDP Port", self.udp_port)
        form.addRow("Nickname", self.nickname)
        form.addRow("Benutzername", self.username)
        form.addRow("Passwort", self.password)
        form.addRow("Client-Name", self.client_name)
        form.addRow("", self.encrypted)
        server_layout.addWidget(form_group)

        # Action buttons
        action_group = QGroupBox("Aktionen")
        action_row = QHBoxLayout(action_group)
        self.connect_btn = QPushButton("&Verbinden")
        self.connect_btn.clicked.connect(self.on_connect)
        self.reconnect_btn = QPushButton("Neu verbin&den")
        self.reconnect_btn.clicked.connect(self.on_reconnect)
        self.join_root_btn = QPushButton("&Root-Kanal")
        self.join_root_btn.clicked.connect(self.on_join_root)
        self.leave_btn = QPushButton("&Kanal verlassen")
        self.leave_btn.clicked.connect(self.on_leave_channel)
        self.logout_btn = QPushButton("&Abmelden")
        self.logout_btn.clicked.connect(self.on_logout)
        self.share_url_btn = QPushButton("TT-&URL kopieren")
        self.share_url_btn.clicked.connect(self.on_copy_tt_url)
        self.auto_reconnect = QCheckBox("Auto&matisch neu verbinden")
        self.auto_reconnect.stateChanged.connect(self.on_auto_reconnect)
        for btn in (self.connect_btn, self.reconnect_btn, self.join_root_btn,
                    self.leave_btn, self.logout_btn, self.share_url_btn):
            action_row.addWidget(btn)
        action_row.addWidget(self.auto_reconnect)
        action_row.addStretch()
        server_layout.addWidget(action_group)

        # Stats
        stats_group = QGroupBox("Verbindungsstatus")
        stats_layout = QVBoxLayout(stats_group)
        self.stats_label = QLabel("UDP Ping: -- ms, TCP Ping: -- ms")
        stats_layout.addWidget(self.stats_label)
        server_layout.addWidget(stats_group)

        root.addWidget(server_group)

        # Stats timer
        self._stats_timer = QTimer(self)
        self._stats_timer.timeout.connect(self._on_stats_timer)
        self._stats_timer.start(5000)
        self._ping_history: list = []

        self.reload_server_list()
        self._refresh_group_choices()

    def destroy_timers(self) -> None:
        self._stats_timer.stop()

    def _refresh_group_choices(self) -> None:
        groups = ["(Alle)"]
        try:
            for p in self.window.store.items():
                g = getattr(p, "group", None) or ""
                if g and g not in groups:
                    groups.append(g)
        except Exception:
            pass
        current = self.server_group_choice.currentText()
        self.server_group_choice.blockSignals(True)
        self.server_group_choice.clear()
        self.server_group_choice.addItems(groups)
        if current in groups:
            self.server_group_choice.setCurrentText(current)
        self.server_group_choice.blockSignals(False)

    def fill_form(self, profile: ServerProfile) -> None:
        self.display_name.setText(profile.display_name or profile.name or "")
        self.host.setText(profile.host)
        self.tcp_port.setText(str(profile.tcp_port))
        self.udp_port.setText(str(profile.udp_port))
        self.nickname.setText(profile.nickname)
        self.username.setText(profile.username)
        self.password.setText(profile.password)
        self.client_name.setText(profile.client_name)
        self.encrypted.setChecked(profile.encrypted)

    def profile_from_form(self) -> Optional[ServerProfile]:
        host = self.host.text().strip()
        if not host:
            self.window.set_status("Server darf nicht leer sein")
            return None
        try:
            tcp_port = int(self.tcp_port.text().strip())
            udp_port = int(self.udp_port.text().strip())
        except ValueError:
            self.window.set_status("Port muss eine Zahl sein")
            return None
        display_name = self.display_name.text().strip()
        return ServerProfile(
            name=display_name or host,
            host=host,
            tcp_port=tcp_port,
            udp_port=udp_port,
            nickname=self.nickname.text().strip(),
            username=self.username.text().strip(),
            password=self.password.text().strip(),
            client_name=self.client_name.text().strip(),
            encrypted=self.encrypted.isChecked(),
            display_name=display_name,
        )

    def reload_server_list(self) -> None:
        self._all_server_names = [p.name for p in self.window.store.items()]
        self._filtered_indices = list(range(len(self._all_server_names)))
        filt = self.server_filter.text().strip().lower()
        if filt:
            self._filtered_indices = [
                i for i, n in enumerate(self._all_server_names)
                if filt in n.lower()
            ]
        self.server_list.blockSignals(True)
        self.server_list.clear()
        for i in self._filtered_indices:
            st = self._server_status.get(i)
            prefix = "✓ " if st is True else "✗ " if st is False else ""
            self.server_list.addItem(prefix + self._all_server_names[i])
        self.server_list.blockSignals(False)

    def _get_real_index(self) -> Optional[int]:
        row = self.server_list.currentRow()
        if row < 0 or row >= len(self._filtered_indices):
            return None
        return self._filtered_indices[row]

    def on_server_selected(self, row: int) -> None:
        real_idx = self._get_real_index()
        if real_idx is None:
            return
        profiles = self.window.store.items()
        if real_idx < len(profiles):
            self.fill_form(profiles[real_idx])

    def on_server_dclick(self, item) -> None:
        self.on_connect()

    def on_server_list_context(self, pos) -> None:
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        connect_action = menu.addAction("Verbinden")
        edit_action = menu.addAction("Bearbeiten")
        remove_action = menu.addAction("Entfernen")
        action = menu.exec(self.server_list.mapToGlobal(pos))
        if action == connect_action:
            self.on_connect()
        elif action == edit_action:
            self.on_server_edit()
        elif action == remove_action:
            self.on_server_remove()

    def on_connect(self) -> None:
        profile = self.profile_from_form()
        if profile:
            self.window.connect_to_server(profile)

    def on_reconnect(self) -> None:
        self.window.reconnect()

    def on_join_root(self) -> None:
        self.window.join_root_channel()

    def on_leave_channel(self) -> None:
        self.window.leave_channel()

    def on_logout(self) -> None:
        self.window.logout()

    def on_copy_tt_url(self) -> None:
        self.window.copy_tt_url()

    def on_auto_reconnect(self, state: int) -> None:
        self.window.settings_store.settings.auto_reconnect = bool(state)
        self.window.settings_store.save()

    def on_server_add(self) -> None:
        self.window.add_server()

    def on_server_edit(self) -> None:
        real_idx = self._get_real_index()
        if real_idx is not None:
            self.window.edit_server(real_idx)

    def on_server_remove(self) -> None:
        real_idx = self._get_real_index()
        if real_idx is not None:
            self.window.remove_server(real_idx)

    def on_enter_join_code(self) -> None:
        self.window.enter_join_code()

    def on_open_server_browser(self) -> None:
        self.window.open_server_browser()

    def _on_filter_changed(self, text: str) -> None:
        self.reload_server_list()

    def _on_group_filter_changed(self, idx: int) -> None:
        self.reload_server_list()

    def _on_manage_groups(self) -> None:
        self.window.manage_server_groups()

    def _on_check_server_status(self) -> None:
        profiles = self.window.store.items()
        if not profiles:
            return
        self._server_status = {}
        self.status_check_btn.setEnabled(False)
        self.window.set_status("Server-Status wird geprüft…")

        from ui_qt.call_after import call_after

        def worker() -> None:
            for i, profile in enumerate(profiles):
                try:
                    conn = socket.create_connection(
                        (profile.host, int(profile.tcp_port or 10333)), timeout=3
                    )
                    conn.close()
                    self._server_status[i] = True
                except Exception:
                    self._server_status[i] = False
            reachable = sum(1 for v in self._server_status.values() if v)
            total = len(self._server_status)
            call_after(self.reload_server_list)
            call_after(lambda: self.status_check_btn.setEnabled(True))
            call_after(self.window.set_status,
                       f"Server-Status: {reachable}/{total} erreichbar")

        threading.Thread(target=worker, daemon=True).start()

    def _on_import_tt_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "TT-Datei importieren", "",
            "TeamTalk-Datei (*.tt);;Alle Dateien (*.*)"
        )
        if path:
            self.window.import_tt_file(path)

    def _on_export_selected_tt(self) -> None:
        real_idx = self._get_real_index()
        if real_idx is not None:
            self.window.export_tt_file(real_idx)

    def _on_stats_timer(self) -> None:
        try:
            stats = self.window.client.get_client_statistics()
            udp = getattr(stats, "nUdpPingTimeMs", 0)
            tcp = getattr(stats, "nTcpPingTimeMs", 0)
            self.stats_label.setText(f"UDP Ping: {udp} ms, TCP Ping: {tcp} ms")
        except Exception:
            pass

    def update_stats(self, text: str) -> None:
        self.stats_label.setText(text)
