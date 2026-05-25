"""Verbindungs-Dialog für Qt — ersetzt den Verbindungs-Tab."""
from __future__ import annotations

import socket
import threading
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGroupBox, QFormLayout,
    QWidget, QLabel, QListWidget, QLineEdit, QCheckBox, QSpinBox,
    QPushButton, QMessageBox, QFileDialog,
)
from PySide6.QtCore import Qt, QTimer

from i18n import _

if TYPE_CHECKING:
    from app_qt import MainWindow


class ConnectDialog(QDialog):
    """Serverliste + Verbindungsformular."""

    def __init__(self, parent: "MainWindow") -> None:
        super().__init__(parent)
        self.window = parent
        self.setWindowTitle(_("Verbinden"))
        self.resize(740, 620)
        self._profiles: list = []
        self._filter_text: str = ""
        self._filtered_indices: list = []
        self._server_status: dict = {}

        layout = QVBoxLayout(self)

        # ── Server list ───────────────────────────────────────────────────
        list_group = QGroupBox(_("Gespeicherte Server"))
        list_inner = QVBoxLayout(list_group)

        # Filter
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel(_("Filter:")))
        self.filter_field = QLineEdit()
        self.filter_field.setPlaceholderText(_("Servername filtern …"))
        self.filter_field.textChanged.connect(self._on_filter_changed)
        filter_row.addWidget(self.filter_field, 1)
        list_inner.addLayout(filter_row)

        self.server_list = QListWidget()
        self.server_list.currentRowChanged.connect(self._on_select)
        self.server_list.itemActivated.connect(lambda _item: self.on_connect())
        list_inner.addWidget(self.server_list, 1)

        btn_row = QHBoxLayout()
        for label, slot in [
            (_("&Neu"), self._on_new),
            (_("&Speichern"), self._on_save),
            (_("&Entfernen"), self._on_delete),
            (_(".tt &importieren"), self._on_import),
            (_(".tt e&xportieren"), self._on_export_tt),
            (_("TT-&Datei speichern"), self._on_save_tt_file),
            (_("TT-&URL kopieren"), self._on_copy_url),
        ]:
            btn = QPushButton(label)
            btn.clicked.connect(slot)
            btn_row.addWidget(btn)
        self._status_check_btn = QPushButton(_("Status &prüfen"))
        self._status_check_btn.clicked.connect(self._on_check_status)
        btn_row.addWidget(self._status_check_btn)
        btn_row.addStretch()
        list_inner.addLayout(btn_row)
        layout.addWidget(list_group)

        # ── Connection form ───────────────────────────────────────────────
        form_group = QGroupBox(_("Verbindungsdetails"))
        form = QFormLayout(form_group)

        self.name_field = QLineEdit()
        self.name_field.setPlaceholderText(_("Anzeigename"))
        form.addRow(_("Name"), self.name_field)

        self.host_field = QLineEdit()
        self.host_field.setPlaceholderText(_("Server-Adresse oder IP"))
        form.addRow(_("Server"), self.host_field)

        port_row = QHBoxLayout()
        self.tcp_field = QSpinBox()
        self.tcp_field.setRange(1, 65535)
        self.tcp_field.setValue(10333)
        port_row.addWidget(self.tcp_field)
        port_row.addWidget(QLabel(_("UDP")))
        self.udp_field = QSpinBox()
        self.udp_field.setRange(1, 65535)
        self.udp_field.setValue(10333)
        port_row.addWidget(self.udp_field)
        form.addRow(_("TCP-Port"), port_row)

        self.nick_field = QLineEdit()
        self.nick_field.setPlaceholderText(_("Nickname"))
        form.addRow(_("Nickname"), self.nick_field)

        self.user_field = QLineEdit()
        form.addRow(_("Benutzername"), self.user_field)

        self.pass_field = QLineEdit()
        self.pass_field.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow(_("Passwort"), self.pass_field)

        self.client_name_field = QLineEdit()
        self.client_name_field.setPlaceholderText("TeamTalk VO Client")
        form.addRow(_("Client-Name"), self.client_name_field)

        self.channel_field = QLineEdit()
        self.channel_field.setPlaceholderText(_("/kanalname (optional)"))
        form.addRow(_("Kanal"), self.channel_field)

        self.ch_pass_field = QLineEdit()
        self.ch_pass_field.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow(_("Kanal-Passwort"), self.ch_pass_field)

        self.encrypted_check = QCheckBox(_("Verschlüsselt (TLS)"))
        form.addRow("", self.encrypted_check)

        layout.addWidget(form_group)

        # ── Action buttons ────────────────────────────────────────────────
        action_group = QGroupBox(_("Aktionen"))
        action_layout = QVBoxLayout(action_group)

        action_row1 = QHBoxLayout()
        self.connect_btn = QPushButton(_("&Verbinden"))
        self.connect_btn.setDefault(True)
        self.connect_btn.clicked.connect(self.on_connect)
        action_row1.addWidget(self.connect_btn)

        self._reconnect_btn = QPushButton(_("Neu verbin&den"))
        self._reconnect_btn.clicked.connect(self._on_reconnect)
        action_row1.addWidget(self._reconnect_btn)

        self._server_check_btn = QPushButton(_("&Server prüfen"))
        self._server_check_btn.clicked.connect(self._on_server_check)
        action_row1.addWidget(self._server_check_btn)

        self._join_root_btn = QPushButton(_("&Root-Kanal beitreten"))
        self._join_root_btn.clicked.connect(self._on_join_root)
        action_row1.addWidget(self._join_root_btn)

        self._leave_btn = QPushButton(_("Kanal &verlassen"))
        self._leave_btn.clicked.connect(self._on_leave_channel)
        action_row1.addWidget(self._leave_btn)

        self._logout_btn = QPushButton(_("&Abmelden"))
        self._logout_btn.clicked.connect(self._on_logout)
        action_row1.addWidget(self._logout_btn)

        self._auto_reconnect_cb = QCheckBox(_("Automatisch neu verbinden"))
        self._auto_reconnect_cb.setChecked(
            bool(getattr(self.window.settings_store.settings, "auto_reconnect_enabled", True))
        )
        self._auto_reconnect_cb.stateChanged.connect(self._on_auto_reconnect_changed)
        action_row1.addWidget(self._auto_reconnect_cb)
        action_row1.addStretch()

        close_btn = QPushButton(_("&Schließen"))
        close_btn.clicked.connect(self.reject)
        action_row1.addWidget(close_btn)
        action_layout.addLayout(action_row1)

        # Ping stats
        self._stats_label = QLabel("UDP Ping: –– ms  |  TCP Ping: –– ms")
        action_layout.addWidget(self._stats_label)
        layout.addWidget(action_group)

        # ── Ping timer ────────────────────────────────────────────────────
        self._ping_timer = QTimer(self)
        self._ping_timer.setInterval(2000)
        self._ping_timer.timeout.connect(self._update_stats)
        self._ping_timer.start()

        self._load_profiles()
        self._update_stats()

        # Tab order: server list → form fields → connect button
        QWidget.setTabOrder(self.server_list, self.filter_field)
        QWidget.setTabOrder(self.filter_field, self.name_field)
        QWidget.setTabOrder(self.name_field, self.host_field)
        QWidget.setTabOrder(self.host_field, self.tcp_field)
        QWidget.setTabOrder(self.tcp_field, self.udp_field)
        QWidget.setTabOrder(self.udp_field, self.nick_field)
        QWidget.setTabOrder(self.nick_field, self.user_field)
        QWidget.setTabOrder(self.user_field, self.pass_field)
        QWidget.setTabOrder(self.pass_field, self.channel_field)
        QWidget.setTabOrder(self.channel_field, self.ch_pass_field)
        QWidget.setTabOrder(self.ch_pass_field, self.connect_btn)

        # Pre-fill with last connected profile
        try:
            last = getattr(self.window, "_last_profile", None)
            if last and self._profiles:
                for i, p in enumerate(self._profiles):
                    if getattr(p, "host", "") == getattr(last, "host", ""):
                        self.server_list.setCurrentRow(i)
                        break
        except Exception:
            pass

    # ── Server list helpers ───────────────────────────────────────────────

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self.server_list.count() > 0:
            self.server_list.setFocus()
        else:
            self.host_field.setFocus()

    def _load_profiles(self) -> None:
        self._profiles = list(self.window.store.items())
        self._apply_filter()

    def _apply_filter(self) -> None:
        filt = self._filter_text.lower()
        self._filtered_indices = [
            i for i, p in enumerate(self._profiles)
            if filt in (getattr(p, "name", "") or "").lower()
            or filt in (getattr(p, "host", "") or "").lower()
        ]
        self.server_list.clear()
        for idx in self._filtered_indices:
            p = self._profiles[idx]
            label = getattr(p, "name", "") or getattr(p, "host", "") or str(p)
            # Show reachability indicator if available
            if idx in self._server_status:
                indicator = "✓ " if self._server_status[idx] else "✗ "
                label = indicator + label
            self.server_list.addItem(label)
        if self.server_list.count() > 0 and self.server_list.currentRow() < 0:
            self.server_list.setCurrentRow(0)

    def _on_filter_changed(self, text: str) -> None:
        self._filter_text = text
        self._apply_filter()

    def _real_index(self, list_row: int) -> Optional[int]:
        if 0 <= list_row < len(self._filtered_indices):
            return self._filtered_indices[list_row]
        return None

    def _on_select(self, row: int) -> None:
        real = self._real_index(row)
        if real is not None:
            p = self._profiles[real]
            self.name_field.setText(getattr(p, "name", "") or "")
            self.host_field.setText(getattr(p, "host", "") or "")
            self.tcp_field.setValue(int(getattr(p, "tcp_port", 10333) or 10333))
            self.udp_field.setValue(int(getattr(p, "udp_port", 10333) or 10333))
            self.nick_field.setText(getattr(p, "nickname", "") or "")
            self.user_field.setText(getattr(p, "username", "") or "")
            self.pass_field.setText(getattr(p, "password", "") or "")
            self.client_name_field.setText(getattr(p, "client_name", "") or "")
            self.channel_field.setText(getattr(p, "channel", "") or "")
            self.ch_pass_field.setText(getattr(p, "channel_password", "") or "")
            self.encrypted_check.setChecked(bool(getattr(p, "encrypted", False)))

    def _profile_from_form(self):
        from ui.models import ServerProfile
        host = self.host_field.text().strip()
        return ServerProfile(
            name=self.name_field.text().strip() or host,
            host=host,
            tcp_port=self.tcp_field.value(),
            udp_port=self.udp_field.value(),
            nickname=self.nick_field.text().strip() or "Gast",
            username=self.user_field.text().strip(),
            password=self.pass_field.text(),
            client_name=self.client_name_field.text().strip() or "TeamTalk VO Client",
            channel=self.channel_field.text().strip(),
            channel_password=self.ch_pass_field.text(),
            encrypted=self.encrypted_check.isChecked(),
        )

    # ── Server list CRUD ──────────────────────────────────────────────────

    def _on_new(self) -> None:
        self.server_list.clearSelection()
        for field in (self.name_field, self.host_field, self.nick_field,
                      self.user_field, self.pass_field, self.client_name_field,
                      self.channel_field, self.ch_pass_field):
            field.clear()
        self.tcp_field.setValue(10333)
        self.udp_field.setValue(10333)
        self.encrypted_check.setChecked(False)
        self.host_field.setFocus()

    def _on_save(self) -> None:
        p = self._profile_from_form()
        if not p.host:
            QMessageBox.warning(self, _("Speichern"), _("Bitte Server-Adresse eingeben."))
            return
        row = self.server_list.currentRow()
        real = self._real_index(row)
        try:
            if real is not None:
                self.window.store.update(real, p)
            else:
                self.window.store.add(p)
            self._load_profiles()
            self.window.set_status(f"Server gespeichert: {p.name}")
            try:
                self.window._rebuild_favorites_menu()
            except Exception:
                pass
        except Exception as exc:
            QMessageBox.warning(self, _("Fehler"), str(exc))

    def _on_delete(self) -> None:
        row = self.server_list.currentRow()
        real = self._real_index(row)
        if real is None:
            return
        name = self._profiles[real].name if self._profiles else "?"
        if QMessageBox.question(self, _("Entfernen"), f"Server '{name}' wirklich entfernen?") \
                == QMessageBox.StandardButton.Yes:
            try:
                self.window.store.remove(real)
                self._load_profiles()
                try:
                    self.window._rebuild_favorites_menu()
                except Exception:
                    pass
            except Exception as exc:
                QMessageBox.warning(self, _("Fehler"), str(exc))

    # ── Import / Export ───────────────────────────────────────────────────

    def _on_import(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self, _("TeamTalk-Datei importieren"), "",
            "TeamTalk-Dateien (*.tt);;Alle Dateien (*.*)"
        )
        if not path:
            return
        try:
            from ui.tt_file_parser import parse_teamtalk_file
            result = parse_teamtalk_file(path)
            if result:
                profile = result.profile if hasattr(result, "profile") else result
                if not profile.name:
                    profile.name = Path(path).stem
                self.window.store.add(profile)
                self._load_profiles()
                self.window.set_status(f"Importiert: {Path(path).name}")
        except Exception as exc:
            QMessageBox.warning(self, _("Import fehlgeschlagen"), str(exc))

    def _on_export_tt(self) -> None:
        row = self.server_list.currentRow()
        real = self._real_index(row)
        if real is None:
            QMessageBox.warning(self, _("Exportieren"), _("Bitte einen Server auswählen."))
            return
        profile = self._profiles[real]
        default_name = f"{profile.name or profile.host}.tt"
        path, _filter = QFileDialog.getSaveFileName(
            self, _("Server als TT-Datei exportieren"), default_name,
            "TeamTalk-Dateien (*.tt);;Alle Dateien (*.*)"
        )
        if not path:
            return
        try:
            from ui.tt_file_parser import build_teamtalk_xml
            xml_text = build_teamtalk_xml(profile)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(xml_text)
            self.window.set_status("TT-Datei exportiert")
        except Exception as exc:
            self.window.set_status(f"Export fehlgeschlagen: {exc}")

    def _on_save_tt_file(self) -> None:
        p = self._profile_from_form()
        if not p.host:
            QMessageBox.warning(self, _("Speichern"), _("Bitte Server-Adresse eingeben."))
            return
        channel_path = self._get_channel_path()
        default_name = f"{p.name or p.host}.tt"
        path, _filter = QFileDialog.getSaveFileName(
            self, _("TT-Datei speichern"), default_name,
            "TeamTalk-Dateien (*.tt);;Alle Dateien (*.*)"
        )
        if not path:
            return
        try:
            from ui.tt_file_parser import build_teamtalk_xml
            xml_text = build_teamtalk_xml(p, channel_path=channel_path)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(xml_text)
            self.window.set_status("TT-Datei gespeichert")
        except Exception as exc:
            self.window.set_status(f"TT-Datei speichern fehlgeschlagen: {exc}")

    def _on_copy_url(self) -> None:
        row = self.server_list.currentRow()
        real = self._real_index(row)
        p = self._profiles[real] if real is not None else self._profile_from_form()
        channel_path = self._get_channel_path()
        try:
            from ui.tt_file_parser import build_teamtalk_url
            from PySide6.QtWidgets import QApplication
            url = build_teamtalk_url(p, channel_path=channel_path)
            QApplication.clipboard().setText(url)
            self.window.set_status("TT-URL kopiert")
        except Exception:
            pass

    def _get_channel_path(self) -> Optional[str]:
        try:
            if not self.window.client.is_connected():
                return None
            ch_id = self.window.client.get_my_channel_id()
            if not ch_id:
                return None
            path = self.window.client.get_channel_path(int(ch_id))
            return self.window.tt_str(path) if path else None
        except Exception:
            return None

    # ── Status prüfen (TCP) ───────────────────────────────────────────────

    def _on_check_status(self) -> None:
        profiles = self._profiles
        if not profiles:
            return
        self._server_status = {}
        self._status_check_btn.setEnabled(False)
        self.window.set_status("Server-Status wird geprüft…")

        def worker():
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
            from ui_qt.call_after import call_after
            call_after(self._finish_status_check, f"Server-Status: {reachable}/{total} erreichbar")

        threading.Thread(target=worker, daemon=True).start()

    def _finish_status_check(self, msg: str) -> None:
        self._apply_filter()
        self._status_check_btn.setEnabled(True)
        self.window.set_status(msg)

    # ── Action handlers ───────────────────────────────────────────────────

    def _on_reconnect(self) -> None:
        self.accept()
        try:
            self.window.reconnect()
        except Exception:
            pass

    def _on_server_check(self) -> None:
        host = self.host_field.text().strip()
        port = self.tcp_field.value()
        if not host:
            QMessageBox.warning(self, _("Server prüfen"), _("Bitte Server-Adresse eingeben."))
            return
        self._server_check_btn.setEnabled(False)
        self.window.set_status(f"Prüfe {host}:{port}…")

        def worker():
            try:
                conn = socket.create_connection((host, port), timeout=3)
                conn.close()
                ok = True
            except Exception:
                ok = False
            from ui_qt.call_after import call_after
            call_after(self._on_server_check_done, host, port, ok)

        threading.Thread(target=worker, daemon=True).start()

    def _on_server_check_done(self, host: str, port: int, ok: bool) -> None:
        self._server_check_btn.setEnabled(True)
        if ok:
            msg = f"Server erreichbar: {host}:{port}"
            self.window.set_status(msg)
            QMessageBox.information(self, _("Server prüfen"), msg)
        else:
            msg = f"Server nicht erreichbar: {host}:{port}"
            self.window.set_status(msg)
            QMessageBox.warning(self, _("Server prüfen"), msg)

    def _on_join_root(self) -> None:
        self.accept()
        try:
            self.window.join_root_channel()
        except Exception:
            pass

    def _on_leave_channel(self) -> None:
        self.accept()
        try:
            self.window.leave_channel()
        except Exception:
            pass

    def _on_logout(self) -> None:
        self.accept()
        try:
            self.window.logout()
        except Exception:
            pass

    def _on_auto_reconnect_changed(self, state: int) -> None:
        checked = bool(state)
        try:
            self.window._auto_reconnect = checked
            self.window.settings_store.settings.auto_reconnect_enabled = checked
            self.window.settings_store.save()
            if hasattr(self.window, "_auto_reconnect_action"):
                self.window._auto_reconnect_action.setChecked(checked)
        except Exception:
            pass

    def _update_stats(self) -> None:
        try:
            if not self.window.client.is_connected():
                self._stats_label.setText("UDP Ping: –– ms  |  TCP Ping: –– ms")
                return
            stats = self.window.client.get_client_statistics()
            if stats is None:
                return
            udp_ms = int(stats.nUdpPingTimeMs)
            tcp_ms = int(stats.nTcpPingTimeMs)
            self._stats_label.setText(f"UDP Ping: {udp_ms} ms  |  TCP Ping: {tcp_ms} ms")
        except Exception:
            pass

    # ── Connect ───────────────────────────────────────────────────────────

    def on_connect(self) -> None:
        p = self._profile_from_form()
        if not p.host:
            QMessageBox.warning(self, _("Verbinden"), _("Bitte Server-Adresse eingeben."))
            return
        self._ping_timer.stop()
        self.window.connect_to_server(p)
        self.accept()

    def reject(self) -> None:
        self._ping_timer.stop()
        super().reject()
