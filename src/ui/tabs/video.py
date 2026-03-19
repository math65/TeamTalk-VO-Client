from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional, Tuple

import wx

if TYPE_CHECKING:
    from app import MainFrame


class VideoTab(wx.Panel):
    """Settings: Video capture and transmission."""

    def __init__(self, parent: wx.Window, frame: MainFrame) -> None:
        super().__init__(parent)
        self.frame = frame
        self.SetName("Video")
        self._devices = []
        self._formats: List[Tuple[object, str]] = []
        self._tx_enabled = False

        root = wx.BoxSizer(wx.VERTICAL)

        device_box = wx.StaticBox(self, label="Video-Geraet")
        device_sizer = wx.StaticBoxSizer(device_box, wx.VERTICAL)

        dev_row = wx.BoxSizer(wx.HORIZONTAL)
        dev_row.Add(wx.StaticText(self, label="Geraet"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.device_choice = wx.Choice(self)
        self.device_choice.SetName("Video-Geraet")
        self.device_choice.Bind(wx.EVT_CHOICE, self.on_device_changed)
        dev_row.Add(self.device_choice, 1, wx.EXPAND)
        device_sizer.Add(dev_row, 0, wx.ALL | wx.EXPAND, 4)

        fmt_row = wx.BoxSizer(wx.HORIZONTAL)
        fmt_row.Add(wx.StaticText(self, label="Format"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.format_choice = wx.Choice(self)
        self.format_choice.SetName("Video-Format")
        fmt_row.Add(self.format_choice, 1, wx.EXPAND)
        device_sizer.Add(fmt_row, 0, wx.ALL | wx.EXPAND, 4)

        apply_row = wx.BoxSizer(wx.HORIZONTAL)
        self.apply_btn = wx.Button(self, label="Video anwenden")
        self.apply_btn.SetName("Video anwenden")
        self.apply_btn.Bind(wx.EVT_BUTTON, self.on_apply)
        self.refresh_btn = wx.Button(self, label="Geraete aktualisieren")
        self.refresh_btn.SetName("Video-Geraete aktualisieren")
        self.refresh_btn.Bind(wx.EVT_BUTTON, self.on_refresh)
        apply_row.Add(self.apply_btn, 0, wx.RIGHT, 8)
        apply_row.Add(self.refresh_btn, 0)
        device_sizer.Add(apply_row, 0, wx.ALL, 4)

        root.Add(device_sizer, 0, wx.ALL | wx.EXPAND, 8)

        tx_box = wx.StaticBox(self, label="Video senden")
        tx_sizer = wx.StaticBoxSizer(tx_box, wx.VERTICAL)

        bitrate_row = wx.BoxSizer(wx.HORIZONTAL)
        bitrate_row.Add(wx.StaticText(self, label="Bitrate (kbps)"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.bitrate = wx.SpinCtrl(self, min=32, max=2000, initial=256)
        self.bitrate.SetName("Video-Bitrate")
        bitrate_row.Add(self.bitrate, 0, wx.RIGHT, 8)
        tx_sizer.Add(bitrate_row, 0, wx.ALL, 4)

        deadline_row = wx.BoxSizer(wx.HORIZONTAL)
        deadline_row.Add(wx.StaticText(self, label="Qualitaet"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.deadline_choice = wx.Choice(self, choices=["Echtzeit", "Gute Qualitaet", "Beste Qualitaet"])
        self.deadline_choice.SetName("Video-Qualitaet")
        self.deadline_choice.SetSelection(0)
        deadline_row.Add(self.deadline_choice, 1, wx.EXPAND)
        tx_sizer.Add(deadline_row, 0, wx.ALL | wx.EXPAND, 4)

        self.tx_toggle = wx.CheckBox(self, label="Video senden")
        self.tx_toggle.SetName("Video senden")
        self.tx_toggle.Bind(wx.EVT_CHECKBOX, self.on_toggle_tx)
        tx_sizer.Add(self.tx_toggle, 0, wx.ALL, 4)

        root.Add(tx_sizer, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)

        self.SetSizer(root)
        self._load_from_settings()
        self.refresh_devices()

    def _load_from_settings(self) -> None:
        settings = self.frame.settings_store.settings
        if settings.video_bitrate_kbps:
            self.bitrate.SetValue(int(settings.video_bitrate_kbps))
        deadline = (settings.video_deadline or "realtime").lower()
        if deadline == "good":
            self.deadline_choice.SetSelection(1)
        elif deadline == "best":
            self.deadline_choice.SetSelection(2)
        else:
            self.deadline_choice.SetSelection(0)

    def refresh_devices(self) -> None:
        self._devices = self.frame.client.get_video_capture_devices()
        self.device_choice.Clear()
        labels = []
        for dev in self._devices:
            labels.append(self.frame.tt_str(dev.szDeviceName))
        if not labels:
            self.device_choice.Append("Kein Geraet gefunden")
            self.device_choice.SetSelection(0)
            self.device_choice.Disable()
            self.format_choice.Clear()
            self.format_choice.Disable()
            return
        self.device_choice.Enable()
        self.device_choice.AppendItems(labels)
        settings = self.frame.settings_store.settings
        selected = 0
        if settings.video_device_id:
            for i, dev in enumerate(self._devices):
                if self.frame.tt_str(dev.szDeviceID) == settings.video_device_id:
                    selected = i
                    break
        self.device_choice.SetSelection(selected)
        self._populate_formats(selected)

    def _populate_formats(self, idx: int) -> None:
        self.format_choice.Clear()
        self._formats = []
        if idx < 0 or idx >= len(self._devices):
            self.format_choice.Disable()
            return
        dev = self._devices[idx]
        count = int(getattr(dev, "nVideoFormatsCount", 0) or 0)
        tt = self.frame.client.tt
        for i in range(count):
            fmt = dev.videoFormats[i]
            fps = 0.0
            if int(fmt.nFPS_Denominator) > 0:
                fps = float(fmt.nFPS_Numerator) / float(fmt.nFPS_Denominator)
            else:
                fps = float(fmt.nFPS_Numerator)
            fourcc = int(fmt.picFourCC)
            if fourcc == int(tt.FourCC.FOURCC_I420):
                pix = "I420"
            elif fourcc == int(tt.FourCC.FOURCC_YUY2):
                pix = "YUY2"
            elif fourcc == int(tt.FourCC.FOURCC_RGB32):
                pix = "RGB32"
            else:
                pix = str(fourcc)
            label = f"{int(fmt.nWidth)}x{int(fmt.nHeight)} @ {fps:.2f} fps ({pix})"
            self._formats.append((fmt, label))
        if not self._formats:
            self.format_choice.Disable()
            return
        self.format_choice.Enable()
        self.format_choice.AppendItems([f[1] for f in self._formats])
        settings = self.frame.settings_store.settings
        idx = min(max(int(settings.video_format_index or 0), 0), len(self._formats) - 1)
        self.format_choice.SetSelection(idx)

    def on_device_changed(self, _event):
        self._populate_formats(self.device_choice.GetSelection())

    def _selected_format(self):
        idx = self.format_choice.GetSelection()
        if idx == wx.NOT_FOUND or idx < 0 or idx >= len(self._formats):
            return None
        return self._formats[idx][0]

    def on_apply(self, _event):
        if not self._devices:
            self.frame.set_status("Kein Video-Geraet")
            return
        dev = self._devices[self.device_choice.GetSelection()]
        device_id = self.frame.tt_str(dev.szDeviceID)
        fmt = self._selected_format()
        if fmt is None:
            self.frame.set_status("Kein Video-Format")
            return
        try:
            self.frame.client.close_video_capture_device()
        except Exception:
            pass
        ok = self.frame.client.init_video_capture_device(device_id, fmt)
        if ok:
            settings = self.frame.settings_store.settings
            settings.video_device_id = device_id
            settings.video_format_index = int(self.format_choice.GetSelection())
            settings.video_bitrate_kbps = int(self.bitrate.GetValue())
            settings.video_deadline = self._deadline_key()
            self.frame.settings_store.save()
            self.frame.set_status("Video-Geraet angewendet")
        else:
            self.frame.set_status("Video-Geraet konnte nicht initialisiert werden")

    def on_refresh(self, _event):
        self.refresh_devices()
        self.frame.set_status("Video-Geraete aktualisiert")

    def _deadline_key(self) -> str:
        sel = self.deadline_choice.GetSelection()
        if sel == 1:
            return "good"
        if sel == 2:
            return "best"
        return "realtime"

    def _deadline_value(self) -> int:
        tt = self.frame.client.tt
        key = self._deadline_key()
        if key == "good":
            return int(tt.WEBM_VPX_DL_GOOD_QUALITY)
        if key == "best":
            return int(tt.WEBM_VPX_DL_BEST_QUALITY)
        return int(tt.WEBM_VPX_DL_REALTIME)

    def on_toggle_tx(self, _event):
        self.set_transmission_enabled(self.tx_toggle.GetValue())

    def set_transmission_enabled(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if enabled:
            if not self._ensure_video_ready():
                self.tx_toggle.SetValue(False)
                return
            codec = self.frame.client.build_default_video_codec(
                bitrate_kbps=int(self.bitrate.GetValue()),
                deadline=self._deadline_value(),
            )
            ok = self.frame.client.start_video_capture_transmission(codec)
            if ok:
                self._tx_enabled = True
                self.tx_toggle.SetValue(True)
                self.frame.set_status("Video senden aktiviert")
            else:
                self._tx_enabled = False
                self.tx_toggle.SetValue(False)
                self.frame.set_status("Video senden fehlgeschlagen")
        else:
            self.frame.client.stop_video_capture_transmission()
            self._tx_enabled = False
            self.tx_toggle.SetValue(False)
            self.frame.set_status("Video senden deaktiviert")

    def _ensure_video_ready(self) -> bool:
        if not self._devices:
            self.frame.set_status("Kein Video-Geraet")
            return False
        dev = self._devices[self.device_choice.GetSelection()]
        device_id = self.frame.tt_str(dev.szDeviceID)
        fmt = self._selected_format()
        if fmt is None:
            self.frame.set_status("Kein Video-Format")
            return False
        try:
            self.frame.client.close_video_capture_device()
        except Exception:
            pass
        return self.frame.client.init_video_capture_device(device_id, fmt)
