"""Qt-Dialoge — Entsprechungen der wx-Dialoge."""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, List

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget,
    QPushButton, QLineEdit, QDialogButtonBox, QMessageBox, QTextEdit,
    QInputDialog,
)
from PySide6.QtCore import Qt

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
        self._list.setObjectName("Online-Nutzer Liste")
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
        self._list.setObjectName("Sperrliste")
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
        self._text.setObjectName("Serverstatistiken")
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
        self._list.setObjectName("Sprechprotokoll")
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
