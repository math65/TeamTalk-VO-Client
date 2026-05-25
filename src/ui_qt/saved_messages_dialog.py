"""Gespeicherte-Nachrichten-Dialog (PySide6 / Windows + Linux)."""
from __future__ import annotations

from typing import TYPE_CHECKING, List

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

if TYPE_CHECKING:
    from saved_messages import SavedMessageManager


class SavedMessagesDialog(QDialog):
    """Zeigt gespeicherte Chat-Nachrichten mit Such-, Kopier- und Löschfunktionen."""

    def __init__(self, parent, manager: "SavedMessageManager") -> None:
        super().__init__(parent)
        self._manager = manager
        self._window = parent
        # Parallele Index-Liste: mappt Listwidget-Position → Original-Index in manager
        self._filtered_indices: List[int] = []

        self.setWindowTitle("Gespeicherte Nachrichten")
        self.resize(680, 520)

        # Cmd+W / Ctrl+W schließt den Dialog
        close_shortcut = QShortcut(QKeySequence("Ctrl+W"), self)
        close_shortcut.activated.connect(self.reject)

        root = QVBoxLayout(self)

        # Suchfeld
        search_row = QHBoxLayout()
        search_lbl = QLabel("Suche:")
        self._search = QLineEdit()
        self._search.setPlaceholderText("Nach Nachrichtentext filtern …")
        self._search.setAccessibleName("Suchfeld")
        search_row.addWidget(search_lbl)
        search_row.addWidget(self._search, 1)
        root.addLayout(search_row)

        # Zähler-Label
        self._count_lbl = QLabel("")
        self._count_lbl.setAccessibleName("Anzahl Nachrichten")
        root.addWidget(self._count_lbl)

        # Nachrichten-Liste
        self._lw = QListWidget()
        self._lw.setAccessibleName("Gespeicherte Nachrichten")
        root.addWidget(self._lw, 1)

        # Volltext-Anzeige
        self._detail = QTextEdit()
        self._detail.setReadOnly(True)
        self._detail.setAccessibleName("Vollständiger Nachrichtentext")
        self._detail.setMaximumHeight(90)
        root.addWidget(self._detail)

        # Buttons
        btn_row = QHBoxLayout()
        self._copy_btn  = QPushButton("Kopieren")
        self._copy_btn.setAccessibleName("Nachricht kopieren")
        self._del_btn   = QPushButton("Löschen")
        self._del_btn.setAccessibleName("Ausgewählte Nachricht löschen")
        self._clear_btn = QPushButton("Alle löschen")
        self._clear_btn.setAccessibleName("Alle gespeicherten Nachrichten löschen")
        btn_row.addWidget(self._copy_btn)
        btn_row.addWidget(self._del_btn)
        btn_row.addWidget(self._clear_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

        # Schließen-Button
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(self.reject)
        root.addWidget(bb)

        # Initialbefüllung
        self._fill("")

        # Events
        self._search.textChanged.connect(self._on_search)
        self._lw.currentRowChanged.connect(self._on_select)
        self._copy_btn.clicked.connect(self._on_copy)
        self._del_btn.clicked.connect(self._on_delete)
        self._clear_btn.clicked.connect(self._on_clear)

    # ------------------------------------------------------------------
    # Hilfsmethoden

    def _entry_label(self, m) -> str:
        srv = f" [{m.server}]" if m.server else ""
        preview = m.text[:100] + ("…" if len(m.text) > 100 else "")
        return f"{m.time_str}{srv}: {preview}"

    def _fill(self, query: str) -> None:
        """Befüllt die Liste entsprechend dem Suchbegriff."""
        query = query.strip().lower()
        all_items = self._manager.items()

        self._lw.clear()
        self._filtered_indices = []
        self._detail.clear()

        for orig_idx, m in enumerate(all_items):
            label = self._entry_label(m)
            if query and query not in label.lower() and query not in m.text.lower():
                continue
            self._lw.addItem(label)
            self._filtered_indices.append(orig_idx)

        count = self._lw.count()
        total = len(all_items)
        if query:
            self._count_lbl.setText(f"{count} von {total} Nachricht(en)")
        else:
            self._count_lbl.setText(f"{total} Nachricht(en)")

        self._update_buttons()

    def _update_buttons(self) -> None:
        has_items = self._lw.count() > 0
        has_sel   = self._lw.currentRow() >= 0
        self._copy_btn.setEnabled(has_sel)
        self._del_btn.setEnabled(has_sel)
        self._clear_btn.setEnabled(has_items)

    def _orig_index(self, lw_row: int) -> int:
        """Gibt den Original-Index im Manager zurück."""
        if 0 <= lw_row < len(self._filtered_indices):
            return self._filtered_indices[lw_row]
        return -1

    def _sr_announce(self, text: str) -> None:
        """NVDA-Ansage (Windows), falls verfügbar."""
        try:
            self._window._sr_announce(text)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Event-Handler

    def _on_search(self, text: str) -> None:
        self._fill(text)

    def _on_select(self, row: int) -> None:
        if row < 0:
            self._detail.clear()
            self._update_buttons()
            return
        orig = self._orig_index(row)
        items = self._manager.items()
        if 0 <= orig < len(items):
            self._detail.setPlainText(items[orig].text)
        self._update_buttons()

    def _on_copy(self) -> None:
        row = self._lw.currentRow()
        if row < 0:
            return
        orig = self._orig_index(row)
        items = self._manager.items()
        if 0 <= orig < len(items):
            from PySide6.QtGui import QGuiApplication
            QGuiApplication.clipboard().setText(items[orig].text)
        try:
            self._window.set_status("Nachricht in Zwischenablage kopiert")
        except Exception:
            pass
        self._sr_announce("Nachricht kopiert")

    def _on_delete(self) -> None:
        row = self._lw.currentRow()
        if row < 0:
            return
        orig = self._orig_index(row)
        self._manager.remove(orig)
        query = self._search.text()
        self._fill(query)
        count = self._lw.count()
        if count > 0:
            new_row = min(row, count - 1)
            self._lw.setCurrentRow(new_row)
            new_orig = self._orig_index(new_row)
            items = self._manager.items()
            if 0 <= new_orig < len(items):
                self._detail.setPlainText(items[new_orig].text)
        self._update_buttons()
        self._sr_announce("Nachricht gelöscht")

    def _on_clear(self) -> None:
        if self._lw.count() == 0:
            return
        result = QMessageBox.question(
            self,
            "Alle löschen",
            "Alle gespeicherten Nachrichten wirklich löschen?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if result != QMessageBox.StandardButton.Yes:
            return
        self._manager.clear()
        self._fill(self._search.text())
        self._sr_announce("Alle gespeicherten Nachrichten gelöscht")
