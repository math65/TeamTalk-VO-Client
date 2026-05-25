"""Qt-Dialoge — Entsprechungen der wx-Dialoge."""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, List

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget,
    QPushButton, QLineEdit, QDialogButtonBox, QMessageBox, QTextEdit,
    QInputDialog, QCheckBox, QComboBox, QSpinBox, QTimeEdit,
    QFileDialog, QGroupBox, QFormLayout,
)
from PySide6.QtCore import Qt, QTime, QUrl
from PySide6.QtGui import QDesktopServices

if TYPE_CHECKING:
    pass


class TTSTranscriptDialog(QDialog):
    """TTS-Mitschrift anzeigen."""

    def __init__(self, parent, tts) -> None:
        super().__init__(parent)
        self.setWindowTitle("TTS-Mitschrift")
        self.resize(600, 400)
        self._tts = tts

        layout = QVBoxLayout(self)
        self._lb = QListWidget()
        layout.addWidget(self._lb, 1)

        btn_row = QHBoxLayout()
        self._refresh_btn = QPushButton("&Aktualisieren")
        self._refresh_btn.clicked.connect(self._fill)
        self._clear_btn = QPushButton("&Leeren")
        self._clear_btn.clicked.connect(self._on_clear)
        close_btn = QPushButton("&Schließen")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(self._refresh_btn)
        btn_row.addWidget(self._clear_btn)
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        self._fill()

    def _fill(self) -> None:
        self._lb.clear()
        for ts, kind, text in list(getattr(self._tts, "_transcript", [])):
            self._lb.addItem(f"{ts}, {kind}: {text}")
        if self._lb.count():
            self._lb.setCurrentRow(self._lb.count() - 1)

    def _on_clear(self) -> None:
        try:
            self._tts._transcript.clear()
        except Exception:
            pass
        self._lb.clear()


class ChatSearchDialog(QDialog):
    """Chat-Verlauf durchsuchen."""

    def __init__(self, parent, chat_history, current_server_key: str) -> None:
        super().__init__(parent)
        self.setWindowTitle("Chat-Suche")
        self.resize(700, 500)
        self._chm = chat_history
        self._server_key = current_server_key

        layout = QVBoxLayout(self)

        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("Suche:"))
        self._search_field = QLineEdit()
        self._search_field.returnPressed.connect(self._on_search)
        search_row.addWidget(self._search_field, 1)
        self._search_btn = QPushButton("&Suchen")
        self._search_btn.clicked.connect(self._on_search)
        search_row.addWidget(self._search_btn)
        layout.addLayout(search_row)

        self._results = QListWidget()
        layout.addWidget(self._results, 1)

        close_btn = QPushButton("&Schließen")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)

    def _on_search(self) -> None:
        query = self._search_field.text().strip().lower()
        if not query:
            return
        self._results.clear()
        try:
            keys = [self._server_key] if self._server_key else self._chm.list_server_keys()
            for key in keys:
                try:
                    history = self._chm.load(key)
                    for entry in history:
                        text = str(entry)
                        if query in text.lower():
                            self._results.addItem(f"[{key}] {text}")
                except Exception:
                    pass
        except Exception as exc:
            self._results.addItem(f"Fehler: {exc}")


class UserWatcherDialog(QDialog):
    """Beobachtete Nutzer verwalten."""

    def __init__(self, parent, settings_store) -> None:
        super().__init__(parent)
        self.setWindowTitle("Nutzerwatcher")
        self.resize(400, 350)
        self._store = settings_store

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Beobachtete Nutzer (einer pro Zeile):"))

        self._list = QListWidget()
        watched = list(getattr(settings_store.settings, "watched_users", []) or [])
        for name in watched:
            self._list.addItem(name)
        layout.addWidget(self._list, 1)

        input_row = QHBoxLayout()
        self._input = QLineEdit()
        self._input.setPlaceholderText("Nutzername hinzufügen...")
        self._input.returnPressed.connect(self._on_add)
        input_row.addWidget(self._input, 1)
        add_btn = QPushButton("&Hinzufügen")
        add_btn.clicked.connect(self._on_add)
        input_row.addWidget(add_btn)
        layout.addLayout(input_row)

        btn_row = QHBoxLayout()
        remove_btn = QPushButton("&Entfernen")
        remove_btn.clicked.connect(self._on_remove)
        save_btn = QPushButton("&Speichern")
        save_btn.clicked.connect(self._on_save)
        close_btn = QPushButton("&Schließen")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(remove_btn)
        btn_row.addWidget(save_btn)
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    def _on_add(self) -> None:
        name = self._input.text().strip()
        if name and not any(
            self._list.item(i).text() == name
            for i in range(self._list.count())
        ):
            self._list.addItem(name)
            self._input.clear()

    def _on_remove(self) -> None:
        row = self._list.currentRow()
        if row >= 0:
            self._list.takeItem(row)

    def _on_save(self) -> None:
        names = [self._list.item(i).text() for i in range(self._list.count())]
        try:
            self._store.settings.watched_users = names
            self._store.save()
        except Exception as exc:
            QMessageBox.warning(self, "Fehler", str(exc))


class OfflineQueueDialog(QDialog):
    """Offline-Nachrichten-Warteschlange anzeigen."""

    def __init__(self, parent, offline_queue) -> None:
        super().__init__(parent)
        self.setWindowTitle("Offline-Warteschlange")
        self.resize(500, 350)
        self._oq = offline_queue

        layout = QVBoxLayout(self)
        self._list = QListWidget()
        self._fill()
        layout.addWidget(self._list, 1)

        btn_row = QHBoxLayout()
        clear_btn = QPushButton("&Leeren")
        clear_btn.clicked.connect(self._on_clear)
        close_btn = QPushButton("&Schließen")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(clear_btn)
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    def _fill(self) -> None:
        self._list.clear()
        try:
            msgs = self._oq.peek()
            for msg in msgs:
                kind   = msg.get("kind", "?")
                text   = msg.get("text", "")
                target = msg.get("target_name", "")
                self._list.addItem(f"[{kind}→{target}] {text}")
        except Exception as exc:
            self._list.addItem(f"Fehler: {exc}")

    def _on_clear(self) -> None:
        try:
            self._oq.clear()
            self._list.clear()
        except Exception:
            pass


class ServerAudioProfileDialog(QDialog):
    """Per-Server-Soundprofile verwalten."""

    def __init__(self, parent, settings_store) -> None:
        super().__init__(parent)
        self.setWindowTitle("Per-Server-Soundprofile")
        self.resize(500, 350)
        self._store = settings_store

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Server → Sound-Profil Zuordnung:"))
        self._list = QListWidget()
        self._fill()
        layout.addWidget(self._list, 1)

        btn_row = QHBoxLayout()
        save_btn = QPushButton("&Speichern")
        save_btn.clicked.connect(self._on_save)
        close_btn = QPushButton("&Schließen")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(save_btn)
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    def _fill(self) -> None:
        self._list.clear()
        try:
            profiles = dict(
                getattr(self._store.settings, "server_audio_profiles", {}) or {}
            )
            for server_key, profile_name in profiles.items():
                self._list.addItem(f"{server_key} → {profile_name}")
        except Exception:
            pass

    def _on_save(self) -> None:
        try:
            self._store.save()
            self.accept()
        except Exception as exc:
            QMessageBox.warning(self, "Fehler", str(exc))


