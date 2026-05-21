"""Benachrichtigungs-Regeln Dialog (wx)."""
from __future__ import annotations

import wx
from notification_manager import EVENTS, SCOPES, ACTIONS, rule_label


class NotificationRulesDialog(wx.Dialog):
    """
    Dialog zum Bearbeiten von Benachrichtigungs-Regeln.

    Jede Regel legt fest, ob für ein Ereignis (z. B. Benutzer betritt Kanal)
    TTS, Sound, beides oder nichts ausgeführt wird – global oder für einen
    bestimmten Server, Kanal oder Benutzer.
    """

    def __init__(self, parent, rules: list) -> None:
        super().__init__(
            parent,
            title="Benachrichtigungs-Regeln",
            size=(640, 520),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self._rules = list(rules)

        panel = wx.Panel(self)
        main = wx.BoxSizer(wx.VERTICAL)

        # ── Regelliste ──────────────────────────────────────────────────────
        main.Add(wx.StaticText(panel, label="Regeln (spezifischere Regeln überschreiben allgemeinere):"),
                 0, wx.LEFT | wx.TOP, 8)
        self._lb = wx.ListBox(panel, style=wx.LB_SINGLE)
        self._lb.SetName("Regelliste")
        main.Add(self._lb, 1, wx.EXPAND | wx.ALL, 6)

        # Schaltflächen über der Liste
        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self._add_btn = wx.Button(panel, label="&Hinzufügen")
        self._add_btn.SetName("Neue Regel")
        self._del_btn = wx.Button(panel, label="&Löschen")
        self._del_btn.SetName("Regel löschen")
        self._up_btn = wx.Button(panel, label="Nach &oben")
        self._up_btn.SetName("Regel nach oben")
        self._down_btn = wx.Button(panel, label="Nach &unten")
        self._down_btn.SetName("Regel nach unten")
        for b in (self._add_btn, self._del_btn, self._up_btn, self._down_btn):
            btn_sizer.Add(b, 0, wx.RIGHT, 6)
        main.Add(btn_sizer, 0, wx.LEFT | wx.BOTTOM, 6)

        # ── Regel-Editor ────────────────────────────────────────────────────
        editor_box = wx.StaticBox(panel, label="Regel bearbeiten")
        editor = wx.StaticBoxSizer(editor_box, wx.VERTICAL)

        form = wx.FlexGridSizer(rows=4, cols=2, hgap=10, vgap=6)
        form.AddGrowableCol(1)

        # Ereignis
        form.Add(wx.StaticText(panel, label="Ereignis:"),
                 0, wx.ALIGN_CENTER_VERTICAL)
        event_labels = ["(Alle Ereignisse)"] + [lbl for _, lbl in EVENTS]
        self._event_ch = wx.Choice(panel, choices=event_labels)
        self._event_ch.SetName("Ereignis auswählen")
        self._event_ch.SetSelection(0)
        form.Add(self._event_ch, 1, wx.EXPAND)

        # Geltungsbereich
        form.Add(wx.StaticText(panel, label="Geltungsbereich:"),
                 0, wx.ALIGN_CENTER_VERTICAL)
        scope_labels = [lbl for _, lbl in SCOPES]
        self._scope_ch = wx.Choice(panel, choices=scope_labels)
        self._scope_ch.SetName("Geltungsbereich")
        self._scope_ch.SetSelection(0)
        form.Add(self._scope_ch, 1, wx.EXPAND)

        # Wert (Server-/Kanal-/Benutzername)
        form.Add(wx.StaticText(panel, label="Wert:"),
                 0, wx.ALIGN_CENTER_VERTICAL)
        self._value_tc = wx.TextCtrl(panel)
        self._value_tc.SetName("Name (Server / Kanal / Benutzer)")
        self._value_tc.SetHint("Bei 'Global' leer lassen")
        form.Add(self._value_tc, 1, wx.EXPAND)

        # Aktion
        form.Add(wx.StaticText(panel, label="Aktion:"),
                 0, wx.ALIGN_CENTER_VERTICAL)
        action_labels = [lbl for _, lbl in ACTIONS]
        self._action_ch = wx.Choice(panel, choices=action_labels)
        self._action_ch.SetName("Aktion")
        self._action_ch.SetSelection(0)
        form.Add(self._action_ch, 1, wx.EXPAND)

        editor.Add(form, 0, wx.EXPAND | wx.ALL, 8)

        self._save_btn = wx.Button(panel, label="Regel &speichern")
        self._save_btn.SetName("Regel speichern")
        editor.Add(self._save_btn, 0, wx.LEFT | wx.BOTTOM, 8)

        main.Add(editor, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)

        # ── OK / Abbrechen ──────────────────────────────────────────────────
        dlg_btns = wx.StdDialogButtonSizer()
        ok_btn = wx.Button(panel, wx.ID_OK)
        ok_btn.SetDefault()
        cancel_btn = wx.Button(panel, wx.ID_CANCEL)
        dlg_btns.AddButton(ok_btn)
        dlg_btns.AddButton(cancel_btn)
        dlg_btns.Realize()
        main.Add(dlg_btns, 0, wx.ALIGN_RIGHT | wx.ALL, 8)

        panel.SetSizer(main)
        self._editing_idx: int | None = None

        self._refresh_list()
        self._update_editor_enable()

        # Bindungen
        self._lb.Bind(wx.EVT_LISTBOX, self._on_select)
        self._scope_ch.Bind(wx.EVT_CHOICE, self._on_scope_change)
        self._add_btn.Bind(wx.EVT_BUTTON, self._on_add)
        self._del_btn.Bind(wx.EVT_BUTTON, self._on_delete)
        self._up_btn.Bind(wx.EVT_BUTTON, self._on_move_up)
        self._down_btn.Bind(wx.EVT_BUTTON, self._on_move_down)
        self._save_btn.Bind(wx.EVT_BUTTON, self._on_save_rule)
        self.Bind(wx.EVT_BUTTON, self._on_ok, id=wx.ID_OK)

    # ── Hilfsmethoden ────────────────────────────────────────────────────────

    def _refresh_list(self) -> None:
        self._lb.Clear()
        for rule in self._rules:
            self._lb.Append(rule_label(rule))

    def _update_editor_enable(self) -> None:
        sc = SCOPES[max(self._scope_ch.GetSelection(), 0)][0]
        self._value_tc.Enable(sc != "global")

    def _get_current_rule(self) -> dict:
        ev_idx = self._event_ch.GetSelection()
        ev_key = "" if ev_idx == 0 else EVENTS[ev_idx - 1][0]
        sc_idx = self._scope_ch.GetSelection()
        sc_key = SCOPES[sc_idx][0] if 0 <= sc_idx < len(SCOPES) else "global"
        value = self._value_tc.GetValue().strip() if sc_key != "global" else ""
        ac_idx = self._action_ch.GetSelection()
        ac_key = ACTIONS[ac_idx][0] if 0 <= ac_idx < len(ACTIONS) else "both"
        return {"event": ev_key, "scope": sc_key, "value": value, "action": ac_key}

    def _load_rule_into_editor(self, rule: dict) -> None:
        ev = rule.get("event", "")
        if not ev:
            self._event_ch.SetSelection(0)
        else:
            keys = [k for k, _ in EVENTS]
            try:
                self._event_ch.SetSelection(keys.index(ev) + 1)
            except ValueError:
                self._event_ch.SetSelection(0)
        sc_keys = [k for k, _ in SCOPES]
        try:
            self._scope_ch.SetSelection(sc_keys.index(rule.get("scope", "global")))
        except ValueError:
            self._scope_ch.SetSelection(0)
        self._value_tc.SetValue(rule.get("value", ""))
        self._update_editor_enable()
        ac_keys = [k for k, _ in ACTIONS]
        try:
            self._action_ch.SetSelection(ac_keys.index(rule.get("action", "both")))
        except ValueError:
            self._action_ch.SetSelection(0)

    # ── Ereignishandler ───────────────────────────────────────────────────────

    def _on_select(self, _event) -> None:
        idx = self._lb.GetSelection()
        if idx < 0 or idx >= len(self._rules):
            return
        self._editing_idx = idx
        self._load_rule_into_editor(self._rules[idx])

    def _on_scope_change(self, _event) -> None:
        self._update_editor_enable()

    def _on_add(self, _event) -> None:
        self._editing_idx = -1
        self._event_ch.SetSelection(0)
        self._scope_ch.SetSelection(0)
        self._value_tc.SetValue("")
        self._value_tc.Disable()
        self._action_ch.SetSelection(0)
        self._event_ch.SetFocus()

    def _on_delete(self, _event) -> None:
        idx = self._lb.GetSelection()
        if idx < 0 or idx >= len(self._rules):
            return
        self._rules.pop(idx)
        self._editing_idx = None
        self._refresh_list()
        if self._rules:
            new_idx = min(idx, len(self._rules) - 1)
            self._lb.SetSelection(new_idx)
            self._load_rule_into_editor(self._rules[new_idx])
            self._editing_idx = new_idx

    def _on_move_up(self, _event) -> None:
        idx = self._lb.GetSelection()
        if idx <= 0 or idx >= len(self._rules):
            return
        self._rules[idx - 1], self._rules[idx] = self._rules[idx], self._rules[idx - 1]
        self._refresh_list()
        self._lb.SetSelection(idx - 1)
        self._editing_idx = idx - 1

    def _on_move_down(self, _event) -> None:
        idx = self._lb.GetSelection()
        if idx < 0 or idx >= len(self._rules) - 1:
            return
        self._rules[idx + 1], self._rules[idx] = self._rules[idx], self._rules[idx + 1]
        self._refresh_list()
        self._lb.SetSelection(idx + 1)
        self._editing_idx = idx + 1

    def _on_save_rule(self, _event) -> None:
        rule = self._get_current_rule()
        if self._editing_idx == -1:
            self._rules.append(rule)
            self._refresh_list()
            new_idx = len(self._rules) - 1
            self._lb.SetSelection(new_idx)
            self._editing_idx = new_idx
        elif self._editing_idx is not None and 0 <= self._editing_idx < len(self._rules):
            self._rules[self._editing_idx] = rule
            self._refresh_list()
            self._lb.SetSelection(self._editing_idx)
        else:
            wx.MessageBox("Bitte erst 'Hinzufügen' drücken oder eine Regel auswählen.",
                          "Kein Ziel", wx.OK | wx.ICON_INFORMATION, self)

    def _on_ok(self, event) -> None:
        event.Skip()

    def get_rules(self) -> list:
        return list(self._rules)
