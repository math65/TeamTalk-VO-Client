from __future__ import annotations

from typing import List, TYPE_CHECKING

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel,
    QListWidget, QPushButton, QProgressBar, QFileDialog,
)

if TYPE_CHECKING:
    from app_qt import MainWindow


class FilesTab(QWidget):
    """Tab 6: Dateien."""

    def __init__(self, parent: QWidget, window: "MainWindow") -> None:
        super().__init__(parent)
        self.window = window
        self._file_ids: List[int] = []
        self._active_transfer_id = 0

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        list_group = QGroupBox("Dateien im aktuellen Kanal")
        list_layout = QVBoxLayout(list_group)
        header = QLabel("Dateiname, Größe, Hochgeladen von, Datum")
        list_layout.addWidget(header)
        self.file_list = QListWidget()
        self.file_list.setObjectName("Dateiliste")
        list_layout.addWidget(self.file_list, 1)
        root.addWidget(list_group, 1)

        action_group = QGroupBox("Aktionen")
        action_layout = QVBoxLayout(action_group)
        btn_row = QHBoxLayout()
        self.upload_btn = QPushButton("&Hochladen")
        self.upload_btn.clicked.connect(self.on_upload)
        self.download_btn = QPushButton("He&runterladen")
        self.download_btn.clicked.connect(self.on_download)
        self.delete_btn = QPushButton("&Löschen")
        self.delete_btn.clicked.connect(self.on_delete)
        self.refresh_btn = QPushButton("&Aktualisieren")
        self.refresh_btn.clicked.connect(self.on_refresh)
        self.history_btn = QPushButton("Ver&lauf")
        self.history_btn.clicked.connect(self.on_history)
        for btn in (self.upload_btn, self.download_btn, self.delete_btn,
                    self.refresh_btn, self.history_btn):
            btn_row.addWidget(btn)
        btn_row.addStretch()
        action_layout.addLayout(btn_row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        self.progress_label = QLabel("")
        action_layout.addWidget(self.progress_label)
        action_layout.addWidget(self.progress_bar)
        root.addWidget(action_group)

    def update_file_list(self, files, tt_str) -> None:
        self.file_list.clear()
        self._file_ids = []
        for f in files:
            try:
                name = tt_str(f.szFileName)
                size_kb = int(f.nFileSize) // 1024
                owner = tt_str(f.szUsername)
                self.file_list.addItem(f"{name}, {size_kb} KB, {owner}")
                self._file_ids.append(int(f.nFileID))
            except Exception:
                pass

    def update_transfer_progress(self, name: str, pct: int) -> None:
        self.progress_label.setText(f"Übertragung: {name} ({pct}%)")
        self.progress_bar.setValue(pct)
        self.progress_bar.setVisible(True)
        if pct >= 100:
            self.progress_bar.setVisible(False)
            self.progress_label.setText("")

    def on_upload(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Datei hochladen", "", "Alle Dateien (*.*)")
        if path:
            self.window.upload_file(path)

    def on_download(self) -> None:
        row = self.file_list.currentRow()
        if 0 <= row < len(self._file_ids):
            save_path, _ = QFileDialog.getSaveFileName(
                self, "Datei speichern", self.file_list.currentItem().text().split(",")[0].strip()
            )
            if save_path:
                self.window.download_file(self._file_ids[row], save_path)

    def on_delete(self) -> None:
        row = self.file_list.currentRow()
        if 0 <= row < len(self._file_ids):
            self.window.delete_file(self._file_ids[row])

    def on_refresh(self) -> None:
        self.window.refresh_files()

    def on_history(self) -> None:
        self.window.show_file_history()
