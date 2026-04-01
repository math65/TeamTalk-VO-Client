from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional

import wx

import screen_capture as sc

if TYPE_CHECKING:
    from app import MainFrame


class DesktopTab(wx.Panel):
    """Tab: Desktop – Bildschirmfreigabe mit Vollbild- und Fensterauswahl.

    Backends (automatisch gewählt):
        macOS  – mss (Vollbild) + Quartz CGWindowList (Fenster)
        Windows – mss + win32gui (Fenster)
        Linux X11 – mss + xdotool (Fenster)
        Linux Wayland – grim via subprocess (Vollbild); Fenster nicht unterstützt
    """

    def __init__(self, parent: wx.Window, frame: MainFrame) -> None:
        super().__init__(parent)
        self.frame = frame
        self.SetName("Desktop")

        self._timer = wx.Timer(self)
        self._active = True
        self._sharing = False
        self._last_sender: Optional[str] = None

        # Parallele Datenlisten (CLAUDE.md-Konvention)
        self._monitor_list: List[sc.MonitorInfo] = []
        self._window_list_data: List[sc.WindowInfo] = []

        self._build_ui()
        self._refresh_monitors()
        self._update_source_panels()

        self.Bind(wx.EVT_TIMER, self._on_timer, self._timer)

    # ------------------------------------------------------------------
    # UI-Aufbau
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = wx.BoxSizer(wx.VERTICAL)

        # --- Aufnahmequelle -------------------------------------------
        src_box = wx.StaticBox(self, label="Aufnahmequelle")
        src_sizer = wx.StaticBoxSizer(src_box, wx.VERTICAL)

        rb_row = wx.BoxSizer(wx.HORIZONTAL)
        self.rb_fullscreen = wx.RadioButton(self, label="&Vollbild", style=wx.RB_GROUP)
        self.rb_fullscreen.SetName("Vollbild")
        self.rb_window = wx.RadioButton(self, label="&Fenster auswählen")
        self.rb_window.SetName("Fenster auswählen")
        rb_row.Add(self.rb_fullscreen, 0, wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 16)
        rb_row.Add(self.rb_window, 0, wx.ALIGN_CENTER_VERTICAL)
        src_sizer.Add(rb_row, 0, wx.ALL, 8)

        # Vollbild-Panel: Monitor-Auswahl
        self._panel_fullscreen = wx.Panel(self)
        fs_sizer = wx.BoxSizer(wx.HORIZONTAL)
        fs_sizer.Add(
            wx.StaticText(self._panel_fullscreen, label="Monitor:"),
            0, wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 8,
        )
        self.monitor_choice = wx.Choice(self._panel_fullscreen, choices=[])
        self.monitor_choice.SetName("Monitor")
        fs_sizer.Add(self.monitor_choice, 1, wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 8)
        self.refresh_monitors_btn = wx.Button(self._panel_fullscreen, label="A&ktualisieren")
        self.refresh_monitors_btn.SetName("Monitore aktualisieren")
        fs_sizer.Add(self.refresh_monitors_btn, 0, wx.ALIGN_CENTER_VERTICAL)
        self._panel_fullscreen.SetSizer(fs_sizer)
        src_sizer.Add(self._panel_fullscreen, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)

        # Fenster-Panel: Fensterliste + Aktualisieren
        self._panel_window = wx.Panel(self)
        win_sizer = wx.BoxSizer(wx.VERTICAL)
        self.window_list = wx.ListBox(self._panel_window, style=wx.LB_SINGLE)
        self.window_list.SetName("Fensterliste")
        win_sizer.Add(self.window_list, 1, wx.EXPAND | wx.BOTTOM, 6)
        self.refresh_windows_btn = wx.Button(self._panel_window, label="&Fenster aktualisieren")
        self.refresh_windows_btn.SetName("Fenster aktualisieren")

        if sc.is_wayland():
            wayland_note = wx.StaticText(
                self._panel_window,
                label="Wayland: Fensterauswahl nicht unterstützt. Vollbild mit grim.",
            )
            win_sizer.Add(wayland_note, 0, wx.BOTTOM, 4)
            self.refresh_windows_btn.Enable(False)
            self.rb_window.Enable(False)

        win_sizer.Add(self.refresh_windows_btn, 0)
        self._panel_window.SetSizer(win_sizer)
        src_sizer.Add(self._panel_window, 1, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)

        root.Add(src_sizer, 0, wx.ALL | wx.EXPAND, 8)

        # --- Capture-Optionen (FPS + Skalierung) ----------------------
        opt_box = wx.StaticBox(self, label="Optionen")
        opt_sizer = wx.StaticBoxSizer(opt_box, wx.HORIZONTAL)

        opt_sizer.Add(
            wx.StaticText(self, label="FPS:"),
            0, wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 6,
        )
        self.fps_choice = wx.Choice(self, choices=["1", "2", "5", "10"])
        self.fps_choice.SetName("FPS")
        self.fps_choice.SetSelection(0)
        opt_sizer.Add(self.fps_choice, 0, wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 16)

        opt_sizer.Add(
            wx.StaticText(self, label="Skalierung:"),
            0, wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 6,
        )
        self.scale_choice = wx.Choice(self, choices=["25%", "50%", "75%", "100%"])
        self.scale_choice.SetName("Skalierung")
        self.scale_choice.SetSelection(1)
        opt_sizer.Add(self.scale_choice, 0, wx.ALIGN_CENTER_VERTICAL)

        root.Add(opt_sizer, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)

        # --- Steuerung ------------------------------------------------
        ctrl_box = wx.StaticBox(self, label="Desktop senden")
        ctrl_sizer = wx.StaticBoxSizer(ctrl_box, wx.VERTICAL)

        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        self.share_toggle = wx.CheckBox(self, label="&Desktop senden")
        self.share_toggle.SetName("Desktop senden")
        btn_row.Add(self.share_toggle, 0, wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 12)

        self.send_once_btn = wx.Button(self, label="&Einmal senden")
        self.send_once_btn.SetName("Desktop einmal senden")
        btn_row.Add(self.send_once_btn, 0, wx.RIGHT, 8)

        self.stop_btn = wx.Button(self, label="&Freigabe beenden")
        self.stop_btn.SetName("Desktopfreigabe beenden")
        btn_row.Add(self.stop_btn, 0)

        ctrl_sizer.Add(btn_row, 0, wx.ALL, 8)
        root.Add(ctrl_sizer, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)

        # --- Remote-Steuerung -----------------------------------------
        remote_box = wx.StaticBox(self, label="Desktop-Steuerung (Remote)")
        remote_sizer = wx.StaticBoxSizer(remote_box, wx.HORIZONTAL)

        self.left_click_btn = wx.Button(self, label="&Linksklick")
        self.left_click_btn.SetName("Desktop Linksklick")
        self.right_click_btn = wx.Button(self, label="&Rechtsklick")
        self.right_click_btn.SetName("Desktop Rechtsklick")
        self.middle_click_btn = wx.Button(self, label="&Mittelklick")
        self.middle_click_btn.SetName("Desktop Mittelklick")

        remote_sizer.Add(self.left_click_btn, 0, wx.ALL, 4)
        remote_sizer.Add(self.right_click_btn, 0, wx.ALL, 4)
        remote_sizer.Add(self.middle_click_btn, 0, wx.ALL, 4)
        root.Add(remote_sizer, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)

        # --- Status ---------------------------------------------------
        status_box = wx.StaticBox(self, label="Status")
        status_sizer = wx.StaticBoxSizer(status_box, wx.VERTICAL)
        self.status_label = wx.StaticText(self, label="Bereit")
        self.status_label.SetName("Desktop Status")
        status_sizer.Add(self.status_label, 0, wx.ALL, 8)
        root.Add(status_sizer, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)

        self.SetSizer(root)

        # --- Events ---------------------------------------------------
        self.rb_fullscreen.Bind(wx.EVT_RADIOBUTTON, self._on_source_changed)
        self.rb_window.Bind(wx.EVT_RADIOBUTTON, self._on_source_changed)
        self.refresh_monitors_btn.Bind(wx.EVT_BUTTON, lambda _e: self._refresh_monitors())
        self.refresh_windows_btn.Bind(wx.EVT_BUTTON, lambda _e: self._refresh_windows())
        self.share_toggle.Bind(wx.EVT_CHECKBOX, self._on_share_toggle)
        self.send_once_btn.Bind(wx.EVT_BUTTON, self._on_send_once)
        self.stop_btn.Bind(wx.EVT_BUTTON, self._on_stop)
        self.left_click_btn.Bind(wx.EVT_BUTTON, lambda _e: self._send_click("left"))
        self.right_click_btn.Bind(wx.EVT_BUTTON, lambda _e: self._send_click("right"))
        self.middle_click_btn.Bind(wx.EVT_BUTTON, lambda _e: self._send_click("middle"))

    # ------------------------------------------------------------------
    # Quell-Panel-Sichtbarkeit
    # ------------------------------------------------------------------

    def _update_source_panels(self) -> None:
        fullscreen = self.rb_fullscreen.GetValue()
        self._panel_fullscreen.Show(fullscreen)
        self._panel_window.Show(not fullscreen)
        self.Layout()

    def _on_source_changed(self, _event) -> None:
        self._update_source_panels()

    # ------------------------------------------------------------------
    # Monitor- und Fensterliste befüllen
    # ------------------------------------------------------------------

    def _refresh_monitors(self) -> None:
        self._monitor_list = sc.list_monitors()
        self.monitor_choice.Clear()
        if self._monitor_list:
            for m in self._monitor_list:
                self.monitor_choice.Append(str(m))
            self.monitor_choice.SetSelection(0)
        else:
            self.monitor_choice.Append("Standard (Primärmonitor)")
            self.monitor_choice.SetSelection(0)

    def _refresh_windows(self) -> None:
        self._set_status("Fensterliste wird geladen …")
        wx.GetApp().Yield()
        self._window_list_data = sc.list_windows()
        self.window_list.Clear()
        if self._window_list_data:
            for w in self._window_list_data:
                self.window_list.Append(str(w))
            self.window_list.SetSelection(0)
            self._set_status(f"{len(self._window_list_data)} Fenster gefunden")
        else:
            self._set_status("Keine Fenster gefunden (xdotool installiert?)")

    # ------------------------------------------------------------------
    # Freigabe-Steuerung
    # ------------------------------------------------------------------

    def set_active(self, active: bool) -> None:
        self._active = active
        if not active and self._timer.IsRunning():
            self._timer.Stop()
        elif active and self._sharing and not self._timer.IsRunning():
            self._timer.Start(self._fps_interval())

    def _on_share_toggle(self, event) -> None:
        if event.IsChecked():
            if not self.frame.client.is_connected():
                self.frame.set_status("Nicht verbunden")
                self.share_toggle.SetValue(False)
                return
            self._sharing = True
            self._start_timer()
            self._set_status("Desktopfreigabe gestartet")
        else:
            self._stop_sharing()

    def _on_send_once(self, _event) -> None:
        if not self.frame.client.is_connected():
            self.frame.set_status("Nicht verbunden")
            return
        ok = self._send_frame()
        self._set_status("Desktopbild gesendet" if ok else "Senden fehlgeschlagen")

    def _on_stop(self, _event) -> None:
        self.share_toggle.SetValue(False)
        self._stop_sharing()

    def _on_timer(self, _event) -> None:
        if not self._sharing or not self._active:
            return
        if not self.frame.client.is_connected():
            self.share_toggle.SetValue(False)
            self._stop_sharing()
            self._set_status("Verbindung verloren")
            return
        if not self._send_frame():
            self._set_status("Senden fehlgeschlagen")

    def on_desktop_window(self, username: str) -> None:
        """Wird aufgerufen wenn ein Remote-Desktop-Stream eingeht."""
        self._last_sender = username
        self._set_status(f"Desktop-Stream aktiv: {username}")

    def _stop_sharing(self) -> None:
        self._sharing = False
        self._stop_timer()
        self.frame.client.close_desktop_window()
        self._set_status("Desktopfreigabe beendet")

    # ------------------------------------------------------------------
    # Capture-Logik
    # ------------------------------------------------------------------

    def _send_frame(self) -> bool:
        """Nimmt den aktuellen Frame auf und sendet ihn via TeamTalk-SDK."""
        result = self._capture()
        if result is None:
            return False
        try:
            sent = self.frame.client.send_desktop_frame(
                result.width, result.height,
                result.bytes_per_line, result.data,
            )
            return sent >= 0
        except Exception:
            return False

    def _capture(self) -> Optional[sc.CaptureResult]:
        """Wählt Backend (Vollbild/Fenster) und gibt CaptureResult zurück."""
        scale = self._get_scale()

        if self.rb_window.GetValue():
            # Fenster-Modus
            idx = self.window_list.GetSelection()
            if idx == wx.NOT_FOUND or idx >= len(self._window_list_data):
                return None
            window = self._window_list_data[idx]
            return sc.capture_window(window, scale=scale)

        # Vollbild-Modus
        monitor_idx = max(1, self.monitor_choice.GetSelection() + 1)
        return sc.capture_screen(monitor_idx=monitor_idx, scale=scale)

    # ------------------------------------------------------------------
    # Remote-Klick
    # ------------------------------------------------------------------

    def _send_click(self, button: str) -> None:
        if not self.frame.client.is_connected():
            self.frame.set_status("Nicht verbunden")
            return
        ok = self.frame.client.send_desktop_click(button)
        labels = {"left": "Linksklick", "right": "Rechtsklick", "middle": "Mittelklick"}
        self._set_status(
            f"{labels.get(button, button)} gesendet" if ok
            else f"{labels.get(button, button)} fehlgeschlagen"
        )

    # ------------------------------------------------------------------
    # Hilfsmethoden
    # ------------------------------------------------------------------

    def _set_status(self, text: str) -> None:
        self.status_label.SetLabel(text)
        self.frame.set_status(text)

    def _start_timer(self) -> None:
        if self._active and not self._timer.IsRunning():
            self._timer.Start(self._fps_interval())

    def _stop_timer(self) -> None:
        if self._timer.IsRunning():
            self._timer.Stop()

    def _fps_interval(self) -> int:
        try:
            fps = max(1, int(self.fps_choice.GetStringSelection()))
        except Exception:
            fps = 1
        return int(1000 / fps)

    def _get_scale(self) -> float:
        label = self.scale_choice.GetStringSelection()
        if label.endswith("%"):
            try:
                val = int(label[:-1]) / 100.0
                return max(0.1, min(1.0, val))
            except Exception:
                pass
        return 0.5
