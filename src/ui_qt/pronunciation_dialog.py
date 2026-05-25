"""Aussprache-Wörterbuch-Dialog (Qt) – v7.0.

Verwaltet Ausspracheregeln: Suchen/Ersetzen mit optionalem Regex,
Wortgrenzen, Groß-/Kleinschreibung und Aktivieren/Deaktivieren pro Regel.
Enthält eine Live-Vorschau zum Testen der Regeln.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QListWidget, QLabel, QLineEdit, QCheckBox, QPushButton,
    QMessageBox, QFileDialog,
)
from PySide6.QtCore import Qt

from pronunciation import PronunciationManager
from i18n import _

if TYPE_CHECKING:
    from app_qt import MainWindow


class PronunciationDialog(QDialog):
    """Aussprache-Wörterbuch-Editor."""

    def __init__(self, parent: "MainWindow") -> None:
        super().__init__(parent)
        self._window = parent
        self._s = parent.settings_store.settings
        self._rules: List[Dict] = list(self._s.pronunciation_rules or [])

        self.setWindowTitle(_("Aussprache-Wörterbuch"))
        self.resize(740, 580)
        self._build_ui()
        self._rebuild_list()

    # ------------------------------------------------------------------
    # UI-Aufbau
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)

        # ── Regelliste ─────────────────────────────────────────────────
        outer.addWidget(QLabel(_("Regeln:")))
        self._lw = QListWidget()
        self._lw.setAccessibleName(_("Regelliste"))
        self._lw.currentRowChanged.connect(self._on_select)
        outer.addWidget(self._lw, 1)

        list_btns = QHBoxLayout()
        self._btn_new = QPushButton(_("&Neue Regel"))
        self._btn_new.clicked.connect(self._on_new)
        self._btn_up  = QPushButton(_("Nach &oben"))
        self._btn_up.clicked.connect(self._on_move_up)
        self._btn_dn  = QPushButton(_("Nach &unten"))
        self._btn_dn.clicked.connect(self._on_move_down)
        self._btn_del = QPushButton(_("&Entfernen"))
        self._btn_del.clicked.connect(self._on_delete)
        self._btn_imp = QPushButton(_("&Importieren…"))
        self._btn_imp.clicked.connect(self._on_import)
        self._btn_exp = QPushButton(_("E&xportieren…"))
        self._btn_exp.clicked.connect(self._on_export)
        for btn in (self._btn_new, self._btn_up, self._btn_dn,
                    self._btn_del, self._btn_imp, self._btn_exp):
            list_btns.addWidget(btn)
        list_btns.addStretch()
        outer.addLayout(list_btns)

        # ── Regel-Editor ───────────────────────────────────────────────
        editor_box = QGroupBox(_("Regel bearbeiten"))
        editor = QFormLayout(editor_box)

        self._find = QLineEdit()
        self._find.setAccessibleName(_("Suchen"))
        self._find.setPlaceholderText(_("Wort, Abkürzung oder Regex"))
        editor.addRow(_("Suchen:"), self._find)

        self._replace = QLineEdit()
        self._replace.setAccessibleName(_("Ersetzen durch"))
        self._replace.setPlaceholderText(_("Aussprache-Alternative"))
        editor.addRow(_("Ersetzen durch:"), self._replace)

        flags_row = QHBoxLayout()
        self._cb_whole = QCheckBox(_("Ganzes Wort"))
        self._cb_whole.setAccessibleName(_("Ganzes Wort"))
        self._cb_regex = QCheckBox(_("Regulärer Ausdruck (Regex)"))
        self._cb_regex.setAccessibleName(_("Regex"))
        self._cb_regex.stateChanged.connect(self._on_regex_toggle)
        self._cb_case  = QCheckBox(_("Groß-/Kleinschreibung beachten"))
        self._cb_case.setAccessibleName(_("Groß-Kleinschreibung"))
        self._cb_en    = QCheckBox(_("Aktiviert"))
        self._cb_en.setAccessibleName(_("Aktiviert"))
        self._cb_en.setChecked(True)
        for cb in (self._cb_whole, self._cb_regex, self._cb_case, self._cb_en):
            flags_row.addWidget(cb)
        flags_row.addStretch()
        editor.addRow("", flags_row)

        self._btn_save = QPushButton(_("Regel &speichern"))
        self._btn_save.clicked.connect(self._on_save_rule)
        editor.addRow("", self._btn_save)

        outer.addWidget(editor_box)

        # ── Live-Test ──────────────────────────────────────────────────
        test_box = QGroupBox(_("Live-Test"))
        test_layout = QHBoxLayout(test_box)
        self._test_in = QLineEdit()
        self._test_in.setAccessibleName(_("Testtext eingeben"))
        self._test_in.setPlaceholderText(_("Testtext eingeben…"))
        self._test_in.textChanged.connect(self._on_test_change)
        test_layout.addWidget(self._test_in, 1)
        self._test_out = QLabel("")
        self._test_out.setAccessibleName(_("Testergebnis"))
        self._test_out.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        test_layout.addWidget(self._test_out, 1)
        outer.addWidget(test_box)

        # ── Schließen ──────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        close_btn = QPushButton(_("&Schließen"))
        close_btn.clicked.connect(self._on_close)
        btn_row.addWidget(close_btn)
        outer.addLayout(btn_row)

    # ------------------------------------------------------------------
    # Listenverwaltung
    # ------------------------------------------------------------------

    def _rule_label(self, r: Dict) -> str:
        find    = r.get("find", "")
        replace = r.get("replace", "")
        tags    = []
        if r.get("use_regex"):              tags.append(_("Regex"))
        if r.get("whole_word"):             tags.append(_("Wortgrenze"))
        if not r.get("enabled", True):     tags.append(_("deaktiviert"))
        tag_str = f" [{', '.join(tags)}]" if tags else ""
        return f"{find} → {replace}{tag_str}"

    def _rebuild_list(self, keep_sel: int = -1) -> None:
        self._lw.clear()
        for r in self._rules:
            self._lw.addItem(self._rule_label(r))
        if keep_sel >= 0 and self._lw.count() > 0:
            self._lw.setCurrentRow(min(keep_sel, self._lw.count() - 1))

    def _on_select(self, idx: int) -> None:
        if not (0 <= idx < len(self._rules)):
            return
        r = self._rules[idx]
        self._find.setText(r.get("find", ""))
        self._replace.setText(r.get("replace", ""))
        self._cb_whole.setChecked(bool(r.get("whole_word", False)))
        self._cb_regex.setChecked(bool(r.get("use_regex", False)))
        self._cb_case.setChecked(bool(r.get("case_sensitive", False)))
        self._cb_en.setChecked(bool(r.get("enabled", True)))
        self._cb_whole.setEnabled(not r.get("use_regex", False))

    def _on_new(self) -> None:
        self._rules.append({"find": "", "replace": "", "whole_word": False,
                             "use_regex": False, "case_sensitive": False, "enabled": True})
        self._rebuild_list(len(self._rules) - 1)
        self._find.clear()
        self._replace.clear()
        self._cb_whole.setChecked(False)
        self._cb_regex.setChecked(False)
        self._cb_case.setChecked(False)
        self._cb_en.setChecked(True)
        self._find.setFocus()

    def _on_move_up(self) -> None:
        idx = self._lw.currentRow()
        if idx <= 0:
            return
        self._rules[idx - 1], self._rules[idx] = self._rules[idx], self._rules[idx - 1]
        self._rebuild_list(idx - 1)
        self._persist()

    def _on_move_down(self) -> None:
        idx = self._lw.currentRow()
        if idx < 0 or idx >= len(self._rules) - 1:
            return
        self._rules[idx], self._rules[idx + 1] = self._rules[idx + 1], self._rules[idx]
        self._rebuild_list(idx + 1)
        self._persist()

    def _on_delete(self) -> None:
        idx = self._lw.currentRow()
        if idx < 0:
            return
        self._rules.pop(idx)
        self._rebuild_list(max(0, idx - 1))
        self._persist()

    def _on_regex_toggle(self) -> None:
        self._cb_whole.setEnabled(not self._cb_regex.isChecked())

    def _on_save_rule(self) -> None:
        idx  = self._lw.currentRow()
        find = self._find.text().strip()
        if not find:
            QMessageBox.information(self, _("Hinweis"), _("Bitte einen Suchbegriff eingeben."))
            return
        rule = {
            "find":           find,
            "replace":        self._replace.text(),
            "whole_word":     self._cb_whole.isChecked() and not self._cb_regex.isChecked(),
            "use_regex":      self._cb_regex.isChecked(),
            "case_sensitive": self._cb_case.isChecked(),
            "enabled":        self._cb_en.isChecked(),
        }
        if idx < 0:
            self._rules.append(rule)
            idx = len(self._rules) - 1
        else:
            self._rules[idx] = rule
        self._rebuild_list(idx)
        self._persist()
        self._window.set_status(f"Regel '{find}' gespeichert")
        self._on_test_change()

    # ------------------------------------------------------------------
    # Import / Export
    # ------------------------------------------------------------------

    def _on_import(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self, _("Ausspracheregeln importieren"), "",
            "JSON (*.json);;Alle Dateien (*)"
        )
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            if isinstance(data, list):
                self._rules = data
            elif isinstance(data, dict):
                from pronunciation import _migrate_dict
                self._rules = _migrate_dict(data)
            self._rebuild_list()
            self._persist()
            self._window.set_status(f"{len(self._rules)} Regeln importiert")
        except Exception as exc:
            QMessageBox.critical(self, _("Fehler"), f"Import fehlgeschlagen:\n{exc}")

    def _on_export(self) -> None:
        path, _filter = QFileDialog.getSaveFileName(
            self, _("Ausspracheregeln exportieren"), "pronunciation.json",
            "JSON (*.json);;Alle Dateien (*)"
        )
        if not path:
            return
        try:
            Path(path).write_text(
                json.dumps(self._rules, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            self._window.set_status(_("Regeln exportiert"))
        except Exception as exc:
            QMessageBox.critical(self, _("Fehler"), f"Export fehlgeschlagen:\n{exc}")

    # ------------------------------------------------------------------
    # Live-Test
    # ------------------------------------------------------------------

    def _on_test_change(self) -> None:
        text = self._test_in.text()
        if not text:
            self._test_out.setText("")
            return
        pm = PronunciationManager(list(self._rules))
        self._test_out.setText(pm.apply(text))

    # ------------------------------------------------------------------
    # Speichern & Schließen
    # ------------------------------------------------------------------

    def _persist(self) -> None:
        self._s.pronunciation_rules = list(self._rules)
        self._window._pronunciation.update_rules(list(self._rules))
        self._window.settings_store.save()

    def _on_close(self) -> None:
        self._persist()
        self.accept()
