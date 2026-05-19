"""Makro-Editor-Dialog (Qt) – v7.0.

Drei Tabs:
  1. Makros   – Erstellen, Bearbeiten, Löschen; Aktionsliste mit Typ-Auswahl
  2. Trigger  – Ereignisbasierte Regeln (user_join, chat_message, …)
  3. Zeitplan – Zeitgesteuerte Makros (HH:MM täglich)
"""
from __future__ import annotations

import copy
from pathlib import Path
from typing import TYPE_CHECKING, List, Dict

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QWidget, QTabWidget, QListWidget, QLabel, QLineEdit,
    QComboBox, QCheckBox, QPushButton, QMessageBox, QFileDialog,
    QSplitter,
)
from PySide6.QtCore import Qt

from macro_manager import ACTION_TYPES, TRIGGER_EVENTS

if TYPE_CHECKING:
    from app_qt import MainWindow


_ACTION_KEYS   = [k for k, _ in ACTION_TYPES]
_ACTION_LABELS = [v for _, v in ACTION_TYPES]
_EVENT_KEYS    = [k for k, _ in TRIGGER_EVENTS]
_EVENT_LABELS  = [v for _, v in TRIGGER_EVENTS]

_ACTIONS_WITH_VALUE = {k for k, _ in ACTION_TYPES} - {"ptt_on", "ptt_off", "mute_toggle"}


