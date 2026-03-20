from __future__ import annotations

from typing import TYPE_CHECKING, Optional

import wx

if TYPE_CHECKING:
    from app import MainFrame


class DesktopTab(wx.Panel):
    """Tab: Desktop -- screen sharing controls and status."""

    def __init__(self, parent: wx.Window, frame: MainFrame) -> None:
        super().__init__(parent)
        self.frame = frame
        self.SetName("Desktop")
        self._timer = wx.Timer(self)
        self._active = True
        self._sharing = False
        self._last_sender: Optional[str] = None

        sizer = wx.BoxSizer(wx.VERTICAL)

        info = wx.StaticText(self, label="Desktopfreigabe senden und Status anzeigen.")
        info.SetName("Desktop Info")
        sizer.Add(info, 0, wx.ALL, 8)

        control_box = wx.StaticBox(self, label="Desktop senden")
        control_sizer = wx.StaticBoxSizer(control_box, wx.VERTICAL)

        row = wx.BoxSizer(wx.HORIZONTAL)
        self.share_toggle = wx.CheckBox(self, label="Desktop senden")
        self.share_toggle.SetName("Desktop senden")
        row.Add(self.share_toggle, 0, wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 12)

        row.Add(wx.StaticText(self, label="FPS"), 0, wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 6)
        self.fps_choice = wx.Choice(self, choices=["1", "2", "5", "10"])
        self.fps_choice.SetName("Desktop FPS")
        self.fps_choice.SetSelection(0)
        row.Add(self.fps_choice, 0, wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 12)

        row.Add(wx.StaticText(self, label="Skalierung"), 0, wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 6)
        self.scale_choice = wx.Choice(self, choices=["25%", "50%", "75%", "100%"])
        self.scale_choice.SetName("Desktop Skalierung")
        self.scale_choice.SetSelection(1)
        row.Add(self.scale_choice, 0, wx.ALIGN_CENTER_VERTICAL)

        control_sizer.Add(row, 0, wx.ALL, 8)

        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        self.send_once_btn = wx.Button(self, label="Einmal senden")
        self.send_once_btn.SetName("Desktop einmal senden")
        btn_row.Add(self.send_once_btn, 0, wx.RIGHT, 8)
        self.stop_btn = wx.Button(self, label="Freigabe beenden")
        self.stop_btn.SetName("Desktop freigabe beenden")
        btn_row.Add(self.stop_btn, 0)
        control_sizer.Add(btn_row, 0, wx.ALL, 8)

        sizer.Add(control_sizer, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)

        input_box = wx.StaticBox(self, label="Desktop-Steuerung (Remote)")
        input_sizer = wx.StaticBoxSizer(input_box, wx.VERTICAL)
        input_row = wx.BoxSizer(wx.HORIZONTAL)
        self.left_click_btn = wx.Button(self, label="Linksklick")
        self.left_click_btn.SetName("Desktop Linksklick")
        self.right_click_btn = wx.Button(self, label="Rechtsklick")
        self.right_click_btn.SetName("Desktop Rechtsklick")
        self.middle_click_btn = wx.Button(self, label="Mittelklick")
        self.middle_click_btn.SetName("Desktop Mittelklick")
        input_row.Add(self.left_click_btn, 0, wx.RIGHT, 8)
        input_row.Add(self.right_click_btn, 0, wx.RIGHT, 8)
        input_row.Add(self.middle_click_btn, 0)
        input_sizer.Add(input_row, 0, wx.ALL, 8)
        sizer.Add(input_sizer, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)

        status_box = wx.StaticBox(self, label="Status")
        status_sizer = wx.StaticBoxSizer(status_box, wx.VERTICAL)
        self.status_label = wx.StaticText(self, label="Bereit")
        self.status_label.SetName("Desktop Status")
        status_sizer.Add(self.status_label, 0, wx.ALL, 8)
        sizer.Add(status_sizer, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)

        self.SetSizer(sizer)

        self.share_toggle.Bind(wx.EVT_CHECKBOX, self.on_share_toggle)
        self.send_once_btn.Bind(wx.EVT_BUTTON, self.on_send_once)
        self.stop_btn.Bind(wx.EVT_BUTTON, self.on_stop)
        self.left_click_btn.Bind(wx.EVT_BUTTON, lambda _e: self._send_click("left"))
        self.right_click_btn.Bind(wx.EVT_BUTTON, lambda _e: self._send_click("right"))
        self.middle_click_btn.Bind(wx.EVT_BUTTON, lambda _e: self._send_click("middle"))
        self.Bind(wx.EVT_TIMER, self.on_timer, self._timer)

    def set_active(self, active: bool) -> None:
        self._active = active
        if not active and self._timer.IsRunning():
            self._timer.Stop()
        elif active and self._sharing and not self._timer.IsRunning():
            self._timer.Start(self._get_timer_interval())

    def on_share_toggle(self, event):
        if event.IsChecked():
            if not self.frame.client.is_connected():
                self.frame.set_status("Nicht verbunden")
                self.share_toggle.SetValue(False)
                return
            self._sharing = True
            self._start_timer()
            self._set_status("Desktopfreigabe gestartet")
        else:
            self._sharing = False
            self._stop_timer()
            self.frame.client.close_desktop_window()
            self._set_status("Desktopfreigabe beendet")

    def on_send_once(self, _event):
        if not self.frame.client.is_connected():
            self.frame.set_status("Nicht verbunden")
            return
        ok = self._send_frame()
        self._set_status("Desktopbild gesendet" if ok else "Senden fehlgeschlagen")

    def on_stop(self, _event):
        self.share_toggle.SetValue(False)
        self._sharing = False
        self._stop_timer()
        self.frame.client.close_desktop_window()
        self._set_status("Desktopfreigabe beendet")

    def on_timer(self, _event):
        if not self._sharing or not self._active:
            return
        if not self.frame.client.is_connected():
            self._sharing = False
            self._stop_timer()
            self.share_toggle.SetValue(False)
            self._set_status("Verbindung verloren")
            return
        if not self._send_frame():
            self._set_status("Senden fehlgeschlagen")

    def on_desktop_window(self, username: str) -> None:
        self._last_sender = username
        self._set_status(f"Desktop-Stream aktiv: {username}")

    def _send_click(self, button: str) -> None:
        if not self.frame.client.is_connected():
            self.frame.set_status("Nicht verbunden")
            return
        ok = self.frame.client.send_desktop_click(button)
        label = "Linksklick" if button == "left" else "Rechtsklick" if button == "right" else "Mittelklick"
        self._set_status(f"{label} gesendet" if ok else f"{label} fehlgeschlagen")

    def _set_status(self, text: str) -> None:
        self.status_label.SetLabel(text)
        self.frame.set_status(text)

    def _start_timer(self) -> None:
        if self._active and not self._timer.IsRunning():
            self._timer.Start(self._get_timer_interval())

    def _stop_timer(self) -> None:
        if self._timer.IsRunning():
            self._timer.Stop()

    def _get_timer_interval(self) -> int:
        try:
            fps = int(self.fps_choice.GetStringSelection())
            fps = max(1, fps)
        except Exception:
            fps = 1
        return int(1000 / fps)

    def _get_scale(self) -> float:
        label = self.scale_choice.GetStringSelection()
        if label.endswith("%"):
            try:
                return max(0.1, min(1.0, int(label[:-1]) / 100.0))
            except Exception:
                return 0.5
        return 0.5

    def _send_frame(self) -> bool:
        try:
            screen = wx.ScreenDC()
            width, height = screen.GetSize()
            bmp = wx.Bitmap(width, height, 32)
            mem = wx.MemoryDC(bmp)
            mem.Blit(0, 0, width, height, screen, 0, 0)
            mem.SelectObject(wx.NullBitmap)
            img = bmp.ConvertToImage()
            scale = self._get_scale()
            if scale != 1.0:
                new_w = max(1, int(width * scale))
                new_h = max(1, int(height * scale))
                img = img.Scale(new_w, new_h, wx.IMAGE_QUALITY_HIGH)
            data = img.GetData()
            if not data:
                return False
            w = img.GetWidth()
            h = img.GetHeight()
            frame = bytearray(w * h * 4)
            j = 0
            for i in range(0, len(data), 3):
                frame[j] = data[i]
                frame[j + 1] = data[i + 1]
                frame[j + 2] = data[i + 2]
                frame[j + 3] = 0
                j += 4
            bytes_per_line = w * 4
            sent = self.frame.client.send_desktop_frame(w, h, bytes_per_line, bytes(frame))
            return sent >= 0
        except Exception:
            return False