class OnlineUsersDialog(QDialog):
    """Online-Nutzer auf dem Server anzeigen.

    Zeigt alle verbundenen Nutzer mit Nick, Benutzername und Kanal.
    Bietet Suche, Aktualisierung, Privatnachricht und Info-Vorlesen per TTS.
    """

    def __init__(self, parent, client, tt_str, tts=None, window=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Online-Nutzer")
        self.resize(560, 480)
        self._client   = client
        self._tt_str   = tt_str
        self._tts      = tts
        self._window   = window
        self._all_items: List[tuple] = []   # (nick, username, ch_name, user_obj)

        layout = QVBoxLayout(self)

        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("Suche:"))
        self._search = QLineEdit()
        self._search.setPlaceholderText("Nick oder Benutzername...")
        self._search.textChanged.connect(self._apply_filter)
        search_row.addWidget(self._search, 1)
        layout.addLayout(search_row)

        self._list = QListWidget()
        self._list.setAccessibleName("Online-Nutzer Liste")
        layout.addWidget(self._list, 1)

        self._count_label = QLabel("")
        layout.addWidget(self._count_label)

        btn_row = QHBoxLayout()
        refresh_btn = QPushButton("&Aktualisieren")
        refresh_btn.clicked.connect(self._fill)
        self._tts_btn = QPushButton("Info &sprechen")
        self._tts_btn.clicked.connect(self._on_speak)
        self._pm_btn  = QPushButton("&Private Nachricht")
        self._pm_btn.clicked.connect(self._on_private_message)
        close_btn = QPushButton("Sc&hließen")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(refresh_btn)
        btn_row.addWidget(self._tts_btn)
        btn_row.addWidget(self._pm_btn)
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        self._fill()

    def _fill(self) -> None:
        self._all_items = []
        try:
            users = list(self._client.get_server_users() or [])
            for u in users:
                nick     = self._tt_str(u.szNickname) or self._tt_str(u.szUsername) or f"User#{u.nUserID}"
                username = self._tt_str(u.szUsername)
                ch_id    = int(getattr(u, "nChannelID", 0) or 0)
                ch_name  = ""
                if ch_id:
                    try:
                        ch = self._client.get_channel(ch_id)
                        ch_name = self._tt_str(ch.szName) if ch else f"#{ch_id}"
                    except Exception:
                        ch_name = f"#{ch_id}"
                self._all_items.append((nick, username, ch_name, u))
        except Exception as exc:
            self._all_items = [(f"Fehler: {exc}", "", "", None)]
        self._apply_filter(self._search.text())

    def _apply_filter(self, text: str) -> None:
        self._list.clear()
        q     = text.strip().lower()
        shown = 0
        for nick, username, ch_name, _ in self._all_items:
            if not q or q in nick.lower() or q in username.lower():
                suffix  = f" ({username})" if username and username != nick else ""
                ch_part = f" — {ch_name}" if ch_name else ""
                self._list.addItem(f"{nick}{suffix}{ch_part}")
                shown += 1
        total = len(self._all_items)
        self._count_label.setText(f"{shown} von {total} Nutzern angezeigt")

    def _get_selected(self):
        row = self._list.currentRow()
        if row < 0:
            return None
        # find matching item from _all_items by visible position
        q = self._search.text().strip().lower()
        visible = [
            item for item in self._all_items
            if not q or q in item[0].lower() or q in item[1].lower()
        ]
        if row < len(visible):
            return visible[row]
        return None

    def _on_speak(self) -> None:
        item = self._get_selected()
        if item is None:
            return
        nick, username, ch_name, _ = item
        text = f"{nick}"
        if username and username != nick:
            text += f", Benutzername {username}"
        if ch_name:
            text += f", Kanal {ch_name}"
        try:
            if self._tts:
                self._tts.speak(text)
        except Exception:
            pass

    def _on_private_message(self) -> None:
        item = self._get_selected()
        if item is None:
            QMessageBox.information(self, "Hinweis", "Bitte einen Nutzer auswählen.")
            return
        nick, _, _, user_obj = item
        if user_obj is None:
            return
        msg, ok = QInputDialog.getText(self, "Private Nachricht", f"Nachricht an {nick}:")
        if ok and msg.strip():
            try:
                self._client.send_user_message(int(user_obj.nUserID), msg.strip())
            except Exception as exc:
                QMessageBox.warning(self, "Fehler", f"Senden fehlgeschlagen: {exc}")


class BanListDialog(QDialog):
    """Sperrliste anzeigen und Sperren aufheben.

    Zeigt IP-Adresse, Benutzername und Sperr-Art.
    Laden ruft client.do_list_bans() auf; Entsperren ruft do_unban_user(ip).
    """

    def __init__(self, parent, client, tt_str) -> None:
        super().__init__(parent)
        self.setWindowTitle("Sperrliste")
        self.resize(560, 420)
        self._client = client
        self._tt_str = tt_str
        self._bans: list = []

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("IP-Adresse, Benutzername, Typ"))

        self._list = QListWidget()
        self._list.setAccessibleName("Sperrliste")
        layout.addWidget(self._list, 1)

        self._status = QLabel("")
        layout.addWidget(self._status)

        btn_row = QHBoxLayout()
        load_btn  = QPushButton("&Sperren laden")
        load_btn.clicked.connect(self._on_load)
        self._unban_btn = QPushButton("&Entsperren")
        self._unban_btn.clicked.connect(self._on_unban)
        close_btn = QPushButton("Sc&hließen")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(load_btn)
        btn_row.addWidget(self._unban_btn)
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    def _on_load(self) -> None:
        self._list.clear()
        self._bans = []
        self._status.setText("Sperren werden geladen...")
        try:
            self._client.do_list_bans()
            self._status.setText("Sperren geladen — Warte auf Serverdaten...")
        except Exception as exc:
            self._status.setText(f"Fehler: {exc}")

    def add_ban(self, ban) -> None:
        """Called externally when a CMD_BAN event arrives."""
        self._bans.append(ban)
        try:
            ip    = self._tt_str(ban.szIPAddress) if hasattr(ban, "szIPAddress") else "?"
            uname = self._tt_str(ban.szUsername)  if hasattr(ban, "szUsername")  else ""
            label = f"{ip}" + (f", {uname}" if uname else "")
            self._list.addItem(label)
        except Exception:
            pass

    def clear(self) -> None:
        self._bans = []
        self._list.clear()

    def _on_unban(self) -> None:
        row = self._list.currentRow()
        if row < 0 or row >= len(self._bans):
            QMessageBox.information(self, "Hinweis", "Bitte eine Sperre auswählen.")
            return
        ban = self._bans[row]
        ip  = self._tt_str(ban.szIPAddress) if hasattr(ban, "szIPAddress") else ""
        if not ip:
            QMessageBox.warning(self, "Fehler", "Keine IP-Adresse verfügbar.")
            return
        try:
            cmd_id = self._client.do_unban_user(ip)
            if cmd_id > 0:
                self._status.setText(f"Entsperrt: {ip}")
                self._bans.pop(row)
                self._list.takeItem(row)
            else:
                self._status.setText(f"Entsperren fehlgeschlagen für: {ip}")
        except Exception as exc:
            self._status.setText(f"Fehler: {exc}")


