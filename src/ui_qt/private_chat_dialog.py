"""Privater Chat-Dialog — öffnet sich beim Enter-Druck auf einen Benutzer."""
from __future__ import annotations

import html
import time
from typing import TYPE_CHECKING, Dict, Optional

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTextEdit,
    QLineEdit, QPushButton, QLabel, QSplitter, QWidget,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QCloseEvent, QShortcut

from i18n import _

if TYPE_CHECKING:
    from app_qt import MainWindow


# Registry of open dialogs: user_id → dialog instance
_open_dialogs: Dict[int, "PrivateChatDialog"] = {}


def open_private_chat(window: "MainWindow", user_id: int, nick: str = "") -> "PrivateChatDialog":
    """Open or focus the private chat dialog for *user_id*."""
    if user_id in _open_dialogs and not _open_dialogs[user_id].isHidden():
        dlg = _open_dialogs[user_id]
        dlg.raise_()
        dlg.activateWindow()
        dlg.focus_input()
        return dlg
    dlg = PrivateChatDialog(window, user_id, nick)
    _open_dialogs[user_id] = dlg
    dlg.show()
    dlg.raise_()
    dlg.activateWindow()
    return dlg


class PrivateChatDialog(QDialog):
    """Nicht-modaler Privat-Chat mit einem Benutzer.

    Layout (ähnlich dem offiziellen TeamTalk 5-Client):
        ┌─────────────────────────────────────┐
        │  Chatverlauf (scrollbar, read-only) │
        ├─────────────────────────────────────┤
        │  Nachricht eingeben        [Senden] │
        │  [Verlauf laden] [Exportieren]      │
        └─────────────────────────────────────┘

    Tastatur:
        Enter / Ctrl+Return  → Nachricht senden
        F6                   → Fokus zwischen Verlauf und Eingabe wechseln
        Escape               → Dialog schließen
    """

    def __init__(self, window: "MainWindow", user_id: int, nick: str = "") -> None:
        super().__init__(window)
        self.window = window
        self.user_id = user_id
        self._nick = nick or f"User#{user_id}"
        self.setWindowTitle(f"Privat: {self._nick}")
        self.resize(520, 420)
        self.setModal(False)

        # NVDA/JAWS: accessible name for the dialog
        self.setAccessibleName(f"Privater Chat mit {self._nick}")  # f-string, kept untranslated

        self._build_ui()
        self._load_history()

        # Keep nick up to date
        self._nick_timer = QTimer(self)
        self._nick_timer.timeout.connect(self._refresh_nick)
        self._nick_timer.start(5000)

    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # Status line (who you're talking to)
        self._status_label = QLabel(f"Chat mit {self._nick}")
        self._status_label.setAccessibleName(_("Gesprächspartner"))
        root.addWidget(self._status_label)

        # Chat log (read-only)
        self.chat_log = QTextEdit()
        self.chat_log.setReadOnly(True)
        self.chat_log.setAccessibleName(f"Verlauf des privaten Chats mit {self._nick}")
        self.chat_log.setAccessibleDescription(_(
            "Chatverlauf. Drücken Sie F6 um zur Eingabe zu wechseln."
        ))
        root.addWidget(self.chat_log, 1)

        # Input row
        input_row = QHBoxLayout()
        self._input = QLineEdit()
        self._input.setPlaceholderText(f"Nachricht an {self._nick} …")
        self._input.setAccessibleName(_("Nachricht eingeben"))
        self._input.setAccessibleDescription(
            f"Nachricht an {self._nick}. Enter zum Senden, F6 für Verlauf."
        )
        self._input.returnPressed.connect(self._on_send)
        self._send_btn = QPushButton(_("&Senden"))
        self._send_btn.setAccessibleName(_("Nachricht senden"))
        self._send_btn.clicked.connect(self._on_send)
        input_row.addWidget(self._input, 1)
        input_row.addWidget(self._send_btn)
        root.addLayout(input_row)

        # Action buttons
        btn_row = QHBoxLayout()
        load_btn = QPushButton(_("Verlauf &laden"))
        load_btn.setAccessibleName(_("Gespeicherten Verlauf laden"))
        load_btn.clicked.connect(self._load_history)
        export_btn = QPushButton(_("&Exportieren"))
        export_btn.setAccessibleName(_("Verlauf exportieren"))
        export_btn.clicked.connect(self._on_export)
        copy_btn = QPushButton(_("&Kopieren"))
        copy_btn.setAccessibleName(_("Ausgewählten Text kopieren"))
        copy_btn.clicked.connect(self._on_copy)
        btn_row.addWidget(load_btn)
        btn_row.addWidget(export_btn)
        btn_row.addWidget(copy_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

        # Keyboard shortcuts
        f6 = QShortcut(QKeySequence("F6"), self)
        f6.activated.connect(self._toggle_focus)
        ctrl_enter = QShortcut(QKeySequence("Ctrl+Return"), self)
        ctrl_enter.activated.connect(self._on_send)

        # Copy shortcut on chat log
        copy_sc = QShortcut(QKeySequence("Ctrl+C"), self.chat_log)
        copy_sc.activated.connect(self._on_copy)

        # Focus input on open
        QTimer.singleShot(0, self._input.setFocus)

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------

    def _load_history(self) -> None:
        """Load saved private chat history from ChatHistoryManager."""
        self.chat_log.clear()
        try:
            key = self._history_key()
            if key and hasattr(self.window, "_chat_history"):
                lines = self.window._chat_history.get_lines(key)
                for line in (lines or []):
                    self.chat_log.append(
                        f'<span style="color:#555">{html.escape(str(line))}</span>'
                    )
        except Exception:
            pass
        self._scroll_to_bottom()

    def _history_key(self) -> str:
        server_key = getattr(self.window, "_current_server_key", "")
        return f"{server_key}:private:{self.user_id}" if server_key else f"private:{self.user_id}"

    # ------------------------------------------------------------------
    # Message display
    # ------------------------------------------------------------------

    def append_message(self, sender: str, text: str, own: bool = False) -> None:
        """Called by MainWindow when a private message is received/sent."""
        ts = time.strftime("%H:%M:%S")
        color = "#27ae60" if own else "#2980b9"
        line = f"[{ts}] {sender}: {html.escape(text)}"
        self.chat_log.append(f'<span style="color:{color}">{line}</span>')
        self._scroll_to_bottom()
        # Persist
        try:
            key = self._history_key()
            if key and hasattr(self.window, "_chat_history"):
                self.window._chat_history.append(key, f"[{ts}] {sender}: {text}")
        except Exception:
            pass

    def _scroll_to_bottom(self) -> None:
        sb = self.chat_log.verticalScrollBar()
        sb.setValue(sb.maximum())

    # ------------------------------------------------------------------
    # Send
    # ------------------------------------------------------------------

    def _on_send(self) -> None:
        text = self._input.text().strip()
        if not text:
            return
        try:
            self.window.send_chat_message(text, private=True, target_id=self.user_id)
            my_nick = ""
            try:
                my_id = self.window.client.get_my_user_id()
                u = self.window.client.get_user(my_id)
                my_nick = self.window.tt_str(u.szNickname) if u else "Ich"
            except Exception:
                my_nick = "Ich"
            self.append_message(my_nick, text, own=True)
            self._input.clear()
        except Exception as exc:
            self.window.set_status(f"Senden fehlgeschlagen: {exc}")

    # ------------------------------------------------------------------
    # Focus toggle (F6)
    # ------------------------------------------------------------------

    def _toggle_focus(self) -> None:
        if self._input.hasFocus():
            self.chat_log.setFocus()
        else:
            self.focus_input()

    def focus_input(self) -> None:
        self._input.setFocus()
        self._input.selectAll()

    # ------------------------------------------------------------------
    # Export / Copy
    # ------------------------------------------------------------------

    def _on_export(self) -> None:
        content = self.chat_log.toPlainText()
        if not content.strip():
            return
        from PySide6.QtWidgets import QFileDialog
        name = f"privat_{self._nick}_{time.strftime('%Y%m%d_%H%M%S')}.txt"
        path, _filter = QFileDialog.getSaveFileName(self, _("Verlauf exportieren"), name,
                                               "Textdateien (*.txt)")
        if path:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(content)
                self.window.set_status(f"Verlauf exportiert: {path}")
            except Exception as exc:
                self.window.set_status(f"Export fehlgeschlagen: {exc}")

    def _on_copy(self) -> None:
        cursor = self.chat_log.textCursor()
        if cursor.hasSelection():
            from PySide6.QtWidgets import QApplication
            QApplication.clipboard().setText(cursor.selectedText())

    # ------------------------------------------------------------------
    # Nick refresh
    # ------------------------------------------------------------------

    def _refresh_nick(self) -> None:
        try:
            u = self.window.client.get_user(self.user_id)
            if u:
                nick = self.window.tt_str(u.szNickname) or f"User#{self.user_id}"
                if nick != self._nick:
                    self._nick = nick
                    self.setWindowTitle(f"Privat: {nick}")
                    self._status_label.setText(f"Chat mit {nick}")
        except Exception:
            pass

    # ------------------------------------------------------------------

    def closeEvent(self, event: QCloseEvent) -> None:
        self._nick_timer.stop()
        _open_dialogs.pop(self.user_id, None)
        super().closeEvent(event)
