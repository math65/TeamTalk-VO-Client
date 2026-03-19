from __future__ import annotations

from typing import TYPE_CHECKING

import wx

if TYPE_CHECKING:
    from app import MainFrame


class ShortcutsTab(wx.Panel):
    """Settings: App-level shortcuts (within the app)."""

    def __init__(self, parent: wx.Window, frame: MainFrame) -> None:
        super().__init__(parent)
        self.frame = frame
        self.SetName("Shortcuts")

        root = wx.BoxSizer(wx.VERTICAL)

        note = wx.StaticText(self, label="Hinweis: Hotkeys funktionieren nur innerhalb der App.")
        root.Add(note, 0, wx.ALL, 8)

        self._rows = []
        self._rows.append(self._make_row("Alles stummschalten", "hotkey_mute_all"))
        self._rows.append(self._make_row("Voice Activation umschalten", "hotkey_voice_activation"))
        self._rows.append(self._make_row("Video senden umschalten", "hotkey_video_tx"))

        for row in self._rows:
            root.Add(row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)

        self.SetSizer(root)
        self.update_labels()

    def _make_row(self, label: str, key: str) -> wx.Panel:
        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.HORIZONTAL)
        title = wx.StaticText(panel, label=label)
        title.SetMinSize((260, -1))
        hotkey_label = wx.StaticText(panel, label="(nicht gesetzt)")
        hotkey_label.SetName(f"{label} Hotkey")
        btn = wx.Button(panel, label="Hotkey aufnehmen")
        btn.SetName(f"{label} Hotkey aufnehmen")
        btn.Bind(wx.EVT_BUTTON, lambda _evt, k=key: self.frame.start_hotkey_capture(k))
        sizer.Add(title, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        sizer.Add(hotkey_label, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        sizer.Add(btn, 0)
        panel.SetSizer(sizer)
        panel._hotkey_key = key  # type: ignore[attr-defined]
        panel._hotkey_label = hotkey_label  # type: ignore[attr-defined]
        return panel

    def update_labels(self) -> None:
        settings = self.frame.settings_store.settings
        mapping = {
            "hotkey_mute_all": int(settings.hotkey_mute_all or 0),
            "hotkey_voice_activation": int(settings.hotkey_voice_activation or 0),
            "hotkey_video_tx": int(settings.hotkey_video_tx or 0),
        }
        for row in self._rows:
            key = getattr(row, "_hotkey_key", "")
            label = getattr(row, "_hotkey_label", None)
            if label is None:
                continue
            keycode = mapping.get(key, 0)
            label.SetLabel(self._format_keycode(keycode))

    def set_capture_label(self, key: str, capturing: bool) -> None:
        for row in self._rows:
            if getattr(row, "_hotkey_key", "") != key:
                continue
            label = getattr(row, "_hotkey_label", None)
            if label is None:
                return
            if capturing:
                label.SetLabel("(Taste druecken...)")
            else:
                self.update_labels()
            return

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
