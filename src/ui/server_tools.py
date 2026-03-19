from __future__ import annotations

from typing import TYPE_CHECKING, Optional, List

import wx

if TYPE_CHECKING:
    from app import MainFrame


class BroadcastMessageDialog(wx.Dialog):
    def __init__(self, parent: wx.Window) -> None:
        super().__init__(parent, title="Servernachricht senden", style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.SetName("Servernachricht senden")

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(wx.StaticText(self, label="Nachricht an alle verbundenen Nutzer senden:"), 0, wx.ALL, 8)

        self.message = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_RICH2)
        self.message.SetName("Broadcast Nachricht")
        self.message.SetMinSize((520, 180))
        sizer.Add(self.message, 1, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)

        btns = self.CreateSeparatedButtonSizer(wx.OK | wx.CANCEL)
        if btns:
            sizer.Add(btns, 0, wx.ALL | wx.EXPAND, 8)

        self.SetSizerAndFit(sizer)

    def get_message(self) -> str:
        return self.message.GetValue().strip()


class OnlineUsersDialog(wx.Dialog):
    def __init__(self, parent: wx.Window, frame: MainFrame) -> None:
        super().__init__(parent, title="Online-Benutzer", style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.frame = frame
        self.SetName("Online-Benutzer")

        sizer = wx.BoxSizer(wx.VERTICAL)

        header = wx.StaticText(self, label="Nickname | Benutzername | Kanal")
        header.SetName("Online-Benutzer Kopfzeile")
        sizer.Add(header, 0, wx.ALL, 8)

        self.user_list = wx.ListBox(self)
        self.user_list.SetName("Online-Benutzer Liste")
        self.user_list.SetMinSize((520, 260))
        sizer.Add(self.user_list, 1, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)

        self.count_label = wx.StaticText(self, label="")
        self.count_label.SetName("Online-Benutzer Anzahl")
        sizer.Add(self.count_label, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        self.refresh_btn = wx.Button(self, label="Aktualisieren")
        self.refresh_btn.SetName("Online-Benutzer aktualisieren")
        self.refresh_btn.Bind(wx.EVT_BUTTON, self.on_refresh)
        close_btn = wx.Button(self, id=wx.ID_CLOSE, label="Schliessen")
        close_btn.SetName("Online-Benutzer schliessen")
        close_btn.Bind(wx.EVT_BUTTON, lambda _evt: self.Close())
        btn_row.Add(self.refresh_btn, 0, wx.RIGHT, 8)
        btn_row.Add(close_btn, 0)
        sizer.Add(btn_row, 0, wx.ALL, 8)

        self.SetSizerAndFit(sizer)

    def on_refresh(self, _event) -> None:
        self.refresh()

    def refresh(self) -> None:
        users = list(self.frame.client.get_server_users())
        items: List[str] = []
        tt_str = self.frame.tt_str
        for user in users:
            nickname = tt_str(user.szNickname) or "-"
            username = tt_str(user.szUsername) or "-"
            ch_id = int(getattr(user, "nChannelID", 0) or 0)
            channel = "-"
            if ch_id:
                ch = self.frame.client.get_channel(ch_id)
                if ch is not None:
                    channel = tt_str(ch.szName) or f"#{ch_id}"
            items.append(f"{nickname} | {username} | {channel}")
        self.user_list.Set(items)
        self.count_label.SetLabel(f"{len(items)} Benutzer online")


class ServerStatisticsDialog(wx.Dialog):
    def __init__(self, parent: wx.Window, frame: MainFrame) -> None:
        super().__init__(parent, title="Serverstatistiken", style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.frame = frame
        self.SetName("Serverstatistiken")
        self._last_stats = None

        sizer = wx.BoxSizer(wx.VERTICAL)

        self.stats_list = wx.ListBox(self)
        self.stats_list.SetName("Serverstatistiken Liste")
        self.stats_list.SetMinSize((520, 260))
        sizer.Add(self.stats_list, 1, wx.ALL | wx.EXPAND, 8)

        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        self.refresh_btn = wx.Button(self, label="Aktualisieren")
        self.refresh_btn.SetName("Serverstatistiken aktualisieren")
        self.refresh_btn.Bind(wx.EVT_BUTTON, self.on_refresh)
        close_btn = wx.Button(self, id=wx.ID_CLOSE, label="Schliessen")
        close_btn.SetName("Serverstatistiken schliessen")
        close_btn.Bind(wx.EVT_BUTTON, lambda _evt: self.Close())
        btn_row.Add(self.refresh_btn, 0, wx.RIGHT, 8)
        btn_row.Add(close_btn, 0)
        sizer.Add(btn_row, 0, wx.ALL, 8)

        self.SetSizerAndFit(sizer)
        self.set_status("Lade Serverstatistiken...")

    def on_refresh(self, _event) -> None:
        self.refresh()

    def refresh(self) -> None:
        self.set_status("Lade Serverstatistiken...")
        self.frame.client.do_query_server_stats()

    def set_status(self, text: str) -> None:
        self.stats_list.Set([text])

    def update_stats(self, stats) -> None:
        self._last_stats = stats
        items = [
            f"Uptime: {self._format_uptime(getattr(stats, 'nUptimeMSec', 0))}",
            f"Benutzer gesamt: {getattr(stats, 'nUsersServed', 0)}",
            f"Benutzer Peak: {getattr(stats, 'nUsersPeak', 0)}",
            f"Gesamt TX: {self._format_bytes(getattr(stats, 'nTotalBytesTX', 0))}",
            f"Gesamt RX: {self._format_bytes(getattr(stats, 'nTotalBytesRX', 0))}",
            f"Voice TX: {self._format_bytes(getattr(stats, 'nVoiceBytesTX', 0))}",
            f"Voice RX: {self._format_bytes(getattr(stats, 'nVoiceBytesRX', 0))}",
            f"Video TX: {self._format_bytes(getattr(stats, 'nVideoCaptureBytesTX', 0))}",
            f"Video RX: {self._format_bytes(getattr(stats, 'nVideoCaptureBytesRX', 0))}",
            f"Mediafile TX: {self._format_bytes(getattr(stats, 'nMediaFileBytesTX', 0))}",
            f"Mediafile RX: {self._format_bytes(getattr(stats, 'nMediaFileBytesRX', 0))}",
            f"Desktop TX: {self._format_bytes(getattr(stats, 'nDesktopBytesTX', 0))}",
            f"Desktop RX: {self._format_bytes(getattr(stats, 'nDesktopBytesRX', 0))}",
            f"Dateien TX: {self._format_bytes(getattr(stats, 'nFilesTx', 0))}",
            f"Dateien RX: {self._format_bytes(getattr(stats, 'nFilesRx', 0))}",
        ]
        self.stats_list.Set(items)

    def _format_bytes(self, value: int) -> str:
        try:
            size = int(value)
        except Exception:
            size = 0
        if size < 1024:
            return f"{size} B"
        if size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        if size < 1024 * 1024 * 1024:
            return f"{size / (1024 * 1024):.1f} MB"
        return f"{size / (1024 * 1024 * 1024):.1f} GB"

    def _format_uptime(self, ms: int) -> str:
        try:
            total = int(ms) // 1000
        except Exception:
            total = 0
        seconds = total % 60
        minutes = (total // 60) % 60
        hours = (total // 3600) % 24
        days = total // (3600 * 24)
        if days:
            return f"{days}d {hours}h {minutes}m"
        if hours:
            return f"{hours}h {minutes}m"
        if minutes:
            return f"{minutes}m {seconds}s"
        return f"{seconds}s"
