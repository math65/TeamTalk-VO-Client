from __future__ import annotations

from typing import TYPE_CHECKING

import wx

from ui.a11y import setup_list_accessible

if TYPE_CHECKING:
    from app import MainFrame


class FilesTab(wx.Panel):
    """Tab 6: Dateien -- file list, upload, download, delete, transfer progress."""

    def __init__(self, parent: wx.Window, frame: MainFrame) -> None:
        super().__init__(parent)
        self.frame = frame
        self.SetName("Dateien")
        self._active_transfer_id = 0

        sizer = wx.BoxSizer(wx.VERTICAL)

        list_box = wx.StaticBox(self, label="Dateien im aktuellen Kanal")
        list_sizer = wx.StaticBoxSizer(list_box, wx.VERTICAL)
        header = wx.StaticText(list_box, label="Dateiname | Größe | Hochgeladen von | Datum")
        header.SetName("Dateiliste Kopfzeile")
        list_sizer.Add(header, 0, wx.LEFT | wx.RIGHT | wx.TOP, 8)

        # ListBox ist fuer VoiceOver verlaesslicher als ListCtrl auf macOS.
        self.file_list = wx.ListBox(list_box)
        self.file_list.SetName("Dateiliste")
        setup_list_accessible(self.file_list)
        list_sizer.Add(self.file_list, 1, wx.ALL | wx.EXPAND, 8)
        sizer.Add(list_sizer, 1, wx.ALL | wx.EXPAND, 8)

        action_box = wx.StaticBox(self, label="Aktionen")
        action_sizer = wx.StaticBoxSizer(action_box, wx.VERTICAL)
        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        self.upload_btn = wx.Button(self, label="Hochladen")
        self.upload_btn.SetName("Datei hochladen")
        self.upload_btn.Bind(wx.EVT_BUTTON, self.on_upload)
        self.download_btn = wx.Button(self, label="Herunterladen")
        self.download_btn.SetName("Datei herunterladen")
        self.download_btn.Bind(wx.EVT_BUTTON, self.on_download)
        self.delete_btn = wx.Button(self, label="Löschen")
        self.delete_btn.SetName("Datei löschen")
        self.delete_btn.Bind(wx.EVT_BUTTON, self.on_delete)
        self.refresh_btn = wx.Button(self, label="Aktualisieren")
        self.refresh_btn.SetName("Dateiliste aktualisieren")
        self.refresh_btn.Bind(wx.EVT_BUTTON, self.on_refresh)
        for btn in (self.upload_btn, self.download_btn, self.delete_btn, self.refresh_btn):
            btn_row.Add(btn, 0, wx.RIGHT, 8)
        action_sizer.Add(btn_row, 0, wx.ALL, 8)
        sizer.Add(action_sizer, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)

        transfer_box = wx.StaticBox(self, label="Dateiübertragung")
        transfer_sizer = wx.StaticBoxSizer(transfer_box, wx.VERTICAL)
        self.transfer_gauge = wx.Gauge(transfer_box, range=100)
        self.transfer_gauge.SetName("Übertragungsfortschritt")
        transfer_sizer.Add(self.transfer_gauge, 0, wx.ALL | wx.EXPAND, 8)
        sizer.Add(transfer_sizer, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)

        self.SetSizer(sizer)


        self._file_ids = []  # parallel to list rows

    def _format_size(self, size_bytes: int) -> str:
        if size_bytes < 1024:
            return f"{size_bytes} B"
        if size_bytes < 1024 * 1024:
            return f"{size_bytes // 1024} KB"
        return f"{size_bytes // (1024 * 1024)} MB"

    def refresh_file_list(self):
        ch_id = self.frame.client.get_my_channel_id()
        if not ch_id:
            self.frame.set_status("Kein Kanal beigetreten")
            return
        files = self.frame.client.get_channel_files(int(ch_id))
        self.file_list.Set([])
        self._file_ids = []
        tt_str = self.frame.tt_str
        items = []
        for f in files:
            name = tt_str(f.szFileName)
            size = self._format_size(int(f.nFileSize))
            user = tt_str(f.szUsername)
            date = tt_str(f.szUploadTime)
            items.append(f"{name} | {size} | {user} | {date}")
            self._file_ids.append(int(f.nFileID))
        if items:
            self.file_list.Set(items)
        else:
            self.frame.set_status("Keine Dateien im aktuellen Kanal")

    def on_refresh(self, _event):
        self.refresh_file_list()
        self.frame.set_status("Dateiliste aktualisiert")

    def on_upload(self, _event):
        ch_id = self.frame.client.get_my_channel_id()
        if not ch_id:
            self.frame.set_status("Kein Kanal beigetreten")
            return
        with wx.FileDialog(self, "Datei hochladen") as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            path = dlg.GetPath()
        tid = self.frame.client.send_file(int(ch_id), path)
        if tid > 0:
            self._active_transfer_id = tid
            self.frame.set_status("Upload gestartet")
        else:
            self.frame.set_status("Upload fehlgeschlagen")

    def on_download(self, _event):
        sel = self.file_list.GetSelection()
        if sel == wx.NOT_FOUND or sel >= len(self._file_ids):
            self.frame.set_status("Bitte eine Datei auswählen")
            return
        file_id = self._file_ids[sel]
        ch_id = self.frame.client.get_my_channel_id()
        if not ch_id:
            return
        name = self.file_list.GetString(sel)
        with wx.FileDialog(
            self, "Datei speichern unter", defaultFile=name,
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
        ) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            path = dlg.GetPath()
        tid = self.frame.client.recv_file(int(ch_id), file_id, path)
        if tid > 0:
            self._active_transfer_id = tid
            self.frame.set_status("Download gestartet")
        else:
            self.frame.set_status("Download fehlgeschlagen")

    def on_delete(self, _event):
        sel = self.file_list.GetSelection()
        if sel == wx.NOT_FOUND or sel >= len(self._file_ids):
            self.frame.set_status("Bitte eine Datei auswählen")
            return
        file_id = self._file_ids[sel]
        ch_id = self.frame.client.get_my_channel_id()
        if not ch_id:
            return
        name = self.file_list.GetString(sel).split(" | ")[0]
        dlg = wx.MessageDialog(
            self, f"Datei '{name}' wirklich löschen?",
            "Datei löschen", wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION,
        )
        dlg.SetYesNoLabels("Ja", "Nein")
        if dlg.ShowModal() != wx.ID_YES:
            dlg.Destroy()
            return
        dlg.Destroy()
        self.frame.client.delete_file(int(ch_id), file_id)
        self.frame.set_status("Datei gelöscht")
        wx.CallLater(500, self.refresh_file_list)

    def on_file_transfer_update(self, transfer_id: int):
        ft = self.frame.client.get_file_transfer_info(transfer_id)
        if ft is None:
            return
        total = int(ft.nFileSize)
        transferred = int(ft.nTransferred)
        if total > 0:
            pct = min(100, int(transferred * 100 / total))
            self.transfer_gauge.SetValue(pct)
        # Check completion
        if transferred >= total and total > 0:
            self.transfer_gauge.SetValue(100)
            self.frame.set_status("Dateitransfer abgeschlossen")
            wx.CallLater(500, self.refresh_file_list)