class ServerStatsDialog(QDialog):
    """Server-Statistiken anzeigen (lesbarer Text)."""

    def __init__(self, parent, client) -> None:
        super().__init__(parent)
        self.setWindowTitle("Server-Statistiken")
        self.resize(460, 400)
        self._client = client

        layout = QVBoxLayout(self)
        self._text = QTextEdit()
        self._text.setReadOnly(True)
        self._text.setAccessibleName("Serverstatistiken")
        layout.addWidget(self._text, 1)

        btn_row = QHBoxLayout()
        refresh_btn = QPushButton("&Aktualisieren")
        refresh_btn.clicked.connect(self._fill)
        close_btn   = QPushButton("Sc&hließen")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(refresh_btn)
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        self._fill()

    @staticmethod
    def _fmt_bytes(value) -> str:
        try:
            size = int(value)
        except Exception:
            size = 0
        if size < 1024:
            return f"{size} B"
        if size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        if size < 1024 * 1024 * 1024:
            return f"{size / (1024 * 1024):.1f} MB"
        return f"{size / (1024 * 1024 * 1024):.1f} GB"

    @staticmethod
    def _fmt_uptime(ms) -> str:
        try:
            total = int(ms) // 1000
        except Exception:
            total = 0
        days    = total // (3600 * 24)
        hours   = (total // 3600) % 24
        minutes = (total // 60) % 60
        seconds = total % 60
        if days:
            return f"{days}d {hours}h {minutes}m"
        if hours:
            return f"{hours}h {minutes}m"
        if minutes:
            return f"{minutes}m {seconds}s"
        return f"{seconds}s"

    def _fill(self) -> None:
        try:
            self._client.do_query_server_stats()
        except Exception:
            pass
        try:
            stats = self._client.get_client_statistics()
            lines = [
                f"Uptime:              {self._fmt_uptime(getattr(stats, 'nUptimeMSec', 0))}",
                f"Nutzer gesamt:       {getattr(stats, 'nUsersServed', 0)}",
                f"Nutzer Peak:         {getattr(stats, 'nUsersPeak', 0)}",
                f"",
                f"Gesamt TX:           {self._fmt_bytes(getattr(stats, 'nTotalBytesTX', 0))}",
                f"Gesamt RX:           {self._fmt_bytes(getattr(stats, 'nTotalBytesRX', 0))}",
                f"Voice TX:            {self._fmt_bytes(getattr(stats, 'nVoiceBytesTX', 0))}",
                f"Voice RX:            {self._fmt_bytes(getattr(stats, 'nVoiceBytesRX', 0))}",
                f"Video TX:            {self._fmt_bytes(getattr(stats, 'nVideoCaptureBytesTX', 0))}",
                f"Video RX:            {self._fmt_bytes(getattr(stats, 'nVideoCaptureBytesRX', 0))}",
                f"Mediafile TX:        {self._fmt_bytes(getattr(stats, 'nMediaFileBytesTX', 0))}",
                f"Mediafile RX:        {self._fmt_bytes(getattr(stats, 'nMediaFileBytesRX', 0))}",
                f"Desktop TX:          {self._fmt_bytes(getattr(stats, 'nDesktopBytesTX', 0))}",
                f"Desktop RX:          {self._fmt_bytes(getattr(stats, 'nDesktopBytesRX', 0))}",
                f"Dateien TX:          {self._fmt_bytes(getattr(stats, 'nFilesTx', 0))}",
                f"Dateien RX:          {self._fmt_bytes(getattr(stats, 'nFilesRx', 0))}",
            ]
            self._text.setPlainText("\n".join(lines))
        except Exception as exc:
            # Fall back to raw attribute dump
            try:
                stats = self._client.get_client_statistics()
                lines = []
                for attr in sorted(dir(stats)):
                    if attr.startswith("_"):
                        continue
                    try:
                        val = getattr(stats, attr)
                        if not callable(val):
                            lines.append(f"{attr}: {val}")
                    except Exception:
                        pass
                self._text.setPlainText("\n".join(lines) if lines else "Keine Statistiken verfügbar")
            except Exception as exc2:
                self._text.setPlainText(f"Fehler: {exc2}")

    def update_stats(self, stats) -> None:
        """Called externally when CMD_SERVERSTATISTICS event arrives."""
        lines = [
            f"Uptime:              {self._fmt_uptime(getattr(stats, 'nUptimeMSec', 0))}",
            f"Nutzer gesamt:       {getattr(stats, 'nUsersServed', 0)}",
            f"Nutzer Peak:         {getattr(stats, 'nUsersPeak', 0)}",
            f"",
            f"Gesamt TX:           {self._fmt_bytes(getattr(stats, 'nTotalBytesTX', 0))}",
            f"Gesamt RX:           {self._fmt_bytes(getattr(stats, 'nTotalBytesRX', 0))}",
            f"Voice TX:            {self._fmt_bytes(getattr(stats, 'nVoiceBytesTX', 0))}",
            f"Voice RX:            {self._fmt_bytes(getattr(stats, 'nVoiceBytesRX', 0))}",
            f"Video TX:            {self._fmt_bytes(getattr(stats, 'nVideoCaptureBytesTX', 0))}",
            f"Video RX:            {self._fmt_bytes(getattr(stats, 'nVideoCaptureBytesRX', 0))}",
            f"Mediafile TX:        {self._fmt_bytes(getattr(stats, 'nMediaFileBytesTX', 0))}",
            f"Mediafile RX:        {self._fmt_bytes(getattr(stats, 'nMediaFileBytesRX', 0))}",
            f"Desktop TX:          {self._fmt_bytes(getattr(stats, 'nDesktopBytesTX', 0))}",
            f"Desktop RX:          {self._fmt_bytes(getattr(stats, 'nDesktopBytesRX', 0))}",
            f"Dateien TX:          {self._fmt_bytes(getattr(stats, 'nFilesTx', 0))}",
            f"Dateien RX:          {self._fmt_bytes(getattr(stats, 'nFilesRx', 0))}",
        ]
        self._text.setPlainText("\n".join(lines))


# Keep old name as alias for backwards compatibility
ServerStatisticsDialog = ServerStatsDialog


class UserInfoDialog(QDialog):
    """Benutzerinfo anzeigen — Nick, Benutzername, Kanal, Status."""

    def __init__(self, parent, user, client, tt_str, is_admin: bool = False) -> None:
        super().__init__(parent)
        self.setWindowTitle("Benutzerinfo")
        self.resize(400, 300)

        layout = QVBoxLayout(self)

        try:
            nick     = tt_str(user.szNickname)  or "-"
            username = tt_str(user.szUsername)   or "-"
            user_id  = int(getattr(user, "nUserID", 0))
            ch_id    = int(getattr(user, "nChannelID", 0) or 0)
            status   = int(getattr(user, "nStatusMode", 0))
            ustate   = int(getattr(user, "uUserState", 0))

            ch_name = "-"
            if ch_id:
                try:
                    ch = client.get_channel(ch_id)
                    ch_name = tt_str(ch.szName) if ch else f"#{ch_id}"
                except Exception:
                    ch_name = f"#{ch_id}"

            # Decode status mode (bit flags from SDK)
            status_parts = []
            if status & 0x00000001:
                status_parts.append("Abwesend")
            if status & 0x00000004:
                status_parts.append("Beschäftigt")
            status_text = ", ".join(status_parts) if status_parts else "Verfügbar"

            # Decode user state (speaking, microphone muted, etc.)
            state_parts = []
            if ustate & 0x0001:
                state_parts.append("Spricht")
            if ustate & 0x0100:
                state_parts.append("Mikrofon stummgeschaltet")
            if ustate & 0x0200:
                state_parts.append("Lautsprecher stummgeschaltet")
            state_text = ", ".join(state_parts) if state_parts else "-"

            lines = [
                ("Nickname",     nick),
                ("Benutzername", username),
                ("Benutzer-ID",  str(user_id)),
                ("Kanal",        ch_name),
                ("Status",       status_text),
                ("Zustand",      state_text),
            ]

            # Show IP only for admins
            if is_admin:
                ip = tt_str(getattr(user, "szIPAddress", "")) or "-"
                lines.append(("IP-Adresse", ip))

            for label, value in lines:
                row = QHBoxLayout()
                lbl = QLabel(f"<b>{label}:</b>")
                lbl.setMinimumWidth(130)
                val = QLabel(value)
                val.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                row.addWidget(lbl)
                row.addWidget(val, 1)
                layout.addLayout(row)

        except Exception as exc:
            layout.addWidget(QLabel(f"Fehler beim Laden der Benutzerinfo: {exc}"))

        layout.addStretch()

        btn_row = QHBoxLayout()
        close_btn = QPushButton("Sc&hließen")
        close_btn.clicked.connect(self.accept)
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)


class SpeakingLogDialog(QDialog):
    """Wer hat wann gesprochen — Sprechprotokoll.

    Zeigt eine QListWidget mit '[HH:MM] Nick: X Sekunden'.
    Der Protokolleintrag-Log wird von außen gepflegt (window._speaking_log).
    """

    def __init__(self, parent, speaking_log: list) -> None:
        super().__init__(parent)
        self.setWindowTitle("Wer hat gesprochen")
        self.resize(500, 420)
        self._log = speaking_log

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Sprechprotokoll:"))

        self._list = QListWidget()
        self._list.setAccessibleName("Sprechprotokoll")
        layout.addWidget(self._list, 1)

        btn_row = QHBoxLayout()
        refresh_btn = QPushButton("&Aktualisieren")
        refresh_btn.clicked.connect(self._fill)
        clear_btn   = QPushButton("&Leeren")
        clear_btn.clicked.connect(self._on_clear)
        close_btn   = QPushButton("Sc&hließen")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(refresh_btn)
        btn_row.addWidget(clear_btn)
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        self._fill()

    def _fill(self) -> None:
        self._list.clear()
        for entry in list(self._log):
            try:
                ts      = entry.get("ts", "??:??")
                nick    = entry.get("nick", "?")
                seconds = entry.get("seconds", 0)
                self._list.addItem(f"[{ts}] {nick}: {seconds} Sekunden")
            except Exception:
                pass
        if self._list.count() == 0:
            self._list.addItem("(Noch keine Einträge)")

    def _on_clear(self) -> None:
        try:
            self._log.clear()
        except Exception:
            pass
        self._list.clear()
        self._list.addItem("(Noch keine Einträge)")


class MacroManagerDialog(QDialog):
    """Makros anzeigen und ausführen."""

    def __init__(self, parent, macro_manager) -> None:
        super().__init__(parent)
        self.setWindowTitle("Makro-Manager")
        self.resize(500, 400)
        self._mgr = macro_manager
        self._macros: list = []

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Verfügbare Makros:"))

        self._list = QListWidget()
        layout.addWidget(self._list, 1)

        btn_row = QHBoxLayout()
        run_btn     = QPushButton("&Ausführen")
        run_btn.clicked.connect(self._on_run)
        refresh_btn = QPushButton("&Aktualisieren")
        refresh_btn.clicked.connect(self._fill)
        close_btn   = QPushButton("&Schließen")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(run_btn)
        btn_row.addWidget(refresh_btn)
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        self._fill()

    def _fill(self) -> None:
        self._list.clear()
        self._macros = []
        try:
            self._macros = list(self._mgr.get_macros() or [])
            for m in self._macros:
                name    = getattr(m, "name", str(m))
                trigger = getattr(m, "trigger", "")
                self._list.addItem(f"{name} [{trigger}]" if trigger else name)
            if not self._macros:
                self._list.addItem("(Keine Makros definiert)")
        except Exception as exc:
            self._list.addItem(f"Fehler: {exc}")

    def _on_run(self) -> None:
        row = self._list.currentRow()
        if row < 0 or row >= len(self._macros):
            return
        try:
            self._mgr.execute(self._macros[row])
        except Exception as exc:
            QMessageBox.warning(self, "Fehler", str(exc))


# ---------------------------------------------------------------------------
# 1. EqPresetsDialog
# ---------------------------------------------------------------------------

class EqPresetsDialog(QDialog):
    """EQ-Voreinstellungen verwalten und anwenden."""

    def __init__(self, parent, window) -> None:
        super().__init__(parent)
        self.setWindowTitle("EQ-Voreinstellungen")
        self.resize(480, 380)
        self._window = window

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Verfügbare EQ-Voreinstellungen:"))

        self._list = QListWidget()
        self._list.setAccessibleName("EQ-Voreinstellungen Liste")
        layout.addWidget(self._list, 1)

        btn_row = QHBoxLayout()
        load_btn    = QPushButton("&Laden")
        load_btn.clicked.connect(self._on_load)
        save_btn    = QPushButton("Speichern &als...")
        save_btn.clicked.connect(self._on_save_as)
        delete_btn  = QPushButton("&Löschen")
        delete_btn.clicked.connect(self._on_delete)
        apply_btn   = QPushButton("&Anwenden")
        apply_btn.clicked.connect(self._on_apply)
        close_btn   = QPushButton("Sc&hließen")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(load_btn)
        btn_row.addWidget(save_btn)
        btn_row.addWidget(delete_btn)
        btn_row.addWidget(apply_btn)
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        self._fill()

    def _mgr(self):
        return getattr(self._window, "_eq_presets", None)

    def _fill(self) -> None:
        self._list.clear()
        try:
            mgr = self._mgr()
            if mgr is None:
                self._list.addItem("(EQ-Manager nicht verfügbar)")
                return
            presets = list(mgr.all_presets() or [])
            for p in presets:
                name = p.get("name", "?") if isinstance(p, dict) else str(p)
                self._list.addItem(name)
            if not presets:
                self._list.addItem("(Keine Voreinstellungen)")
        except Exception as exc:
            self._list.addItem(f"Fehler: {exc}")

    def _selected_name(self):
        row = self._list.currentRow()
        if row < 0:
            return None
        item = self._list.item(row)
        return item.text() if item else None

    def _on_load(self) -> None:
        self._fill()

    def _on_save_as(self) -> None:
        name, ok = QInputDialog.getText(self, "Voreinstellung speichern", "Name:")
        if not ok or not name.strip():
            return
        try:
            mgr = self._mgr()
            if mgr is None:
                return
            # Try to read current mic/out values from window audio tab
            mic_gain = 100
            out_vol  = 100
            try:
                mic_gain = int(getattr(self._window, "_current_mic_gain_pct", 100))
                out_vol  = int(getattr(self._window, "_current_out_vol_pct", 100))
            except Exception:
                pass
            mgr.add_or_update(name.strip(), mic_gain, out_vol)
            self._fill()
        except Exception as exc:
            QMessageBox.warning(self, "Fehler", str(exc))

    def _on_delete(self) -> None:
        name = self._selected_name()
        if name is None or name.startswith("("):
            return
        try:
            mgr = self._mgr()
            if mgr is None:
                return
            mgr.remove(name)
            self._fill()
        except Exception as exc:
            QMessageBox.warning(self, "Fehler", str(exc))

    def _on_apply(self) -> None:
        name = self._selected_name()
        if name is None or name.startswith("("):
            return
        try:
            mgr = self._mgr()
            if mgr is None:
                return
            preset = mgr.get(name)
            if preset is None:
                return
            # Apply to window audio settings if possible
            try:
                mic_gain = int(preset.get("mic_gain_pct", 100))
                out_vol  = int(preset.get("out_volume_pct", 100))
                apply_fn = getattr(self._window, "apply_eq_preset", None)
                if callable(apply_fn):
                    apply_fn(mic_gain, out_vol)
            except Exception:
                pass
        except Exception as exc:
            QMessageBox.warning(self, "Fehler", str(exc))


# ---------------------------------------------------------------------------
# 2. ScheduledRecordingsDialog
# ---------------------------------------------------------------------------

class ScheduledRecordingsDialog(QDialog):
    """Geplante Aufnahmen verwalten."""

    _WEEKDAY_LABELS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]

    def __init__(self, parent, window) -> None:
        super().__init__(parent)
        self.setWindowTitle("Geplante Aufnahmen")
        self.resize(560, 520)
        self._window = window

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Geplante Aufnahmen:"))

        self._list = QListWidget()
        self._list.setAccessibleName("Geplante Aufnahmen Liste")
        layout.addWidget(self._list, 1)

        # Form group
        form_group = QGroupBox("Neue Aufnahme hinzufügen")
        form_layout = QFormLayout(form_group)

        self._label_edit = QLineEdit()
        self._label_edit.setPlaceholderText("Bezeichnung...")
        form_layout.addRow("Bezeichnung:", self._label_edit)

        self._time_edit = QTimeEdit()
        self._time_edit.setDisplayFormat("HH:mm")
        form_layout.addRow("Startzeit:", self._time_edit)

        # Weekday checkboxes
        wd_widget_layout = QHBoxLayout()
        self._wd_checks: List[QCheckBox] = []
        for label in self._WEEKDAY_LABELS:
            cb = QCheckBox(label)
            self._wd_checks.append(cb)
            wd_widget_layout.addWidget(cb)
        wd_widget_layout.addStretch()
        from PySide6.QtWidgets import QWidget
        wd_container = QWidget()
        wd_container.setLayout(wd_widget_layout)
        form_layout.addRow("Wochentage:", wd_container)

        self._duration_spin = QSpinBox()
        self._duration_spin.setRange(1, 1440)
        self._duration_spin.setValue(60)
        self._duration_spin.setSuffix(" min")
        form_layout.addRow("Dauer:", self._duration_spin)

        layout.addWidget(form_group)

        btn_row = QHBoxLayout()
        add_btn    = QPushButton("&Hinzufügen")
        add_btn.clicked.connect(self._on_add)
        remove_btn = QPushButton("&Entfernen")
        remove_btn.clicked.connect(self._on_remove)
        toggle_btn = QPushButton("Aktivieren/&Deaktivieren")
        toggle_btn.clicked.connect(self._on_toggle)
        close_btn  = QPushButton("Sc&hließen")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(add_btn)
        btn_row.addWidget(remove_btn)
        btn_row.addWidget(toggle_btn)
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        self._fill()

    def _mgr(self):
        return getattr(self._window, "_scheduled_rec_manager", None)

    def _fill(self) -> None:
        self._list.clear()
        try:
            mgr = self._mgr()
            if mgr is None:
                self._list.addItem("(Manager nicht verfügbar)")
                return
            for rec in mgr.items():
                status = "" if rec.enabled else " [AUS]"
                self._list.addItem(
                    f"{rec.label} — {rec.start_time}, {rec.duration_min} min{status}"
                )
            if self._list.count() == 0:
                self._list.addItem("(Keine Aufnahmen geplant)")
        except Exception as exc:
            self._list.addItem(f"Fehler: {exc}")

    def _on_add(self) -> None:
        label = self._label_edit.text().strip() or "Aufnahme"
        time_str = self._time_edit.time().toString("HH:mm")
        weekdays = [i for i, cb in enumerate(self._wd_checks) if cb.isChecked()]
        duration = self._duration_spin.value()
        try:
            mgr = self._mgr()
            if mgr is None:
                return
            from scheduled_recordings import ScheduledRecording
            rec = ScheduledRecording.new(label, weekdays, time_str, duration)
            mgr.add(rec)
            mgr.save()
            self._fill()
            self._label_edit.clear()
        except Exception as exc:
            QMessageBox.warning(self, "Fehler", str(exc))

    def _on_remove(self) -> None:
        row = self._list.currentRow()
        if row < 0:
            return
        try:
            mgr = self._mgr()
            if mgr is None:
                return
            items = mgr.items()
            if row < len(items):
                mgr.remove(row)
                mgr.save()
                self._fill()
        except Exception as exc:
            QMessageBox.warning(self, "Fehler", str(exc))

    def _on_toggle(self) -> None:
        row = self._list.currentRow()
        if row < 0:
            return
        try:
            mgr = self._mgr()
            if mgr is None:
                return
            items = mgr.items()
            if row < len(items):
                mgr.toggle_enabled(row)
                mgr.save()
                self._fill()
        except Exception as exc:
            QMessageBox.warning(self, "Fehler", str(exc))


