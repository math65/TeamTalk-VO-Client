from __future__ import annotations

from typing import TYPE_CHECKING

import wx

from ui.a11y import setup_list_accessible

if TYPE_CHECKING:
    from app import MainFrame


class ClientStatisticsDialog(wx.Dialog):
    def __init__(self, parent: wx.Window, frame: MainFrame) -> None:
        super().__init__(parent, title="Verbindungsstatistiken", style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.frame = frame
        self.SetName("Verbindungsstatistiken")

        sizer = wx.BoxSizer(wx.VERTICAL)

        self.stats_list = wx.ListBox(self)
        self.stats_list.SetName("Verbindungsstatistiken Liste")
        setup_list_accessible(self.stats_list)
        self.stats_list.SetMinSize((520, 260))
        sizer.Add(self.stats_list, 1, wx.ALL | wx.EXPAND, 8)

        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        self.refresh_btn = wx.Button(self, label="Aktualisieren")
        self.refresh_btn.SetName("Verbindungsstatistiken aktualisieren")
        self.refresh_btn.Bind(wx.EVT_BUTTON, self.on_refresh)
        close_btn = wx.Button(self, id=wx.ID_CLOSE, label="Schließen")
        close_btn.SetName("Verbindungsstatistiken schließen")
        close_btn.Bind(wx.EVT_BUTTON, lambda _evt: self.Close())
        btn_row.Add(self.refresh_btn, 0, wx.RIGHT, 8)
        btn_row.Add(close_btn, 0)
        sizer.Add(btn_row, 0, wx.ALL, 8)

        self.SetSizerAndFit(sizer)
        self.refresh()

    def on_refresh(self, _event) -> None:
        self.refresh()

    def refresh(self) -> None:
        if not self.frame.client.is_connected():
            self.stats_list.Set(["Nicht verbunden"])
            return
        stats = self.frame.client.get_client_statistics()
        if stats is None:
            self.stats_list.Set(["Keine Statistik verfügbar"])
            return
        items = [
            f"UDP Ping: {getattr(stats, 'nUdpPingTimeMs', 0)} ms",
            f"TCP Ping: {getattr(stats, 'nTcpPingTimeMs', 0)} ms",
            f"UDP TX: {self._format_bytes(getattr(stats, 'nUdpBytesSent', 0))}",
            f"UDP RX: {self._format_bytes(getattr(stats, 'nUdpBytesRecv', 0))}",
            f"Voice TX: {self._format_bytes(getattr(stats, 'nVoiceBytesSent', 0))}",
            f"Voice RX: {self._format_bytes(getattr(stats, 'nVoiceBytesRecv', 0))}",
            f"Video TX: {self._format_bytes(getattr(stats, 'nVideoCaptureBytesSent', 0))}",
            f"Video RX: {self._format_bytes(getattr(stats, 'nVideoCaptureBytesRecv', 0))}",
            f"Media Audio TX: {self._format_bytes(getattr(stats, 'nMediaFileAudioBytesSent', 0))}",
            f"Media Audio RX: {self._format_bytes(getattr(stats, 'nMediaFileAudioBytesRecv', 0))}",
            f"Media Video TX: {self._format_bytes(getattr(stats, 'nMediaFileVideoBytesSent', 0))}",
            f"Media Video RX: {self._format_bytes(getattr(stats, 'nMediaFileVideoBytesRecv', 0))}",
            f"Desktop TX: {self._format_bytes(getattr(stats, 'nDesktopBytesSent', 0))}",
            f"Desktop RX: {self._format_bytes(getattr(stats, 'nDesktopBytesRecv', 0))}",
            f"TCP Stille: {getattr(stats, 'nTcpServerSilenceSec', 0)} s",
            f"UDP Stille: {getattr(stats, 'nUdpServerSilenceSec', 0)} s",
            f"Input-Device Delay: {getattr(stats, 'nSoundInputDeviceDelayMSec', 0)} ms",
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
