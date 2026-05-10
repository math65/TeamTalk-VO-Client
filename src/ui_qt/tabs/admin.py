from __future__ import annotations

import threading
from typing import List, TYPE_CHECKING

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel,
    QListWidget, QPushButton,
)

if TYPE_CHECKING:
    from app_qt import MainWindow


class AdminTab(QWidget):
    """Tab 7: Administration."""

    def __init__(self, parent: QWidget, window: "MainWindow") -> None:
        super().__init__(parent)
        self.window = window
        self._accounts: List = []
        self._bans: List = []

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.addWidget(QLabel("Administrationsfunktionen (nur für Admins)"))

        # Accounts
        acc_group = QGroupBox("Benutzerkonten")
        acc_layout = QVBoxLayout(acc_group)
        acc_layout.addWidget(QLabel("Benutzername, Typ, Notiz"))
        self.account_list = QListWidget()
        self.account_list.setObjectName("Benutzerkonten")
        acc_layout.addWidget(self.account_list, 1)
        acc_btn_row = QHBoxLayout()
        self.load_accounts_btn = QPushButton("&Konten laden")
        self.load_accounts_btn.clicked.connect(self.on_load_accounts)
        self.add_account_btn = QPushButton("Konto &hinzufügen")
        self.add_account_btn.clicked.connect(self.on_add_account)
        self.del_account_btn = QPushButton("Konto &löschen")
        self.del_account_btn.clicked.connect(self.on_del_account)
        for btn in (self.load_accounts_btn, self.add_account_btn, self.del_account_btn):
            acc_btn_row.addWidget(btn)
        acc_btn_row.addStretch()
        acc_layout.addLayout(acc_btn_row)
        root.addWidget(acc_group, 1)

        # Bans
        ban_group = QGroupBox("Sperren")
        ban_layout = QVBoxLayout(ban_group)
        ban_layout.addWidget(QLabel("IP-Adresse, Benutzername, Zeitpunkt"))
        self.ban_list = QListWidget()
        self.ban_list.setObjectName("Sperrliste")
        ban_layout.addWidget(self.ban_list, 1)
        ban_btn_row = QHBoxLayout()
        self.load_bans_btn = QPushButton("&Sperren laden")
        self.load_bans_btn.clicked.connect(self.on_load_bans)
        self.unban_btn = QPushButton("&Entsperren")
        self.unban_btn.clicked.connect(self.on_unban)
        self.ban_ip_btn = QPushButton("IP-Adresse &bannen...")
        self.ban_ip_btn.clicked.connect(self.on_ban_ip)
        for btn in (self.load_bans_btn, self.unban_btn, self.ban_ip_btn):
            ban_btn_row.addWidget(btn)
        ban_btn_row.addStretch()
        ban_layout.addLayout(ban_btn_row)
        root.addWidget(ban_group, 1)

        # Server properties
        srv_group = QGroupBox("Servereigenschaften")
        srv_layout = QHBoxLayout(srv_group)
        self.edit_srv_btn = QPushButton("Servereigenschaften &bearbeiten...")
        self.edit_srv_btn.clicked.connect(self.on_edit_server_properties)
        srv_layout.addWidget(self.edit_srv_btn)
        srv_layout.addStretch()
        root.addWidget(srv_group)

    def on_load_accounts(self) -> None:
        self.window.load_user_accounts(self.account_list)

    def on_add_account(self) -> None:
        self.window.add_user_account()

    def on_del_account(self) -> None:
        row = self.account_list.currentRow()
        if row >= 0 and row < len(self._accounts):
            self.window.delete_user_account(self._accounts[row])

    def on_load_bans(self) -> None:
        self.window.load_ban_list(self.ban_list)

    def on_unban(self) -> None:
        row = self.ban_list.currentRow()
        if row >= 0 and row < len(self._bans):
            self.window.unban_entry(self._bans[row])

    def on_ban_ip(self) -> None:
        self.window.ban_ip_address()

    def on_edit_server_properties(self) -> None:
        self.window.edit_server_properties()

    def update_accounts(self, accounts, tt_str) -> None:
        self._accounts = list(accounts)
        self.account_list.clear()
        for acc in accounts:
            try:
                name = tt_str(acc.szUsername)
                utype = "Admin" if getattr(acc, "uUserType", 0) == 2 else "Gast"
                note = tt_str(acc.szNote) if hasattr(acc, "szNote") else ""
                self.account_list.addItem(f"{name}, {utype}" + (f", {note}" if note else ""))
            except Exception:
                pass

    def update_bans(self, bans, tt_str) -> None:
        self._bans = list(bans)
        self.ban_list.clear()
        for ban in bans:
            try:
                ip = tt_str(ban.szIPAddress) if hasattr(ban, "szIPAddress") else "?"
                uname = tt_str(ban.szUsername) if hasattr(ban, "szUsername") else ""
                self.ban_list.addItem(f"{ip}" + (f", {uname}" if uname else ""))
            except Exception:
                pass
