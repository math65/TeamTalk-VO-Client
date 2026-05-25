from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QFormLayout,
    QLabel, QPushButton, QCheckBox, QComboBox, QRadioButton,
    QListWidget, QButtonGroup, QStackedWidget,
)
from PySide6.QtCore import QTimer

try:
    import screen_capture as sc
    HAVE_SC = True
except ImportError:
    sc = None  # type: ignore
    HAVE_SC = False

from i18n import _

if TYPE_CHECKING:
    from app_qt import MainWindow


class DesktopTab(QWidget):
    """Tab 9: Desktopfreigabe."""

    def __init__(self, parent: QWidget, window: "MainWindow") -> None:
        super().__init__(parent)
        self.window = window
        self._sharing = False
        self._last_sender: Optional[str] = None
        self._monitor_list: list = []
        self._window_list_data: list = []
        self._share_timer = QTimer(self)
        self._share_timer.timeout.connect(self._on_timer)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        # ── Aufnahmequelle ────────────────────────────────────────────────
        src_group = QGroupBox(_("Aufnahmequelle"))
        src_layout = QVBoxLayout(src_group)

        rb_row = QHBoxLayout()
        self.rb_fullscreen = QRadioButton(_("&Vollbild"))
        self.rb_window = QRadioButton(_("&Fenster auswählen"))
        self.rb_fullscreen.setChecked(True)
        rb_row.addWidget(self.rb_fullscreen)
        rb_row.addWidget(self.rb_window)
        rb_row.addStretch()
        src_layout.addLayout(rb_row)

        self._rb_group = QButtonGroup(self)
        self._rb_group.addButton(self.rb_fullscreen, 0)
        self._rb_group.addButton(self.rb_window, 1)
        self._rb_group.idToggled.connect(self._on_source_changed)

        # Stacked widget for fullscreen / window panels
        self._source_stack = QStackedWidget()

        # Page 0: Monitor selection
        fs_page = QWidget()
        fs_layout = QHBoxLayout(fs_page)
        fs_layout.setContentsMargins(0, 0, 0, 0)
        fs_layout.addWidget(QLabel(_("Monitor:")))
        self.monitor_choice = QComboBox()
        self.monitor_choice.setAccessibleName(_("Monitor"))
        fs_layout.addWidget(self.monitor_choice, 1)
        self.refresh_monitors_btn = QPushButton(_("A&ktualisieren"))
        self.refresh_monitors_btn.clicked.connect(self._refresh_monitors)
        fs_layout.addWidget(self.refresh_monitors_btn)
        self._source_stack.addWidget(fs_page)

        # Page 1: Window list
        win_page = QWidget()
        win_layout = QVBoxLayout(win_page)
        win_layout.setContentsMargins(0, 0, 0, 0)
        self.window_list = QListWidget()
        self.window_list.setAccessibleName(_("Fensterliste"))
        win_layout.addWidget(self.window_list, 1)
        self.refresh_windows_btn = QPushButton(_("&Fenster aktualisieren"))
        self.refresh_windows_btn.clicked.connect(self._refresh_windows)
        if not HAVE_SC or (HAVE_SC and hasattr(sc, "is_wayland") and sc.is_wayland()):
            self.refresh_windows_btn.setEnabled(False)
            self.rb_window.setEnabled(False)
        win_layout.addWidget(self.refresh_windows_btn)
        self._source_stack.addWidget(win_page)

        src_layout.addWidget(self._source_stack)
        root.addWidget(src_group)

        # ── Capture-Optionen ──────────────────────────────────────────────
        opt_group = QGroupBox(_("Optionen"))
        opt_form = QFormLayout(opt_group)

        self.fps_choice = QComboBox()
        self.fps_choice.setAccessibleName("FPS")
        self.fps_choice.addItems(["1", "2", "5", "10"])
        self.fps_choice.setCurrentIndex(2)  # default 5
        opt_form.addRow(QLabel("FPS"), self.fps_choice)

        self.scale_choice = QComboBox()
        self.scale_choice.setAccessibleName(_("Skalierung"))
        self.scale_choice.addItems(["25%", "50%", "75%", "100%"])
        self.scale_choice.setCurrentIndex(1)  # default 50%
        opt_form.addRow(QLabel(_("Skalierung")), self.scale_choice)

        root.addWidget(opt_group)

        # ── Desktop senden ────────────────────────────────────────────────
        ctrl_group = QGroupBox(_("Desktop senden"))
        ctrl_layout = QVBoxLayout(ctrl_group)

        share_btn_row = QHBoxLayout()
        self.start_btn = QPushButton(_("&Freigabe starten"))
        self.start_btn.clicked.connect(self.on_start_share)
        self.stop_btn = QPushButton(_("Freigabe &beenden"))
        self.stop_btn.clicked.connect(self.on_stop_share)
        share_btn_row.addWidget(self.start_btn)
        share_btn_row.addWidget(self.stop_btn)
        share_btn_row.addStretch()
        ctrl_layout.addLayout(share_btn_row)
        root.addWidget(ctrl_group)

        # ── Remote-Steuerung ──────────────────────────────────────────────
        remote_group = QGroupBox(_("Desktop-Steuerung (Remote)"))
        remote_row = QHBoxLayout(remote_group)
        self.left_click_btn = QPushButton(_("&Linksklick senden"))
        self.left_click_btn.clicked.connect(lambda: self._send_click("left"))
        self.right_click_btn = QPushButton(_("&Rechtsklick senden"))
        self.right_click_btn.clicked.connect(lambda: self._send_click("right"))
        self.middle_click_btn = QPushButton(_("&Mittelklick senden"))
        self.middle_click_btn.clicked.connect(lambda: self._send_click("middle"))
        remote_row.addWidget(self.left_click_btn)
        remote_row.addWidget(self.right_click_btn)
        remote_row.addWidget(self.middle_click_btn)
        remote_row.addStretch()
        root.addWidget(remote_group)

        # ── Status ───────────────────────────────────────────────────────
        status_group = QGroupBox(_("Status"))
        status_layout = QVBoxLayout(status_group)
        self.status_label = QLabel(_("Bereit"))
        self.status_label.setAccessibleName(_("Desktop-Status"))
        status_layout.addWidget(self.status_label)
        root.addWidget(status_group)

        root.addStretch()

        # Initial population
        self._refresh_monitors()

    # ── Source panel switching ────────────────────────────────────────────

    def _on_source_changed(self, btn_id: int, checked: bool) -> None:
        if checked:
            self._source_stack.setCurrentIndex(btn_id)

    # ── Monitor/Window list refresh ───────────────────────────────────────

    def _refresh_monitors(self) -> None:
        self.monitor_choice.clear()
        if HAVE_SC:
            try:
                self._monitor_list = sc.list_monitors()
                if self._monitor_list:
                    for m in self._monitor_list:
                        self.monitor_choice.addItem(str(m))
                    return
            except Exception:
                pass
        # Fallback: use Qt screen information
        from PySide6.QtGui import QGuiApplication
        screens = QGuiApplication.screens()
        for i, screen in enumerate(screens):
            self.monitor_choice.addItem(
                f"Monitor {i + 1} ({screen.name()})"
            )
        if not screens:
            self.monitor_choice.addItem(_("Standard (Primärmonitor)"))

    def _refresh_windows(self) -> None:
        self._set_status(_("Fensterliste wird geladen…"))
        self.window_list.clear()
        if HAVE_SC:
            try:
                self._window_list_data = sc.list_windows()
                if self._window_list_data:
                    for w in self._window_list_data:
                        self.window_list.addItem(str(w))
                    self._set_status(
                        f"{len(self._window_list_data)} Fenster gefunden"
                    )
                else:
                    self._set_status(_("Keine Fenster gefunden"))
                return
            except Exception as exc:
                self._set_status(f"Fensterliste Fehler: {exc}")
                return
        self.window_list.addItem(_("Fensterliste nicht verfügbar"))
        self._set_status(_("screen_capture-Modul nicht verfügbar"))

    # ── Share control ─────────────────────────────────────────────────────

    def set_active(self, active: bool) -> None:
        if not active and self._share_timer.isActive():
            self._share_timer.stop()
        elif active and self._sharing and not self._share_timer.isActive():
            self._share_timer.start(self._fps_interval())

    def on_start_share(self) -> None:
        if not self.window.client.is_connected():
            self.window.set_status(_("Nicht verbunden"))
            return
        self._sharing = True
        self._share_timer.start(self._fps_interval())
        self._set_status(_("Desktopfreigabe gestartet"))

    def on_stop_share(self) -> None:
        self._stop_sharing()

    def _stop_sharing(self) -> None:
        self._sharing = False
        if self._share_timer.isActive():
            self._share_timer.stop()
        try:
            self.window.client.close_desktop_window()
        except Exception:
            pass
        self._set_status(_("Desktopfreigabe beendet"))

    def _on_timer(self) -> None:
        if not self._sharing:
            return
        if not self.window.client.is_connected():
            self._stop_sharing()
            self._set_status(_("Verbindung verloren"))
            return
        if not self._send_frame():
            self._set_status(_("Senden fehlgeschlagen"))

    def on_desktop_window(self, username: str) -> None:
        """Called when a remote desktop stream arrives."""
        self._last_sender = username
        self._set_status(f"Desktop-Stream aktiv: {username}")

    # ── Capture logic ─────────────────────────────────────────────────────

    def _send_frame(self) -> bool:
        if not HAVE_SC:
            return False
        result = self._capture()
        if result is None:
            return False
        try:
            sent = self.window.client.send_desktop_frame(
                result.width, result.height,
                result.bytes_per_line, result.data,
            )
            return sent >= 0
        except Exception:
            return False

    def _capture(self):
        if not HAVE_SC:
            return None
        scale = self._get_scale()
        try:
            if self.rb_window.isChecked():
                row = self.window_list.currentRow()
                if row < 0 or row >= len(self._window_list_data):
                    return None
                return sc.capture_window(self._window_list_data[row], scale=scale)
            monitor_idx = max(1, self.monitor_choice.currentIndex() + 1)
            return sc.capture_screen(monitor_idx=monitor_idx, scale=scale)
        except Exception:
            return None

    # ── Remote click ──────────────────────────────────────────────────────

    def _send_click(self, button: str) -> None:
        if not self.window.client.is_connected():
            self.window.set_status(_("Nicht verbunden"))
            return
        try:
            ok = self.window.client.send_desktop_click(button)
            labels = {
                "left": _("Linksklick"),
                "right": _("Rechtsklick"),
                "middle": _("Mittelklick"),
            }
            name = labels.get(button, button)
            self._set_status(
                f"{name} gesendet" if ok else f"{name} fehlgeschlagen"
            )
        except Exception as exc:
            self._set_status(f"Klick-Fehler: {exc}")

    # ── Helpers ───────────────────────────────────────────────────────────

    def _set_status(self, text: str) -> None:
        self.status_label.setText(text)
        self.window.set_status(text)

    def _fps_interval(self) -> int:
        try:
            fps = max(1, int(self.fps_choice.currentText()))
        except Exception:
            fps = 1
        return int(1000 / fps)

    def _get_scale(self) -> float:
        label = self.scale_choice.currentText()
        if label.endswith("%"):
            try:
                return max(0.1, min(1.0, int(label[:-1]) / 100.0))
            except Exception:
                pass
        return 0.5
