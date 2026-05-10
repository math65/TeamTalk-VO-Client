from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel,
    QPushButton, QCheckBox, QComboBox, QSpinBox,
)

if TYPE_CHECKING:
    from app_qt import MainWindow


class DesktopTab(QWidget):
    """Tab 9: Desktopfreigabe."""

    def __init__(self, parent: QWidget, window: "MainWindow") -> None:
        super().__init__(parent)
        self.window = window

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        share_group = QGroupBox("Desktopfreigabe senden")
        share_layout = QVBoxLayout(share_group)

        monitor_row = QHBoxLayout()
        monitor_row.addWidget(QLabel("Monitor:"))
        self.monitor_choice = QComboBox()
        self.monitor_choice.addItem("Monitor 1")
        monitor_row.addWidget(self.monitor_choice, 1)
        share_layout.addLayout(monitor_row)

        fps_row = QHBoxLayout()
        fps_row.addWidget(QLabel("Framerate (1–30):"))
        self.fps_spin = QSpinBox()
        self.fps_spin.setRange(1, 30)
        self.fps_spin.setValue(5)
        fps_row.addWidget(self.fps_spin)
        fps_row.addStretch()
        share_layout.addLayout(fps_row)

        btn_row = QHBoxLayout()
        self.start_btn = QPushButton("&Freigabe starten")
        self.start_btn.clicked.connect(self.on_start_share)
        self.stop_btn = QPushButton("&Freigabe stoppen")
        self.stop_btn.clicked.connect(self.on_stop_share)
        btn_row.addWidget(self.start_btn)
        btn_row.addWidget(self.stop_btn)
        btn_row.addStretch()
        share_layout.addLayout(btn_row)
        root.addWidget(share_group)

        recv_group = QGroupBox("Desktopfreigabe empfangen")
        recv_layout = QVBoxLayout(recv_group)
        self.receive_check = QCheckBox("Desktop-Freigaben &anzeigen")
        self.receive_check.stateChanged.connect(self._on_receive_changed)
        recv_layout.addWidget(self.receive_check)
        root.addWidget(recv_group)
        root.addStretch()

    def on_start_share(self) -> None:
        monitor_idx = self.monitor_choice.currentIndex()
        fps = self.fps_spin.value()
        self.window.start_desktop_share(monitor_idx, fps)

    def on_stop_share(self) -> None:
        self.window.stop_desktop_share()

    def _on_receive_changed(self, state: int) -> None:
        self.window.set_desktop_receive(bool(state))
