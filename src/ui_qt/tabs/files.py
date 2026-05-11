from __future__ import annotations

import os
from datetime import datetime
from typing import List, TYPE_CHECKING

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel,
    QListWidget, QPushButton, QProgressBar, QFileDialog,
    QDialog, QTextEdit, QMessageBox,
)
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices

if TYPE_CHECKING:
    from app_qt import MainWindow


class FilesTab(QWidget):
    """Tab 6: Dateien — Dateiliste, Hoch-/Herunterladen, Löschen, Verlauf."""

    def __init__(self, parent: QWidget, window: "MainWindow") -> None:
        super().__init__(parent)
        self.window = window
        self._file_ids: List[int]   = []
        self._file_names: List[str] = []
        self._active_transfer_id    = 0
        self._active_transfer_name  = ""
        self._history: List[dict]   = []   # local transfer log

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        # ------------------------------------------------------------------ #
        # File list
        # ------------------------------------------------------------------ #
        list_group = QGroupBox("Dateien im aktuellen Kanal")
        list_layout = QVBoxLayout(list_group)
        list_layout.addWidget(QLabel("Dateiname (Größe) [Kanal]"))
        self.file_list = QListWidget()
        self.file_list.setObjectName("Dateiliste")
        list_layout.addWidget(self.file_list, 1)
        root.addWidget(list_group, 1)

        # ------------------------------------------------------------------ #
        # Action buttons
        # ------------------------------------------------------------------ #
        action_group = QGroupBox("Aktionen")
        action_layout = QVBoxLayout(action_group)

        btn_row1 = QHBoxLayout()
        self.upload_btn       = QPushButton("&Hochladen")
        self.download_btn     = QPushButton("He&runterladen")
        self.delete_btn       = QPushButton("&Löschen")
        self.refresh_btn      = QPushButton("&Aktualisieren")
        self.upload_btn.clicked.connect(self.on_upload)
        self.download_btn.clicked.connect(self.on_download)
        self.delete_btn.clicked.connect(self.on_delete)
        self.refresh_btn.clicked.connect(self.on_refresh)
        for btn in (self.upload_btn, self.download_btn, self.delete_btn, self.refresh_btn):
            btn_row1.addWidget(btn)
        btn_row1.addStretch()
        action_layout.addLayout(btn_row1)

        btn_row2 = QHBoxLayout()
        self.download_all_btn = QPushButton("Alle he&runterladen")
        self.open_folder_btn  = QPushButton("Ordner &öffnen")
        self.history_btn      = QPushButton("Ver&lauf anzeigen...")
        self.download_all_btn.clicked.connect(self.on_download_all)
        self.open_folder_btn.clicked.connect(self.on_open_folder)
        self.history_btn.clicked.connect(self.on_history)
        for btn in (self.download_all_btn, self.open_folder_btn, self.history_btn):
            btn_row2.addWidget(btn)
        btn_row2.addStretch()
        action_layout.addLayout(btn_row2)

        # Progress
        self.progress_label = QLabel("")
        self.progress_bar   = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        action_layout.addWidget(self.progress_label)
        action_layout.addWidget(self.progress_bar)

        root.addWidget(action_group)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _set_status(self, text: str) -> None:
        try:
            self.window.set_status(text)
        except Exception:
            pass

    @staticmethod
    def _format_size(size_bytes: int) -> str:
        if size_bytes < 1024:
            return f"{size_bytes} B"
        if size_bytes < 1024 * 1024:
            return f"{size_bytes // 1024} KB"
        return f"{size_bytes // (1024 * 1024)} MB"

    def _get_download_dir(self) -> str:
        try:
            path = getattr(self.window, "_download_dir", None)
            if path and os.path.isdir(path):
                return path
        except Exception:
            pass
        return os.path.expanduser("~")

    # ------------------------------------------------------------------
    # Update from SDK / MainWindow
    # ------------------------------------------------------------------

    def update_file_list(self, files, tt_str) -> None:
        """Called by MainWindow with the current channel's file list."""
        self.file_list.clear()
        self._file_ids   = []
        self._file_names = []
        try:
            ch_id = int(self.window.client.get_my_channel_id() or 0)
            try:
                ch = self.window.client.get_channel(ch_id)
                ch_name = tt_str(ch.szName) if ch else str(ch_id)
            except Exception:
                ch_name = str(ch_id)
        except Exception:
            ch_name = ""
        for f in files:
            try:
                name      = tt_str(f.szFileName)
                size_str  = self._format_size(int(f.nFileSize))
                label     = f"{name} ({size_str})" + (f" [{ch_name}]" if ch_name else "")
                self.file_list.addItem(label)
                self._file_ids.append(int(f.nFileID))
                self._file_names.append(name)
            except Exception:
                pass

    def update_transfer_progress(self, name: str, pct: int) -> None:
        self.progress_label.setText(f"Übertragung: {name} ({pct}%)")
        self.progress_bar.setValue(pct)
        self.progress_bar.setVisible(True)
        if pct >= 100:
            self.progress_bar.setVisible(False)
            self.progress_label.setText("")

    # ------------------------------------------------------------------
    # History tracking (called externally when transfers complete)
    # ------------------------------------------------------------------

    def record_history(self, filename: str, size_bytes: int, direction: str,
                       channel_name: str = "", completed: bool = True) -> None:
        ts = datetime.now().strftime("%H:%M")
        self._history.append({
            "ts": ts,
            "filename": filename,
            "size": size_bytes,
            "direction": direction,
            "channel": channel_name,
            "completed": completed,
        })

    # ------------------------------------------------------------------
    # Button handlers
    # ------------------------------------------------------------------

    def on_refresh(self) -> None:
        self.window.refresh_files()
        self._set_status("Dateiliste aktualisiert")

    def on_upload(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Datei hochladen", "", "Alle Dateien (*.*)")
        if path:
            name = os.path.basename(path)
            try:
                size = os.path.getsize(path)
            except Exception:
                size = 0
            self.window.upload_file(path)
            self.record_history(name, size, "upload", completed=False)
            self._set_status(f"Upload gestartet: {name}")

    def on_download(self) -> None:
        row = self.file_list.currentRow()
        if row < 0 or row >= len(self._file_ids):
            self._set_status("Bitte eine Datei auswählen")
            return
        file_id   = self._file_ids[row]
        default   = self._file_names[row] if row < len(self._file_names) else ""
        save_path, _ = QFileDialog.getSaveFileName(
            self, "Datei speichern unter",
            os.path.join(self._get_download_dir(), default),
        )
        if save_path:
            self.window.download_file(file_id, save_path)
            self.record_history(default, 0, "download", completed=False)
            self._set_status(f"Download gestartet: {default}")

    def on_delete(self) -> None:
        row = self.file_list.currentRow()
        if row < 0 or row >= len(self._file_ids):
            self._set_status("Bitte eine Datei auswählen")
            return
        name = self._file_names[row] if row < len(self._file_names) else "?"
        reply = QMessageBox.question(
            self, "Datei löschen",
            f"Datei '{name}' wirklich löschen?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.window.delete_file(self._file_ids[row])
            self._set_status(f"Datei gelöscht: {name}")

    def on_download_all(self) -> None:
        if not self._file_ids:
            self._set_status("Keine Dateien zum Herunterladen")
            return
        save_dir = QFileDialog.getExistingDirectory(
            self, "Zielordner für alle Dateien wählen", self._get_download_dir()
        )
        if not save_dir:
            return
        for i, file_id in enumerate(self._file_ids):
            name = self._file_names[i] if i < len(self._file_names) else f"file_{file_id}"
            save_path = os.path.join(save_dir, name)
            try:
                self.window.download_file(file_id, save_path)
                self.record_history(name, 0, "download", completed=False)
            except Exception:
                pass
        self._set_status(f"{len(self._file_ids)} Dateien werden heruntergeladen")

    def on_open_folder(self) -> None:
        folder = self._get_download_dir()
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def on_history(self) -> None:
        dlg = _FileHistoryDialog(self, self._history)
        dlg.exec()

    # keep old method name for external callers (menu etc.)
    def _on_download(self) -> None:
        self.on_download()


class _FileHistoryDialog(QDialog):
    """Zeigt den lokalen Dateiübertragungsverlauf."""

    def __init__(self, parent: QWidget, history: list) -> None:
        super().__init__(parent)
        self.setWindowTitle("Dateiübertragungsverlauf")
        self.resize(700, 450)

        layout = QVBoxLayout(self)

        self._text = QTextEdit()
        self._text.setReadOnly(True)
        self._text.setObjectName("Dateiübertragungsverlauf")

        if history:
            lines = []
            downloads = sum(1 for e in history if e.get("direction") == "download")
            uploads   = sum(1 for e in history if e.get("direction") == "upload")
            lines.append(f"Downloads: {downloads}  |  Uploads: {uploads}")
            lines.append("")
            for entry in history:
                ts        = entry.get("ts", "??:??")
                direction = "↓" if entry.get("direction") == "download" else "↑"
                name      = entry.get("filename", "?")
                size      = entry.get("size", 0)
                ch        = entry.get("channel", "")
                state     = "fertig" if entry.get("completed") else "offen"
                size_str  = FilesTab._format_size(size) if size else "?"
                ch_str    = f" [{ch}]" if ch else ""
                lines.append(f"[{ts}] {direction} {name} ({size_str}){ch_str} — {state}")
            self._text.setPlainText("\n".join(lines))
        else:
            self._text.setPlainText("Noch kein Dateiübertragungsverlauf vorhanden.")

        layout.addWidget(self._text, 1)

        btn_row = QHBoxLayout()
        close_btn = QPushButton("&Schließen")
        close_btn.clicked.connect(self.accept)
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)
