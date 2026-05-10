"""Qt-Dialoge — Entsprechungen der wx-Dialoge."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget,
    QPushButton, QLineEdit, QDialogButtonBox, QMessageBox,
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
                kind = msg.get("kind", "?")
                text = msg.get("text", "")
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
