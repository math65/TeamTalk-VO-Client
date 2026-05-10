from __future__ import annotations

import html
import re
import time
from typing import TYPE_CHECKING, List

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QLabel, QCheckBox, QComboBox, QTextEdit, QLineEdit,
    QPushButton, QFileDialog,
)
from PySide6.QtCore import Qt

if TYPE_CHECKING:
    from app_qt import MainWindow

_MD_PATTERNS = [
    (re.compile(r'\*\*(.+?)\*\*'), r'\1'),
    (re.compile(r'\*(.+?)\*'),     r'\1'),
    (re.compile(r'`(.+?)`'),       r'\1'),
]

_EMOJI_SHORTCODES = {
    ":+1:": "👍", ":-1:": "👎", ":smile:": "😊", ":laughing:": "😂",
    ":wink:": "😉", ":heart:": "❤️", ":fire:": "🔥", ":wave:": "👋",
    ":ok:": "✅", ":x:": "❌", ":warning:": "⚠️", ":info:": "ℹ️",
    ":mic:": "🎤", ":headphones:": "🎧", ":speaker:": "🔊",
    ":mute:": "🔇", ":clap:": "👏", ":star:": "⭐", ":check:": "✔️",
    ":question:": "❓", ":exclamation:": "❗", ":tada:": "🎉", ":eyes:": "👀",
}


def _strip_markdown(text: str) -> str:
    for pattern, repl in _MD_PATTERNS:
        text = pattern.sub(repl, text)
    return text


def expand_emoji_shortcodes(text: str) -> str:
    for code, emoji in _EMOJI_SHORTCODES.items():
        text = text.replace(code, emoji)
    return text


