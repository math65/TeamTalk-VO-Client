from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import wx

if TYPE_CHECKING:
    from app import MainFrame


class ShortcutsTab(wx.Panel):
    """Settings: App-level shortcuts (within the app) and global hotkeys."""

    def __init__(self, parent: wx.Window, frame: MainFrame) -> None:
        super().__init__(parent)
        self.frame = frame
        self.SetName("Tastenkürzel")

        root = wx.BoxSizer(wx.VERTICAL)

        # --- In-app hotkeys ---
        inapp_box = wx.StaticBox(self, label="App-Hotkeys (nur innerhalb der App)")
        inapp_sizer = wx.StaticBoxSizer(inapp_box, wx.VERTICAL)

        self._rows = []
        self._rows.append(self._make_row(inapp_box, "Alles stummschalten", "hotkey_mute_all", global_key=False))
        self._rows.append(self._make_row(inapp_box, "Sprachaktivierung umschalten", "hotkey_voice_activation", global_key=False))
        self._rows.append(self._make_row(inapp_box, "Video senden umschalten", "hotkey_video_tx", global_key=False))
        self._rows.append(self._make_row(inapp_box, "Eingangspegel ansagen", "hotkey_announce_level", global_key=False))
        self._rows.append(self._make_row(inapp_box, "Nutzerinfo ansagen", "hotkey_announce_user_info", global_key=False))
        self._rows.append(self._make_row(inapp_box, "Ping ansagen", "hotkey_announce_ping", global_key=False))
        self._rows.append(self._make_row(inapp_box, "Privatantwort (letzter Absender)", "hotkey_reply_last_sender", global_key=False))
        self._rows.append(self._make_row(inapp_box, "Sound-Profil wechseln", "hotkey_cycle_sound_profile", global_key=False))
        self._rows.append(self._make_row(inapp_box, "Braille-Verbosität wechseln", "hotkey_cycle_braille_verbosity", global_key=False))
        self._rows.append(self._make_row(inapp_box, "KI-Zusammenfassung ansagen", "hotkey_ai_summary", global_key=False))
        self._rows.append(self._make_row(inapp_box, "Lesezeichen 1 springen", "hotkey_bookmark_1", global_key=False))
        self._rows.append(self._make_row(inapp_box, "Lesezeichen 2 springen", "hotkey_bookmark_2", global_key=False))
        self._rows.append(self._make_row(inapp_box, "Lesezeichen 3 springen", "hotkey_bookmark_3", global_key=False))
        self._rows.append(self._make_row(inapp_box, "Aufnahme umschalten", "hotkey_record_toggle", global_key=False))
        self._rows.append(self._make_row(inapp_box, "Status-Vorlage 1", "hotkey_status_template_1", global_key=False))
        self._rows.append(self._make_row(inapp_box, "Status-Vorlage 2", "hotkey_status_template_2", global_key=False))
        self._rows.append(self._make_row(inapp_box, "Status-Vorlage 3", "hotkey_status_template_3", global_key=False))
        # v2.9.0
        self._rows.append(self._make_row(inapp_box, "Mikrofon-Boost hoch", "hotkey_mic_boost_up", global_key=False))
        self._rows.append(self._make_row(inapp_box, "Mikrofon-Boost runter", "hotkey_mic_boost_down", global_key=False))

        for row in self._rows:
            inapp_sizer.Add(row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)

        root.Add(inapp_sizer, 0, wx.ALL | wx.EXPAND, 8)

        # --- Global hotkeys (macOS only) ---
        if sys.platform == "darwin":
            global_box = wx.StaticBox(self, label="Globale Hotkeys (systemweit, auch wenn App im Hintergrund)")
            global_sizer = wx.StaticBoxSizer(global_box, wx.VERTICAL)

            self._global_enable = wx.CheckBox(global_box, label="&Globale Hotkeys aktivieren")
            self._global_enable.SetName("Globale Hotkeys aktivieren")
            self._global_enable.SetValue(bool(frame.settings_store.settings.global_hotkeys_enabled))
            self._global_enable.Bind(wx.EVT_CHECKBOX, self._on_global_enable_changed)
            global_sizer.Add(self._global_enable, 0, wx.ALL, 8)

            self._global_rows = []
            self._global_rows.append(self._make_row(global_box, "PTT (Sprechtaste)", "global_hotkey_ptt", global_key=True))
            self._global_rows.append(self._make_row(global_box, "Stummschalten umschalten", "global_hotkey_mute", global_key=True))

            for row in self._global_rows:
                global_sizer.Add(row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)

            root.Add(global_sizer, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)
        else:
            self._global_enable = None
            self._global_rows = []

        # --- Profile import/export ---
        profile_box = wx.StaticBox(self, label="Profil Import/Export")
        profile_sizer = wx.StaticBoxSizer(profile_box, wx.HORIZONTAL)
        export_btn = wx.Button(profile_box, label="Profil &exportieren")
        export_btn.SetName("Tastenkürzel-Profil exportieren")
        export_btn.Bind(wx.EVT_BUTTON, self._on_export_profile)
        import_btn = wx.Button(profile_box, label="Profil &importieren")
        import_btn.SetName("Tastenkürzel-Profil importieren")
        import_btn.Bind(wx.EVT_BUTTON, self._on_import_profile)
        profile_sizer.Add(export_btn, 0, wx.ALL, 8)
        profile_sizer.Add(import_btn, 0, wx.ALL, 8)
        root.Add(profile_sizer, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)

        self.SetSizer(root)
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
        panel._is_global = global_key  # type: ignore[attr-defined]
        return panel

    def update_labels(self) -> None:
        settings = self.frame.settings_store.settings
        inapp_map = {
            "hotkey_mute_all": int(settings.hotkey_mute_all or 0),
            "hotkey_voice_activation": int(settings.hotkey_voice_activation or 0),
            "hotkey_video_tx": int(settings.hotkey_video_tx or 0),
            "hotkey_announce_level": int(settings.hotkey_announce_level or 0),
            "hotkey_announce_user_info": int(settings.hotkey_announce_user_info or 0),
            "hotkey_announce_ping": int(settings.hotkey_announce_ping or 0),
            "hotkey_reply_last_sender": int(settings.hotkey_reply_last_sender or 0),
            "hotkey_cycle_sound_profile": int(settings.hotkey_cycle_sound_profile or 0),
            "hotkey_cycle_braille_verbosity": int(getattr(settings, "hotkey_cycle_braille_verbosity", 0) or 0),
            "hotkey_ai_summary": int(getattr(settings, "hotkey_ai_summary", 0) or 0),
            "hotkey_bookmark_1": int(getattr(settings, "hotkey_bookmark_1", 0) or 0),
            "hotkey_bookmark_2": int(getattr(settings, "hotkey_bookmark_2", 0) or 0),
            "hotkey_bookmark_3": int(getattr(settings, "hotkey_bookmark_3", 0) or 0),
            "hotkey_record_toggle": int(getattr(settings, "hotkey_record_toggle", 0) or 0),
            "hotkey_status_template_1": int(getattr(settings, "hotkey_status_template_1", 0) or 0),
            "hotkey_status_template_2": int(getattr(settings, "hotkey_status_template_2", 0) or 0),
            "hotkey_status_template_3": int(getattr(settings, "hotkey_status_template_3", 0) or 0),
            # v2.9.0
            "hotkey_mic_boost_up": int(getattr(settings, "hotkey_mic_boost_up", 0) or 0),
            "hotkey_mic_boost_down": int(getattr(settings, "hotkey_mic_boost_down", 0) or 0),
        }
        global_map = {
            "global_hotkey_ptt": int(settings.global_hotkey_ptt or 0),
            "global_hotkey_mute": int(settings.global_hotkey_mute or 0),
        }
        all_rows = list(self._rows) + list(self._global_rows)
        for row in all_rows:
            key = getattr(row, "_hotkey_key", "")
            label = getattr(row, "_hotkey_label", None)
            is_global = getattr(row, "_is_global", False)
            if label is None:
                continue
            keycode = global_map.get(key, 0) if is_global else inapp_map.get(key, 0)
            if is_global:
                label.SetLabel(self._format_vk(keycode))
            else:
                label.SetLabel(self._format_keycode(keycode))

    def set_capture_label(self, key: str, capturing: bool) -> None:
        for row in self._rows:
            if getattr(row, "_hotkey_key", "") != key:
                continue
            label = getattr(row, "_hotkey_label", None)
            if label is None:
                return
            if capturing:
                label.SetLabel("(Taste drücken...)")
            else:
                self.update_labels()
            return

    def set_global_capture_label(self, key: str, capturing: bool) -> None:
        for row in self._global_rows:
            if getattr(row, "_hotkey_key", "") != key:
                continue
            label = getattr(row, "_hotkey_label", None)
            if label is None:
                return
            if capturing:
                label.SetLabel("(Taste drücken...)")
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

    def _on_export_profile(self, _event) -> None:
        """Exportiert alle App-Hotkeys als JSON-Profildatei."""
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
        """Importiert App-Hotkeys aus einer JSON-Profildatei."""
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
