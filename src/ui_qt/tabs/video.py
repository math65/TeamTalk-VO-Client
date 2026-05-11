from __future__ import annotations

from typing import TYPE_CHECKING, List, Tuple

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QFormLayout,
    QLabel, QPushButton, QCheckBox, QComboBox, QSpinBox, QSlider,
)
from PySide6.QtCore import Qt

if TYPE_CHECKING:
    from app_qt import MainWindow


class VideoTab(QWidget):
    """Tab 13: Video – Kameraauswahl, Einstellungen, Übertragung."""

    def __init__(self, parent: QWidget, window: "MainWindow") -> None:
        super().__init__(parent)
        self.window = window
        self._devices: list = []
        self._formats: List[Tuple[object, str]] = []
        self._tx_enabled = False

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        # ── Kamera-Gerät ──────────────────────────────────────────────────
        dev_group = QGroupBox("Video-Gerät")
        dev_form = QFormLayout(dev_group)

        self.camera_choice = QComboBox()
        self.camera_choice.setObjectName("Kamera")
        self.camera_choice.currentIndexChanged.connect(self._on_device_changed)
        dev_form.addRow(QLabel("Kamera"), self.camera_choice)

        self.format_choice = QComboBox()
        self.format_choice.setObjectName("Format")
        dev_form.addRow(QLabel("Format"), self.format_choice)

        refresh_row = QHBoxLayout()
        self.refresh_btn = QPushButton("Kamera a&ktualisieren")
        self.refresh_btn.clicked.connect(self.refresh_devices)
        refresh_row.addWidget(self.refresh_btn)
        refresh_row.addStretch()
        dev_form.addRow(refresh_row)
        root.addWidget(dev_group)

        # ── Einstellungen ─────────────────────────────────────────────────
        settings_group = QGroupBox("Einstellungen")
        settings_form = QFormLayout(settings_group)

        self.fps_choice = QComboBox()
        self.fps_choice.setObjectName("FPS")
        self.fps_choice.addItems(["5", "10", "15", "20", "25", "30"])
        self.fps_choice.setCurrentIndex(2)  # default 15
        settings_form.addRow(QLabel("FPS"), self.fps_choice)

        self.resolution_choice = QComboBox()
        self.resolution_choice.setObjectName("Auflösung")
        self.resolution_choice.addItems(
            ["320x240", "640x480", "1280x720", "1920x1080"]
        )
        self.resolution_choice.setCurrentIndex(1)  # default 640x480
        settings_form.addRow(QLabel("Auflösung"), self.resolution_choice)

        self.codec_choice = QComboBox()
        self.codec_choice.setObjectName("Codec")
        self.codec_choice.addItems(["H.264", "MJPEG", "Theora"])
        saved_codec = getattr(
            self.window.settings_store.settings, "video_codec", "H.264"
        )
        idx = self.codec_choice.findText(saved_codec)
        if idx >= 0:
            self.codec_choice.setCurrentIndex(idx)
        self.codec_choice.currentIndexChanged.connect(self._on_codec_changed)
        settings_form.addRow(QLabel("Codec"), self.codec_choice)

        # Bitrate slider 100-2000 kbps
        bitrate_row = QHBoxLayout()
        self.bitrate_slider = QSlider(Qt.Horizontal)
        self.bitrate_slider.setRange(100, 2000)
        self.bitrate_slider.setValue(
            int(
                getattr(
                    self.window.settings_store.settings,
                    "video_bitrate_kbps",
                    256,
                )
                or 256
            )
        )
        self.bitrate_label = QLabel(str(self.bitrate_slider.value()) + " kbps")
        self.bitrate_slider.valueChanged.connect(self._on_bitrate_changed)
        bitrate_row.addWidget(self.bitrate_slider)
        bitrate_row.addWidget(self.bitrate_label)
        settings_form.addRow(QLabel("Bitrate (100–2000 kbps)"), bitrate_row)

        root.addWidget(settings_group)

        # ── Video senden ──────────────────────────────────────────────────
        tx_group = QGroupBox("Video senden")
        tx_layout = QVBoxLayout(tx_group)

        apply_row = QHBoxLayout()
        self.apply_btn = QPushButton("Video an&wenden")
        self.apply_btn.clicked.connect(self.on_apply)
        apply_row.addWidget(self.apply_btn)
        apply_row.addStretch()
        tx_layout.addLayout(apply_row)

        tx_btn_row = QHBoxLayout()
        self.start_btn = QPushButton("&Video senden")
        self.start_btn.clicked.connect(self.on_start_video)
        self.stop_btn = QPushButton("&Stopp")
        self.stop_btn.clicked.connect(self.on_stop_video)
        tx_btn_row.addWidget(self.start_btn)
        tx_btn_row.addWidget(self.stop_btn)
        tx_btn_row.addStretch()
        tx_layout.addLayout(tx_btn_row)

        self.stats_label = QLabel("")
        self.stats_label.setObjectName("Video-Statistik")
        self.stats_label.setWordWrap(True)
        tx_layout.addWidget(self.stats_label)

        root.addWidget(tx_group)

        # ── Aufzeichnung ──────────────────────────────────────────────────
        rec_group = QGroupBox("Aufzeichnung")
        rec_layout = QHBoxLayout(rec_group)
        self.record_btn = QPushButton("A&ufzeichnen")
        self.record_btn.clicked.connect(self._on_record)
        rec_layout.addWidget(self.record_btn)
        rec_layout.addStretch()
        root.addWidget(rec_group)

        root.addStretch()

        # Load devices
        self._load_from_settings()
        self.refresh_devices()

    # ── Settings persistence ──────────────────────────────────────────────

    def _load_from_settings(self) -> None:
        settings = self.window.settings_store.settings
        if getattr(settings, "video_bitrate_kbps", None):
            self.bitrate_slider.setValue(int(settings.video_bitrate_kbps))

    # ── Device refresh ────────────────────────────────────────────────────

    def refresh_devices(self) -> None:
        try:
            self._devices = list(self.window.client.get_video_capture_devices())
        except Exception:
            self._devices = []

        self.camera_choice.blockSignals(True)
        self.camera_choice.clear()
        if not self._devices:
            self.camera_choice.addItem("Kein Gerät gefunden")
            self.camera_choice.setEnabled(False)
            self.format_choice.clear()
            self.format_choice.setEnabled(False)
            self.camera_choice.blockSignals(False)
            return

        self.camera_choice.setEnabled(True)
        for dev in self._devices:
            self.camera_choice.addItem(self.window.tt_str(dev.szDeviceName))

        # Restore saved device
        settings = self.window.settings_store.settings
        selected = 0
        saved_id = getattr(settings, "video_device_id", None)
        if saved_id:
            for i, dev in enumerate(self._devices):
                if self.window.tt_str(dev.szDeviceID) == saved_id:
                    selected = i
                    break
        self.camera_choice.blockSignals(False)
        self.camera_choice.setCurrentIndex(selected)
        self._populate_formats(selected)

    def _populate_formats(self, dev_idx: int) -> None:
        self.format_choice.clear()
        self._formats = []
        if dev_idx < 0 or dev_idx >= len(self._devices):
            self.format_choice.setEnabled(False)
            return
        dev = self._devices[dev_idx]
        count = int(getattr(dev, "nVideoFormatsCount", 0) or 0)
        try:
            tt = self.window.client.tt
            for i in range(count):
                fmt = dev.videoFormats[i]
                fps = 0.0
                denom = int(getattr(fmt, "nFPS_Denominator", 0) or 0)
                num = int(getattr(fmt, "nFPS_Numerator", 0) or 0)
                fps = float(num) / float(denom) if denom > 0 else float(num)
                fourcc = int(fmt.picFourCC)
                try:
                    if fourcc == int(tt.FourCC.FOURCC_I420):
                        pix = "I420"
                    elif fourcc == int(tt.FourCC.FOURCC_YUY2):
                        pix = "YUY2"
                    elif fourcc == int(tt.FourCC.FOURCC_RGB32):
                        pix = "RGB32"
                    else:
                        pix = str(fourcc)
                except Exception:
                    pix = str(fourcc)
                label = (
                    f"{int(fmt.nWidth)}x{int(fmt.nHeight)}"
                    f" @ {fps:.2f} fps ({pix})"
                )
                self._formats.append((fmt, label))
        except Exception:
            pass

        if not self._formats:
            self.format_choice.setEnabled(False)
            return

        self.format_choice.setEnabled(True)
        for _, label in self._formats:
            self.format_choice.addItem(label)
        saved_idx = int(
            getattr(self.window.settings_store.settings, "video_format_index", 0)
            or 0
        )
        saved_idx = min(max(saved_idx, 0), len(self._formats) - 1)
        self.format_choice.setCurrentIndex(saved_idx)

    def _on_device_changed(self, idx: int) -> None:
        self._populate_formats(idx)

    def _selected_format(self):
        idx = self.format_choice.currentIndex()
        if idx < 0 or idx >= len(self._formats):
            return None
        return self._formats[idx][0]

    # ── Apply ─────────────────────────────────────────────────────────────

    def on_apply(self) -> None:
        if not self._devices:
            self.window.set_status("Kein Video-Gerät")
            return
        dev_idx = self.camera_choice.currentIndex()
        if dev_idx < 0 or dev_idx >= len(self._devices):
            self.window.set_status("Bitte Video-Gerät auswählen")
            return
        dev = self._devices[dev_idx]
        device_id = self.window.tt_str(dev.szDeviceID)
        fmt = self._selected_format()
        if fmt is None:
            self.window.set_status("Kein Video-Format")
            return
        try:
            self.window.client.close_video_capture_device()
        except Exception:
            pass
        ok = False
        try:
            ok = self.window.client.init_video_capture_device(device_id, fmt)
        except Exception:
            pass
        if ok:
            settings = self.window.settings_store.settings
            settings.video_device_id = device_id
            settings.video_format_index = self.format_choice.currentIndex()
            settings.video_bitrate_kbps = self.bitrate_slider.value()
            settings.video_codec = self.codec_choice.currentText()
            self.window.settings_store.save()
            self.window.set_status("Video-Gerät angewendet")
        else:
            self.window.set_status("Video-Gerät konnte nicht initialisiert werden")

    # ── Transmission ──────────────────────────────────────────────────────

    def on_start_video(self) -> None:
        if not self._devices:
            self.window.set_status("Kein Video-Gerät")
            return
        # Ensure device is initialized first
        dev_idx = self.camera_choice.currentIndex()
        if dev_idx < 0 or dev_idx >= len(self._devices):
            self.window.set_status("Bitte Video-Gerät auswählen")
            return
        fmt = self._selected_format()
        if fmt is None:
            self.window.set_status("Kein Video-Format")
            return
        dev = self._devices[dev_idx]
        device_id = self.window.tt_str(dev.szDeviceID)
        try:
            self.window.client.close_video_capture_device()
            if not self.window.client.init_video_capture_device(device_id, fmt):
                self.window.set_status("Video-Gerät konnte nicht initialisiert werden")
                return
        except Exception as exc:
            self.window.set_status(f"Video-Init Fehler: {exc}")
            return
        try:
            codec = self.window.client.build_default_video_codec(
                bitrate_kbps=self.bitrate_slider.value()
            )
            ok = self.window.client.start_video_capture_transmission(codec)
        except Exception as exc:
            self.window.set_status(f"Video-Übertragung Fehler: {exc}")
            return
        if ok:
            self._tx_enabled = True
            self.stats_label.setText("Video-Übertragung aktiv")
            self.window.set_status("Video senden aktiviert")
        else:
            self.window.set_status("Video senden fehlgeschlagen")

    def on_stop_video(self) -> None:
        try:
            self.window.client.stop_video_capture_transmission()
        except Exception:
            pass
        self._tx_enabled = False
        self.stats_label.setText("")
        self.window.set_status("Video senden deaktiviert")

    # ── Recording ─────────────────────────────────────────────────────────

    def _on_record(self) -> None:
        try:
            if hasattr(self.window.client, "start_video_recording"):
                ok = self.window.client.start_video_recording()
                if ok:
                    self.window.set_status("Video-Aufzeichnung gestartet")
                    return
        except Exception:
            pass
        self.window.set_status("Video-Aufzeichnung nicht verfügbar")

    # ── Settings change handlers ──────────────────────────────────────────

    def _on_bitrate_changed(self, value: int) -> None:
        self.bitrate_label.setText(f"{value} kbps")
        setattr(self.window.settings_store.settings, "video_bitrate_kbps", value)
        self.window.settings_store.save()

    def _on_codec_changed(self, idx: int) -> None:
        codec = self.codec_choice.currentText()
        setattr(self.window.settings_store.settings, "video_codec", codec)
        self.window.settings_store.save()
