from __future__ import annotations

import sys
from typing import TYPE_CHECKING, List, Tuple

import wx

if TYPE_CHECKING:
    from app import MainFrame

_INAPP_CATEGORIES: List[Tuple[str, List[Tuple[str, str]]]] = [
    ("Audio & Aufnahme", [
        ("Alles stummschalten", "hotkey_mute_all"),
        ("Sprachaktivierung umschalten", "hotkey_voice_activation"),
        ("Video senden umschalten", "hotkey_video_tx"),
        ("Ausgabelautstärke hoch", "hotkey_volume_up"),
        ("Ausgabelautstärke runter", "hotkey_volume_down"),
        ("Mikrofon-Boost hoch", "hotkey_mic_boost_up"),
        ("Mikrofon-Boost runter", "hotkey_mic_boost_down"),
        ("Aufnahme umschalten", "hotkey_record_toggle"),
    ]),
    ("Ansagen & TTS", [
        ("Eingangspegel ansagen", "hotkey_announce_level"),
        ("Nutzerinfo ansagen", "hotkey_announce_user_info"),
        ("Ping ansagen", "hotkey_announce_ping"),
        ("Braille-Status ansagen", "hotkey_announce_status"),
        ("TTS abbrechen", "hotkey_tts_cancel"),
        ("Braille-Verbosität wechseln", "hotkey_cycle_braille_verbosity"),
        ("Sound-Profil wechseln", "hotkey_cycle_sound_profile"),
    ]),
    ("Navigation & Chat", [
        ("Privatantwort (letzter Absender)", "hotkey_reply_last_sender"),
        ("Lesezeichen 1 springen", "hotkey_bookmark_1"),
        ("Lesezeichen 2 springen", "hotkey_bookmark_2"),
        ("Lesezeichen 3 springen", "hotkey_bookmark_3"),
        ("Lesezeichen 4 springen", "hotkey_bookmark_4"),
        ("Lesezeichen 5 springen", "hotkey_bookmark_5"),
        ("Lesezeichen 6 springen", "hotkey_bookmark_6"),
        ("Lesezeichen 7 springen", "hotkey_bookmark_7"),
        ("Lesezeichen 8 springen", "hotkey_bookmark_8"),
        ("Lesezeichen 9 springen", "hotkey_bookmark_9"),
    ]),
    ("KI & Automatisierung", [
        ("KI-Zusammenfassung ansagen", "hotkey_ai_summary"),
        ("KI-Antwortvorschläge", "hotkey_ai_reply_suggestions"),
        ("Status-Vorlage 1", "hotkey_status_template_1"),
        ("Status-Vorlage 2", "hotkey_status_template_2"),
        ("Status-Vorlage 3", "hotkey_status_template_3"),
    ]),
]