# ---------------------------------------------------------------------------
# 3. RecordingsBrowserDialog
# ---------------------------------------------------------------------------

class RecordingsBrowserDialog(QDialog):
    """Aufnahmen im Aufnahme-Verzeichnis durchsuchen."""

    def __init__(self, parent, window) -> None:
        super().__init__(parent)
        self.setWindowTitle("Aufnahmen durchsuchen")
        self.resize(600, 460)
        self._window = window

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Aufnahmedateien:"))

        self._list = QListWidget()
        self._list.setAccessibleName("Aufnahmen Liste")
        layout.addWidget(self._list, 1)

        btn_row = QHBoxLayout()
        open_btn    = QPushButton("&Ordner öffnen")
        open_btn.clicked.connect(self._on_open_folder)
        play_btn    = QPushButton("&Abspielen")
        play_btn.clicked.connect(self._on_play)
        delete_btn  = QPushButton("&Löschen")
        delete_btn.clicked.connect(self._on_delete)
        refresh_btn = QPushButton("A&ktualisieren")
        refresh_btn.clicked.connect(self._fill)
        close_btn   = QPushButton("Sc&hließen")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(open_btn)
        btn_row.addWidget(play_btn)
        btn_row.addWidget(delete_btn)
        btn_row.addWidget(refresh_btn)
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        self._fill()

    def _recordings_dir(self) -> Path:
        try:
            settings = getattr(self._window, "settings_store", None)
            if settings is not None:
                rec_dir = getattr(settings.settings, "recordings_dir", None)
                if rec_dir:
                    return Path(rec_dir)
        except Exception:
            pass
        return Path.home() / "TeamTalk Aufnahmen"

    def _fill(self) -> None:
        self._list.clear()
        self._files: List[Path] = []
        rec_dir = self._recordings_dir()
        if not rec_dir.exists():
            self._list.addItem(f"Verzeichnis nicht gefunden: {rec_dir}")
            return
        try:
            files = sorted(
                [p for p in rec_dir.iterdir() if p.suffix.lower() in (".wav", ".mp3")],
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            self._files = files
            for p in files:
                try:
                    stat  = p.stat()
                    size  = stat.st_size
                    mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%d.%m.%Y %H:%M")
                    if size < 1024 * 1024:
                        size_str = f"{size / 1024:.1f} KB"
                    else:
                        size_str = f"{size / (1024 * 1024):.1f} MB"
                    self._list.addItem(f"{p.name} — {size_str}, {mtime}")
                except Exception:
                    self._list.addItem(p.name)
            if not files:
                self._list.addItem("(Keine Aufnahmen gefunden)")
        except Exception as exc:
            self._list.addItem(f"Fehler: {exc}")

    def _selected_file(self):
        row = self._list.currentRow()
        if row < 0 or row >= len(self._files):
            return None
        return self._files[row]

    def _on_open_folder(self) -> None:
        rec_dir = self._recordings_dir()
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(rec_dir)))

    def _on_play(self) -> None:
        path = self._selected_file()
        if path is None:
            return
        try:
            if sys.platform == "win32":
                os.startfile(str(path))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["afplay", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as exc:
            QMessageBox.warning(self, "Fehler", f"Abspielen fehlgeschlagen: {exc}")

    def _on_delete(self) -> None:
        path = self._selected_file()
        if path is None:
            return
        answer = QMessageBox.question(
            self, "Löschen bestätigen",
            f"'{path.name}' wirklich löschen?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            try:
                path.unlink()
                self._fill()
            except Exception as exc:
                QMessageBox.warning(self, "Fehler", str(exc))


# ---------------------------------------------------------------------------
# 4. ServerAudioProfilesDialog  (extended version with form)
# ---------------------------------------------------------------------------

class ServerAudioProfilesDialog(QDialog):
    """Server-Audioprofile verwalten."""

    def __init__(self, parent, window) -> None:
        super().__init__(parent)
        self.setWindowTitle("Server-Audioprofile")
        self.resize(520, 480)
        self._window = window

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Server → Audio-Profil Zuordnung:"))

        self._list = QListWidget()
        self._list.setAccessibleName("Server-Audioprofile Liste")
        layout.addWidget(self._list, 1)

        # Form for new/edit entry
        form_group = QGroupBox("Profil-Einstellungen")
        form = QFormLayout(form_group)

        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("Profilname...")
        form.addRow("Profilname:", self._name_edit)

        self._server_edit = QLineEdit()
        self._server_edit.setPlaceholderText("host:port oder Schlüssel")
        form.addRow("Server-Schlüssel:", self._server_edit)

        self._mic_spin = QSpinBox()
        self._mic_spin.setRange(0, 200)
        self._mic_spin.setValue(100)
        self._mic_spin.setSuffix(" %")
        form.addRow("Mikrofon-Verstärkung:", self._mic_spin)

        self._out_spin = QSpinBox()
        self._out_spin.setRange(0, 200)
        self._out_spin.setValue(100)
        self._out_spin.setSuffix(" %")
        form.addRow("Ausgabelautstärke:", self._out_spin)

        layout.addWidget(form_group)

        btn_row = QHBoxLayout()
        new_btn    = QPushButton("&Neu / Aktualisieren")
        new_btn.clicked.connect(self._on_new)
        apply_btn  = QPushButton("&Anwenden")
        apply_btn.clicked.connect(self._on_apply)
        delete_btn = QPushButton("&Löschen")
        delete_btn.clicked.connect(self._on_delete)
        close_btn  = QPushButton("Sc&hließen")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(new_btn)
        btn_row.addWidget(apply_btn)
        btn_row.addWidget(delete_btn)
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        self._list.currentRowChanged.connect(self._on_select)
        self._fill()

    def _store(self):
        return getattr(self._window, "settings_store", None)

    def _profiles_dict(self) -> dict:
        try:
            store = self._store()
            if store is None:
                return {}
            return dict(getattr(store.settings, "server_audio_profiles", {}) or {})
        except Exception:
            return {}

    def _fill(self) -> None:
        self._list.clear()
        for key, val in self._profiles_dict().items():
            if isinstance(val, dict):
                name = val.get("name", key)
                mic  = val.get("mic_gain_pct", 100)
                out  = val.get("out_volume_pct", 100)
                self._list.addItem(f"{key} → {name} (Mic {mic}%, Out {out}%)")
            else:
                self._list.addItem(f"{key} → {val}")
        if self._list.count() == 0:
            self._list.addItem("(Keine Profile)")

    def _on_select(self, row: int) -> None:
        profiles = self._profiles_dict()
        keys = list(profiles.keys())
        if row < 0 or row >= len(keys):
            return
        key = keys[row]
        val = profiles[key]
        self._server_edit.setText(key)
        if isinstance(val, dict):
            self._name_edit.setText(val.get("name", ""))
            self._mic_spin.setValue(int(val.get("mic_gain_pct", 100)))
            self._out_spin.setValue(int(val.get("out_volume_pct", 100)))
        else:
            self._name_edit.setText(str(val))

    def _on_new(self) -> None:
        key  = self._server_edit.text().strip()
        name = self._name_edit.text().strip()
        if not key:
            QMessageBox.information(self, "Hinweis", "Bitte Server-Schlüssel eingeben.")
            return
        entry = {
            "name": name or key,
            "mic_gain_pct": self._mic_spin.value(),
            "out_volume_pct": self._out_spin.value(),
        }
        try:
            store = self._store()
            if store is None:
                return
            profiles = dict(getattr(store.settings, "server_audio_profiles", {}) or {})
            profiles[key] = entry
            store.settings.server_audio_profiles = profiles
            store.save()
            self._fill()
        except Exception as exc:
            QMessageBox.warning(self, "Fehler", str(exc))

    def _on_apply(self) -> None:
        row = self._list.currentRow()
        profiles = self._profiles_dict()
        keys = list(profiles.keys())
        if row < 0 or row >= len(keys):
            return
        val = profiles[keys[row]]
        try:
            apply_fn = getattr(self._window, "apply_audio_profile", None)
            if callable(apply_fn):
                apply_fn(val)
        except Exception as exc:
            QMessageBox.warning(self, "Fehler", str(exc))

    def _on_delete(self) -> None:
        row = self._list.currentRow()
        profiles = self._profiles_dict()
        keys = list(profiles.keys())
        if row < 0 or row >= len(keys):
            return
        key = keys[row]
        try:
            store = self._store()
            if store is None:
                return
            del profiles[key]
            store.settings.server_audio_profiles = profiles
            store.save()
            self._fill()
        except Exception as exc:
            QMessageBox.warning(self, "Fehler", str(exc))


# ---------------------------------------------------------------------------
# 5. UserWatcherDialogFull  (extended, replaces/augments existing UserWatcherDialog)
# ---------------------------------------------------------------------------

class UserWatcherDialogFull(QDialog):
    """Nutzerwatcher — Benachrichtigung wenn Nutzer sich verbindet/trennt."""

    def __init__(self, parent, window) -> None:
        super().__init__(parent)
        self.setWindowTitle("Nutzerwatcher")
        self.resize(420, 400)
        self._window = window

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Benachrichtigung wenn Nutzer sich verbindet/trennt:"))

        self._list = QListWidget()
        self._list.setAccessibleName("Beobachtete Nutzer Liste")
        layout.addWidget(self._list, 1)
        self._fill_list()

        input_row = QHBoxLayout()
        self._input = QLineEdit()
        self._input.setPlaceholderText("Nutzername hinzufügen...")
        self._input.returnPressed.connect(self._on_add)
        input_row.addWidget(self._input, 1)
        add_btn = QPushButton("&Hinzufügen")
        add_btn.clicked.connect(self._on_add)
        input_row.addWidget(add_btn)
        layout.addLayout(input_row)

        self._cb_join  = QCheckBox("TTS-Ansage bei Beitritt")
        self._cb_leave = QCheckBox("TTS-Ansage bei Verlassen")
        try:
            settings = getattr(self._window, "settings_store", None)
            if settings is not None:
                self._cb_join.setChecked(bool(getattr(settings.settings, "watcher_tts_join", True)))
                self._cb_leave.setChecked(bool(getattr(settings.settings, "watcher_tts_leave", True)))
        except Exception:
            pass
        layout.addWidget(self._cb_join)
        layout.addWidget(self._cb_leave)

        btn_row = QHBoxLayout()
        remove_btn = QPushButton("&Entfernen")
        remove_btn.clicked.connect(self._on_remove)
        save_btn   = QPushButton("&Speichern")
        save_btn.clicked.connect(self._on_save)
        close_btn  = QPushButton("Sc&hließen")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(remove_btn)
        btn_row.addWidget(save_btn)
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    def _watched_list(self) -> List[str]:
        try:
            # Check _watched_users dict first
            watched_users = getattr(self._window, "_watched_users", None)
            if isinstance(watched_users, dict):
                return list(watched_users.keys())
            elif isinstance(watched_users, list):
                return list(watched_users)
            # Fall back to settings
            store = getattr(self._window, "settings_store", None)
            if store is not None:
                return list(getattr(store.settings, "watched_users", []) or [])
        except Exception:
            pass
        return []

    def _fill_list(self) -> None:
        self._list.clear()
        for name in self._watched_list():
            self._list.addItem(name)

    def _on_add(self) -> None:
        name = self._input.text().strip()
        if not name:
            return
        for i in range(self._list.count()):
            if self._list.item(i).text() == name:
                return
        self._list.addItem(name)
        self._input.clear()

    def _on_remove(self) -> None:
        row = self._list.currentRow()
        if row >= 0:
            self._list.takeItem(row)

    def _on_save(self) -> None:
        names = [self._list.item(i).text() for i in range(self._list.count())]
        try:
            store = getattr(self._window, "settings_store", None)
            if store is not None:
                store.settings.watched_users = names
                store.settings.watcher_tts_join  = self._cb_join.isChecked()
                store.settings.watcher_tts_leave = self._cb_leave.isChecked()
                store.save()
            # Also update _watched_users dict if it exists
            watched_users = getattr(self._window, "_watched_users", None)
            if isinstance(watched_users, dict):
                # Preserve existing data, remove deleted, keep added
                existing = set(watched_users.keys())
                new_set  = set(names)
                for removed in existing - new_set:
                    del watched_users[removed]
                for added in new_set - existing:
                    watched_users[added] = {}
        except Exception as exc:
            QMessageBox.warning(self, "Fehler", str(exc))


# ---------------------------------------------------------------------------
# 6. TtsTranscriptDialogFull  (extended version with QTextEdit + export)
# ---------------------------------------------------------------------------

class TtsTranscriptDialogFull(QDialog):
    """TTS-Mitschrift — alle gesprochenen Texte mit Zeitstempel."""

    def __init__(self, parent, window) -> None:
        super().__init__(parent)
        self.setWindowTitle("TTS-Mitschrift")
        self.resize(620, 460)
        self._window = window
        # Non-modal
        self.setWindowModality(Qt.WindowModality.NonModal)

        layout = QVBoxLayout(self)

        self._text = QTextEdit()
        self._text.setReadOnly(True)
        self._text.setAccessibleName("TTS-Mitschrift Text")
        layout.addWidget(self._text, 1)

        btn_row = QHBoxLayout()
        export_btn  = QPushButton("&Exportieren")
        export_btn.clicked.connect(self._on_export)
        clear_btn   = QPushButton("&Leeren")
        clear_btn.clicked.connect(self._on_clear)
        refresh_btn = QPushButton("A&ktualisieren")
        refresh_btn.clicked.connect(self._fill)
        close_btn   = QPushButton("Sc&hließen")
        close_btn.clicked.connect(self.close)
        btn_row.addWidget(export_btn)
        btn_row.addWidget(clear_btn)
        btn_row.addWidget(refresh_btn)
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        self._fill()

    def _transcript(self) -> List[str]:
        try:
            tts = getattr(self._window, "tts", None)
            if tts is not None:
                raw = getattr(tts, "_transcript", None)
                if raw is not None:
                    return [f"{ts}, {kind}: {text}" for ts, kind, text in list(raw)]
            # Fall back to _tts_transcript list on window
            tts_transcript = getattr(self._window, "_tts_transcript", None)
            if tts_transcript is not None:
                return list(tts_transcript)
        except Exception:
            pass
        return []

    def _fill(self) -> None:
        lines = self._transcript()
        if lines:
            self._text.setPlainText("\n".join(lines))
        else:
            self._text.setPlainText("(Keine TTS-Einträge vorhanden)")

    def _on_clear(self) -> None:
        try:
            tts = getattr(self._window, "tts", None)
            if tts is not None:
                transcript = getattr(tts, "_transcript", None)
                if transcript is not None:
                    transcript.clear()
            tts_transcript = getattr(self._window, "_tts_transcript", None)
            if tts_transcript is not None:
                tts_transcript.clear()
        except Exception:
            pass
        self._text.clear()

    def _on_export(self) -> None:
        lines = self._transcript()
        if not lines:
            QMessageBox.information(self, "Hinweis", "Keine Einträge zum Exportieren.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Mitschrift exportieren", "tts_mitschrift.txt",
            "Textdateien (*.txt);;Alle Dateien (*)"
        )
        if not path:
            return
        try:
            Path(path).write_text("\n".join(lines), encoding="utf-8")
        except Exception as exc:
            QMessageBox.warning(self, "Fehler", str(exc))


# ---------------------------------------------------------------------------
# 7. OfflineQueueDialogFull  (extended with send + remove)
# ---------------------------------------------------------------------------

class OfflineQueueDialogFull(QDialog):
    """Offline-Nachrichtenwarteschlange verwalten."""

    def __init__(self, parent, window) -> None:
        super().__init__(parent)
        self.setWindowTitle("Offline-Nachrichtenwarteschlange")
        self.resize(540, 400)
        self._window = window

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Nachrichten, die im Offline-Modus gepuffert wurden:"))

        self._list = QListWidget()
        self._list.setAccessibleName("Offline-Warteschlange Liste")
        layout.addWidget(self._list, 1)

        self._status = QLabel("")
        layout.addWidget(self._status)

        btn_row = QHBoxLayout()
        send_btn   = QPushButton("Alle &senden")
        send_btn.clicked.connect(self._on_send_all)
        remove_btn = QPushButton("&Entfernen")
        remove_btn.clicked.connect(self._on_remove)
        clear_btn  = QPushButton("&Leeren")
        clear_btn.clicked.connect(self._on_clear)
        close_btn  = QPushButton("Sc&hließen")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(send_btn)
        btn_row.addWidget(remove_btn)
        btn_row.addWidget(clear_btn)
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        self._fill()

    def _oq(self):
        return getattr(self._window, "_offline_queue", None)

    def _fill(self) -> None:
        self._list.clear()
        try:
            oq = self._oq()
            if oq is None:
                self._list.addItem("(Offline-Queue nicht verfügbar)")
                return
            msgs = list(oq.peek() or [])
            for m in msgs:
                try:
                    target      = getattr(m, "target_name", None) or str(getattr(m, "target_id", "?"))
                    text        = getattr(m, "text", "")
                    target_type = getattr(m, "target_type", "channel")
                    kind_label  = "Privat" if target_type == "private" else "Kanal"
                    age         = getattr(m, "age_str", "?")
                    preview     = text[:60] + ("…" if len(text) > 60 else "")
                    self._list.addItem(f"[{age} alt, {kind_label} → {target}] {preview}")
                except Exception:
                    self._list.addItem(str(m))
            count = len(msgs)
            self._status.setText(f"{count} Nachricht(en) ausstehend")
            if count == 0:
                self._list.addItem("(Warteschlange leer)")
            client = getattr(self._window, "_client", None) or getattr(self._window, "client", None)
            connected = bool(client and client.is_connected())
            for btn in self.findChildren(QPushButton):
                if btn.text() in ("Alle &senden", "Alle senden"):
                    btn.setEnabled(connected and count > 0)
        except Exception as exc:
            self._list.addItem(f"Fehler: {exc}")

    def _on_send_all(self) -> None:
        try:
            client = getattr(self._window, "_client", None) or getattr(self._window, "client", None)
            oq     = self._oq()
            if oq is None or client is None or not client.is_connected():
                QMessageBox.information(self, "Hinweis", "Nicht verbunden – Nachrichten können nicht gesendet werden.")
                return
            msgs = list(oq.dequeue_all() or [])
            sent = 0
            for m in msgs:
                try:
                    target_id   = int(getattr(m, "target_id", 0))
                    text        = getattr(m, "text", "")
                    target_type = getattr(m, "target_type", "channel")
                    if target_type == "private":
                        ok = client.send_user_message(target_id, text)
                    else:
                        ok = client.send_channel_message(target_id, text)
                    if ok:
                        sent += 1
                except Exception:
                    pass
            self._fill()
            self._status.setText(f"{sent} von {len(msgs)} Nachricht(en) gesendet")
        except Exception as exc:
            QMessageBox.warning(self, "Fehler", str(exc))

    def _on_remove(self) -> None:
        row = self._list.currentRow()
        if row < 0:
            QMessageBox.information(self, "Hinweis", "Bitte zuerst einen Eintrag auswählen.")
            return
        try:
            oq = self._oq()
            if oq is None:
                return
            oq.remove_at(row)
            self._fill()
            count = self._list.count()
            if count > 0:
                self._list.setCurrentRow(min(row, count - 1))
        except Exception as exc:
            QMessageBox.warning(self, "Fehler", str(exc))

    def _on_clear(self) -> None:
        try:
            oq = self._oq()
            if oq is not None:
                oq.clear()
            self._fill()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# 8. PluginManagerDialogQt
# ---------------------------------------------------------------------------

class PluginManagerDialogQt(QDialog):
    """Plugin-Manager — Plugins ansehen, aktivieren/deaktivieren und neu laden."""

    def __init__(self, parent, window) -> None:
        super().__init__(parent)
        self.setWindowTitle("Plugin-Manager")
        self.resize(580, 460)
        self._window = window

        layout = QVBoxLayout(self)

        # Plugin dir info
        try:
            plugins_dir = Path(getattr(self._loader(), "_plugins_dir",
                               Path(__file__).resolve().parent.parent.parent / "plugins"))
        except Exception:
            plugins_dir = Path(__file__).resolve().parent.parent.parent / "plugins"
        self._plugins_dir = plugins_dir
        layout.addWidget(QLabel(f"Plugin-Verzeichnis: {plugins_dir}"))

        self._list = QListWidget()
        self._list.setAccessibleName("Plugin-Liste")
        layout.addWidget(self._list, 1)

        self._detail = QTextEdit()
        self._detail.setReadOnly(True)
        self._detail.setAccessibleName("Plugin-Details")
        self._detail.setMaximumHeight(100)
        layout.addWidget(self._detail)

        self._list.currentRowChanged.connect(self._on_select)

        btn_row = QHBoxLayout()
        self._toggle_btn = QPushButton("&Aktivieren/Deaktivieren")
        self._toggle_btn.clicked.connect(self._on_toggle)
        reload_btn  = QPushButton("Neu &laden")
        reload_btn.clicked.connect(self._on_reload)
        open_dir_btn = QPushButton("&Ordner öffnen")
        open_dir_btn.clicked.connect(self._on_open_dir)
        close_btn   = QPushButton("Sc&hließen")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(self._toggle_btn)
        btn_row.addWidget(reload_btn)
        btn_row.addWidget(open_dir_btn)
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        self._filenames: List[str] = []
        self._fill()

    def _loader(self):
        return getattr(self._window, "_plugin_loader", None)

    def _disabled_list(self) -> List[str]:
        try:
            store = getattr(self._window, "settings_store", None)
            if store is not None:
                return list(getattr(store.settings, "disabled_plugins", []) or [])
        except Exception:
            pass
        return []

    def _fill(self) -> None:
        self._list.clear()
        self._filenames = []
        try:
            loader = self._loader()
            if loader is None:
                self._list.addItem("(Plugin-Loader nicht verfügbar)")
                return
            disabled = self._disabled_list()
            meta_all = loader.all_metadata()
            for filename, meta in sorted(meta_all.items()):
                name    = meta.get("name") or filename
                version = meta.get("version", "")
                is_dis  = filename in disabled
                label   = f"{'[AUS] ' if is_dis else ''}{name}"
                if version:
                    label += f" v{version}"
                self._list.addItem(label)
                self._filenames.append(filename)
            if self._list.count() == 0:
                self._list.addItem("(Keine Plugins geladen)")
        except Exception as exc:
            self._list.addItem(f"Fehler: {exc}")

    def _on_select(self, row: int) -> None:
        if row < 0 or row >= len(self._filenames):
            self._detail.clear()
            return
        filename = self._filenames[row]
        try:
            loader   = self._loader()
            meta     = loader.get_metadata(filename) if loader else {}
            disabled = self._disabled_list()
            is_dis   = filename in disabled
            lines = [
                f"Datei:        {filename}",
                f"Name:         {meta.get('name') or filename}",
                f"Version:      {meta.get('version') or '–'}",
                f"Autor:        {meta.get('author') or '–'}",
                f"Beschreibung: {meta.get('description') or '–'}",
                f"Status:       {'Deaktiviert (wirkt beim nächsten Start)' if is_dis else 'Aktiv'}",
            ]
            self._detail.setPlainText("\n".join(lines))
            self._toggle_btn.setText("&Aktivieren" if is_dis else "&Deaktivieren")
        except Exception as exc:
            self._detail.setPlainText(f"Fehler: {exc}")

    def _on_toggle(self) -> None:
        row = self._list.currentRow()
        if row < 0 or row >= len(self._filenames):
            return
        filename = self._filenames[row]
        try:
            store = getattr(self._window, "settings_store", None)
            if store is None:
                return
            disabled = list(getattr(store.settings, "disabled_plugins", []) or [])
            if filename in disabled:
                disabled.remove(filename)
            else:
                disabled.append(filename)
            store.settings.disabled_plugins = disabled
            store.save()
            self._fill()
            if row < self._list.count():
                self._list.setCurrentRow(row)
        except Exception as exc:
            QMessageBox.warning(self, "Fehler", str(exc))

    def _on_reload(self) -> None:
        row = self._list.currentRow()
        if row < 0 or row >= len(self._filenames):
            return
        filename = self._filenames[row]
        try:
            loader = self._loader()
            if loader is None:
                return
            ok = loader.reload_plugin(filename)
            if ok:
                self._fill()
                if row < self._list.count():
                    self._list.setCurrentRow(row)
            else:
                errors = loader.get_errors()
                err = errors.get(filename, "Unbekannter Fehler")
                QMessageBox.warning(self, "Plugin-Fehler",
                                    f"Fehler beim Neu-Laden von {filename}:\n\n{err[:500]}")
        except Exception as exc:
            QMessageBox.warning(self, "Fehler", str(exc))

    def _on_open_dir(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._plugins_dir)))
