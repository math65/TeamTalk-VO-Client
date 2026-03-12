from __future__ import annotations

from typing import TYPE_CHECKING, List

import wx
import zipfile
from datetime import datetime

from .audio import AudioTab
from .system import SystemTab
from platform_paths import app_data_dir, log_dir

if TYPE_CHECKING:
    from app import MainFrame


class SettingsTab(wx.Panel):
    """Settings container for Audio and System/TTS sections."""

    def __init__(self, parent: wx.Window, frame: MainFrame) -> None:
        super().__init__(parent)
        self.frame = frame
        self.SetName("Einstellungen")

        root = wx.BoxSizer(wx.VERTICAL)

        top_row = wx.BoxSizer(wx.HORIZONTAL)
        top_row.Add(wx.StaticText(self, label="Bereich"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.section_choice = wx.Choice(self, choices=["Audio", "System & TTS"])
        self.section_choice.SetName("Einstellungsbereich")
        self.section_choice.SetSelection(0)
        self.section_choice.Bind(wx.EVT_CHOICE, self._on_section_changed)
        top_row.Add(self.section_choice, 1, wx.EXPAND)
        root.Add(top_row, 0, wx.ALL | wx.EXPAND, 8)

        # --- Log sharing ---
        log_row = wx.BoxSizer(wx.HORIZONTAL)
        self.share_logs_btn = wx.Button(self, label="Logs senden")
        self.share_logs_btn.SetName("Logs senden")
        self.share_logs_btn.Bind(wx.EVT_BUTTON, self._on_share_logs_menu)
        log_row.Add(self.share_logs_btn, 0, wx.RIGHT, 8)
        log_row.Add(wx.StaticText(self, label="Sende deine Logs an den Entwickler"), 0, wx.ALIGN_CENTER_VERTICAL)
        root.Add(log_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        self.audio_tab = AudioTab(self, frame)
        self.system_tab = SystemTab(self, frame)
        self._sections = {
            "Audio": self.audio_tab,
            "System & TTS": self.system_tab,
        }

        root.Add(self.audio_tab, 1, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)
        root.Add(self.system_tab, 1, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)

        self.SetSizer(root)
        self._show_section("Audio")

    def _on_section_changed(self, _event):
        self._show_section(self.section_choice.GetStringSelection())

    def _on_share_logs_menu(self, _event):
        menu = wx.Menu()
        export_item = menu.Append(wx.ID_ANY, "Logs exportieren (ZIP)")
        copy_item = menu.Append(wx.ID_ANY, "Logs kopieren")
        both_item = menu.Append(wx.ID_ANY, "Beides (ZIP + Kopieren)")
        self.Bind(wx.EVT_MENU, lambda evt: self._export_logs_zip(), export_item)
        self.Bind(wx.EVT_MENU, lambda evt: self._copy_logs_to_clipboard(), copy_item)
        self.Bind(wx.EVT_MENU, lambda evt: self._export_and_copy_logs(), both_item)
        self.PopupMenu(menu)
        menu.Destroy()

    def _collect_log_paths(self) -> List:
        paths = []
        # Primary logs
        paths.append(app_data_dir() / "client.log")
        paths.append(log_dir() / "startup.log")
        paths.append(log_dir() / "last_crash.txt")
        return [p for p in paths if p.exists()]

    def _copy_logs_to_clipboard(self) -> None:
        paths = self._collect_log_paths()
        if not paths:
            self.frame.set_status("Keine Logdateien gefunden")
            return
        parts = []
        for path in paths:
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except Exception as exc:
                text = f"[Fehler beim Lesen: {exc}]"
            parts.append(f"===== {path.name} =====\n{text}\n")
        payload = "\n".join(parts)
        if wx.TheClipboard.Open():
            wx.TheClipboard.SetData(wx.TextDataObject(payload))
            wx.TheClipboard.Close()
            self.frame.set_status("Logs in die Zwischenablage kopiert")
        else:
            self.frame.set_status("Zwischenablage konnte nicht geoeffnet werden")

    def _export_logs_zip(self) -> None:
        paths = self._collect_log_paths()
        if not paths:
            self.frame.set_status("Keine Logdateien gefunden")
            return
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"TeamTalkVOClient_logs_{ts}.zip"
        with wx.FileDialog(
            self,
            "Logs exportieren",
            wildcard="ZIP (*.zip)|*.zip",
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
            defaultFile=default_name,
        ) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            out_path = dlg.GetPath()
        try:
            with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                for path in paths:
                    zf.write(path, arcname=path.name)
            self.frame.set_status(f"Logs exportiert: {out_path}")
        except Exception as exc:
            self.frame.set_status(f"Log-Export fehlgeschlagen: {exc}")

    def _export_and_copy_logs(self) -> None:
        self._export_logs_zip()
        self._copy_logs_to_clipboard()

    def _show_section(self, section: str) -> None:
        for name, panel in self._sections.items():
            panel.Show(name == section)
        self.Layout()
