from __future__ import annotations

import html
import re
import threading
import time
from typing import TYPE_CHECKING, List

from i18n import _

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QLabel, QCheckBox, QComboBox, QTextEdit, QLineEdit,
    QPushButton, QFileDialog, QMessageBox,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut

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

        # --- Search bar at top ---
        search_row = QHBoxLayout()
        search_row.addWidget(QLabel(_("Suchen:")))
        self.search_input = QLineEdit()
        self.search_input.setAccessibleName("Verlauf durchsuchen")
        self.search_input.setPlaceholderText("Im Verlauf suchen …")
        self.search_input.returnPressed.connect(self._on_search)
        search_row.addWidget(self.search_input, 1)
        self.search_btn = QPushButton(_("&Suchen"))
        self.search_btn.clicked.connect(self._on_search)
        search_row.addWidget(self.search_btn)
        self.search_count = QLabel(_("0 Treffer"))
        self.search_count.setAccessibleName("Suchergebnis")
        search_row.addWidget(self.search_count)
        root.addLayout(search_row)

        # --- Chat target group ---
        target_group = QGroupBox(_("Chat-Ziel"))
        target_layout = QVBoxLayout(target_group)
        self.chat_target = QLabel(_("Ziel: (kein)"))
        self.chat_target.setAccessibleName("Chat-Ziel")
        target_layout.addWidget(self.chat_target)

        target_row = QHBoxLayout()
        self.private_chat = QCheckBox(_("&Privat"))
        self.private_chat.setAccessibleName("Privat senden")
        self.private_chat.stateChanged.connect(lambda _: self.update_chat_target())
        lbl_private = QLabel(_("Privat an:"))
        self.private_user = QComboBox()
        self.private_user.setAccessibleName("Privat an")
        self.private_user.currentIndexChanged.connect(self._on_private_user_changed)
        target_row.addWidget(self.private_chat)
        target_row.addWidget(lbl_private)
        target_row.addWidget(self.private_user, 1)
        target_layout.addLayout(target_row)
        root.addWidget(target_group)

        # --- Chat log ---
        root.addWidget(QLabel(_("Chatverlauf")))
        self.chat_log = QTextEdit()
        self.chat_log.setReadOnly(True)
        self.chat_log.setAccessibleName("Chatverlauf")
        self.chat_log.setAccessibleDescription(
            "Lese-only Bereich. Strg+C kopiert markierten Text. "
            "F6 wechselt zur Eingabe."
        )
        root.addWidget(self.chat_log, 1)

        # --- History action buttons ---
        history_row = QHBoxLayout()
        self.export_btn = QPushButton(_("Verlauf &exportieren"))
        self.export_btn.clicked.connect(self._on_export_history)
        self.export_html_btn = QPushButton(_("Als &HTML"))
        self.export_html_btn.clicked.connect(self._on_export_html)
        self.clear_btn = QPushButton(_("Verlauf &leeren"))
        self.clear_btn.clicked.connect(self._on_clear_history)
        self.quote_btn = QPushButton(_("&Zitieren"))
        self.quote_btn.clicked.connect(self._on_quote)
        self.copy_btn = QPushButton(_("&Kopieren"))
        self.copy_btn.clicked.connect(self._on_copy)
        self.save_msg_btn = QPushButton(_("&Speichern"))
        self.save_msg_btn.clicked.connect(self._on_save_msg)
        for btn in (self.export_btn, self.export_html_btn, self.clear_btn,
                    self.quote_btn, self.copy_btn, self.save_msg_btn):
            history_row.addWidget(btn)
        history_row.addStretch()
        root.addLayout(history_row)

        # --- Message input ---
        root.addWidget(QLabel(_("Nachricht")))
        self.chat_input = QLineEdit()
        self.chat_input.setAccessibleName("Nachricht eingeben")
        self.chat_input.setAccessibleDescription(
            "Nachricht tippen und Enter drücken oder Senden klicken. "
            "F6 springt zum Chatverlauf."
        )
        self.chat_input.setPlaceholderText("Nachricht eingeben …")
        self.chat_input.returnPressed.connect(self._on_send)
        root.addWidget(self.chat_input)

        # F6 toggles focus between chat log and input
        f6 = QShortcut(QKeySequence("F6"), self)
        f6.activated.connect(self._toggle_focus)

        send_row = QHBoxLayout()
        self.send_btn = QPushButton(_("&Senden"))
        self.send_btn.setAccessibleName("Nachricht senden")
        self.send_btn.clicked.connect(self._on_send)
        self.improve_btn = QPushButton(_("&Verbessern"))
        self.improve_btn.setAccessibleName("Text verbessern")
        self.improve_btn.clicked.connect(self._on_improve_text)
        self.char_count_label = QLabel(_("0 Zeichen"))
        self.char_count_label.setAccessibleName("Zeichenanzahl")
        send_row.addWidget(self.send_btn)
        send_row.addWidget(self.improve_btn)
        send_row.addWidget(self.char_count_label)
        send_row.addStretch()
        root.addLayout(send_row)
        self.chat_input.textChanged.connect(self._on_input_changed)

        # Ctrl+C shortcut to copy selected text from chat log
        copy_sc = QShortcut(QKeySequence("Ctrl+C"), self.chat_log)
        copy_sc.activated.connect(self._on_copy)

    # ------------------------------------------------------------------
    # Input helpers
    # ------------------------------------------------------------------

    def _toggle_focus(self) -> None:
        if self.chat_input.hasFocus():
            self.chat_log.setFocus()
        else:
            self.chat_input.setFocus()

    def _on_input_changed(self, text: str) -> None:
        self.char_count_label.setText(f"{len(text)} Zeichen")

    # ------------------------------------------------------------------
    # Chat target
    # ------------------------------------------------------------------

    def _on_private_user_changed(self, _idx: int) -> None:
        self.update_chat_target()

    def update_chat_target(self) -> None:
        is_private = self.private_chat.isChecked()
        if is_private:
            idx = self.private_user.currentIndex()
            if idx >= 0 and idx < len(self._private_user_ids):
                name = self.private_user.currentText()
                self.chat_target.setText(f"Ziel: {name} (privat)")
            else:
                self.chat_target.setText("Ziel: (kein Nutzer)")
        else:
            ch_name = getattr(self.window, "_current_channel_name", "(kein Kanal)")
            self.chat_target.setText(f"Ziel: {ch_name} (Kanal)")

    def refresh_private_user_choice(self, users) -> None:
        current_id = (
            self._private_user_ids[self.private_user.currentIndex()]
            if self._private_user_ids and self.private_user.currentIndex() >= 0
            else None
        )
        self.private_user.blockSignals(True)
        self.private_user.clear()
        self._private_user_ids = []
        tt_str = self.window.tt_str
        items = []
        for u in users:
            try:
                uid = int(u.nUserID)
                my_id = self.window.client.get_my_user_id()
                if uid == my_id:
                    continue
                nickname = tt_str(u.szNickname)
                username = tt_str(u.szUsername)
                name = nickname or username or f"User#{uid}"
                if nickname and username and nickname != username:
                    name = f"{nickname} ({username})"
                items.append((name, uid))
            except Exception:
                pass
        items.sort(key=lambda x: x[0].lower())
        for name, uid in items:
            self.private_user.addItem(name)
            self._private_user_ids.append(uid)
        if current_id and current_id in self._private_user_ids:
            self.private_user.setCurrentIndex(self._private_user_ids.index(current_id))
        self.private_user.blockSignals(False)
        self.update_chat_target()

    def select_private_recipient(self, user_id: int) -> None:
        """Select a user in the private chat combo (for reply hotkey)."""
        if user_id in self._private_user_ids:
            self.private_chat.setChecked(True)
            self.private_user.setCurrentIndex(self._private_user_ids.index(user_id))
            self.update_chat_target()

    # ------------------------------------------------------------------
    # Message display
    # ------------------------------------------------------------------

    def append_message(self, sender: str, text: str, ts: str = "", private: bool = False,
                       own: bool = False, kind: str = "channel") -> None:
        """Append a formatted chat message with timestamp to the log."""
        text = expand_emoji_shortcodes(_strip_markdown(text))
        ts_str = ts or time.strftime("%H:%M:%S")
        prefix = "[Privat] " if private else ""
        line = f"[{ts_str}] {prefix}{sender}: {text}"

        # Color by message kind
        if own:
            color = "#27ae60"
        elif private:
            color = "#2980b9"
        elif kind == "system":
            color = "#888888"
        else:
            color = "#000000"

        self.chat_log.append(
            f'<span style="color:{color}">{html.escape(line)}</span>'
        )

        # Persist to chat history if available
        try:
            key = getattr(self.window, "_current_server_key", "")
            if key and hasattr(self.window, "_chat_history"):
                self.window._chat_history.append(key, line, kind)
        except Exception:
            pass

    def append_system_message(self, text: str, ts: str = "") -> None:
        ts_str = ts or time.strftime("%H:%M:%S")
        line = f"[{ts_str}] *** {text}"
        self.chat_log.append(
            f'<span style="color:#888888">{html.escape(line)}</span>'
        )

    # alias used by some callers
    def append_chat(self, text: str, kind: str = "chat", speak: bool = True) -> None:
        """wx-compat alias: appends a pre-formatted line to the chat log."""
        if getattr(self.window.settings_store.settings, "chat_relative_timestamps", False):
            ts_str = "gerade eben"
        elif getattr(self.window.settings_store.settings, "chat_show_timestamps", True):
            ts_str = time.strftime("%H:%M")
        else:
            ts_str = time.strftime("%H:%M")
        color_map = {
            "system": "#888888",
            "broadcast": "#8B4513",
            "private": "#2980b9",
            "own": "#27ae60",
        }
        color = color_map.get(kind, "#000000")
        line = f"[{ts_str}] {text}"
        self.chat_log.append(
            f'<span style="color:{color}">{html.escape(line)}</span>'
        )
        if speak:
            try:
                self.window.tts.speak(text, kind=kind)
            except Exception:
                pass
        try:
            key = getattr(self.window, "_current_server_key", "")
            if key and hasattr(self.window, "_chat_history"):
                self.window._chat_history.append(key, line, kind)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Improve text
    # ------------------------------------------------------------------

    def _on_improve_text(self) -> None:
        """Verbessert den aktuellen Eingabetext via KI."""
        text = self.chat_input.text()
        if not text.strip():
            return
        self.improve_btn.setEnabled(False)

        def _worker():
            try:
                result = self.window._ai_reply.improve_text(text)
            except Exception:
                result = None

            def _done():
                self.improve_btn.setEnabled(True)
                if result:
                    self.chat_input.setText(result)
                    self.chat_input.setCursorPosition(len(result))
                    try:
                        self.window._sr_announce("Text verbessert")
                    except Exception:
                        pass

            QTimer.singleShot(0, _done)

        threading.Thread(target=_worker, daemon=True).start()

    # ------------------------------------------------------------------
    # Send
    # ------------------------------------------------------------------

    def _on_send(self) -> None:
        text = self.chat_input.text().strip()
        if not text:
            return
        text = expand_emoji_shortcodes(text)
        is_private = self.private_chat.isChecked()
        target_id = 0
        if is_private and self._private_user_ids:
            idx = self.private_user.currentIndex()
            if 0 <= idx < len(self._private_user_ids):
                target_id = self._private_user_ids[idx]
        self.window.send_chat_message(text, private=is_private, target_id=target_id)
        self.chat_input.clear()

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def _on_search(self) -> None:
        """Search the chat history and highlight matches."""
        query = self.search_input.text().strip().lower()
        self._search_positions = []
        if not query:
            self.search_count.setText("0 Treffer")
            return
        text = self.chat_log.toPlainText()
        lines = text.split("\n")
        hits = []
        pos = 0
        for line in lines:
            if query in line.lower():
                hits.append((line, pos))
            pos += len(line) + 1
        total = len(hits)
        shown = min(total, 100)
        self._search_positions = [p for _, p in hits[:shown]]
        label = f"{total} Treffer" if total <= shown else f"{total} Treffer (zeige {shown})"
        self.search_count.setText(label)
        # Scroll to first hit
        if self._search_positions:
            cursor = self.chat_log.textCursor()
            cursor.setPosition(self._search_positions[0])
            self.chat_log.setTextCursor(cursor)
            self.chat_log.ensureCursorVisible()
        try:
            self.window._sr_announce(label)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # History buttons
    # ------------------------------------------------------------------

    def _on_export_history(self) -> None:
        content = self.chat_log.toPlainText()
        if not content.strip():
            self.window.set_status("Kein Chat-Verlauf zum Exportieren")
            return
        default_name = f"chatverlauf_{time.strftime('%Y%m%d_%H%M%S')}.txt"
        path, _ = QFileDialog.getSaveFileName(
            self, _("Chatverlauf exportieren"), default_name,
            "Textdateien (*.txt);;Alle Dateien (*.*)"
        )
        if path:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(content)
                self.window.set_status(f"Verlauf exportiert: {path}")
            except Exception as exc:
                self.window.set_status(f"Export fehlgeschlagen: {exc}")

    def _on_export_html(self) -> None:
        content = self.chat_log.toPlainText()
        if not content.strip():
            self.window.set_status("Kein Chat-Verlauf zum Exportieren")
            return
        server_name = getattr(self.window, "_current_server_key", "TeamTalk")
        default_name = f"chatverlauf_{time.strftime('%Y%m%d_%H%M%S')}.html"
        path, _ = QFileDialog.getSaveFileName(
            self, _("Chatverlauf als HTML"), default_name,
            "HTML-Dateien (*.html);;Alle Dateien (*.*)"
        )
        if path:
            try:
                lines = content.splitlines()
                rows = []
                for line in lines:
                    if not line.strip():
                        continue
                    escaped = html.escape(line)
                    if line.startswith("Ich:") or line.startswith("An "):
                        css_class = "own"
                    elif "[Privat]" in line[:30]:
                        css_class = "private"
                    elif line.startswith("***") or line.startswith("["):
                        css_class = "system"
                    else:
                        css_class = "chat"
                    rows.append(f'<div class="{css_class}">{escaped}</div>')
                html_content = (
                    f'<!DOCTYPE html><html lang="de"><head>'
                    f'<meta charset="UTF-8"><title>Chat-Verlauf – {html.escape(server_name)}</title>'
                    f'<style>'
                    f'body{{font-family:monospace;max-width:900px;margin:1em auto;background:#fafafa;padding:0 1em}}'
                    f'.chat{{color:#222;margin:.15em 0}}.own{{color:#27ae60}}.private{{color:#2980b9}}'
                    f'.system{{color:#888;font-style:italic}}'
                    f'h1{{font-size:1.1em;color:#555}}'
                    f'</style></head><body>'
                    f'<h1>Chat-Verlauf – {html.escape(server_name)} – '
                    f'Exportiert: {time.strftime("%Y-%m-%d %H:%M:%S")}</h1>'
                    + "".join(rows)
                    + "</body></html>"
                )
                with open(path, "w", encoding="utf-8") as f:
                    f.write(html_content)
                self.window.set_status(f"HTML exportiert: {path}")
            except Exception as exc:
                self.window.set_status(f"HTML-Export fehlgeschlagen: {exc}")

    def _on_clear_history(self) -> None:
        reply = QMessageBox.question(
            self, _("Verlauf leeren"),
            _("Chat-Verlauf wirklich leeren?\n\nDies löscht den angezeigten Verlauf."),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.chat_log.clear()
            # Also clear persisted history if available
            try:
                key = getattr(self.window, "_current_server_key", "")
                if key and hasattr(self.window, "_chat_history"):
                    self.window._chat_history.clear(key)
            except Exception:
                pass
            self.window.set_status("Chat-Verlauf geleert")

    def _on_quote(self) -> None:
        selected = self.chat_log.textCursor().selectedText().strip()
        if not selected:
            # Fallback: last non-empty line
            full = self.chat_log.toPlainText()
            lines = [l for l in full.splitlines() if l.strip()]
            selected = lines[-1] if lines else ""
        if not selected:
            self.window.set_status("Kein Text zum Zitieren")
            return
        quoted = "\n".join(f"> {line}" for line in selected.splitlines())
        current = self.chat_input.text()
        if current:
            self.chat_input.setText(quoted + "\n" + current)
        else:
            self.chat_input.setText(quoted + "\n")
        self.chat_input.setFocus()

    def _on_copy(self) -> None:
        """Copy selected text from the chat log to clipboard."""
        cursor = self.chat_log.textCursor()
        if cursor.hasSelection():
            from PySide6.QtWidgets import QApplication
            QApplication.clipboard().setText(cursor.selectedText())
        else:
            self.window.set_status("Kein Text ausgewählt")

    def _on_save_msg(self) -> None:
        selected = self.chat_log.textCursor().selectedText().strip()
        if not selected:
            full = self.chat_log.toPlainText()
            lines = [l for l in full.splitlines() if l.strip()]
            selected = lines[-1] if lines else ""
        if not selected:
            self.window.set_status("Kein Text zum Speichern")
            return
        try:
            self.window.save_message(selected)
        except Exception as exc:
            self.window.set_status(f"Speichern fehlgeschlagen: {exc}")
