"""update_dialog (Qt) – Update-Manager-Dialog für Windows/Linux."""
from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import Qt, Signal, QObject
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget,
    QTextEdit, QProgressBar, QPushButton, QSplitter, QWidget,
)

import update_manager as um
from i18n import _


class _Signals(QObject):
    releases_loaded = Signal(list)
    progress = Signal(int, str)
    download_done = Signal(str)
    error = Signal(str)


class UpdateManagerDialog(QDialog):
    def __init__(self, parent, current_version: str):
        super().__init__(parent)
        self.setWindowTitle(_("Update-Manager"))
        self.resize(660, 500)
        self._current = current_version.lstrip("v")
        self._releases: List[um.Release] = []
        self._selected: Optional[um.Release] = None
        self._download_path: Optional[str] = None
        self._sig = _Signals()
        self._build_ui()
        self._connect()
        self._load_releases()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        layout = QVBoxLayout(self)

        self._header = QLabel(f"<b>Installierte Version: v{self._current}</b>")
        layout.addWidget(self._header)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Linke Seite: Versionsliste
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(QLabel(_("Verfügbare Versionen:")))
        self._list = QListWidget()
        self._list.setAccessibleName(_("Versionsliste"))
        ll.addWidget(self._list)
        splitter.addWidget(left)

        # Rechte Seite: Changelog
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(QLabel(_("Changelog:")))
        self._changelog = QTextEdit()
        self._changelog.setReadOnly(True)
        self._changelog.setAccessibleName(_("Changelog"))
        rl.addWidget(self._changelog)
        splitter.addWidget(right)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter, 1)

        # Fortschrittsbalken
        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setAccessibleName(_("Download-Fortschritt"))
        self._progress.hide()
        layout.addWidget(self._progress)

        # Status
        self._status = QLabel(_("Versionen werden geladen…"))
        layout.addWidget(self._status)

        # Buttons
        btn_row = QHBoxLayout()
        self._btn_refresh = QPushButton(_("Aktualisieren"))
        self._btn_download = QPushButton(_("Herunterladen"))
        self._btn_open = QPushButton(_("Im Explorer anzeigen"))
        self._btn_close = QPushButton(_("Schließen"))
        self._btn_download.setEnabled(False)
        self._btn_open.hide()
        btn_row.addWidget(self._btn_refresh)
        btn_row.addWidget(self._btn_download)
        btn_row.addWidget(self._btn_open)
        btn_row.addStretch()
        btn_row.addWidget(self._btn_close)
        layout.addLayout(btn_row)

    def _connect(self):
        self._list.currentRowChanged.connect(self._on_select)
        self._btn_refresh.clicked.connect(self._on_refresh)
        self._btn_download.clicked.connect(self._on_download)
        self._btn_open.clicked.connect(self._on_open)
        self._btn_close.clicked.connect(self.reject)
        self._sig.releases_loaded.connect(self._on_releases_loaded)
        self._sig.progress.connect(self._on_progress)
        self._sig.download_done.connect(self._on_download_done)
        self._sig.error.connect(self._on_download_error)

    # ------------------------------------------------------------------
    # Releases laden
    # ------------------------------------------------------------------

    def _load_releases(self):
        self._set_status(_("Versionen werden geladen…"))
        self._btn_refresh.setEnabled(False)

        def worker():
            try:
                releases = um.fetch_releases(limit=50)
                self._sig.releases_loaded.emit(releases)
            except Exception as exc:
                self._sig.error.emit(f"Fehler beim Laden: {exc}")

        threading.Thread(target=worker, daemon=True).start()

    def _on_releases_loaded(self, releases: List[um.Release]):
        self._releases = releases
        self._list.clear()
        current_v = self._current.lstrip("v")
        for r in releases:
            tag = r.tag.lstrip("v")
            marker = _(" ★ NEU") if _version_gt(tag, current_v) else (_(" ✓ aktuell") if tag == current_v else "")
            has_asset = r.platform_asset is not None
            asset_info = f"  [{um.format_size(r.platform_asset.size)}]" if has_asset else _("  [kein Windows-Asset]")
            self._list.addItem(f"{r.tag}  {r.date}{marker}{asset_info}")
        self._btn_refresh.setEnabled(True)
        if releases:
            self._set_status(f"{len(releases)} Versionen geladen.")
            self._list.setCurrentRow(0)
        else:
            self._set_status(_("Keine Versionen gefunden."))

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def _on_select(self, idx: int):
        if idx < 0 or idx >= len(self._releases):
            return
        self._selected = self._releases[idx]
        self._changelog.setPlainText(self._selected.body or _("(kein Changelog)"))
        has_asset = self._selected.platform_asset is not None
        self._btn_download.setEnabled(has_asset)
        if not has_asset:
            self._set_status(_("Kein Windows-Asset für diese Version verfügbar."))
        else:
            self._set_status(f"Bereit zum Herunterladen: {self._selected.tag}")

    def _on_refresh(self):
        self._download_path = None
        self._btn_open.hide()
        self._load_releases()

    def _on_download(self):
        if not self._selected or not self._selected.platform_asset:
            return
        asset = self._selected.platform_asset
        dest = str(Path.home() / "Downloads")
        self._btn_download.setEnabled(False)
        self._btn_refresh.setEnabled(False)
        self._progress.setValue(0)
        self._progress.show()
        self._set_status(f"Lade herunter: {asset.name}…")

        def worker():
            try:
                def on_progress(done, total):
                    if total > 0:
                        pct = min(100, int(done * 100 / total))
                        self._sig.progress.emit(pct, f"{um.format_size(done)} / {um.format_size(total)}")
                    else:
                        self._sig.progress.emit(-1, f"{um.format_size(done)} heruntergeladen…")

                path = um.download_asset(asset, dest, progress_cb=on_progress)
                self._sig.download_done.emit(path)
            except Exception as exc:
                self._sig.error.emit(str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _on_progress(self, pct: int, text: str):
        if pct >= 0:
            self._progress.setValue(pct)
        self._set_status(text)

    def _on_download_done(self, path: str):
        from PySide6.QtWidgets import QMessageBox
        self._download_path = path
        self._progress.setValue(100)
        self._btn_download.setEnabled(True)
        self._btn_refresh.setEnabled(True)
        self._btn_open.show()
        self._set_status(f"Download abgeschlossen: {os.path.basename(path)}")
        if path.endswith(".zip"):
            reply = QMessageBox.question(
                self, _("Download fertig"),
                f"Download abgeschlossen:\n{path}\n\nIm Explorer anzeigen?",
            )
            if reply == QMessageBox.StandardButton.Yes:
                um.reveal_in_finder(path)

    def _on_download_error(self, msg: str):
        self._progress.hide()
        self._btn_download.setEnabled(True)
        self._btn_refresh.setEnabled(True)
        self._set_status(f"Fehler: {msg}")

    def _on_open(self):
        if self._download_path:
            um.reveal_in_finder(self._download_path)

    def _set_status(self, text: str):
        self._status.setText(text)


def _version_gt(a: str, b: str) -> bool:
    def parts(v: str):
        return tuple(int(x) for x in v.lstrip("v").split(".") if x.isdigit())
    try:
        return parts(a) > parts(b)
    except Exception:
        return False
