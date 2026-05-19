"""Aussprache-Wörterbuch-Dialog (wx) – v7.0.

Verwaltet Ausspracheregeln: Suchen/Ersetzen mit optionalem Regex,
Wortgrenzen, Groß-/Kleinschreibung und Aktivieren/Deaktivieren pro Regel.
Enthält eine Live-Vorschau zum Testen der Regeln.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List

import wx

from pronunciation import PronunciationManager

if TYPE_CHECKING:
    from app_wx import MainFrame


class PronunciationDialog(wx.Dialog):
    """Aussprache-Wörterbuch-Editor."""

    def __init__(self, parent: "MainFrame") -> None:
        super().__init__(parent, title="Aussprache-Wörterbuch",
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self._frame = parent
        self._s = parent.settings_store.settings
        self._rules: List[Dict] = list(self._s.pronunciation_rules or [])

        self._build_ui()
        self._bind()
        self._rebuild_list()

        accel = wx.AcceleratorTable([(wx.ACCEL_CMD, ord("W"), wx.ID_CLOSE)])
        self.SetAcceleratorTable(accel)
        self.Bind(wx.EVT_MENU, lambda e: self._on_close(None), id=wx.ID_CLOSE)
        self.SetSize((720, 560))
        self.CentreOnParent()

    # ------------------------------------------------------------------
    # UI-Aufbau
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        outer = wx.BoxSizer(wx.VERTICAL)

        # ── Regelliste ─────────────────────────────────────────────────
        outer.Add(wx.StaticText(self, label="Regeln:"), 0, wx.LEFT | wx.TOP, 8)
        self._lb = wx.ListBox(self, style=wx.LB_SINGLE)
        self._lb.SetName("Regelliste")
        outer.Add(self._lb, 1, wx.EXPAND | wx.ALL, 8)

        list_btns = wx.BoxSizer(wx.HORIZONTAL)
        self._btn_new  = wx.Button(self, label="&Neue Regel")
        self._btn_new.SetName("Regel neu")
        self._btn_up   = wx.Button(self, label="Nach &oben")
        self._btn_up.SetName("Regel nach oben")
        self._btn_dn   = wx.Button(self, label="Nach &unten")
        self._btn_dn.SetName("Regel nach unten")
        self._btn_del  = wx.Button(self, label="&Entfernen")
        self._btn_del.SetName("Regel entfernen")
        self._btn_imp  = wx.Button(self, label="&Importieren…")
        self._btn_imp.SetName("Regeln importieren")
        self._btn_exp  = wx.Button(self, label="E&xportieren…")
        self._btn_exp.SetName("Regeln exportieren")
        for btn in (self._btn_new, self._btn_up, self._btn_dn,
                    self._btn_del, self._btn_imp, self._btn_exp):
            list_btns.Add(btn, 0, wx.RIGHT, 6)
        outer.Add(list_btns, 0, wx.LEFT | wx.BOTTOM, 8)

        # ── Regel-Editor ───────────────────────────────────────────────
        editor_box = wx.StaticBox(self, label="Regel bearbeiten")
        editor = wx.StaticBoxSizer(editor_box, wx.VERTICAL)

        grid = wx.FlexGridSizer(cols=2, vgap=8, hgap=8)
        grid.AddGrowableCol(1)

        grid.Add(wx.StaticText(self, label="Suchen:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self._find = wx.TextCtrl(self)
        self._find.SetName("Suchen")
        self._find.SetHint("Wort, Abkürzung oder Regex")
        grid.Add(self._find, 1, wx.EXPAND)

        grid.Add(wx.StaticText(self, label="Ersetzen durch:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self._replace = wx.TextCtrl(self)
        self._replace.SetName("Ersetzen durch")
        self._replace.SetHint("Aussprache-Alternative")
        grid.Add(self._replace, 1, wx.EXPAND)

        editor.Add(grid, 0, wx.EXPAND | wx.ALL, 8)

        flags_row = wx.BoxSizer(wx.HORIZONTAL)
        self._cb_whole  = wx.CheckBox(self, label="Ganzes Wort")
        self._cb_whole.SetName("Ganzes Wort")
        self._cb_regex  = wx.CheckBox(self, label="Regulärer Ausdruck (Regex)")
        self._cb_regex.SetName("Regex")
        self._cb_case   = wx.CheckBox(self, label="Groß-/Kleinschreibung beachten")
        self._cb_case.SetName("Groß-Kleinschreibung")
        self._cb_en     = wx.CheckBox(self, label="Aktiviert")
        self._cb_en.SetName("Aktiviert")
        self._cb_en.SetValue(True)
        for cb in (self._cb_whole, self._cb_regex, self._cb_case, self._cb_en):
            flags_row.Add(cb, 0, wx.RIGHT, 16)
        editor.Add(flags_row, 0, wx.LEFT | wx.BOTTOM, 8)

        self._btn_save = wx.Button(self, label="Regel &speichern")
        self._btn_save.SetName("Regel speichern")
        editor.Add(self._btn_save, 0, wx.LEFT | wx.BOTTOM, 8)

        outer.Add(editor, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # ── Live-Test ──────────────────────────────────────────────────
        test_box = wx.StaticBox(self, label="Live-Test")
        test_sizer = wx.StaticBoxSizer(test_box, wx.VERTICAL)

        test_row = wx.BoxSizer(wx.HORIZONTAL)
        self._test_in = wx.TextCtrl(self, size=(-1, -1))
        self._test_in.SetName("Testtext eingeben")
        self._test_in.SetHint("Testtext eingeben…")
        test_row.Add(self._test_in, 1, wx.RIGHT, 8)
        self._test_out = wx.StaticText(self, label="")
        self._test_out.SetName("Testergebnis")
        test_row.Add(self._test_out, 1, wx.ALIGN_CENTER_VERTICAL)
        test_sizer.Add(test_row, 0, wx.EXPAND | wx.ALL, 8)
        outer.Add(test_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # ── Schliesenbutton ────────────────────────────────────────────
        close_btn = wx.Button(self, wx.ID_CLOSE, label="&Schließen")
        close_btn.Bind(wx.EVT_BUTTON, self._on_close)
        outer.Add(close_btn, 0, wx.ALIGN_RIGHT | wx.ALL, 8)

        self.SetSizer(outer)

    # ------------------------------------------------------------------
    # Bindungen
    # ------------------------------------------------------------------

    def _bind(self) -> None:
        self._lb.Bind(wx.EVT_LISTBOX, self._on_select)
        self._btn_new.Bind(wx.EVT_BUTTON, self._on_new)
        self._btn_up.Bind(wx.EVT_BUTTON, self._on_move_up)
        self._btn_dn.Bind(wx.EVT_BUTTON, self._on_move_down)
        self._btn_del.Bind(wx.EVT_BUTTON, self._on_delete)
        self._btn_imp.Bind(wx.EVT_BUTTON, self._on_import)
        self._btn_exp.Bind(wx.EVT_BUTTON, self._on_export)
        self._btn_save.Bind(wx.EVT_BUTTON, self._on_save_rule)
        self._cb_regex.Bind(wx.EVT_CHECKBOX, self._on_regex_toggle)
        self._test_in.Bind(wx.EVT_TEXT, self._on_test_change)

    # ------------------------------------------------------------------
    # Listenverwaltung
    # ------------------------------------------------------------------

    def _rule_label(self, r: Dict) -> str:
        find    = r.get("find", "")
        replace = r.get("replace", "")
        tags    = []
        if r.get("use_regex"):    tags.append("Regex")
        if r.get("whole_word"):   tags.append("Wortgrenze")
        if not r.get("enabled", True): tags.append("deaktiviert")
        tag_str = f" [{', '.join(tags)}]" if tags else ""
        return f"{find} → {replace}{tag_str}"

    def _rebuild_list(self, keep_sel: int = -1) -> None:
        self._lb.Clear()
        for r in self._rules:
            self._lb.Append(self._rule_label(r))
        if keep_sel >= 0 and self._lb.GetCount() > 0:
            self._lb.SetSelection(min(keep_sel, self._lb.GetCount() - 1))

    def _current_idx(self) -> int:
        return self._lb.GetSelection()

    def _load_rule(self, idx: int) -> None:
        if not (0 <= idx < len(self._rules)):
            return
        r = self._rules[idx]
        self._find.SetValue(r.get("find", ""))
        self._replace.SetValue(r.get("replace", ""))
        self._cb_whole.SetValue(bool(r.get("whole_word", False)))
        self._cb_regex.SetValue(bool(r.get("use_regex", False)))
        self._cb_case.SetValue(bool(r.get("case_sensitive", False)))
        self._cb_en.SetValue(bool(r.get("enabled", True)))
        self._cb_whole.Enable(not r.get("use_regex", False))

    def _on_select(self, _evt) -> None:
        idx = self._current_idx()
        if idx != wx.NOT_FOUND:
            self._load_rule(idx)

    def _on_new(self, _evt) -> None:
        self._rules.append({"find": "", "replace": "", "whole_word": False,
                             "use_regex": False, "case_sensitive": False, "enabled": True})
        self._rebuild_list(len(self._rules) - 1)
        self._find.SetValue("")
        self._replace.SetValue("")
        self._cb_whole.SetValue(False)
        self._cb_regex.SetValue(False)
        self._cb_case.SetValue(False)
        self._cb_en.SetValue(True)
        self._find.SetFocus()

    def _on_move_up(self, _evt) -> None:
        idx = self._current_idx()
        if idx <= 0:
            return
        self._rules[idx - 1], self._rules[idx] = self._rules[idx], self._rules[idx - 1]
        self._rebuild_list(idx - 1)
        self._persist()

    def _on_move_down(self, _evt) -> None:
        idx = self._current_idx()
        if idx < 0 or idx >= len(self._rules) - 1:
            return
        self._rules[idx], self._rules[idx + 1] = self._rules[idx + 1], self._rules[idx]
        self._rebuild_list(idx + 1)
        self._persist()

    def _on_delete(self, _evt) -> None:
        idx = self._current_idx()
        if idx == wx.NOT_FOUND:
            return
        self._rules.pop(idx)
        self._rebuild_list(max(0, idx - 1))
        self._persist()

    def _on_regex_toggle(self, _evt) -> None:
        self._cb_whole.Enable(not self._cb_regex.GetValue())

    def _on_save_rule(self, _evt) -> None:
        idx = self._current_idx()
        find = self._find.GetValue().strip()
        if not find:
            wx.MessageBox("Bitte einen Suchbegriff eingeben.", "Hinweis", wx.OK, self)
            return
        rule = {
            "find":          find,
            "replace":       self._replace.GetValue(),
            "whole_word":    self._cb_whole.GetValue() and not self._cb_regex.GetValue(),
            "use_regex":     self._cb_regex.GetValue(),
            "case_sensitive": self._cb_case.GetValue(),
            "enabled":       self._cb_en.GetValue(),
        }
        if idx == wx.NOT_FOUND:
            self._rules.append(rule)
            idx = len(self._rules) - 1
        else:
            self._rules[idx] = rule
        self._rebuild_list(idx)
        self._persist()
        self._frame.set_status(f"Regel '{find}' gespeichert")
        self._on_test_change(None)

    # ------------------------------------------------------------------
    # Import / Export
    # ------------------------------------------------------------------

    def _on_import(self, _evt) -> None:
        path = wx.FileSelector(
            "Ausspracheregeln importieren", "", "pronunciation.json",
            "JSON (*.json)|*.json|Alle Dateien|*.*",
            wx.FD_OPEN | wx.FD_FILE_MUST_EXIST, self,
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
            self._frame.set_status(f"{len(self._rules)} Regeln importiert")
        except Exception as exc:
            wx.MessageBox(f"Import fehlgeschlagen:\n{exc}", "Fehler", wx.OK | wx.ICON_ERROR, self)

    def _on_export(self, _evt) -> None:
        path = wx.FileSelector(
            "Ausspracheregeln exportieren", "", "pronunciation.json",
            "JSON (*.json)|*.json|Alle Dateien|*.*",
            wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT, self,
        )
        if not path:
            return
        try:
            Path(path).write_text(
                json.dumps(self._rules, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            self._frame.set_status("Regeln exportiert")
        except Exception as exc:
            wx.MessageBox(f"Export fehlgeschlagen:\n{exc}", "Fehler", wx.OK | wx.ICON_ERROR, self)

    # ------------------------------------------------------------------
    # Live-Test
    # ------------------------------------------------------------------

    def _on_test_change(self, _evt) -> None:
        text = self._test_in.GetValue()
        if not text:
            self._test_out.SetLabel("")
            return
        pm = PronunciationManager(list(self._rules))
        result = pm.apply(text)
        self._test_out.SetLabel(result)

    # ------------------------------------------------------------------
    # Speichern & Schließen
    # ------------------------------------------------------------------

    def _persist(self) -> None:
        self._s.pronunciation_rules = list(self._rules)
        self._frame._pronunciation.update_rules(list(self._rules))
        self._frame.settings_store.save()

    def _on_close(self, _evt) -> None:
        self._persist()
        self.EndModal(wx.ID_CLOSE)
