from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel,
    QPushButton, QCheckBox, QComboBox, QSpinBox,
)

if TYPE_CHECKING:
    from app_qt import MainWindow


class VideoTab(QWidget):
    """Tab 13: Video."""

    def __init__(self, parent: QWidget, window: "MainWindow") -> None:
        super().__init__(parent)
        self.window = window

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        send_group = QGroupBox("Video senden")
        send_layout = QVBoxLayout(send_group)

        cam_row = QHBoxLayout()
        cam_row.addWidget(QLabel("Kamera:"))
        self.camera_choice = QComboBox()
        self.camera_choice.addItem("(keine Kamera)")
        cam_row.addWidget(self.camera_choice, 1)
        send_layout.addLayout(cam_row)

        fmt_row = QHBoxLayout()
        fmt_row.addWidget(QLabel("Format:"))
        self.format_choice = QComboBox()
        self.format_choice.addItems(["640x480", "1280x720", "1920x1080"])
        fmt_row.addWidget(self.format_choice, 1)
        send_layout.addLayout(fmt_row)

        fps_row = QHBoxLayout()
        fps_row.addWidget(QLabel("Framerate (1–30):"))
        self.fps_spin = QSpinBox()
        self.fps_spin.setRange(1, 30)
        self.fps_spin.setValue(15)
        fps_row.addWidget(self.fps_spin)
        fps_row.addStretch()
        send_layout.addLayout(fps_row)

        btn_row = QHBoxLayout()
        self.start_btn = QPushButton("&Video starten")
        self.start_btn.clicked.connect(self.on_start_video)
        self.stop_btn = QPushButton("&Video stoppen")
        self.stop_btn.clicked.connect(self.on_stop_video)
        btn_row.addWidget(self.start_btn)
        btn_row.addWidget(self.stop_btn)
        btn_row.addStretch()
        send_layout.addLayout(btn_row)
        root.addWidget(send_group)

        recv_group = QGroupBox("Video empfangen")
        recv_layout = QVBoxLayout(recv_group)
        self.receive_check = QCheckBox("Video-Streams &anzeigen")
        self.receive_check.stateChanged.connect(self._on_receive_changed)
        recv_layout.addWidget(self.receive_check)
        root.addWidget(recv_group)
        root.addStretch()

    def on_start_video(self) -> None:
        cam_idx = self.camera_choice.currentIndex()
        fps = self.fps_spin.value()
        self.window.start_video(cam_idx, fps)

    def on_stop_video(self) -> None:
        self.window.stop_video()

    def _on_receive_changed(self, state: int) -> None:
        self.window.set_video_receive(bool(state))