class ShortcutsTab(wx.Panel):
    """Tab 11: Tastenkürzel – kategorisiert, durchsuchbar, mit Alle-zurücksetzen."""

    def __init__(self, parent: wx.Window, frame: MainFrame) -> None:
        super().__init__(parent)
        self.frame = frame
        self.SetName("Tastenkürzel")

        outer = wx.BoxSizer(wx.VERTICAL)

        # --- Search field ---
        search_row = wx.BoxSizer(wx.HORIZONTAL)
        search_lbl = wx.StaticText(self, label="Suche:")
        self._search = wx.TextCtrl(self, value="")
        self._search.SetName("Tastenkürzel suchen")
        self._search.SetHelpText("Stichwort eingeben, um Tastenkürzel zu filtern")
        self._search.Bind(wx.EVT_TEXT, self._on_search_changed)
        clear_search_btn = wx.Button(self, label="Such&e löschen")
        clear_search_btn.SetName("Suche löschen")
        clear_search_btn.Bind(wx.EVT_BUTTON, lambda _: self._search.SetValue(""))
        search_row.Add(search_lbl, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        search_row.Add(self._search, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        search_row.Add(clear_search_btn, 0)
        outer.Add(search_row, 0, wx.ALL | wx.EXPAND, 8)

        # --- Scrolled content area ---
        self._scroll = wx.ScrolledWindow(self, style=wx.TAB_TRAVERSAL | wx.VSCROLL)
        self._scroll.SetScrollRate(0, 20)
        scroll_sizer = wx.BoxSizer(wx.VERTICAL)

        self._rows: List = []
        self._global_rows: List = []
        self._sections: List[Tuple] = []  # (header_lbl, [row_panels])

        bold_font = wx.Font(wx.FontInfo().Bold())

        for cat_name, entries in _INAPP_CATEGORIES:
            header = wx.StaticText(self._scroll, label=cat_name)
            header.SetFont(bold_font)
            header.SetName(cat_name)
            scroll_sizer.Add(header, 0, wx.LEFT | wx.TOP, 8)
            scroll_sizer.Add(wx.StaticLine(self._scroll), 0, wx.LEFT | wx.RIGHT | wx.EXPAND | wx.BOTTOM, 8)
            cat_rows = []
            for label, key in entries:
                row = self._make_row(self._scroll, label, key, global_key=False)
                scroll_sizer.Add(row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)
                cat_rows.append(row)
                self._rows.append(row)
            self._sections.append((header, cat_rows))

        # --- Global hotkeys (macOS only) ---
        if sys.platform == "darwin":
            g_header = wx.StaticText(self._scroll, label="Globale Hotkeys (systemweit, auch wenn App im Hintergrund)")
            g_header.SetFont(bold_font)
            g_header.SetName("Globale Hotkeys")
            scroll_sizer.Add(g_header, 0, wx.LEFT | wx.TOP, 8)
            scroll_sizer.Add(wx.StaticLine(self._scroll), 0, wx.LEFT | wx.RIGHT | wx.EXPAND | wx.BOTTOM, 8)

            self._global_enable = wx.CheckBox(self._scroll, label="&Globale Hotkeys aktivieren")
            self._global_enable.SetName("Globale Hotkeys aktivieren")
            self._global_enable.SetValue(bool(frame.settings_store.settings.global_hotkeys_enabled))
            self._global_enable.Bind(wx.EVT_CHECKBOX, self._on_global_enable_changed)
            scroll_sizer.Add(self._global_enable, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

            for label, key in [("PTT (Sprechtaste)", "global_hotkey_ptt"),
                                ("Stummschalten umschalten", "global_hotkey_mute")]:
                row = self._make_row(self._scroll, label, key, global_key=True)
                scroll_sizer.Add(row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)
                self._global_rows.append(row)
        else:
            self._global_enable = None

        self._scroll.SetSizer(scroll_sizer)
        self._scroll.FitInside()
        outer.Add(self._scroll, 1, wx.LEFT | wx.RIGHT | wx.EXPAND, 0)

        # --- Bottom toolbar ---
        bottom_row = wx.BoxSizer(wx.HORIZONTAL)
        export_btn = wx.Button(self, label="Profil &exportieren")
        export_btn.SetName("Tastenkürzel-Profil exportieren")
        export_btn.Bind(wx.EVT_BUTTON, self._on_export_profile)
        import_btn = wx.Button(self, label="Profil &importieren")
        import_btn.SetName("Tastenkürzel-Profil importieren")
        import_btn.Bind(wx.EVT_BUTTON, self._on_import_profile)
        reset_all_btn = wx.Button(self, label="A&lle zurücksetzen")
        reset_all_btn.SetName("Alle Tastenkürzel zurücksetzen")
        reset_all_btn.Bind(wx.EVT_BUTTON, self._on_reset_all)
        bottom_row.Add(export_btn, 0, wx.RIGHT, 8)
        bottom_row.Add(import_btn, 0, wx.RIGHT, 8)
        bottom_row.Add(reset_all_btn, 0)
        outer.Add(bottom_row, 0, wx.ALL, 8)

        self.SetSizer(outer)
        self.update_labels()

    def _make_row(self, parent: wx.Window, label: str, key: str, global_key: bool) -> wx.Panel:
        panel = wx.Panel(parent)
        sizer = wx.BoxSizer(wx.HORIZONTAL)
        title = wx.StaticText(panel, label=label)
        title.SetMinSize((260, -1))
        hotkey_label = wx.StaticText(panel, label="(nicht gesetzt)")
        hotkey_label.SetName(f"{label} Hotkey")
        btn = wx.Button(panel, label="&Hotkey aufnehmen")
        btn.SetName(f"{label} Hotkey aufnehmen")
        if global_key:
            btn.Bind(wx.EVT_BUTTON, lambda _evt, k=key: self.frame.start_global_hotkey_capture(k))
        else:
            btn.Bind(wx.EVT_BUTTON, lambda _evt, k=key: self.frame.start_hotkey_capture(k))
        sizer.Add(title, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        sizer.Add(hotkey_label, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        sizer.Add(btn, 0)
        panel.SetSizer(sizer)
        panel._hotkey_key = key  # type: ignore[attr-defined]
        panel._hotkey_label = hotkey_label  # type: ignore[attr-defined]
        panel._hotkey_title = label  # type: ignore[attr-defined]
        panel._is_global = global_key  # type: ignore[attr-defined]
        return panel

    def _on_search_changed(self, _event) -> None:
        q = self._search.GetValue().strip().lower()
        for header, cat_rows in self._sections:
            any_visible = False
            for row in cat_rows:
                title = getattr(row, "_hotkey_title", "").lower()
                visible = not q or q in title
                row.Show(visible)
                if visible:
                    any_visible = True
            header.Show(any_visible)
        self._scroll.FitInside()
        self._scroll.Refresh()

    def update_labels(self) -> None:
        settings = self.frame.settings_store.settings
        all_rows = list(self._rows) + list(self._global_rows)
        for row in all_rows:
            key = getattr(row, "_hotkey_key", "")
            lbl = getattr(row, "_hotkey_label", None)
            if lbl is None:
                continue
            is_global = getattr(row, "_is_global", False)
            keycode = int(getattr(settings, key, 0) or 0)
            lbl.SetLabel(self._format_vk(keycode) if is_global else self._format_keycode(keycode))

    def set_capture_label(self, key: str, capturing: bool) -> None:
        for row in self._rows:
            if getattr(row, "_hotkey_key", "") != key:
                continue
            lbl = getattr(row, "_hotkey_label", None)
            if lbl is None:
                return
            if capturing:
                lbl.SetLabel("(Taste drücken...)")
            else:
                self.update_labels()
            return

    def set_global_capture_label(self, key: str, capturing: bool) -> None:
        for row in self._global_rows:
            if getattr(row, "_hotkey_key", "") != key:
                continue
            lbl = getattr(row, "_hotkey_label", None)
            if lbl is None:
                return
            if capturing:
                lbl.SetLabel("(Taste drücken...)")
            else:
                self.update_labels()
            return

    def _on_global_enable_changed(self, _event) -> None:
        enabled = self._global_enable.GetValue()
        self.frame.settings_store.settings.global_hotkeys_enabled = enabled
        self.frame.settings_store.save()
        self.frame.apply_global_hotkeys()

    def _format_keycode(self, keycode: int) -> str:
        if not keycode:
            return "(nicht gesetzt)"
        if keycode == wx.WXK_SPACE:
            return "Leertaste"
        if wx.WXK_F1 <= keycode <= wx.WXK_F24:
            return f"F{int(keycode - wx.WXK_F1 + 1)}"
        if 32 <= keycode <= 126:
            return chr(keycode).upper()
        return str(int(keycode))

    def _format_vk(self, vk: int) -> str:
        if not vk:
            return "(nicht gesetzt)"
        try:
            from global_hotkeys import vk_to_name
            return vk_to_name(vk)
        except Exception:
            return f"VK-{vk:#04x}"

    def _on_reset_all(self, _event) -> None:
        confirm = wx.MessageDialog(
            self, "Alle Tastenkürzel auf '(nicht gesetzt)' zurücksetzen?",
            "Alle zurücksetzen", wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION,
        )
        confirm.SetYesNoLabels("Ja", "Nein")
        if confirm.ShowModal() != wx.ID_YES:
            confirm.Destroy()
            return
        confirm.Destroy()
        import dataclasses
        s = self.frame.settings_store.settings
        for f in dataclasses.fields(s):
            if f.name.startswith("hotkey_") or f.name.startswith("global_hotkey_"):
                setattr(s, f.name, 0)
        self.frame.settings_store.save()
        self.update_labels()
        self.frame.set_status("Alle Tastenkürzel zurückgesetzt")

    def _on_export_profile(self, _event) -> None:
        import json
        import dataclasses
        s = self.frame.settings_store.settings
        profile = {
            f.name: getattr(s, f.name)
            for f in dataclasses.fields(s)
            if f.name.startswith("hotkey_") or f.name.startswith("global_hotkey_")
        }
        with wx.FileDialog(
            self, "Tastenkürzel-Profil exportieren",
            wildcard="JSON-Profil (*.json)|*.json|Alle Dateien|*.*",
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
            defaultFile="shortcuts_profil.json",
        ) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            path = dlg.GetPath()
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(profile, f, indent=2, ensure_ascii=False)
            self.frame.set_status(f"Profil exportiert: {path}")
        except Exception as exc:
            self.frame.set_status(f"Export fehlgeschlagen: {exc}")

    def _on_import_profile(self, _event) -> None:
        import json
        import dataclasses
        with wx.FileDialog(
            self, "Tastenkürzel-Profil importieren",
            wildcard="JSON-Profil (*.json)|*.json|Alle Dateien|*.*",
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        ) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            path = dlg.GetPath()
        try:
            with open(path, "r", encoding="utf-8") as f:
                profile = json.load(f)
        except Exception as exc:
            self.frame.set_status(f"Import fehlgeschlagen: {exc}")
            return
        s = self.frame.settings_store.settings
        valid_keys = {
            f.name for f in dataclasses.fields(s)
            if f.name.startswith("hotkey_") or f.name.startswith("global_hotkey_")
        }
        count = 0
        for key, value in profile.items():
            if key in valid_keys:
                try:
                    setattr(s, key, int(value or 0))
                    count += 1
                except Exception:
                    pass
        self.frame.settings_store.save()
        self.update_labels()
        self.frame.set_status(f"Profil importiert: {count} Tastenkürzel übernommen")
