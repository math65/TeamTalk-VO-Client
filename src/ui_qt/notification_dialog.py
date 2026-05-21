"""Benachrichtigungs-Regeln Dialog (Qt)."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGroupBox,
    QLabel, QListWidget, QPushButton, QComboBox,
    QLineEdit, QFormLayout, QDialogButtonBox,
    QMessageBox,
)
from PySide6.QtCore import Qt

from notification_manager import EVENTS, SCOPES, ACTIONS, rule_label


class NotificationRulesDialog(QDialog):
    """
    Dialog zum Bearbeiten von Benachrichtigungs-Regeln (Qt-Version).
    """

    def __init__(self, parent, rules: list) -> None:
        super().__init__(parent)
        self.setWindowTitle("Benachrichtigungs-Regeln")
        self.resize(660, 520)
        self._rules = list(rules)
        self._editing_idx: int | None = None

        layout = QVBoxLayout(self)

        # ── Regelliste ──────────────────────────────────────────────────────
        layout.addWidget(QLabel(
            "Regeln (spezifischere Regeln überschreiben allgemeinere):"
        ))
        self._list = QListWidget()
        self._list.setAccessibleName("Regelliste")
        layout.addWidget(self._list, 1)

        btn_row = QHBoxLayout()
        self._add_btn = QPushButton("Hinzufügen")
        self._add_btn.setAccessibleName("Neue Regel")
        self._del_btn = QPushButton("Löschen")
        self._del_btn.setAccessibleName("Regel löschen")
        self._up_btn = QPushButton("Nach oben")
        self._up_btn.setAccessibleName("Regel nach oben")
        self._down_btn = QPushButton("Nach unten")
        self._down_btn.setAccessibleName("Regel nach unten")
        for b in (self._add_btn, self._del_btn, self._up_btn, self._down_btn):
            btn_row.addWidget(b)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # ── Regel-Editor ────────────────────────────────────────────────────
        editor_box = QGroupBox("Regel bearbeiten")
        editor_layout = QVBoxLayout(editor_box)

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)

        self._event_cb = QComboBox()
        self._event_cb.setAccessibleName("Ereignis")
        self._event_cb.addItem("(Alle Ereignisse)", "")
        for key, lbl in EVENTS:
            self._event_cb.addItem(lbl, key)
        form.addRow("Ereignis:", self._event_cb)

        self._scope_cb = QComboBox()
        self._scope_cb.setAccessibleName("Geltungsbereich")
        for key, lbl in SCOPES:
            self._scope_cb.addItem(lbl, key)
        form.addRow("Geltungsbereich:", self._scope_cb)

        self._value_le = QLineEdit()
        self._value_le.setAccessibleName("Wert (Server / Kanal / Benutzer)")
        self._value_le.setPlaceholderText("Bei 'Global' leer lassen")
        form.addRow("Wert:", self._value_le)

        self._action_cb = QComboBox()
        self._action_cb.setAccessibleName("Aktion")
        for key, lbl in ACTIONS:
            self._action_cb.addItem(lbl, key)
        form.addRow("Aktion:", self._action_cb)

        editor_layout.addLayout(form)

        self._save_btn = QPushButton("Regel speichern")
        self._save_btn.setAccessibleName("Regel speichern")
        editor_layout.addWidget(self._save_btn)

        layout.addWidget(editor_box)

        # ── OK / Abbrechen ──────────────────────────────────────────────────
        dlg_btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        dlg_btns.accepted.connect(self.accept)
        dlg_btns.rejected.connect(self.reject)
        layout.addWidget(dlg_btns)

        self._refresh_list()
        self._update_editor_enable()

        # Verbindungen
        self._list.currentRowChanged.connect(self._on_select)
        self._scope_cb.currentIndexChanged.connect(self._update_editor_enable)
        self._add_btn.clicked.connect(self._on_add)
        self._del_btn.clicked.connect(self._on_delete)
        self._up_btn.clicked.connect(self._on_move_up)
        self._down_btn.clicked.connect(self._on_move_down)
        self._save_btn.clicked.connect(self._on_save_rule)

    # ── Hilfsmethoden ────────────────────────────────────────────────────────

    def _refresh_list(self) -> None:
        current = self._list.currentRow()
        self._list.clear()
        for rule in self._rules:
            self._list.addItem(rule_label(rule))
        if self._rules:
            self._list.setCurrentRow(min(current, len(self._rules) - 1))

    def _update_editor_enable(self) -> None:
        sc_key = self._scope_cb.currentData() or "global"
        self._value_le.setEnabled(sc_key != "global")

    def _get_current_rule(self) -> dict:
        ev_key = self._event_cb.currentData() or ""
        sc_key = self._scope_cb.currentData() or "global"
        value = self._value_le.text().strip() if sc_key != "global" else ""
        ac_key = self._action_cb.currentData() or "both"
        return {"event": ev_key, "scope": sc_key, "value": value, "action": ac_key}

    def _load_rule_into_editor(self, rule: dict) -> None:
        ev = rule.get("event", "")
        for i in range(self._event_cb.count()):
            if self._event_cb.itemData(i) == ev:
                self._event_cb.setCurrentIndex(i)
                break
        sc = rule.get("scope", "global")
        for i in range(self._scope_cb.count()):
            if self._scope_cb.itemData(i) == sc:
                self._scope_cb.setCurrentIndex(i)
                break
        self._value_le.setText(rule.get("value", ""))
        ac = rule.get("action", "both")
        for i in range(self._action_cb.count()):
            if self._action_cb.itemData(i) == ac:
                self._action_cb.setCurrentIndex(i)
                break
        self._update_editor_enable()

    # ── Ereignishandler ───────────────────────────────────────────────────────

    def _on_select(self, idx: int) -> None:
        if idx < 0 or idx >= len(self._rules):
            return
        self._editing_idx = idx
        self._load_rule_into_editor(self._rules[idx])

    def _on_add(self) -> None:
        self._editing_idx = -1
        self._event_cb.setCurrentIndex(0)
        self._scope_cb.setCurrentIndex(0)
        self._value_le.clear()
        self._action_cb.setCurrentIndex(0)
        self._update_editor_enable()
        self._event_cb.setFocus()

    def _on_delete(self) -> None:
        idx = self._list.currentRow()
        if idx < 0 or idx >= len(self._rules):
            return
        self._rules.pop(idx)
        self._editing_idx = None
        self._refresh_list()

    def _on_move_up(self) -> None:
        idx = self._list.currentRow()
        if idx <= 0 or idx >= len(self._rules):
            return
        self._rules[idx - 1], self._rules[idx] = self._rules[idx], self._rules[idx - 1]
        self._refresh_list()
        self._list.setCurrentRow(idx - 1)
        self._editing_idx = idx - 1

    def _on_move_down(self) -> None:
        idx = self._list.currentRow()
        if idx < 0 or idx >= len(self._rules) - 1:
            return
        self._rules[idx + 1], self._rules[idx] = self._rules[idx], self._rules[idx + 1]
        self._refresh_list()
        self._list.setCurrentRow(idx + 1)
        self._editing_idx = idx + 1

    def _on_save_rule(self) -> None:
        rule = self._get_current_rule()
        if self._editing_idx == -1:
            self._rules.append(rule)
            self._refresh_list()
            self._list.setCurrentRow(len(self._rules) - 1)
            self._editing_idx = len(self._rules) - 1
        elif self._editing_idx is not None and 0 <= self._editing_idx < len(self._rules):
            self._rules[self._editing_idx] = rule
            self._refresh_list()
            self._list.setCurrentRow(self._editing_idx)
        else:
            QMessageBox.information(self, "Kein Ziel",
                                    "Bitte erst 'Hinzufügen' drücken oder eine Regel auswählen.")

    def get_rules(self) -> list:
        return list(self._rules)
