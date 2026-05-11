from __future__ import annotations

import sys
from typing import Optional, TYPE_CHECKING

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QFormLayout,
    QLabel, QCheckBox, QComboBox, QSpinBox, QSlider, QPushButton,
    QProgressBar,
)
from PySide6.QtCore import Qt, QTimer

import system_audio as sa

if TYPE_CHECKING:
    from app_qt import MainWindow

_IS_MAC = sys.platform == "darwin"


class AudioTab(QWidget):
    """Tab 4: Audio – devices, loopback, preprocessing, voice activation, levels."""

    def __init__(self, parent: QWidget, window: "MainWindow") -> None:
        super().__init__(parent)
        self.window = window
        self._input_devices = []
        self._output_devices = []
        self._loopback_handle: Optional[int] = None
        self._lp_session_id: Optional[int] = None
        self._lp_paused = False

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        # ── Device selection ─────────────────────────────────────────────
        dev_group = QGroupBox("Geräte")
        dev_form = QFormLayout(dev_group)
        self.input_device = QComboBox()
        self.input_device.setObjectName("Eingabegerät")
        self.output_device = QComboBox()
        self.output_device.setObjectName("Ausgabegerät")
        dev_form.addRow(QLabel("Eingabegerät"), self.input_device)
        dev_form.addRow(QLabel("Ausgabegerät"), self.output_device)
        root.addWidget(dev_group)

        # ── Systemton (Loopback-Hinweis) ─────────────────────────────────
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

        # ── Mikrofontest (Loopback) ───────────────────────────────────────
        mic_group = QGroupBox("Mikrofontest")
        mic_layout = QHBoxLayout(mic_group)
        self.loopback_check = QCheckBox("&Mikrofontest")
        self.loopback_check.setToolTip(
            "Startet einen Loopback-Test: Sie hören sich selbst (kein Server nötig)."
        )
        self.loopback_check.stateChanged.connect(self._on_loopback_toggle)
        mic_layout.addWidget(self.loopback_check)
        mic_layout.addStretch()
        root.addWidget(mic_group)

        # ── Audiovorverarbeitung ─────────────────────────────────────────
        preprocess_group = QGroupBox("Audiovorverarbeitung")
        preprocess_layout = QVBoxLayout(preprocess_group)
        self.denoise_check = QCheckBox("&Rauschunterdrückung")
        self.denoise_check.setChecked(
            bool(getattr(self.window.settings_store.settings, "denoise", False))
        )
        self.denoise_check.stateChanged.connect(self._on_preprocess_changed)
        preprocess_layout.addWidget(self.denoise_check)

        self.echo_check = QCheckBox("&Echounterdrückung")
        self.echo_check.setChecked(
            bool(getattr(self.window.settings_store.settings, "echo_cancel", False))
        )
        self.echo_check.stateChanged.connect(self._on_preprocess_changed)
        preprocess_layout.addWidget(self.echo_check)

        self.agc_check = QCheckBox("Automatische Lautstärke&regelung (AGC)")
        self.agc_check.setChecked(
            bool(getattr(self.window.settings_store.settings, "agc", False))
        )
        self.agc_check.stateChanged.connect(self._on_preprocess_changed)
        preprocess_layout.addWidget(self.agc_check)
        root.addWidget(preprocess_group)

        # ── Sprachaktivierung ────────────────────────────────────────────
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

        # ── Eingangspegel / VU ───────────────────────────────────────────
        vu_group = QGroupBox("Eingangspegel")
        vu_layout = QVBoxLayout(vu_group)
        self.vu_bar = QProgressBar()
        self.vu_bar.setRange(0, 100)
        self.vu_bar.setObjectName("VU-Meter")
        vu_layout.addWidget(self.vu_bar)
        root.addWidget(vu_group)

        # ── Master-Lautstärke und Mikrofonverstärkung (Slider) ───────────
        levels_group = QGroupBox("Pegel und Lautstärke")
        levels_form = QFormLayout(levels_group)

        # Master volume slider 0-200, default 100
        master_row = QHBoxLayout()
        self.master_volume_slider = QSlider(Qt.Horizontal)
        self.master_volume_slider.setRange(0, 200)
        self.master_volume_slider.setValue(
            int(getattr(self.window.settings_store.settings, "master_volume", 100))
        )
        self.master_volume_slider.setObjectName("Master-Lautstärke")
        self.master_volume_label = QLabel(
            str(self.master_volume_slider.value())
        )
        self.master_volume_slider.valueChanged.connect(self._on_master_volume_changed)
        master_row.addWidget(self.master_volume_slider)
        master_row.addWidget(self.master_volume_label)
        levels_form.addRow(QLabel("Master-Lautstärke (0–200)"), master_row)

        # Mic gain slider 0-200, default 100
        mic_gain_row = QHBoxLayout()
        self.mic_gain_slider = QSlider(Qt.Horizontal)
        self.mic_gain_slider.setRange(0, 200)
        self.mic_gain_slider.setValue(
            int(getattr(self.window.settings_store.settings, "mic_gain", 100))
        )
        self.mic_gain_slider.setObjectName("Mikrofonverstärkung")
        self.mic_gain_label = QLabel(
            str(self.mic_gain_slider.value())
        )
        self.mic_gain_slider.valueChanged.connect(self._on_mic_gain_changed)
        mic_gain_row.addWidget(self.mic_gain_slider)
        mic_gain_row.addWidget(self.mic_gain_label)
        levels_form.addRow(QLabel("Mikrofonverstärkung (0–200)"), mic_gain_row)

        root.addWidget(levels_group)

        # ── Aktionen ─────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        self.refresh_btn = QPushButton("Geräte a&ktualisieren")
        self.refresh_btn.clicked.connect(self.refresh_devices)
        self.apply_btn = QPushButton("Audio &anwenden")
        self.apply_btn.clicked.connect(self.on_apply)
        btn_row.addWidget(self.refresh_btn)
        btn_row.addWidget(self.apply_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)
        root.addStretch()

        # ── VU-Timer ─────────────────────────────────────────────────────
        self._vu_timer = QTimer(self)
        self._vu_timer.setInterval(250)
        self._vu_timer.timeout.connect(self._on_vu_timer)

        # Init devices after UI is ready
        QTimer.singleShot(10, lambda: self.refresh_devices())

    # ── VU Timer ─────────────────────────────────────────────────────────

    def set_active(self, active: bool) -> None:
        if active:
            self._vu_timer.start()
        else:
            self._vu_timer.stop()

    def _on_vu_timer(self) -> None:
        try:
            if not self.window.client.is_connected():
                self.vu_bar.setValue(0)
                return
            level = self.window.client.get_sound_input_level()
            self.vu_bar.setValue(max(0, min(100, int(level))))
        except Exception:
            pass

    def set_vu_level(self, level: int) -> None:
        self.vu_bar.setValue(max(0, min(100, level)))

    # ── Device refresh ───────────────────────────────────────────────────

    def refresh_devices(self) -> None:
        try:
            devices = list(self.window.client.get_sound_devices())
        except Exception:
            devices = []
        self._input_devices = [
            d for d in devices if getattr(d, "nMaxInputChannels", 0) > 0
        ]
        self._output_devices = [
            d for d in devices if getattr(d, "nMaxOutputChannels", 0) > 0
        ]
        tt_str = self.window.tt_str

        prev_in = self.input_device.currentIndex()
        prev_out = self.output_device.currentIndex()

        self.input_device.blockSignals(True)
        self.output_device.blockSignals(True)
        self.input_device.clear()
        self.output_device.clear()

        for d in self._input_devices:
            name = tt_str(d.szDeviceName)
            from system_audio import _is_loopback_name
            label = f"[Systemton] {name}" if _is_loopback_name(name) else name
            self.input_device.addItem(label)
        for d in self._output_devices:
            self.output_device.addItem(tt_str(d.szDeviceName))

        # Restore previous selection if still valid
        if 0 <= prev_in < self.input_device.count():
            self.input_device.setCurrentIndex(prev_in)
        if 0 <= prev_out < self.output_device.count():
            self.output_device.setCurrentIndex(prev_out)

        self.input_device.blockSignals(False)
        self.output_device.blockSignals(False)

    # ── Apply ─────────────────────────────────────────────────────────────

    def on_apply(self) -> None:
        try:
            in_idx = self.input_device.currentIndex()
            out_idx = self.output_device.currentIndex()
            if self._input_devices and 0 <= in_idx < len(self._input_devices):
                self.window.client.close_sound_input_device()
                self.window.client.init_sound_input_device(
                    int(self._input_devices[in_idx].nDeviceID)
                )
            if self._output_devices and 0 <= out_idx < len(self._output_devices):
                self.window.client.close_sound_output_device()
                self.window.client.init_sound_output_device(
                    int(self._output_devices[out_idx].nDeviceID)
                )
            # Apply gain levels
            try:
                self.window.client.set_sound_input_gain(self.mic_gain_slider.value() * 160)
            except Exception:
                pass
            try:
                self.window.client.set_sound_output_volume(
                    self.master_volume_slider.value() * 160
                )
            except Exception:
                pass
            self.window.set_status("Audio-Einstellungen übernommen")
        except Exception as exc:
            self.window.set_status(f"Audio-Fehler: {exc}")

    # ── Voice activation ──────────────────────────────────────────────────

    def on_voice_activation(self, *_) -> None:
        enabled = self.voice_activation.isChecked()
        try:
            self.window.client.enable_voice_activation(enabled)
            if enabled:
                self.window.client.enable_voice_transmission(True)
            else:
                self.window.client.enable_voice_transmission(False)
        except Exception:
            pass
        self.window.set_status(
            "Sprachaktivierung an" if enabled else "Sprachaktivierung aus"
        )

    def on_voice_level(self, value: int) -> None:
        try:
            self.window.client.set_voice_activation_level(value)
        except Exception:
            pass

    def on_va_delay(self, value: int) -> None:
        try:
            self.window.client.set_voice_activation_stop_delay(value)
        except Exception:
            pass

    # ── Preprocessing ─────────────────────────────────────────────────────

    def _on_preprocess_changed(self, *_) -> None:
        denoise = self.denoise_check.isChecked()
        echo = self.echo_check.isChecked()
        agc = self.agc_check.isChecked()
        # Save to settings
        setattr(self.window.settings_store.settings, "denoise", denoise)
        setattr(self.window.settings_store.settings, "echo_cancel", echo)
        setattr(self.window.settings_store.settings, "agc", agc)
        self.window.settings_store.save()
        # Apply to SDK if possible
        try:
            self.window.client.set_sound_device_effects(
                agc=agc, denoise=denoise, echo_cancel=echo
            )
        except Exception:
            pass

    # ── Loopback / Mikrofontest ───────────────────────────────────────────

    def _on_loopback_toggle(self, state: int) -> None:
        enabled = bool(state)
        if enabled:
            in_idx = self.input_device.currentIndex()
            out_idx = self.output_device.currentIndex()
            if (
                not self._input_devices
                or not (0 <= in_idx < len(self._input_devices))
                or not self._output_devices
                or not (0 <= out_idx < len(self._output_devices))
            ):
                self.window.set_status("Bitte zuerst Geräte wählen und anwenden")
                self.loopback_check.blockSignals(True)
                self.loopback_check.setChecked(False)
                self.loopback_check.blockSignals(False)
                return
            try:
                indev_id = int(self._input_devices[in_idx].nDeviceID)
                outdev_id = int(self._output_devices[out_idx].nDeviceID)
                handle = self.window.client.start_sound_loopback_test(
                    indev_id, outdev_id
                )
                if handle:
                    self._loopback_handle = handle
                    self.window.set_status("Mikrofontest gestartet")
                else:
                    self.window.set_status(
                        "Mikrofontest konnte nicht gestartet werden"
                    )
                    self.loopback_check.blockSignals(True)
                    self.loopback_check.setChecked(False)
                    self.loopback_check.blockSignals(False)
            except Exception as exc:
                self.window.set_status(f"Mikrofontest Fehler: {exc}")
                self.loopback_check.blockSignals(True)
                self.loopback_check.setChecked(False)
                self.loopback_check.blockSignals(False)
        else:
            if self._loopback_handle is not None:
                try:
                    self.window.client.close_sound_loopback_test(
                        self._loopback_handle
                    )
                except Exception:
                    pass
                self._loopback_handle = None
            self.window.set_status("Mikrofontest beendet")

    # ── Master volume / mic gain sliders ─────────────────────────────────

    def _on_master_volume_changed(self, value: int) -> None:
        self.master_volume_label.setText(str(value))
        setattr(self.window.settings_store.settings, "master_volume", value)
        self.window.settings_store.save()
        try:
            # Scale 0-200 to SDK range 0-32000 (100 = 16000 = nominal)
            self.window.client.set_sound_output_volume(value * 160)
        except Exception:
            pass

    def _on_mic_gain_changed(self, value: int) -> None:
        self.mic_gain_label.setText(str(value))
        setattr(self.window.settings_store.settings, "mic_gain", value)
        self.window.settings_store.save()
        try:
            self.window.client.set_sound_input_gain(value * 160)
        except Exception:
            pass

    # ── Systemton ─────────────────────────────────────────────────────────

    def _on_install_loopback(self) -> None:
        try:
            sa.open_loopback_installer(self)
        except Exception as exc:
            self.window.set_status(f"BlackHole-Installer: {exc}")

    def _on_refresh_sys_hint(self) -> None:
        self.sys_hint_label.setText(sa.loopback_hint())
        self.window.set_status("Systemton-Status aktualisiert")

    # ── Legacy delegate methods (called from app_qt) ──────────────────────

    def on_mic_gain(self, value: int) -> None:
        """Delegate from app_qt.set_mic_gain (dB scale). Kept for compatibility."""
        self.window.set_mic_gain(value)

    def on_out_gain(self, value: int) -> None:
        """Delegate from app_qt.set_out_gain (dB scale). Kept for compatibility."""
        self.window.set_out_gain(value)

    def apply_audio_prefs(self, prefs: dict) -> None:
        pass
