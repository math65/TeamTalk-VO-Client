"""Aufnahmen-Browser — scans recording directories for .wav/.mp3 files."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import List

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QDialogButtonBox, QMessageBox,
)
from PySide6.QtCore import Qt

from i18n import _


def _collect_recordings(settings_store) -> List[Path]:
    from platform_paths import app_data_dir
    dirs = []

    rec_dir = getattr(settings_store.settings, "rec_directory", "") or ""
    if rec_dir:
        dirs.append(Path(rec_dir))

    dirs.append(app_data_dir() / "Aufnahmen")
    dirs.append(Path.home() / "Downloads")

    seen = set()
    files = []
    for d in dirs:
        if not d.is_dir():
            continue
        for p in d.iterdir():
            if p.suffix.lower() in (".wav", ".mp3") and p not in seen:
                seen.add(p)
                files.append(p)

    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files[:200]


class RecordingsBrowserDialog(QDialog):
    def __init__(self, parent, settings_store) -> None:
        super().__init__(parent)
        self.setWindowTitle(_("Aufnahmen-Browser"))
        self.resize(680, 480)
        self._settings_store = settings_store
        self._files: List[Path] = []

        layout = QVBoxLayout(self)
        self._count_label = QLabel()
        layout.addWidget(self._count_label)

        self._list = QListWidget()
        self._list.setAccessibleName(_("Aufnahmen"))
        layout.addWidget(self._list, 1)

        btn_row = QHBoxLayout()
        self._play_btn = QPushButton(_("&Abspielen"))
        self._play_btn.setAccessibleName(_("Aufnahme abspielen"))
        self._play_btn.clicked.connect(self._on_play)
        btn_row.addWidget(self._play_btn)

        self._folder_btn = QPushButton(_("&Ordner öffnen"))
        self._folder_btn.setAccessibleName(_("Ordner der Aufnahme öffnen"))
        self._folder_btn.clicked.connect(self._on_open_folder)
        btn_row.addWidget(self._folder_btn)

        self._delete_btn = QPushButton(_("&Löschen"))
        self._delete_btn.setAccessibleName(_("Aufnahme löschen"))
        self._delete_btn.clicked.connect(self._on_delete)
        btn_row.addWidget(self._delete_btn)

        btn_row.addStretch()

        self._refresh_btn = QPushButton(_("A&ktualisieren"))
        self._refresh_btn.clicked.connect(self._refresh)
        btn_row.addWidget(self._refresh_btn)

        layout.addLayout(btn_row)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(self.reject)
        layout.addWidget(bb)

        self._refresh()

    def _refresh(self) -> None:
        self._files = _collect_recordings(self._settings_store)
        self._list.clear()
        for f in self._files:
            try:
                size_kb = f.stat().st_size // 1024
                import time
                mtime = time.strftime("%d.%m.%Y %H:%M", time.localtime(f.stat().st_mtime))
                label = f"{f.name}  ({size_kb} KB, {mtime})"
            except Exception:
                label = f.name
            item = QListWidgetItem(label)
            item.setToolTip(str(f))
            self._list.addItem(item)
        count = len(self._files)
        self._count_label.setText(f"{count} Aufnahme(n) gefunden")
        if self._files:
            self._list.setCurrentRow(0)

    def _selected_path(self) -> Path | None:
        row = self._list.currentRow()
        if 0 <= row < len(self._files):
            return self._files[row]
        return None

    def _on_play(self) -> None:
        path = self._selected_path()
        if not path:
            return
        try:
            if sys.platform == "win32":
                os.startfile(str(path))
            elif sys.platform == "darwin":
                subprocess.Popen(["afplay", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as exc:
            QMessageBox.warning(self, _("Fehler"), f"Abspielen fehlgeschlagen: {exc}")

    def _on_open_folder(self) -> None:
        path = self._selected_path()
        if not path:
            return
        folder = str(path.parent)
        try:
            if sys.platform == "win32":
                subprocess.Popen(["explorer", "/select,", str(path)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", folder])
            else:
                subprocess.Popen(["xdg-open", folder])
        except Exception as exc:
            QMessageBox.warning(self, _("Fehler"), f"Ordner öffnen fehlgeschlagen: {exc}")

    def _on_delete(self) -> None:
        path = self._selected_path()
        if not path:
            return
        answer = QMessageBox.question(
            self, _("Löschen bestätigen"),
            f'Aufnahme "{path.name}" wirklich löschen?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            path.unlink()
            self._refresh()
        except Exception as exc:
            QMessageBox.warning(self, _("Fehler"), f"Löschen fehlgeschlagen: {exc}")
