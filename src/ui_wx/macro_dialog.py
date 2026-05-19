"""Makro-Editor-Dialog (wx) – v7.0.

Drei Tabs:
  1. Makros   – Erstellen, Bearbeiten, Löschen; Aktionsliste mit Typ-Auswahl
  2. Trigger  – Ereignisbasierte Regeln (user_join, chat_message, …)
  3. Zeitplan – Zeitgesteuerte Makros (HH:MM täglich)
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, List, Dict

import wx

from macro_manager import ACTION_TYPES, TRIGGER_EVENTS

if TYPE_CHECKING:
    from app_wx import MainFrame


_ACTION_KEYS   = [k for k, _ in ACTION_TYPES]
_ACTION_LABELS = [v for _, v in ACTION_TYPES]
_EVENT_KEYS    = [k for k, _ in TRIGGER_EVENTS]
_EVENT_LABELS  = [v for _, v in TRIGGER_EVENTS]

_ACTIONS_WITH_VALUE = {k for k, _ in ACTION_TYPES} - {"ptt_on", "ptt_off", "mute_toggle"}
_HELP_TEXT = (
    "Template-Variablen: {user}  {channel}  {message}  {time}\n"
    "Beispiel: \"Hallo {user}, willkommen in {channel}!\""
)


class MacroDialog(wx.Dialog):
    """Vollständiger Makro-Editor mit drei Tabs."""

    def __init__(self, parent: "MainFrame") -> None:
        super().__init__(parent, title="Makro-Editor",
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self._frame = parent
        self._s = parent.settings_store.settings

        self._macros: List[Dict] = list(self._s.macros or [])
        self._triggers: List[Dict] = list(self._s.macro_triggers or [])
        self._scheduled: List[Dict] = list(self._s.scheduled_macros or [])

        self._build_ui()
        self._bind()

        accel = wx.AcceleratorTable([
            (wx.ACCEL_CMD, ord("W"), wx.ID_CLOSE),
        ])
        self.SetAcceleratorTable(accel)
        self.Bind(wx.EVT_MENU, lambda e: self._on_close(None), id=wx.ID_CLOSE)

        self.SetSize((820, 580))
        self.CentreOnParent()

    # ------------------------------------------------------------------
    # UI-Aufbau
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        outer = wx.BoxSizer(wx.VERTICAL)

        self._nb = wx.Notebook(self)
        self._nb.AddPage(self._build_macros_tab(), "Makros")
        self._nb.AddPage(self._build_triggers_tab(), "Trigger")
        self._nb.AddPage(self._build_schedule_tab(), "Zeitplan")
        outer.Add(self._nb, 1, wx.EXPAND | wx.ALL, 6)

        close_btn = wx.Button(self, wx.ID_CLOSE, label="&Schließen")
        close_btn.Bind(wx.EVT_BUTTON, self._on_close)
        outer.Add(close_btn, 0, wx.ALIGN_RIGHT | wx.ALL, 8)

        self.SetSizer(outer)

    # ── Tab 1: Makros ─────────────────────────────────────────────────

    def _build_macros_tab(self) -> wx.Panel:
        panel = wx.Panel(self._nb)
        root = wx.BoxSizer(wx.HORIZONTAL)

        # -- Left: macro list --
        left = wx.BoxSizer(wx.VERTICAL)
        left.Add(wx.StaticText(panel, label="Makros:"), 0, wx.BOTTOM, 2)
        self._macro_lb = wx.ListBox(panel, style=wx.LB_SINGLE)
        self._macro_lb.SetName("Makroliste")
        for m in self._macros:
            self._macro_lb.Append(m.get("name", "?"))
        left.Add(self._macro_lb, 1, wx.EXPAND | wx.BOTTOM, 4)

        lbtn = wx.BoxSizer(wx.HORIZONTAL)
        self._m_new  = wx.Button(panel, label="&Neu")
        self._m_new.SetName("Makro neu")
        self._m_dup  = wx.Button(panel, label="D&uplizieren")
        self._m_dup.SetName("Makro duplizieren")
        self._m_del  = wx.Button(panel, label="&Löschen")
        self._m_del.SetName("Makro löschen")
        lbtn.Add(self._m_new, 1, wx.RIGHT, 4)
        lbtn.Add(self._m_dup, 1, wx.RIGHT, 4)
        lbtn.Add(self._m_del, 1)
        left.Add(lbtn, 0, wx.EXPAND)
        root.Add(left, 0, wx.ALL | wx.EXPAND, 8)

        # -- Right: detail editor --
        right = wx.BoxSizer(wx.VERTICAL)

        # Name
        nr = wx.BoxSizer(wx.HORIZONTAL)
        nr.Add(wx.StaticText(panel, label="Name:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self._m_name = wx.TextCtrl(panel, size=(220, -1))
        self._m_name.SetName("Makro-Name")
        nr.Add(self._m_name, 1)
        right.Add(nr, 0, wx.EXPAND | wx.BOTTOM, 8)

        # Actions list
        right.Add(wx.StaticText(panel, label="Aktionen:"), 0, wx.BOTTOM, 2)
        self._act_lb = wx.ListBox(panel, style=wx.LB_SINGLE)
        self._act_lb.SetName("Aktionsliste")
        right.Add(self._act_lb, 1, wx.EXPAND | wx.BOTTOM, 4)

        # Action reorder + remove
        abtn = wx.BoxSizer(wx.HORIZONTAL)
        self._a_up   = wx.Button(panel, label="Nach &oben")
        self._a_up.SetName("Aktion nach oben")
        self._a_dn   = wx.Button(panel, label="Nach &unten")
        self._a_dn.SetName("Aktion nach unten")
        self._a_del  = wx.Button(panel, label="A&ktion entfernen")
        self._a_del.SetName("Aktion entfernen")
        abtn.Add(self._a_up, 0, wx.RIGHT, 4)
        abtn.Add(self._a_dn, 0, wx.RIGHT, 4)
        abtn.Add(self._a_del, 0)
        right.Add(abtn, 0, wx.BOTTOM, 8)

        # New action form
        right.Add(wx.StaticText(panel, label="Neue Aktion:"), 0, wx.BOTTOM, 2)
        aform = wx.BoxSizer(wx.HORIZONTAL)
        self._a_type = wx.Choice(panel, choices=_ACTION_LABELS)
        self._a_type.SetName("Aktionstyp")
        self._a_type.SetSelection(0)
        aform.Add(self._a_type, 1, wx.RIGHT, 6)
        self._a_val = wx.TextCtrl(panel, size=(180, -1))
        self._a_val.SetName("Aktionswert")
        self._a_val.SetHint("Wert (z.B. Text, Kanalname, Sekunden)")
        aform.Add(self._a_val, 1, wx.RIGHT, 4)
        self._a_browse = wx.Button(panel, label="…")
        self._a_browse.SetName("Datei wählen")
        self._a_browse.SetToolTip("Datei auswählen (nur für Sound)")
        aform.Add(self._a_browse, 0)
        right.Add(aform, 0, wx.EXPAND | wx.BOTTOM, 4)

        right.Add(wx.StaticText(panel, label=_HELP_TEXT), 0, wx.BOTTOM, 6)

        self._a_add  = wx.Button(panel, label="Aktion &hinzufügen")
        self._a_add.SetName("Aktion hinzufügen")
        right.Add(self._a_add, 0, wx.BOTTOM, 12)

        self._m_save = wx.Button(panel, label="Makro &speichern")
        self._m_save.SetName("Makro speichern")
        right.Add(self._m_save, 0)

        root.Add(right, 1, wx.ALL | wx.EXPAND, 8)
        panel.SetSizer(root)
        return panel

    # ── Tab 2: Trigger ────────────────────────────────────────────────

    def _build_triggers_tab(self) -> wx.Panel:
        panel = wx.Panel(self._nb)
        root = wx.BoxSizer(wx.HORIZONTAL)

        # Left: trigger list
        left = wx.BoxSizer(wx.VERTICAL)
        left.Add(wx.StaticText(panel, label="Trigger-Regeln:"), 0, wx.BOTTOM, 2)
        self._tr_lb = wx.ListBox(panel, style=wx.LB_SINGLE)
        self._tr_lb.SetName("Triggerliste")
        self._rebuild_trigger_list()
        left.Add(self._tr_lb, 1, wx.EXPAND | wx.BOTTOM, 4)

        tbtn = wx.BoxSizer(wx.HORIZONTAL)
        self._t_new = wx.Button(panel, label="&Neu")
        self._t_new.SetName("Trigger neu")
        self._t_del = wx.Button(panel, label="&Entfernen")
        self._t_del.SetName("Trigger entfernen")
        tbtn.Add(self._t_new, 1, wx.RIGHT, 4)
        tbtn.Add(self._t_del, 1)
        left.Add(tbtn, 0, wx.EXPAND)
        root.Add(left, 0, wx.ALL | wx.EXPAND, 8)

        # Right: trigger editor
        right = wx.BoxSizer(wx.VERTICAL)

        form = wx.FlexGridSizer(cols=2, vgap=8, hgap=8)
        form.AddGrowableCol(1)

        form.Add(wx.StaticText(panel, label="Ereignis:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self._t_event = wx.Choice(panel, choices=_EVENT_LABELS)
        self._t_event.SetName("Trigger-Ereignis")
        self._t_event.SetSelection(0)
        form.Add(self._t_event, 1, wx.EXPAND)

        form.Add(wx.StaticText(panel, label="Filter:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self._t_filter = wx.TextCtrl(panel)
        self._t_filter.SetName("Trigger-Filter")
        self._t_filter.SetHint("Leer = alle; Benutzername, Kanalname oder Nachrichteninhalt")
        form.Add(self._t_filter, 1, wx.EXPAND)

        form.Add(wx.StaticText(panel, label=""), 0)
        self._t_regex = wx.CheckBox(panel, label="Filter als Regulären Ausdruck (Regex) verwenden")
        self._t_regex.SetName("Regex-Filter")
        form.Add(self._t_regex, 0)

        form.Add(wx.StaticText(panel, label="Makro:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self._t_macro = wx.Choice(panel, choices=self._macro_name_list())
        self._t_macro.SetName("Trigger-Makro")
        form.Add(self._t_macro, 1, wx.EXPAND)

        right.Add(form, 0, wx.EXPAND | wx.BOTTOM, 12)

        right.Add(wx.StaticText(panel, label=(
            "Hinweis: Bei 'Chat-Nachricht' prüft der Filter den Nachrichteninhalt.\n"
            "Bei anderen Ereignissen prüft der Filter den Benutzer- oder Kanalnamen."
        )), 0, wx.BOTTOM, 12)

        self._t_save = wx.Button(panel, label="Regel &speichern")
        self._t_save.SetName("Trigger speichern")
        right.Add(self._t_save, 0)

        root.Add(right, 1, wx.ALL | wx.EXPAND, 8)
        panel.SetSizer(root)
        return panel

    # ── Tab 3: Zeitplan ───────────────────────────────────────────────

    def _build_schedule_tab(self) -> wx.Panel:
        panel = wx.Panel(self._nb)
        root = wx.BoxSizer(wx.VERTICAL)

        root.Add(wx.StaticText(panel, label="Geplante Makros werden täglich zur angegebenen Uhrzeit ausgeführt."),
                 0, wx.ALL, 8)

        self._sc_lb = wx.ListBox(panel, style=wx.LB_SINGLE)
        self._sc_lb.SetName("Zeitplan-Liste")
        self._rebuild_schedule_list()
        root.Add(self._sc_lb, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        form = wx.BoxSizer(wx.HORIZONTAL)
        form.Add(wx.StaticText(panel, label="Zeit (HH:MM):"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self._sc_time = wx.TextCtrl(panel, value="08:00", size=(80, -1))
        self._sc_time.SetName("Geplante Zeit")
        form.Add(self._sc_time, 0, wx.RIGHT, 16)
        form.Add(wx.StaticText(panel, label="Makro:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self._sc_macro = wx.Choice(panel, choices=self._macro_name_list())
        self._sc_macro.SetName("Geplantes Makro")
        form.Add(self._sc_macro, 1)
        root.Add(form, 0, wx.ALL | wx.EXPAND, 8)

        sbtn = wx.BoxSizer(wx.HORIZONTAL)
        self._sc_add = wx.Button(panel, label="&Hinzufügen")
        self._sc_add.SetName("Zeitplan hinzufügen")
        self._sc_del = wx.Button(panel, label="&Entfernen")
        self._sc_del.SetName("Zeitplan entfernen")
        sbtn.Add(self._sc_add, 0, wx.RIGHT, 8)
        sbtn.Add(self._sc_del, 0)
        root.Add(sbtn, 0, wx.LEFT | wx.BOTTOM, 8)

        panel.SetSizer(root)
        return panel

    # ------------------------------------------------------------------
    # Event-Bindungen
    # ------------------------------------------------------------------

    def _bind(self) -> None:
        # Makro-Tab
        self._macro_lb.Bind(wx.EVT_LISTBOX, self._on_macro_select)
        self._m_new.Bind(wx.EVT_BUTTON, self._on_macro_new)
        self._m_dup.Bind(wx.EVT_BUTTON, self._on_macro_dup)
        self._m_del.Bind(wx.EVT_BUTTON, self._on_macro_del)
        self._a_type.Bind(wx.EVT_CHOICE, self._on_atype_change)
        self._a_browse.Bind(wx.EVT_BUTTON, self._on_browse_sound)
        self._a_add.Bind(wx.EVT_BUTTON, self._on_action_add)
        self._a_up.Bind(wx.EVT_BUTTON, self._on_action_up)
        self._a_dn.Bind(wx.EVT_BUTTON, self._on_action_down)
        self._a_del.Bind(wx.EVT_BUTTON, self._on_action_del)
        self._m_save.Bind(wx.EVT_BUTTON, self._on_macro_save)
        # Trigger-Tab
        self._tr_lb.Bind(wx.EVT_LISTBOX, self._on_trigger_select)
        self._t_new.Bind(wx.EVT_BUTTON, self._on_trigger_new)
        self._t_del.Bind(wx.EVT_BUTTON, self._on_trigger_del)
        self._t_save.Bind(wx.EVT_BUTTON, self._on_trigger_save)
        # Zeitplan-Tab
        self._sc_add.Bind(wx.EVT_BUTTON, self._on_schedule_add)
        self._sc_del.Bind(wx.EVT_BUTTON, self._on_schedule_del)

    # ------------------------------------------------------------------
    # Makro-Tab-Logik
    # ------------------------------------------------------------------

    def _current_macro_idx(self) -> int:
        return self._macro_lb.GetSelection()

    def _load_macro_into_editor(self, idx: int) -> None:
        if not (0 <= idx < len(self._macros)):
            return
        m = self._macros[idx]
        self._m_name.SetValue(m.get("name", ""))
        self._act_lb.Clear()
        for a in m.get("actions", []):
            self._act_lb.Append(self._action_label(a))

    def _action_label(self, a: Dict) -> str:
        atype = a.get("type", "")
        val   = a.get("value", "")
        label = dict(ACTION_TYPES).get(atype, atype)
        return f"{label}: {val}" if val else label

    def _on_macro_select(self, _evt) -> None:
        idx = self._current_macro_idx()
        if idx != wx.NOT_FOUND:
            self._load_macro_into_editor(idx)

    def _on_macro_new(self, _evt) -> None:
        name = f"Makro {len(self._macros) + 1}"
        self._macros.append({"name": name, "hotkey": 0, "actions": []})
        self._macro_lb.Append(name)
        new_idx = len(self._macros) - 1
        self._macro_lb.SetSelection(new_idx)
        self._load_macro_into_editor(new_idx)
        self._refresh_macro_choices()
        self._m_name.SetFocus()

    def _on_macro_dup(self, _evt) -> None:
        idx = self._current_macro_idx()
        if idx == wx.NOT_FOUND:
            return
        import copy
        orig = self._macros[idx]
        dup  = copy.deepcopy(orig)
        dup["name"] = orig.get("name", "Makro") + " (Kopie)"
        dup.pop("hotkey", None)
        dup["hotkey"] = 0
        self._macros.append(dup)
        self._macro_lb.Append(dup["name"])
        new_idx = len(self._macros) - 1
        self._macro_lb.SetSelection(new_idx)
        self._load_macro_into_editor(new_idx)
        self._refresh_macro_choices()

    def _on_macro_del(self, _evt) -> None:
        idx = self._current_macro_idx()
        if idx == wx.NOT_FOUND:
            return
        name = self._macros[idx].get("name", "?")
        if wx.MessageBox(f"Makro '{name}' wirklich löschen?", "Löschen",
                         wx.YES_NO | wx.ICON_QUESTION, self) != wx.YES:
            return
        self._macros.pop(idx)
        self._macro_lb.Delete(idx)
        self._act_lb.Clear()
        self._m_name.SetValue("")
        self._refresh_macro_choices()
        self._persist()

    def _on_atype_change(self, _evt) -> None:
        key = _ACTION_KEYS[self._a_type.GetSelection()]
        has_val = key in _ACTIONS_WITH_VALUE
        self._a_val.Enable(has_val)
        self._a_browse.Enable(key == "play_sound")

    def _on_browse_sound(self, _evt) -> None:
        path = wx.FileSelector(
            "Sounddatei wählen", "", "",
            "Audio-Dateien (*.wav;*.mp3;*.ogg)|*.wav;*.mp3;*.ogg|Alle Dateien|*.*",
            wx.FD_OPEN | wx.FD_FILE_MUST_EXIST, self,
        )
        if path:
            self._a_val.SetValue(path)

    def _on_action_add(self, _evt) -> None:
        idx = self._current_macro_idx()
        if idx == wx.NOT_FOUND:
            wx.MessageBox("Bitte erst ein Makro auswählen.", "Hinweis", wx.OK, self)
            return
        key = _ACTION_KEYS[self._a_type.GetSelection()]
        val = self._a_val.GetValue().strip() if key in _ACTIONS_WITH_VALUE else ""
        action = {"type": key}
        if val:
            action["value"] = val
        self._macros[idx].setdefault("actions", []).append(action)
        self._act_lb.Append(self._action_label(action))
        self._a_val.SetValue("")

    def _on_action_up(self, _evt) -> None:
        macro_idx = self._current_macro_idx()
        act_idx   = self._act_lb.GetSelection()
        if macro_idx == wx.NOT_FOUND or act_idx <= 0:
            return
        actions = self._macros[macro_idx].get("actions", [])
        actions[act_idx - 1], actions[act_idx] = actions[act_idx], actions[act_idx - 1]
        self._reload_action_list(macro_idx, act_idx - 1)

    def _on_action_down(self, _evt) -> None:
        macro_idx = self._current_macro_idx()
        act_idx   = self._act_lb.GetSelection()
        actions   = self._macros[macro_idx].get("actions", []) if macro_idx != wx.NOT_FOUND else []
        if macro_idx == wx.NOT_FOUND or act_idx < 0 or act_idx >= len(actions) - 1:
            return
        actions[act_idx], actions[act_idx + 1] = actions[act_idx + 1], actions[act_idx]
        self._reload_action_list(macro_idx, act_idx + 1)

    def _on_action_del(self, _evt) -> None:
        macro_idx = self._current_macro_idx()
        act_idx   = self._act_lb.GetSelection()
        if macro_idx == wx.NOT_FOUND or act_idx == wx.NOT_FOUND:
            return
        self._macros[macro_idx].get("actions", []).pop(act_idx)
        self._reload_action_list(macro_idx, max(0, act_idx - 1))

    def _reload_action_list(self, macro_idx: int, select: int = -1) -> None:
        self._act_lb.Clear()
        for a in self._macros[macro_idx].get("actions", []):
            self._act_lb.Append(self._action_label(a))
        if select >= 0 and self._act_lb.GetCount() > 0:
            self._act_lb.SetSelection(min(select, self._act_lb.GetCount() - 1))

    def _on_macro_save(self, _evt) -> None:
        idx = self._current_macro_idx()
        if idx == wx.NOT_FOUND:
            return
        name = self._m_name.GetValue().strip()
        if not name:
            wx.MessageBox("Bitte einen Namen eingeben.", "Hinweis", wx.OK, self)
            return
        self._macros[idx]["name"] = name
        self._macro_lb.SetString(idx, name)
        self._refresh_macro_choices()
        self._persist()
        self._frame.set_status(f"Makro '{name}' gespeichert")

    # ------------------------------------------------------------------
    # Trigger-Tab-Logik
    # ------------------------------------------------------------------

    def _rebuild_trigger_list(self) -> None:
        self._tr_lb.Clear()
        ev_map = dict(TRIGGER_EVENTS)
        for rule in self._triggers:
            ev   = ev_map.get(rule.get("event", ""), rule.get("event", "?"))
            filt = rule.get("filter", "")
            mac  = rule.get("macro", "?")
            fstr = f" [{filt}]" if filt else ""
            self._tr_lb.Append(f"{ev}{fstr} → {mac}")

    def _on_trigger_select(self, _evt) -> None:
        idx = self._tr_lb.GetSelection()
        if idx == wx.NOT_FOUND or idx >= len(self._triggers):
            return
        rule = self._triggers[idx]
        ev_key = rule.get("event", "user_join")
        ev_idx = _EVENT_KEYS.index(ev_key) if ev_key in _EVENT_KEYS else 0
        self._t_event.SetSelection(ev_idx)
        self._t_filter.SetValue(rule.get("filter", ""))
        self._t_regex.SetValue(bool(rule.get("use_regex", False)))
        mac = rule.get("macro", "")
        names = self._macro_name_list()
        self._t_macro.SetSelection(names.index(mac) if mac in names else 0)

    def _on_trigger_new(self, _evt) -> None:
        self._triggers.append({"event": "user_join", "filter": "", "use_regex": False, "macro": ""})
        self._rebuild_trigger_list()
        new_idx = len(self._triggers) - 1
        self._tr_lb.SetSelection(new_idx)
        self._t_event.SetSelection(0)
        self._t_filter.SetValue("")
        self._t_regex.SetValue(False)
        self._t_filter.SetFocus()

    def _on_trigger_del(self, _evt) -> None:
        idx = self._tr_lb.GetSelection()
        if idx == wx.NOT_FOUND:
            return
        self._triggers.pop(idx)
        self._rebuild_trigger_list()
        self._persist()

    def _on_trigger_save(self, _evt) -> None:
        idx = self._tr_lb.GetSelection()
        if idx == wx.NOT_FOUND:
            wx.MessageBox("Bitte erst eine Regel auswählen oder 'Neu' klicken.", "Hinweis", wx.OK, self)
            return
        ev_idx = self._t_event.GetSelection()
        mac_idx = self._t_macro.GetSelection()
        names = self._macro_name_list()
        self._triggers[idx] = {
            "event":     _EVENT_KEYS[ev_idx] if ev_idx != wx.NOT_FOUND else "user_join",
            "filter":    self._t_filter.GetValue().strip(),
            "use_regex": self._t_regex.GetValue(),
            "macro":     names[mac_idx] if 0 <= mac_idx < len(names) else "",
        }
        self._rebuild_trigger_list()
        self._tr_lb.SetSelection(idx)
        self._persist()
        self._frame.set_status("Trigger-Regel gespeichert")

    # ------------------------------------------------------------------
    # Zeitplan-Tab-Logik
    # ------------------------------------------------------------------

    def _rebuild_schedule_list(self) -> None:
        self._sc_lb.Clear()
        for e in self._scheduled:
            self._sc_lb.Append(f"{e.get('time', '?')}, Makro: {e.get('macro', '?')}")

    def _on_schedule_add(self, _evt) -> None:
        t = self._sc_time.GetValue().strip()
        if len(t) != 5 or t[2] != ":":
            wx.MessageBox("Ungültiges Zeitformat. Bitte HH:MM eingeben.", "Fehler", wx.OK, self)
            return
        names   = self._macro_name_list()
        mac_idx = self._sc_macro.GetSelection()
        mname   = names[mac_idx] if 0 <= mac_idx < len(names) else ""
        if not mname:
            wx.MessageBox("Bitte ein Makro auswählen.", "Hinweis", wx.OK, self)
            return
        self._scheduled.append({"time": t, "macro": mname})
        self._rebuild_schedule_list()
        self._persist()
        self._frame.set_status(f"Zeitplan {t} → '{mname}' gespeichert")

    def _on_schedule_del(self, _evt) -> None:
        idx = self._sc_lb.GetSelection()
        if idx == wx.NOT_FOUND:
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
        for ctrl in (self._t_macro, self._sc_macro):
            cur = ctrl.GetStringSelection()
            ctrl.Clear()
            for n in names:
                ctrl.Append(n)
            if cur in names:
                ctrl.SetSelection(names.index(cur))
            elif names:
                ctrl.SetSelection(0)

    def _persist(self) -> None:
        self._s.macros           = list(self._macros)
        self._s.macro_triggers   = list(self._triggers)
        self._s.scheduled_macros = list(self._scheduled)
        self._frame.settings_store.save()

    def _on_close(self, _evt) -> None:
        self._persist()
        self.EndModal(wx.ID_CLOSE)