class MacroDialog(QDialog):
    """Vollständiger Makro-Editor mit drei Tabs."""

    def __init__(self, parent: "MainWindow", initial_tab: int = 0) -> None:
        super().__init__(parent)
        self._window = parent
        s = parent.settings_store.settings
        self._macros: List[Dict]    = list(s.macros or [])
        self._triggers: List[Dict]  = list(s.macro_triggers or [])
        self._scheduled: List[Dict] = list(s.scheduled_macros or [])

        self.setWindowTitle("Makro-Editor")
        self.resize(860, 600)

        root = QVBoxLayout(self)

        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_macros_tab(),   "Makros")
        self._tabs.addTab(self._build_triggers_tab(), "Trigger")
        self._tabs.addTab(self._build_schedule_tab(), "Zeitplan")
        self._tabs.setCurrentIndex(initial_tab)
        root.addWidget(self._tabs, 1)

        close_btn = QPushButton("&Schließen")
        close_btn.clicked.connect(self._on_close)
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        root.addLayout(btn_row)

    # ------------------------------------------------------------------
    # Tab 1: Makros
    # ------------------------------------------------------------------

    def _build_macros_tab(self) -> QWidget:
        widget = QWidget()
        splitter = QSplitter(Qt.Orientation.Horizontal, widget)

        # ── Left: macro list ──────────────────────────────────────────
        left_w = QWidget()
        left = QVBoxLayout(left_w)
        left.setContentsMargins(0, 0, 0, 0)
        left.addWidget(QLabel("Makros:"))
        self._macro_lw = QListWidget()
        self._macro_lw.setAccessibleName("Makroliste")
        for m in self._macros:
            self._macro_lw.addItem(m.get("name", "?"))
        self._macro_lw.currentRowChanged.connect(self._on_macro_select)
        left.addWidget(self._macro_lw, 1)

        m_btns = QHBoxLayout()
        self._m_new = QPushButton("&Neu")
        self._m_new.clicked.connect(self._on_macro_new)
        self._m_dup = QPushButton("D&uplizieren")
        self._m_dup.clicked.connect(self._on_macro_dup)
        self._m_del = QPushButton("&Löschen")
        self._m_del.clicked.connect(self._on_macro_del)
        for b in (self._m_new, self._m_dup, self._m_del):
            m_btns.addWidget(b)
        left.addLayout(m_btns)
        splitter.addWidget(left_w)

        # ── Right: detail editor ──────────────────────────────────────
        right_w = QWidget()
        right = QVBoxLayout(right_w)
        right.setContentsMargins(0, 0, 0, 0)

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Name:"))
        self._m_name = QLineEdit()
        self._m_name.setAccessibleName("Makro-Name")
        name_row.addWidget(self._m_name, 1)
        right.addLayout(name_row)

        right.addWidget(QLabel("Aktionen:"))
        self._act_lw = QListWidget()
        self._act_lw.setAccessibleName("Aktionsliste")
        right.addWidget(self._act_lw, 1)

        a_btns = QHBoxLayout()
        self._a_up  = QPushButton("Nach &oben")
        self._a_up.clicked.connect(self._on_action_up)
        self._a_dn  = QPushButton("Nach &unten")
        self._a_dn.clicked.connect(self._on_action_down)
        self._a_del = QPushButton("A&ktion entfernen")
        self._a_del.clicked.connect(self._on_action_del)
        for b in (self._a_up, self._a_dn, self._a_del):
            a_btns.addWidget(b)
        right.addLayout(a_btns)

        right.addWidget(QLabel("Neue Aktion:"))
        aform = QHBoxLayout()
        self._a_type = QComboBox()
        self._a_type.setAccessibleName("Aktionstyp")
        self._a_type.addItems(_ACTION_LABELS)
        self._a_type.currentIndexChanged.connect(self._on_atype_change)
        aform.addWidget(self._a_type, 1)
        self._a_val = QLineEdit()
        self._a_val.setAccessibleName("Aktionswert")
        self._a_val.setPlaceholderText("Wert (z.B. Text, Kanalname, Sekunden)")
        aform.addWidget(self._a_val, 1)
        self._a_browse = QPushButton("…")
        self._a_browse.setAccessibleName("Datei wählen")
        self._a_browse.setToolTip("Datei auswählen (nur für Sound)")
        self._a_browse.setEnabled(False)
        self._a_browse.clicked.connect(self._on_browse_sound)
        aform.addWidget(self._a_browse)
        right.addLayout(aform)

        right.addWidget(QLabel(
            "Template-Variablen: {user}  {channel}  {message}  {time}\n"
            'Beispiel: "Hallo {user}, willkommen in {channel}!"'
        ))

        self._a_add  = QPushButton("Aktion &hinzufügen")
        self._a_add.clicked.connect(self._on_action_add)
        right.addWidget(self._a_add)

        self._m_save = QPushButton("Makro &speichern")
        self._m_save.clicked.connect(self._on_macro_save)
        right.addWidget(self._m_save)

        splitter.addWidget(right_w)
        splitter.setSizes([240, 580])

        outer = QVBoxLayout(widget)
        outer.addWidget(splitter)
        return widget

    # ------------------------------------------------------------------
    # Tab 2: Trigger
    # ------------------------------------------------------------------

    def _build_triggers_tab(self) -> QWidget:
        widget = QWidget()
        splitter = QSplitter(Qt.Orientation.Horizontal, widget)

        # ── Left: trigger list ────────────────────────────────────────
        left_w = QWidget()
        left = QVBoxLayout(left_w)
        left.setContentsMargins(0, 0, 0, 0)
        left.addWidget(QLabel("Trigger-Regeln:"))
        self._tr_lw = QListWidget()
        self._tr_lw.setAccessibleName("Triggerliste")
        self._tr_lw.currentRowChanged.connect(self._on_trigger_select)
        self._rebuild_trigger_list()
        left.addWidget(self._tr_lw, 1)

        t_btns = QHBoxLayout()
        self._t_new = QPushButton("&Neu")
        self._t_new.clicked.connect(self._on_trigger_new)
        self._t_del = QPushButton("&Entfernen")
        self._t_del.clicked.connect(self._on_trigger_del)
        t_btns.addWidget(self._t_new)
        t_btns.addWidget(self._t_del)
        left.addLayout(t_btns)
        splitter.addWidget(left_w)

        # ── Right: trigger editor ─────────────────────────────────────
        right_w = QWidget()
        right = QVBoxLayout(right_w)
        right.setContentsMargins(0, 0, 0, 0)

        form = QFormLayout()
        self._t_event = QComboBox()
        self._t_event.setAccessibleName("Trigger-Ereignis")
        self._t_event.addItems(_EVENT_LABELS)
        form.addRow("Ereignis:", self._t_event)

        self._t_filter = QLineEdit()
        self._t_filter.setAccessibleName("Trigger-Filter")
        self._t_filter.setPlaceholderText("Leer = alle; Benutzername, Kanalname oder Nachrichteninhalt")
        form.addRow("Filter:", self._t_filter)

        self._t_regex = QCheckBox("Filter als Regulären Ausdruck (Regex) verwenden")
        self._t_regex.setAccessibleName("Regex-Filter")
        form.addRow("", self._t_regex)

        self._t_macro = QComboBox()
        self._t_macro.setAccessibleName("Trigger-Makro")
        self._t_macro.addItems(self._macro_name_list())
        form.addRow("Makro:", self._t_macro)
        right.addLayout(form)

        right.addWidget(QLabel(
            "Hinweis: Bei 'Chat-Nachricht' prüft der Filter den Nachrichteninhalt.\n"
            "Bei anderen Ereignissen prüft der Filter den Benutzer- oder Kanalnamen."
        ))
        right.addStretch()

        self._t_save = QPushButton("Regel &speichern")
        self._t_save.clicked.connect(self._on_trigger_save)
        right.addWidget(self._t_save)

        splitter.addWidget(right_w)
        splitter.setSizes([280, 540])

        outer = QVBoxLayout(widget)
        outer.addWidget(splitter)
        return widget

    # ------------------------------------------------------------------
    # Tab 3: Zeitplan
    # ------------------------------------------------------------------

    def _build_schedule_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        layout.addWidget(QLabel("Geplante Makros werden täglich zur angegebenen Uhrzeit ausgeführt."))

        self._sc_lw = QListWidget()
        self._sc_lw.setAccessibleName("Zeitplan-Liste")
        self._rebuild_schedule_list()
        layout.addWidget(self._sc_lw, 1)

        form = QFormLayout()
        self._sc_time = QLineEdit("08:00")
        self._sc_time.setAccessibleName("Geplante Zeit")
        self._sc_time.setMaximumWidth(80)
        form.addRow("Zeit (HH:MM):", self._sc_time)

        self._sc_macro = QComboBox()
        self._sc_macro.setAccessibleName("Geplantes Makro")
        self._sc_macro.addItems(self._macro_name_list())
        form.addRow("Makro:", self._sc_macro)
        layout.addLayout(form)

        sc_btns = QHBoxLayout()
        self._sc_add = QPushButton("&Hinzufügen")
        self._sc_add.clicked.connect(self._on_schedule_add)
        self._sc_del = QPushButton("&Entfernen")
        self._sc_del.clicked.connect(self._on_schedule_del)
        sc_btns.addWidget(self._sc_add)
        sc_btns.addWidget(self._sc_del)
        sc_btns.addStretch()
        layout.addLayout(sc_btns)

        return widget

    # ------------------------------------------------------------------
    # Makro-Tab-Logik
    # ------------------------------------------------------------------

    def _on_macro_select(self, idx: int) -> None:
        if not (0 <= idx < len(self._macros)):
            return
        m = self._macros[idx]
        self._m_name.setText(m.get("name", ""))
        self._act_lw.clear()
        for a in m.get("actions", []):
            self._act_lw.addItem(self._action_label(a))

    def _action_label(self, a: Dict) -> str:
        label = dict(ACTION_TYPES).get(a.get("type", ""), a.get("type", ""))
        val   = a.get("value", "")
        return f"{label}: {val}" if val else label

    def _on_macro_new(self) -> None:
        name = f"Makro {len(self._macros) + 1}"
        self._macros.append({"name": name, "hotkey": 0, "actions": []})
        self._macro_lw.addItem(name)
        new_idx = len(self._macros) - 1
        self._macro_lw.setCurrentRow(new_idx)
        self._refresh_macro_choices()
        self._m_name.setFocus()

    def _on_macro_dup(self) -> None:
        idx = self._macro_lw.currentRow()
        if idx < 0:
            return
        dup = copy.deepcopy(self._macros[idx])
        dup["name"] = dup.get("name", "Makro") + " (Kopie)"
        dup["hotkey"] = 0
        self._macros.append(dup)
        self._macro_lw.addItem(dup["name"])
        new_idx = len(self._macros) - 1
        self._macro_lw.setCurrentRow(new_idx)
        self._refresh_macro_choices()

    def _on_macro_del(self) -> None:
        idx = self._macro_lw.currentRow()
        if idx < 0:
            return
        name = self._macros[idx].get("name", "?")
        if QMessageBox.question(self, "Löschen", f"Makro '{name}' wirklich löschen?",
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                                ) != QMessageBox.StandardButton.Yes:
            return
        self._macros.pop(idx)
        self._macro_lw.takeItem(idx)
        self._act_lw.clear()
        self._m_name.clear()
        self._refresh_macro_choices()
        self._persist()

    def _on_atype_change(self, sel: int) -> None:
        key = _ACTION_KEYS[sel]
        has_val = key in _ACTIONS_WITH_VALUE
        self._a_val.setEnabled(has_val)
        self._a_browse.setEnabled(key == "play_sound")

    def _on_browse_sound(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Sounddatei wählen", "",
            "Audio-Dateien (*.wav *.mp3 *.ogg);;Alle Dateien (*)"
        )
        if path:
            self._a_val.setText(path)

    def _on_action_add(self) -> None:
        idx = self._macro_lw.currentRow()
        if idx < 0:
            QMessageBox.information(self, "Hinweis", "Bitte erst ein Makro auswählen.")
            return
        sel = self._a_type.currentIndex()
        key = _ACTION_KEYS[sel]
        val = self._a_val.text().strip() if key in _ACTIONS_WITH_VALUE else ""
        action: Dict = {"type": key}
        if val:
            action["value"] = val
        self._macros[idx].setdefault("actions", []).append(action)
        self._act_lw.addItem(self._action_label(action))
        self._a_val.clear()

    def _on_action_up(self) -> None:
        midx = self._macro_lw.currentRow()
        aidx = self._act_lw.currentRow()
        if midx < 0 or aidx <= 0:
            return
        actions = self._macros[midx].get("actions", [])
        actions[aidx - 1], actions[aidx] = actions[aidx], actions[aidx - 1]
        self._reload_action_list(midx, aidx - 1)

    def _on_action_down(self) -> None:
        midx = self._macro_lw.currentRow()
        aidx = self._act_lw.currentRow()
        if midx < 0 or aidx < 0:
            return
        actions = self._macros[midx].get("actions", [])
        if aidx >= len(actions) - 1:
            return
        actions[aidx], actions[aidx + 1] = actions[aidx + 1], actions[aidx]
        self._reload_action_list(midx, aidx + 1)

    def _on_action_del(self) -> None:
        midx = self._macro_lw.currentRow()
        aidx = self._act_lw.currentRow()
        if midx < 0 or aidx < 0:
            return
        self._macros[midx].get("actions", []).pop(aidx)
        self._reload_action_list(midx, max(0, aidx - 1))

    def _reload_action_list(self, midx: int, select: int = -1) -> None:
        self._act_lw.clear()
        for a in self._macros[midx].get("actions", []):
            self._act_lw.addItem(self._action_label(a))
        if select >= 0 and self._act_lw.count() > 0:
            self._act_lw.setCurrentRow(min(select, self._act_lw.count() - 1))

    def _on_macro_save(self) -> None:
        idx = self._macro_lw.currentRow()
        if idx < 0:
            return
        name = self._m_name.text().strip()
        if not name:
            QMessageBox.information(self, "Hinweis", "Bitte einen Namen eingeben.")
            return
        self._macros[idx]["name"] = name
        self._macro_lw.item(idx).setText(name)
        self._refresh_macro_choices()
        self._persist()
        self._window.set_status(f"Makro '{name}' gespeichert")

    # ------------------------------------------------------------------
    # Trigger-Tab-Logik
    # ------------------------------------------------------------------

    def _rebuild_trigger_list(self) -> None:
        self._tr_lw.clear()
        ev_map = dict(TRIGGER_EVENTS)
        for rule in self._triggers:
            ev   = ev_map.get(rule.get("event", ""), rule.get("event", "?"))
            filt = rule.get("filter", "")
            mac  = rule.get("macro", "?")
            fstr = f" [{filt}]" if filt else ""
            self._tr_lw.addItem(f"{ev}{fstr} → {mac}")

    def _on_trigger_select(self, idx: int) -> None:
        if not (0 <= idx < len(self._triggers)):
            return
        rule = self._triggers[idx]
        ev_key = rule.get("event", "user_join")
        ev_idx = _EVENT_KEYS.index(ev_key) if ev_key in _EVENT_KEYS else 0
        self._t_event.setCurrentIndex(ev_idx)
        self._t_filter.setText(rule.get("filter", ""))
        self._t_regex.setChecked(bool(rule.get("use_regex", False)))
        names = self._macro_name_list()
        mac = rule.get("macro", "")
        self._t_macro.setCurrentIndex(names.index(mac) if mac in names else 0)

    def _on_trigger_new(self) -> None:
        self._triggers.append({"event": "user_join", "filter": "", "use_regex": False, "macro": ""})
        self._rebuild_trigger_list()
        self._tr_lw.setCurrentRow(len(self._triggers) - 1)
        self._t_event.setCurrentIndex(0)
        self._t_filter.clear()
        self._t_regex.setChecked(False)
        self._t_filter.setFocus()

    def _on_trigger_del(self) -> None:
        idx = self._tr_lw.currentRow()
        if idx < 0:
            return
        self._triggers.pop(idx)
        self._rebuild_trigger_list()
        self._persist()

    def _on_trigger_save(self) -> None:
        idx = self._tr_lw.currentRow()
        if idx < 0:
            QMessageBox.information(self, "Hinweis",
                                    "Bitte erst eine Regel auswählen oder 'Neu' klicken.")
            return
        ev_idx  = self._t_event.currentIndex()
        mac_idx = self._t_macro.currentIndex()
        names   = self._macro_name_list()
        self._triggers[idx] = {
            "event":     _EVENT_KEYS[ev_idx] if ev_idx >= 0 else "user_join",
            "filter":    self._t_filter.text().strip(),
            "use_regex": self._t_regex.isChecked(),
            "macro":     names[mac_idx] if 0 <= mac_idx < len(names) else "",
        }
        self._rebuild_trigger_list()
        self._tr_lw.setCurrentRow(idx)
        self._persist()
        self._window.set_status("Trigger-Regel gespeichert")

    # ------------------------------------------------------------------
    # Zeitplan-Tab-Logik
    # ------------------------------------------------------------------

    def _rebuild_schedule_list(self) -> None:
        self._sc_lw.clear()
        for e in self._scheduled:
            self._sc_lw.addItem(f"{e.get('time', '?')}, Makro: {e.get('macro', '?')}")

    def _on_schedule_add(self) -> None:
        t = self._sc_time.text().strip()
        if len(t) != 5 or t[2] != ":":
            QMessageBox.warning(self, "Fehler", "Ungültiges Zeitformat. Bitte HH:MM eingeben.")
            return
        names   = self._macro_name_list()
        mac_idx = self._sc_macro.currentIndex()
        mname   = names[mac_idx] if 0 <= mac_idx < len(names) else ""
        if not mname:
            QMessageBox.information(self, "Hinweis", "Bitte ein Makro auswählen.")
            return
        self._scheduled.append({"time": t, "macro": mname})
        self._rebuild_schedule_list()
        self._persist()
        self._window.set_status(f"Zeitplan {t} → '{mname}' gespeichert")

    def _on_schedule_del(self) -> None:
        idx = self._sc_lw.currentRow()
        if idx < 0:
            return
        self._scheduled.pop(idx)
        self._rebuild_schedule_list()
        self._persist()

    # ------------------------------------------------------------------
    # Hilfsmethoden
    # ------------------------------------------------------------------

    def _macro_name_list(self) -> List[str]:
        return [m.get("name", "?") for m in self._macros]

    def _refresh_macro_choices(self) -> None:
        names = self._macro_name_list()
        for combo in (self._t_macro, self._sc_macro):
            cur = combo.currentText()
            combo.clear()
            combo.addItems(names)
            if cur in names:
                combo.setCurrentIndex(names.index(cur))
            elif names:
                combo.setCurrentIndex(0)

    def _persist(self) -> None:
        s = self._window.settings_store.settings
        s.macros           = list(self._macros)
        s.macro_triggers   = list(self._triggers)
        s.scheduled_macros = list(self._scheduled)
        self._window.settings_store.save()

    def _on_close(self) -> None:
        self._persist()
        self.accept()
