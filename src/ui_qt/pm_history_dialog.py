"""Privatnachrichten-Verlauf-Browser (Qt)."""
from __future__ import annotations
from typing import TYPE_CHECKING, List
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QTextEdit,
    QLineEdit, QLabel, QPushButton, QSplitter, QWidget, QDialogButtonBox,
    QFileDialog, QMessageBox,
)
from PySide6.QtCore import Qt
if TYPE_CHECKING:
    from app_qt import MainWindow
    from chat_history import ChatHistoryManager


class PMHistoryDialog(QDialog):
    """Durchsucht gespeicherte Privatnachrichten-Verläufe."""

    def __init__(self, window: "MainWindow", chat_history: "ChatHistoryManager", server_key: str) -> None:
        super().__init__(window)
        self.setWindowTitle("Privatnachrichten-Verlauf")
        self.setAccessibleName("Privatnachrichten-Verlauf")
        self.resize(700, 500)
        self._history = chat_history
        self._server_key = server_key
        self._partners: List[str] = []
        self._build_ui()
        self._load_partners()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        # Filter
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Suche:"))
        self._filter = QLineEdit()
        self._filter.setAccessibleName("Partner suchen")
        self._filter.setPlaceholderText("Name eingeben …")
        self._filter.textChanged.connect(self._on_filter)
        filter_row.addWidget(self._filter, 1)
        root.addLayout(filter_row)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: partner list
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(QLabel("Gesprächspartner"))
        self._partner_lw = QListWidget()
        self._partner_lw.setAccessibleName("Gesprächspartner-Liste")
        self._partner_lw.currentRowChanged.connect(self._on_partner_selected)
        ll.addWidget(self._partner_lw)

        # Right: messages
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        self._partner_label = QLabel("Kein Gesprächspartner gewählt")
        rl.addWidget(self._partner_label)
        self._msg_view = QTextEdit()
        self._msg_view.setReadOnly(True)
        self._msg_view.setAccessibleName("Nachrichten")
        rl.addWidget(self._msg_view, 1)

        btn_row = QHBoxLayout()
        self._export_btn = QPushButton("&Exportieren")
        self._export_btn.setAccessibleName("Verlauf exportieren")
        self._export_btn.setEnabled(False)
        self._export_btn.clicked.connect(self._on_export)
        btn_row.addWidget(self._export_btn)
        btn_row.addStretch()
        rl.addLayout(btn_row)

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([200, 500])
        root.addWidget(splitter, 1)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(self.reject)
        root.addWidget(bb)

    def _load_partners(self) -> None:
        try:
            partners = self._history.list_private_partners(self._server_key)
        except Exception:
            partners = []
        self._partners = sorted(partners)
        self._partner_lw.clear()
        for p in self._partners:
            self._partner_lw.addItem(p)
        if self._partners:
            self._partner_lw.setCurrentRow(0)

    def _on_filter(self, text: str) -> None:
        query = text.strip().lower()
        try:
            all_partners = self._history.list_private_partners(self._server_key)
        except Exception:
            all_partners = []
        filtered = sorted(p for p in all_partners if not query or query in p.lower())
        self._partners = filtered
        self._partner_lw.clear()
        for p in filtered:
            self._partner_lw.addItem(p)
        self._msg_view.clear()
        self._partner_label.setText("Kein Gesprächspartner gewählt")
        self._export_btn.setEnabled(False)

    def _on_partner_selected(self, row: int) -> None:
        if row < 0 or row >= len(self._partners):
            return
        partner = self._partners[row]
        self._partner_label.setText(f"Verlauf mit {partner}")
        try:
            entries = self._history.load_private(self._server_key, partner)
        except Exception:
            entries = []
        self._msg_view.clear()
        for e in entries:
            ts = e.get("ts", "")
            text = e.get("text", "")
            line = f"[{ts}] {text}" if ts else text
            self._msg_view.append(line)
        self._export_btn.setEnabled(bool(entries))
        try:
            if hasattr(self.parent(), "_sr_announce"):
                self.parent()._sr_announce(f"{len(entries)} Nachrichten mit {partner}")
        except Exception:
            pass

    def _on_export(self) -> None:
        row = self._partner_lw.currentRow()
        if row < 0 or row >= len(self._partners):
            return
        partner = self._partners[row]
        path, _ = QFileDialog.getSaveFileName(
            self, "Verlauf exportieren", f"privat_{partner}.txt",
            "Textdateien (*.txt)"
        )
        if path:
            try:
                entries = self._history.load_private(self._server_key, partner)
                lines = []
                for e in entries:
                    ts = e.get("ts", "")
                    text = e.get("text", "")
                    lines.append(f"[{ts}] {text}" if ts else text)
                with open(path, "w", encoding="utf-8") as f:
                    f.write("\n".join(lines))
                try:
                    if hasattr(self.parent(), "_sr_announce"):
                        self.parent()._sr_announce(f"Exportiert: {path}")
                except Exception:
                    pass
            except Exception as ex:
                QMessageBox.critical(self, "Fehler", str(ex))