class ChatTab(QWidget):
    """Tab 3: Chat."""

    def __init__(self, parent: QWidget, window: "MainWindow") -> None:
        super().__init__(parent)
        self.window = window
        self._search_positions: List[int] = []
        self._private_user_ids: List[int] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        # Chat target
        target_group = QGroupBox("Chat-Ziel")
        target_layout = QVBoxLayout(target_group)
        self.chat_target = QLabel("Ziel: (kein)")
        self.chat_target.setObjectName("Chat-Ziel")
        target_layout.addWidget(self.chat_target)

        target_row = QHBoxLayout()
        self.private_chat = QCheckBox("&Privat")
        self.private_chat.stateChanged.connect(lambda _: self.update_chat_target())
        lbl_private = QLabel("Privat an:")
        self.private_user = QComboBox()
        self.private_user.setObjectName("Privat an")
        target_row.addWidget(self.private_chat)
        target_row.addWidget(lbl_private)
        target_row.addWidget(self.private_user, 1)
        target_layout.addLayout(target_row)
        root.addWidget(target_group)

        root.addWidget(QLabel("Chatverlauf"))
        self.chat_log = QTextEdit()
        self.chat_log.setReadOnly(True)
        self.chat_log.setObjectName("Chatverlauf")
        root.addWidget(self.chat_log, 1)

        # History buttons
        history_row = QHBoxLayout()
        self.export_btn = QPushButton("Verlauf &exportieren")
        self.export_btn.clicked.connect(self._on_export_history)
        self.export_html_btn = QPushButton("Als &HTML")
        self.export_html_btn.clicked.connect(self._on_export_html)
        self.clear_btn = QPushButton("Verlauf &leeren")
        self.clear_btn.clicked.connect(self._on_clear_history)
        self.quote_btn = QPushButton("&Zitieren")
        self.quote_btn.clicked.connect(self._on_quote)
        self.save_msg_btn = QPushButton("&Speichern")
        self.save_msg_btn.clicked.connect(self._on_save_msg)
        for btn in (self.export_btn, self.export_html_btn, self.clear_btn,
                    self.quote_btn, self.save_msg_btn):
            history_row.addWidget(btn)
        history_row.addStretch()
        root.addLayout(history_row)

        # Message input
        root.addWidget(QLabel("Nachricht"))
        self.chat_input = QLineEdit()
        self.chat_input.setObjectName("Nachricht eingeben")
        self.chat_input.setPlaceholderText("Nachricht eingeben …")
        self.chat_input.returnPressed.connect(self._on_send)
        root.addWidget(self.chat_input)

        send_row = QHBoxLayout()
        self.send_btn = QPushButton("&Senden")
        self.send_btn.clicked.connect(self._on_send)
        self.char_count_label = QLabel("0 Zeichen")
        self.char_count_label.setObjectName("Zeichenanzahl")
        send_row.addWidget(self.send_btn)
        send_row.addWidget(self.char_count_label)
        send_row.addStretch()
        root.addLayout(send_row)
        self.chat_input.textChanged.connect(self._on_input_changed)

    def _on_input_changed(self, text: str) -> None:
        self.char_count_label.setText(f"{len(text)} Zeichen")

    def update_chat_target(self) -> None:
        is_private = self.private_chat.isChecked()
        if is_private:
            idx = self.private_user.currentIndex()
            if idx >= 0 and idx < len(self._private_user_ids):
                uid = self._private_user_ids[idx]
                name = self.private_user.currentText()
                self.chat_target.setText(f"Ziel: {name} (privat)")
            else:
                self.chat_target.setText("Ziel: (kein Nutzer)")
        else:
            ch_name = getattr(self.window, "_current_channel_name", "(kein Kanal)")
            self.chat_target.setText(f"Ziel: {ch_name} (Kanal)")

    def refresh_private_user_choice(self, users) -> None:
        current_id = self._private_user_ids[self.private_user.currentIndex()] \
            if self._private_user_ids and self.private_user.currentIndex() >= 0 else None
        self.private_user.blockSignals(True)
        self.private_user.clear()
        self._private_user_ids = []
        tt_str = self.window.tt_str
        for u in users:
            try:
                uid = int(u.nUserID)
                my_id = self.window.client.get_my_user_id()
                if uid == my_id:
                    continue
                name = tt_str(u.szNickname) or tt_str(u.szUsername) or f"User#{uid}"
                self.private_user.addItem(name)
                self._private_user_ids.append(uid)
            except Exception:
                pass
        if current_id and current_id in self._private_user_ids:
            self.private_user.setCurrentIndex(self._private_user_ids.index(current_id))
        self.private_user.blockSignals(False)
        self.update_chat_target()

    def append_message(self, sender: str, text: str, ts: str = "", private: bool = False,
                       own: bool = False, kind: str = "channel") -> None:
        text = expand_emoji_shortcodes(_strip_markdown(text))
        ts_str = ts or time.strftime("%H:%M:%S")
        prefix = "[Privat] " if private else ""
        line = f"[{ts_str}] {prefix}{sender}: {text}"
        self.chat_log.append(line)

    def append_system_message(self, text: str, ts: str = "") -> None:
        ts_str = ts or time.strftime("%H:%M:%S")
        self.chat_log.append(f"[{ts_str}] *** {text}")

    def _on_send(self) -> None:
        text = self.chat_input.text().strip()
        if not text:
            return
        is_private = self.private_chat.isChecked()
        target_id = 0
        if is_private and self._private_user_ids:
            idx = self.private_user.currentIndex()
            if 0 <= idx < len(self._private_user_ids):
                target_id = self._private_user_ids[idx]
        self.window.send_chat_message(text, private=is_private, target_id=target_id)
        self.chat_input.clear()

    def _on_export_history(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Chatverlauf exportieren", "chatverlauf.txt",
            "Textdateien (*.txt);;Alle Dateien (*.*)"
        )
        if path:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(self.chat_log.toPlainText())
                self.window.set_status(f"Verlauf exportiert: {path}")
            except Exception as exc:
                self.window.set_status(f"Export fehlgeschlagen: {exc}")

    def _on_export_html(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Chatverlauf als HTML", "chatverlauf.html",
            "HTML-Dateien (*.html);;Alle Dateien (*.*)"
        )
        if path:
            try:
                lines = self.chat_log.toPlainText().splitlines()
                body = "\n".join(f"<p>{html.escape(l)}</p>" for l in lines)
                with open(path, "w", encoding="utf-8") as f:
                    f.write(f"<html><body>{body}</body></html>")
                self.window.set_status(f"HTML exportiert: {path}")
            except Exception as exc:
                self.window.set_status(f"Export fehlgeschlagen: {exc}")

    def _on_clear_history(self) -> None:
        self.chat_log.clear()

    def _on_quote(self) -> None:
        selected = self.chat_log.textCursor().selectedText().strip()
        if selected:
            self.chat_input.setText(f"> {selected}\n")

    def _on_save_msg(self) -> None:
        selected = self.chat_log.textCursor().selectedText().strip()
        if selected:
            self.window.save_message(selected)
