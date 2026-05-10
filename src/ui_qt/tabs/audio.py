from __future__ import annotations

import sys
from typing import Optional, TYPE_CHECKING

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QFormLayout,
    QLabel, QCheckBox, QComboBox, QSpinBox, QSlider, QPushButton,
    QProgressBar,
)
from PySide6.QtCore import Qt

import system_audio as sa

if TYPE_CHECKING:
    from app_qt import MainWindow

_IS_MAC = sys.platform == "darwin"


class AudioTab(QWidget):
    """Tab 4: Audio."""

    def __init__(self, parent: QWidget, window: "MainWindow") -> None:
        super().__init__(parent)
        self.window = window
        self._input_devices = []
        self._output_devices = []
        self._loopback_handle = None
        self._lp_session_id: Optional[int] = None
        self._lp_paused = False

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        # Device selection
        dev_group = QGroupBox("Geräte")
        dev_form = QFormLayout(dev_group)
        self.input_device = QComboBox()
        self.input_device.setObjectName("Eingabegerät")
        self.output_device = QComboBox()
        self.output_device.setObjectName("Ausgabegerät")
        dev_form.addRow(QLabel("Eingabegerät"), self.input_device)
        dev_form.addRow(QLabel("Ausgabegerät"), self.output_device)
        root.addWidget(dev_group)

        # Loopback / system audio
        sys_group = QGroupBox("Systemton")
        sys_layout = QVBoxLayout(sys_group)
        self.sys_hint_label = QLabel(sa.loopback_hint())
        self.sys_hint_label.setWordWrap(True)
        sys_layout.addWidget(self.sys_hint_label)
        sys_btn_row = QHBoxLayout()
        if _IS_MAC:
            self.sys_install_btn = QPushButton("BlackHole &installieren")
            self.sys_install_btn.clicked.connect(self._on_install_loopback)
            sys_btn_row.addWidget(self.sys_install_btn)
        self.sys_refresh_hint_btn = QPushButton("Status aktuali&sieren")
        self.sys_refresh_hint_btn.clicked.connect(self._on_refresh_sys_hint)
        sys_btn_row.addWidget(self.sys_refresh_hint_btn)
        sys_btn_row.addStretch()
        sys_layout.addLayout(sys_btn_row)
        root.addWidget(sys_group)

        # Voice activation
        va_group = QGroupBox("Sprachaktivierung")
        va_form = QFormLayout(va_group)
        self.voice_activation = QCheckBox("&Sprachaktivierung")
        self.voice_activation.stateChanged.connect(self.on_voice_activation)
        va_form.addRow(QLabel("Sprachaktivierung"), self.voice_activation)

        self.voice_level = QSpinBox()
        self.voice_level.setRange(0, 100)
        self.voice_level.setValue(30)
        self.voice_level.setObjectName("Aktivierungspegel")
        self.voice_level.valueChanged.connect(self.on_voice_level)
        va_form.addRow(QLabel("Aktivierungspegel (0–100)"), self.voice_level)

        self.va_delay = QSpinBox()
        self.va_delay.setRange(0, 5000)
        self.va_delay.setValue(0)
        self.va_delay.setObjectName("Nachlauf")
        self.va_delay.valueChanged.connect(self.on_va_delay)
        va_form.addRow(QLabel("Nachlauf (ms, 0–5000)"), self.va_delay)
        root.addWidget(va_group)

        # VU meter
        vu_group = QGroupBox("Eingangspegel")
        vu_layout = QVBoxLayout(vu_group)
        self.vu_bar = QProgressBar()
        self.vu_bar.setRange(0, 100)
        self.vu_bar.setObjectName("VU-Meter")
        vu_layout.addWidget(self.vu_bar)
        root.addWidget(vu_group)

        # Gain
        gain_group = QGroupBox("Verstärkung")
        gain_form = QFormLayout(gain_group)
        self.mic_gain = QSpinBox()
        self.mic_gain.setRange(-20, 20)
        self.mic_gain.setValue(0)
        self.mic_gain.setObjectName("Mikrofon-Verstärkung")
        self.mic_gain.valueChanged.connect(self.on_mic_gain)
        gain_form.addRow(QLabel("Mikrofon-Verstärkung (dB)"), self.mic_gain)

        self.out_gain = QSpinBox()
        self.out_gain.setRange(-20, 20)
        self.out_gain.setValue(0)
        self.out_gain.setObjectName("Ausgabe-Verstärkung")
        self.out_gain.valueChanged.connect(self.on_out_gain)
        gain_form.addRow(QLabel("Ausgabe-Verstärkung (dB)"), self.out_gain)
        root.addWidget(gain_group)

        # Buttons
        btn_row = QHBoxLayout()
        self.apply_btn = QPushButton("&Übernehmen")
        self.apply_btn.clicked.connect(self.on_apply)
        self.refresh_btn = QPushButton("Geräte &aktualisieren")
        self.refresh_btn.clicked.connect(self.refresh_devices)
        btn_row.addWidget(self.apply_btn)
        btn_row.addWidget(self.refresh_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)
        root.addStretch()

        self.input_device.currentIndexChanged.connect(self._on_device_changed)
        self.output_device.currentIndexChanged.connect(self._on_device_changed)

    def refresh_devices(self) -> None:
        try:
            devices = self.window.client.get_sound_devices()
        except Exception:
            devices = []
        self._input_devices = [d for d in devices if getattr(d, "nMaxInputChannels", 0) > 0]
        self._output_devices = [d for d in devices if getattr(d, "nMaxOutputChannels", 0) > 0]
        tt_str = self.window.tt_str
        self.input_device.blockSignals(True)
        self.output_device.blockSignals(True)
        self.input_device.clear()
        self.output_device.clear()
        for d in self._input_devices:
            self.input_device.addItem(tt_str(d.szDeviceName))
        for d in self._output_devices:
            self.output_device.addItem(tt_str(d.szDeviceName))
        self.input_device.blockSignals(False)
        self.output_device.blockSignals(False)

    def _on_device_changed(self, *_) -> None:
        pass

    def on_apply(self) -> None:
        self.window.apply_audio_prefs()

    def on_voice_activation(self, *_) -> None:
        self.window.set_voice_activation(self.voice_activation.isChecked())

    def on_voice_level(self, value: int) -> None:
        self.window.set_voice_activation_level(value)

    def on_va_delay(self, value: int) -> None:
        self.window.set_va_delay(value)

    def on_mic_gain(self, value: int) -> None:
        self.window.set_mic_gain(value)

    def on_out_gain(self, value: int) -> None:
        self.window.set_out_gain(value)

    def set_vu_level(self, level: int) -> None:
        self.vu_bar.setValue(max(0, min(100, level)))

    def _on_install_loopback(self) -> None:
        self.window.install_loopback()

    def _on_refresh_sys_hint(self) -> None:
        self.sys_hint_label.setText(sa.loopback_hint())

    def apply_audio_prefs(self, prefs: dict) -> None:
        pass
