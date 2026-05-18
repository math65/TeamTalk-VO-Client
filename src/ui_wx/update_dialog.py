"""update_dialog (wx) – Update-Manager-Dialog für macOS."""
from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import List, Optional

import wx

import update_manager as um


class UpdateManagerDialog(wx.Dialog):
    def __init__(self, parent, current_version: str):
        super().__init__(parent, title="Update-Manager", size=(620, 520),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self._current = current_version.lstrip("v")
        self._releases: List[um.Release] = []
        self._selected: Optional[um.Release] = None
        self._download_path: Optional[str] = None
        self._build_ui()
        self._bind()
        wx.CallAfter(self._load_releases)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        outer = wx.BoxSizer(wx.VERTICAL)

        # Header
        header = wx.StaticText(self, label=f"Installierte Version: v{self._current}")
        font = header.GetFont()
        font.MakeBold()
        header.SetFont(font)
        outer.Add(header, 0, wx.ALL, 10)

        splitter = wx.BoxSizer(wx.HORIZONTAL)

        # Linke Seite: Versionsliste
        left = wx.BoxSizer(wx.VERTICAL)
        left.Add(wx.StaticText(self, label="Verfügbare Versionen:"), 0, wx.LEFT | wx.BOTTOM, 4)
        self._list = wx.ListBox(self, style=wx.LB_SINGLE)
        self._list.SetName("Versionsliste")
        left.Add(self._list, 1, wx.EXPAND)
        splitter.Add(left, 1, wx.EXPAND | wx.RIGHT, 8)

        # Rechte Seite: Changelog
        right = wx.BoxSizer(wx.VERTICAL)
        right.Add(wx.StaticText(self, label="Changelog:"), 0, wx.BOTTOM, 4)
        self._changelog = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_BESTWRAP)
        self._changelog.SetName("Changelog")
        right.Add(self._changelog, 1, wx.EXPAND)
        splitter.Add(right, 2, wx.EXPAND)

        outer.Add(splitter, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        # Fortschrittsbalken
        self._progress = wx.Gauge(self, range=100)
        self._progress.SetName("Download-Fortschritt")
        self._progress.Hide()
        outer.Add(self._progress, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 10)

        # Statuszeile
        self._status = wx.StaticText(self, label="Versionen werden geladen…")
        outer.Add(self._status, 0, wx.LEFT | wx.TOP | wx.BOTTOM, 10)

        # Buttons
        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        self._btn_refresh = wx.Button(self, label="Aktualisieren")
        self._btn_download = wx.Button(self, label="Herunterladen")
        self._btn_open = wx.Button(self, label="Im Finder anzeigen")
        self._btn_close = wx.Button(self, id=wx.ID_CLOSE, label="Schließen")
        self._btn_download.Disable()
        self._btn_open.Hide()
        btn_row.Add(self._btn_refresh, 0, wx.RIGHT, 6)
        btn_row.Add(self._btn_download, 0, wx.RIGHT, 6)
        btn_row.Add(self._btn_open, 0, wx.RIGHT, 6)
        btn_row.AddStretchSpacer()
        btn_row.Add(self._btn_close, 0)
        outer.Add(btn_row, 0, wx.EXPAND | wx.ALL, 10)

        self.SetSizer(outer)
        self.Layout()
        accel = wx.AcceleratorTable([
            (wx.ACCEL_CMD, ord("W"), wx.ID_CLOSE),
            (wx.ACCEL_CMD, ord("Q"), wx.ID_EXIT),
        ])
        self.SetAcceleratorTable(accel)

    def _bind(self):
        self._list.Bind(wx.EVT_LISTBOX, self._on_select)
        self._btn_refresh.Bind(wx.EVT_BUTTON, self._on_refresh)
        self._btn_download.Bind(wx.EVT_BUTTON, self._on_download)
        self._btn_open.Bind(wx.EVT_BUTTON, self._on_open)
        self.Bind(wx.EVT_MENU, lambda e: self.EndModal(wx.ID_CANCEL), id=wx.ID_CLOSE)
        self._btn_close.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_CANCEL))
        self.Bind(wx.EVT_MENU, self._on_app_quit, id=wx.ID_EXIT)

    # ------------------------------------------------------------------
    # Releases laden
    # ------------------------------------------------------------------

    def _load_releases(self):
        self._set_status("Versionen werden geladen…")
        self._btn_refresh.Disable()

        def worker():
            try:
                releases = um.fetch_releases(limit=50)
                wx.CallAfter(self._on_releases_loaded, releases)
            except Exception as exc:
                wx.CallAfter(self._set_status, f"Fehler beim Laden: {exc}")
                wx.CallAfter(self._btn_refresh.Enable)

        threading.Thread(target=worker, daemon=True).start()

    def _on_releases_loaded(self, releases: List[um.Release]):
        self._releases = releases
        self._list.Clear()
        current_v = self._current.lstrip("v")
        for r in releases:
            tag = r.tag.lstrip("v")
            marker = " ★ NEU" if _version_gt(tag, current_v) else (" ✓ aktuell" if tag == current_v else "")
            has_asset = r.platform_asset is not None
            size_str = f", {um.format_size(r.platform_asset.size)}" if has_asset else ", kein macOS-Asset"
            self._list.Append(f"{r.tag}, {r.date}{marker}{size_str}")
        self._btn_refresh.Enable()
        if releases:
            self._set_status(f"{len(releases)} Versionen geladen.")
            self._list.SetSelection(0)
            self._on_select(None)
        else:
            self._set_status("Keine Versionen gefunden.")

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def _on_select(self, _event):
        idx = self._list.GetSelection()
        if idx == wx.NOT_FOUND or idx >= len(self._releases):
            return
        self._selected = self._releases[idx]
        body = (self._selected.body or "(kein Changelog)").replace("\r\n", "\n").replace("\r", "\n")
        self._changelog.SetValue(body)
        has_asset = self._selected.platform_asset is not None
        self._btn_download.Enable(has_asset)
        if not has_asset:
            self._set_status("Kein macOS-Asset für diese Version verfügbar.")
        else:
            self._set_status(f"Bereit zum Herunterladen: {self._selected.tag}")

    def _on_refresh(self, _event):
        self._download_path = None
        self._btn_open.Hide()
        self.Layout()
        self._load_releases()

    def _on_download(self, _event):
        if not self._selected or not self._selected.platform_asset:
            return
        asset = self._selected.platform_asset
        dest = str(Path.home() / "Downloads")
        self._btn_download.Disable()
        self._btn_refresh.Disable()
        self._progress.SetValue(0)
        self._progress.Show()
        self.Layout()
        self._set_status(f"Lade herunter: {asset.name}…")

        def worker():
            try:
                def on_progress(done, total):
                    if total > 0:
                        pct = min(100, int(done * 100 / total))
                        wx.CallAfter(self._progress.SetValue, pct)
                        wx.CallAfter(self._set_status,
                                     f"{um.format_size(done)} / {um.format_size(total)}")
                    else:
                        wx.CallAfter(self._set_status, f"{um.format_size(done)} heruntergeladen…")

                path = um.download_asset(asset, dest, progress_cb=on_progress)
                wx.CallAfter(self._on_download_done, path)
            except Exception as exc:
                wx.CallAfter(self._on_download_error, str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _on_download_done(self, path: str):
        self._download_path = path
        self._progress.SetValue(100)
        self._btn_download.Enable()
        self._btn_refresh.Enable()
        self._btn_open.Show()
        self.Layout()
        self._set_status(f"Download abgeschlossen: {os.path.basename(path)}")
        # DMG direkt öffnen anbieten
        if path.endswith(".dmg"):
            if wx.MessageBox(
                f"Download abgeschlossen:\n{path}\n\nDMG jetzt öffnen?",
                "Download fertig",
                wx.YES_NO | wx.ICON_QUESTION,
                self,
            ) == wx.YES:
                um.open_file_or_folder(path)

    def _on_download_error(self, msg: str):
        self._progress.Hide()
        self.Layout()
        self._btn_download.Enable()
        self._btn_refresh.Enable()
        self._set_status(f"Fehler: {msg}")

    def _on_open(self, _event):
        if self._download_path:
            um.reveal_in_finder(self._download_path)

    def _on_app_quit(self, _event):
        self.EndModal(wx.ID_CANCEL)
        wx.CallAfter(wx.GetApp().GetTopWindow().Close)

    def _set_status(self, text: str):
        self._status.SetLabel(text)


# ------------------------------------------------------------------
# Hilfsfunktion: Versionsvergleich
# ------------------------------------------------------------------

def _version_gt(a: str, b: str) -> bool:
    """True wenn Version a neuer als b ist."""
    def parts(v: str):
        return tuple(int(x) for x in v.lstrip("v").split(".") if x.isdigit())
    try:
        return parts(a) > parts(b)
    except Exception:
        return False
