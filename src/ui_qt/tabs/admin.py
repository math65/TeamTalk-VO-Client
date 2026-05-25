from __future__ import annotations

import threading
from typing import List, TYPE_CHECKING

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel,
    QListWidget, QPushButton, QLineEdit, QTextEdit, QSpinBox,
    QComboBox, QCheckBox, QFormLayout, QDialog, QDialogButtonBox,
    QMessageBox, QInputDialog,
)
from PySide6.QtCore import Qt

from ui_qt.call_after import call_after
from i18n import _

if TYPE_CHECKING:
    from app_qt import MainWindow

# ---------------------------------------------------------------------------
# UserRight bit-flags (from TeamTalk5 SDK)
# ---------------------------------------------------------------------------
_UR_CREATE_CHANNEL = 0x00000004
_UR_BROADCAST      = 0x00000010
_UR_OPERATOR       = 0x00000100
_UR_RECORD         = 0x00000008   # USERRIGHT_RECORD_VOICE
_UR_UPLOAD         = 0x00000200
_UR_DOWNLOAD       = 0x00000400

# UserType values
_USERTYPE_NONE     = 0x00
_USERTYPE_DEFAULT  = 0x01
_USERTYPE_ADMIN    = 0x02


class AdminTab(QWidget):
    """Tab 7: Administration — Benutzerkonten, Sperrliste, Servereigenschaften."""

    def __init__(self, parent: QWidget, window: "MainWindow") -> None:
        super().__init__(parent)
        self.window = window
        self._accounts: List = []
        self._bans: List = []
        self._selected_account_index: int = -1

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.addWidget(QLabel(_("Administrationsfunktionen (nur für Admins)")))

        # ------------------------------------------------------------------ #
        # Section 1: Benutzerkonten
        # ------------------------------------------------------------------ #
        acc_group = QGroupBox(_("Benutzerkonten"))
        acc_layout = QVBoxLayout(acc_group)

        acc_layout.addWidget(QLabel(_("Benutzername, Typ")))
        self.account_list = QListWidget()
        self.account_list.setAccessibleName(_("Benutzerkonten"))
        self.account_list.currentRowChanged.connect(self._on_account_selected)
        acc_layout.addWidget(self.account_list, 1)

        acc_btn_row = QHBoxLayout()
        self.load_accounts_btn = QPushButton(_("&Laden"))
        self.load_accounts_btn.clicked.connect(self.on_load_accounts)
        self.new_account_btn = QPushButton(_("&Neu"))
        self.new_account_btn.clicked.connect(self.on_new_account)
        self.edit_account_btn = QPushButton(_("&Bearbeiten"))
        self.edit_account_btn.clicked.connect(self.on_edit_account)
        self.del_account_btn = QPushButton(_("&Löschen"))
        self.del_account_btn.clicked.connect(self.on_del_account)
        for btn in (self.load_accounts_btn, self.new_account_btn,
                    self.edit_account_btn, self.del_account_btn):
            acc_btn_row.addWidget(btn)
        acc_btn_row.addStretch()
        acc_layout.addLayout(acc_btn_row)

        # Account edit form (hidden until needed)
        self._account_form_group = QGroupBox(_("Kontodetails"))
        form_layout = QFormLayout(self._account_form_group)

        self._acc_username = QLineEdit()
        self._acc_username.setAccessibleName(_("Benutzername"))
        form_layout.addRow(_("Benutzername:"), self._acc_username)

        self._acc_password = QLineEdit()
        self._acc_password.setEchoMode(QLineEdit.EchoMode.Password)
        self._acc_password.setAccessibleName(_("Passwort"))
        form_layout.addRow(_("Passwort:"), self._acc_password)

        self._acc_usertype = QComboBox()
        self._acc_usertype.addItems([_("Standard"), _("Administrator"), _("Gesperrt")])
        self._acc_usertype.setAccessibleName(_("Benutzertyp"))
        form_layout.addRow(_("Benutzertyp:"), self._acc_usertype)

        rights_label = QLabel(_("Rechte:"))
        form_layout.addRow(rights_label)

        self._cb_create_channel = QCheckBox(_("Kanal erstellen"))
        self._cb_broadcast      = QCheckBox(_("Broadcast senden"))
        self._cb_operator       = QCheckBox(_("Kanal-Operator"))
        self._cb_record         = QCheckBox(_("Aufnahme erlaubt"))
        self._cb_upload         = QCheckBox(_("Upload erlaubt"))
        self._cb_download       = QCheckBox(_("Download erlaubt"))
        for cb in (self._cb_create_channel, self._cb_broadcast, self._cb_operator,
                   self._cb_record, self._cb_upload, self._cb_download):
            form_layout.addRow("", cb)

        form_btn_row = QHBoxLayout()
        self._save_account_btn   = QPushButton(_("&Speichern"))
        self._cancel_account_btn = QPushButton(_("&Abbrechen"))
        self._save_account_btn.clicked.connect(self._on_save_account)
        self._cancel_account_btn.clicked.connect(self._on_cancel_account)
        form_btn_row.addWidget(self._save_account_btn)
        form_btn_row.addWidget(self._cancel_account_btn)
        form_btn_row.addStretch()
        form_layout.addRow(form_btn_row)

        self._account_form_group.setVisible(False)
        acc_layout.addWidget(self._account_form_group)

        root.addWidget(acc_group, 2)

        # ------------------------------------------------------------------ #
        # Section 2: Sperrliste
        # ------------------------------------------------------------------ #
        ban_group = QGroupBox(_("Sperrliste (Server-Bans)"))
        ban_layout = QVBoxLayout(ban_group)

        ban_layout.addWidget(QLabel(_("IP-Adresse, Benutzername")))
        self.ban_list = QListWidget()
        self.ban_list.setAccessibleName(_("Sperrliste"))
        ban_layout.addWidget(self.ban_list, 1)

        ban_btn_row = QHBoxLayout()
        self.load_bans_btn = QPushButton(_("&Laden"))
        self.load_bans_btn.clicked.connect(self.on_load_bans)
        self.unban_btn = QPushButton(_("&Entsperren"))
        self.unban_btn.clicked.connect(self.on_unban)
        for btn in (self.load_bans_btn, self.unban_btn):
            ban_btn_row.addWidget(btn)
        ban_btn_row.addStretch()
        ban_layout.addLayout(ban_btn_row)

        root.addWidget(ban_group, 1)

        # ------------------------------------------------------------------ #
        # Section 3: Server-Eigenschaften
        # ------------------------------------------------------------------ #
        srv_group = QGroupBox(_("Server-Eigenschaften"))
        srv_form = QFormLayout(srv_group)

        self.srv_name = QLineEdit()
        self.srv_name.setAccessibleName(_("Servername"))
        srv_form.addRow(_("Servername:"), self.srv_name)

        self.srv_motd = QTextEdit()
        self.srv_motd.setAccessibleName(_("Willkommensnachricht"))
        self.srv_motd.setMaximumHeight(80)
        srv_form.addRow(_("Willkommensnachricht:"), self.srv_motd)

        self.srv_maxusers = QSpinBox()
        self.srv_maxusers.setRange(1, 1000)
        self.srv_maxusers.setValue(100)
        self.srv_maxusers.setAccessibleName(_("Max. Benutzer"))
        srv_form.addRow(_("Max. Benutzer:"), self.srv_maxusers)

        srv_btn_row = QHBoxLayout()
        self.load_props_btn  = QPushButton(_("&Laden"))
        self.save_props_btn  = QPushButton(_("&Speichern"))
        self.save_config_btn = QPushButton(_("&Konfiguration speichern"))
        self.load_props_btn.clicked.connect(self.on_load_props)
        self.save_props_btn.clicked.connect(self.on_save_props)
        self.save_config_btn.clicked.connect(self.on_save_config)
        for btn in (self.load_props_btn, self.save_props_btn, self.save_config_btn):
            srv_btn_row.addWidget(btn)
        srv_btn_row.addStretch()
        srv_form.addRow(srv_btn_row)

        root.addWidget(srv_group)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _set_status(self, text: str) -> None:
        try:
            self.window.set_status(text)
        except Exception:
            pass

    def _tt_str(self, s) -> str:
        try:
            return self.window.tt_str(s)
        except Exception:
            return str(s) if s else ""

    # ------------------------------------------------------------------
    # Account list
    # ------------------------------------------------------------------

    def _on_account_selected(self, row: int) -> None:
        self._selected_account_index = row

    def on_load_accounts(self) -> None:
        self.load_accounts_btn.setEnabled(False)
        self.account_list.clear()
        self._accounts = []
        self._account_form_group.setVisible(False)
        self._set_status("Benutzerkonten werden geladen...")

        def worker():
            try:
                cmdid = self.window.client.do_list_user_accounts()
                if cmdid <= 0:
                    call_after(self._set_status,
                               "Kein Zugriff auf Benutzerkonten (keine Admin-Rechte?)")
                    return
                import time
                time.sleep(1.5)
                call_after(self._finish_load_accounts)
            except Exception as exc:
                call_after(self._set_status, f"Fehler beim Laden der Konten: {exc}")
            finally:
                call_after(self.load_accounts_btn.setEnabled, True)

        threading.Thread(target=worker, daemon=True).start()

    def _finish_load_accounts(self) -> None:
        count = len(self._accounts)
        if count == 0:
            self._set_status(
                "Keine Benutzerkonten empfangen – "
                "prüfe Admin-Rechte und 'Nutzerkonten anzeigen'-Berechtigung."
            )
        else:
            self._set_status(f"{count} Benutzerkonto(en) geladen")

    def add_account_to_list(self, account) -> None:
        """Called by MainWindow when a CMD_USERACCOUNT event arrives."""
        self._accounts.append(account)
        try:
            name  = self._tt_str(account.szUsername)
            utype_val = int(getattr(account, "uUserType", 0))
            if utype_val & _USERTYPE_ADMIN:
                utype = "Administrator"
            elif utype_val == _USERTYPE_NONE:
                utype = "Gesperrt"
            else:
                utype = "Standard"
            note = self._tt_str(account.szNote) if hasattr(account, "szNote") else ""
            label = f"{name}, {utype}" + (f", {note}" if note else "")
            self.account_list.addItem(label)
        except Exception:
            pass

    def update_accounts(self, accounts, tt_str) -> None:
        """Batch-update called from MainWindow (fallback)."""
        self._accounts = list(accounts)
        self.account_list.clear()
        for acc in accounts:
            try:
                name = tt_str(acc.szUsername)
                utype_val = int(getattr(acc, "uUserType", 0))
                if utype_val & _USERTYPE_ADMIN:
                    utype = "Administrator"
                elif utype_val == _USERTYPE_NONE:
                    utype = "Gesperrt"
                else:
                    utype = "Standard"
                note = tt_str(acc.szNote) if hasattr(acc, "szNote") else ""
                label = f"{name}, {utype}" + (f", {note}" if note else "")
                self.account_list.addItem(label)
            except Exception:
                pass

    def on_new_account(self) -> None:
        self._selected_account_index = -1
        self._acc_username.clear()
        self._acc_password.clear()
        self._acc_usertype.setCurrentIndex(0)
        for cb in (self._cb_create_channel, self._cb_broadcast, self._cb_operator,
                   self._cb_record, self._cb_upload, self._cb_download):
            cb.setChecked(False)
        self._acc_username.setReadOnly(False)
        self._account_form_group.setVisible(True)
        self._acc_username.setFocus()

    def on_edit_account(self) -> None:
        row = self.account_list.currentRow()
        if row < 0 or row >= len(self._accounts):
            self._set_status("Bitte ein Konto auswählen")
            return
        acc = self._accounts[row]
        self._selected_account_index = row
        self._acc_username.setText(self._tt_str(acc.szUsername))
        self._acc_username.setReadOnly(True)  # username is PK, cannot change
        self._acc_password.clear()
        utype_val = int(getattr(acc, "uUserType", 0))
        if utype_val & _USERTYPE_ADMIN:
            self._acc_usertype.setCurrentIndex(1)
        elif utype_val == _USERTYPE_NONE:
            self._acc_usertype.setCurrentIndex(2)
        else:
            self._acc_usertype.setCurrentIndex(0)
        rights = int(getattr(acc, "uUserRights", 0))
        self._cb_create_channel.setChecked(bool(rights & _UR_CREATE_CHANNEL))
        self._cb_broadcast.setChecked(bool(rights & _UR_BROADCAST))
        self._cb_operator.setChecked(bool(rights & _UR_OPERATOR))
        self._cb_record.setChecked(bool(rights & _UR_RECORD))
        self._cb_upload.setChecked(bool(rights & _UR_UPLOAD))
        self._cb_download.setChecked(bool(rights & _UR_DOWNLOAD))
        self._account_form_group.setVisible(True)
        self._acc_password.setFocus()

    def _on_save_account(self) -> None:
        username = self._acc_username.text().strip()
        password = self._acc_password.text().strip()
        if not username:
            QMessageBox.warning(self, _("Fehler"), _("Benutzername darf nicht leer sein."))
            return
        utype_idx = self._acc_usertype.currentIndex()
        if utype_idx == 1:
            utype = _USERTYPE_ADMIN
        elif utype_idx == 2:
            utype = _USERTYPE_NONE
        else:
            utype = _USERTYPE_DEFAULT
        rights = 0
        if self._cb_create_channel.isChecked(): rights |= _UR_CREATE_CHANNEL
        if self._cb_broadcast.isChecked():      rights |= _UR_BROADCAST
        if self._cb_operator.isChecked():       rights |= _UR_OPERATOR
        if self._cb_record.isChecked():         rights |= _UR_RECORD
        if self._cb_upload.isChecked():         rights |= _UR_UPLOAD
        if self._cb_download.isChecked():       rights |= _UR_DOWNLOAD

        self._save_account_btn.setEnabled(False)
        self._set_status(f"Konto wird gespeichert: {username}...")

        def worker():
            try:
                cmd_id = self.window.client.do_new_user_account(
                    username, password, utype, user_rights=rights
                )
                if cmd_id > 0:
                    call_after(self._set_status, f"Konto gespeichert: {username}")
                    call_after(self._account_form_group.setVisible, False)
                    call_after(self.on_load_accounts)
                else:
                    call_after(self._set_status, f"Fehler: Konto konnte nicht gespeichert werden")
            except Exception as exc:
                call_after(self._set_status, f"Fehler beim Speichern: {exc}")
            finally:
                call_after(self._save_account_btn.setEnabled, True)

        threading.Thread(target=worker, daemon=True).start()

    def _on_cancel_account(self) -> None:
        self._account_form_group.setVisible(False)

    def on_del_account(self) -> None:
        row = self.account_list.currentRow()
        if row < 0 or row >= len(self._accounts):
            self._set_status("Bitte ein Konto auswählen")
            return
        username = self._tt_str(self._accounts[row].szUsername)
        reply = QMessageBox.question(
            self, _("Konto löschen"),
            f"Konto '{username}' wirklich löschen?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.del_account_btn.setEnabled(False)
        self._set_status(f"Konto wird gelöscht: {username}...")

        def worker():
            try:
                cmd_id = self.window.client.do_delete_user_account(username)
                if cmd_id > 0:
                    call_after(self._set_status, f"Konto gelöscht: {username}")
                    call_after(self.on_load_accounts)
                else:
                    call_after(self._set_status, f"Löschen fehlgeschlagen für: {username}")
            except Exception as exc:
                call_after(self._set_status, f"Fehler beim Löschen: {exc}")
            finally:
                call_after(self.del_account_btn.setEnabled, True)

        threading.Thread(target=worker, daemon=True).start()

    # ------------------------------------------------------------------
    # Bans
    # ------------------------------------------------------------------

    def on_load_bans(self) -> None:
        self.load_bans_btn.setEnabled(False)
        self.ban_list.clear()
        self._bans = []
        self._set_status("Sperren werden geladen...")

        def worker():
            try:
                self.window.client.do_list_bans()
                call_after(self._set_status, "Sperren geladen — Warte auf Serverdaten...")
            except Exception as exc:
                call_after(self._set_status, f"Fehler beim Laden der Sperren: {exc}")
            finally:
                call_after(self.load_bans_btn.setEnabled, True)

        threading.Thread(target=worker, daemon=True).start()

    def add_ban_to_list(self, ban) -> None:
        """Called by MainWindow when a CMD_BAN event arrives."""
        self._bans.append(ban)
        try:
            ip    = self._tt_str(ban.szIPAddress) if hasattr(ban, "szIPAddress") else "?"
            uname = self._tt_str(ban.szUsername)  if hasattr(ban, "szUsername")  else ""
            label = f"{ip}" + (f", {uname}" if uname else "")
            self.ban_list.addItem(label)
        except Exception:
            pass

    def update_bans(self, bans, tt_str) -> None:
        """Batch-update called from MainWindow (fallback)."""
        self._bans = list(bans)
        self.ban_list.clear()
        for ban in bans:
            try:
                ip    = tt_str(ban.szIPAddress) if hasattr(ban, "szIPAddress") else "?"
                uname = tt_str(ban.szUsername)  if hasattr(ban, "szUsername")  else ""
                self.ban_list.addItem(f"{ip}" + (f", {uname}" if uname else ""))
            except Exception:
                pass

    def on_unban(self) -> None:
        row = self.ban_list.currentRow()
        if row < 0 or row >= len(self._bans):
            self._set_status("Bitte eine Sperre auswählen")
            return
        ban = self._bans[row]
        ip = self._tt_str(ban.szIPAddress) if hasattr(ban, "szIPAddress") else ""
        if not ip:
            self._set_status("Keine IP-Adresse verfügbar")
            return

        self.unban_btn.setEnabled(False)
        self._set_status(f"Sperre wird aufgehoben für: {ip}...")

        def worker():
            try:
                cmd_id = self.window.client.do_unban_user(ip)
                if cmd_id > 0:
                    call_after(self._set_status, f"Entsperrt: {ip}")
                    call_after(self.on_load_bans)
                else:
                    call_after(self._set_status, f"Entsperren fehlgeschlagen für: {ip}")
            except Exception as exc:
                call_after(self._set_status, f"Fehler beim Entsperren: {exc}")
            finally:
                call_after(self.unban_btn.setEnabled, True)

        threading.Thread(target=worker, daemon=True).start()

    # ------------------------------------------------------------------
    # Server properties
    # ------------------------------------------------------------------

    def on_load_props(self) -> None:
        self.load_props_btn.setEnabled(False)
        self._set_status("Servereigenschaften werden geladen...")

        def worker():
            try:
                props = self.window.client.get_server_properties()
                if props is None:
                    call_after(self._set_status, "Servereigenschaften konnten nicht geladen werden")
                    return
                tt_str = self._tt_str
                name     = tt_str(props.szServerName)
                motd     = tt_str(props.szMOTDRaw)
                maxusers = int(props.nMaxUsers)
                call_after(self.srv_name.setText, name)
                call_after(self.srv_motd.setPlainText, motd)
                call_after(self.srv_maxusers.setValue, maxusers)
                call_after(self._set_status, "Servereigenschaften geladen")
            except Exception as exc:
                call_after(self._set_status, f"Fehler beim Laden: {exc}")
            finally:
                call_after(self.load_props_btn.setEnabled, True)

        threading.Thread(target=worker, daemon=True).start()

    def on_save_props(self) -> None:
        name     = self.srv_name.text().strip()
        motd     = self.srv_motd.toPlainText().strip()
        maxusers = self.srv_maxusers.value()

        self.save_props_btn.setEnabled(False)
        self._set_status("Servereigenschaften werden gespeichert...")

        def worker():
            try:
                self.window.client.do_update_server(
                    server_name=name, motd=motd, max_users=maxusers
                )
                call_after(self._set_status, "Servereigenschaften gespeichert")
            except Exception as exc:
                call_after(self._set_status, f"Fehler beim Speichern: {exc}")
            finally:
                call_after(self.save_props_btn.setEnabled, True)

        threading.Thread(target=worker, daemon=True).start()

    def on_save_config(self) -> None:
        self.save_config_btn.setEnabled(False)
        self._set_status("Serverkonfiguration wird gespeichert...")

        def worker():
            try:
                self.window.client.do_save_config()
                call_after(self._set_status, "Serverkonfiguration gespeichert")
            except Exception as exc:
                call_after(self._set_status, f"Fehler beim Speichern der Konfiguration: {exc}")
            finally:
                call_after(self.save_config_btn.setEnabled, True)

        threading.Thread(target=worker, daemon=True).start()
