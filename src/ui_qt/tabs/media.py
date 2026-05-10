from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import List, Optional, TYPE_CHECKING

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QFormLayout,
    QLabel, QLineEdit, QListWidget, QPushButton, QComboBox,
    QCheckBox, QProgressBar, QFileDialog, QTabWidget,
)

if TYPE_CHECKING:
    from app_qt import MainWindow

_RADIO_ENTRIES = [
    ("localradio Aachen und region", "https://stream.dashitradio.de/dashitradio/mp3-128/stream.mp3"),
    ("90s90s - Main", "https://streams.90s90s.de/main/mp3-128/streams.90s90s.de/"),
    ("90s90s - Rock", "https://streams.90s90s.de/rock/mp3-192/streams.90s90s.de/"),
    ("90s90s - Pop", "https://streams.90s90s.de/pop/mp3-128/streams.90s90s.de/"),
    ("90s90s - Eurodance", "https://streams.90s90s.de/eurodance/mp3-128/streams.90s90s.de/"),
    ("90s90s - House", "https://streams.90s90s.de/house/mp3-192/streams.90s90s.de/"),
    ("90s90s - Trance", "https://streams.90s90s.de/trance/mp3-128/streams.90s90s.de/"),
    ("90s90s - Techno", "https://streams.90s90s.de/techno/mp3-192/streams.90s90s.de/"),
    ("TechnoBase.FM", "http://listen.technobase.fm/tunein-mp3"),
    ("HouseTime.FM", "http://listen.housetime.fm/listen.mp3.m3u"),
    ("HardBase.FM", "http://listen.hardbase.fm/listen.mp3.m3u"),
    ("TranceBase.FM", "http://listen.trancebase.fm/listen.mp3.m3u"),
    ("Hoerspiele rund um die Uhr", "https://stream.laut.fm/hoerspiel"),
]


class MediaTab(QWidget):
    """Tab 5: Aufnahme & Medien."""

    def __init__(self, parent: QWidget, window: "MainWindow") -> None:
        super().__init__(parent)
        self.window = window
        self._recording = False
        self._streaming = False

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)

        inner = QTabWidget()
        root.addWidget(inner)

        # --- Aufnahme ---
        rec_widget = QWidget()
        rec_layout = QVBoxLayout(rec_widget)
        rec_group = QGroupBox("Aufnahme")
        rec_form = QFormLayout(rec_group)
        self.rec_path = QLineEdit()
        rec_browse = QPushButton("Durchsuchen…")
        rec_browse.clicked.connect(self._on_browse_rec)
        rec_path_row = QHBoxLayout()
        rec_path_row.addWidget(self.rec_path, 1)
        rec_path_row.addWidget(rec_browse)
        rec_form.addRow("Aufnahmeordner", rec_path_row)
        self.rec_format = QComboBox()
        self.rec_format.addItems(["MP3", "WAV", "OGG"])
        rec_form.addRow("Format", self.rec_format)
        rec_layout.addWidget(rec_group)
        rec_btn_row = QHBoxLayout()
        self.rec_start_btn = QPushButton("&Aufnahme starten")
        self.rec_start_btn.clicked.connect(self.on_start_recording)
        self.rec_stop_btn = QPushButton("&Aufnahme stoppen")
        self.rec_stop_btn.clicked.connect(self.on_stop_recording)
        rec_btn_row.addWidget(self.rec_start_btn)
        rec_btn_row.addWidget(self.rec_stop_btn)
        rec_btn_row.addStretch()
        rec_layout.addLayout(rec_btn_row)
        rec_layout.addStretch()
        inner.addTab(rec_widget, "Aufnahme")

        # --- Medienstreaming (URL) ---
        stream_widget = QWidget()
        stream_layout = QVBoxLayout(stream_widget)
        url_group = QGroupBox("URL / Datei streamen")
        url_form = QFormLayout(url_group)
        self.stream_url = QLineEdit()
        self.stream_url.setPlaceholderText("https://... oder Pfad zur Mediendatei")
        url_form.addRow("URL / Pfad", self.stream_url)
        stream_layout.addWidget(url_group)
        stream_btn_row = QHBoxLayout()
        self.stream_start_btn = QPushButton("&Streamen starten")
        self.stream_start_btn.clicked.connect(self.on_start_stream)
        self.stream_stop_btn = QPushButton("&Streamen stoppen")
        self.stream_stop_btn.clicked.connect(self.on_stop_stream)
        self.stream_browse_btn = QPushButton("Datei wählen…")
        self.stream_browse_btn.clicked.connect(self._on_browse_stream)
        stream_btn_row.addWidget(self.stream_start_btn)
        stream_btn_row.addWidget(self.stream_stop_btn)
        stream_btn_row.addWidget(self.stream_browse_btn)
        stream_btn_row.addStretch()
        stream_layout.addLayout(stream_btn_row)
        self.stream_progress = QProgressBar()
        self.stream_progress.setRange(0, 100)
        self.stream_progress.setVisible(False)
        stream_layout.addWidget(self.stream_progress)
        stream_layout.addStretch()
        inner.addTab(stream_widget, "Medienstreaming")

        # --- Radio ---
        radio_widget = QWidget()
        radio_layout = QVBoxLayout(radio_widget)
        radio_group = QGroupBox("Radiosender")
        radio_inner = QVBoxLayout(radio_group)
        self.radio_list = QListWidget()
        self.radio_list.setObjectName("Radiosender")
        for name, _ in _RADIO_ENTRIES:
            self.radio_list.addItem(name)
        self.radio_list.itemActivated.connect(self._on_radio_activate)
        radio_inner.addWidget(self.radio_list, 1)
        radio_btn_row = QHBoxLayout()
        self.radio_play_btn = QPushButton("&Abspielen")
        self.radio_play_btn.clicked.connect(self._on_radio_activate)
        radio_btn_row.addWidget(self.radio_play_btn)
        radio_btn_row.addStretch()
        radio_inner.addLayout(radio_btn_row)
        radio_layout.addWidget(radio_group, 1)
        inner.addTab(radio_widget, "Radio")

        # --- YouTube/yt-dlp ---
        yt_widget = QWidget()
        yt_layout = QVBoxLayout(yt_widget)
        yt_group = QGroupBox("YouTube / yt-dlp")
        yt_inner = QVBoxLayout(yt_group)
        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("Suche / URL:"))
        self.yt_search = QLineEdit()
        self.yt_search.setPlaceholderText("URL oder Suchbegriff eingeben")
        self.yt_search.returnPressed.connect(self.on_yt_search)
        search_row.addWidget(self.yt_search, 1)
        self.yt_source = QComboBox()
        self.yt_source.addItems(["YouTube", "SoundCloud"])
        search_row.addWidget(self.yt_source)
        yt_inner.addLayout(search_row)
        self.yt_list = QListWidget()
        self.yt_list.setObjectName("Suchergebnisse")
        yt_inner.addWidget(self.yt_list, 1)
        yt_btn_row = QHBoxLayout()
        self.yt_search_btn = QPushButton("&Suchen")
        self.yt_search_btn.clicked.connect(self.on_yt_search)
        self.yt_play_btn = QPushButton("&Streamen")
        self.yt_play_btn.clicked.connect(self.on_yt_play)
        yt_btn_row.addWidget(self.yt_search_btn)
        yt_btn_row.addWidget(self.yt_play_btn)
        yt_btn_row.addStretch()
        yt_inner.addLayout(yt_btn_row)
        yt_layout.addWidget(yt_group, 1)
        inner.addTab(yt_widget, "YouTube/yt-dlp")

    def _on_browse_rec(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Aufnahmeordner wählen")
        if path:
            self.rec_path.setText(path)

    def _on_browse_stream(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Mediendatei wählen", "",
            "Mediendateien (*.mp3 *.wav *.ogg *.flac *.aac *.m4a *.mp4);;Alle Dateien (*.*)"
        )
        if path:
            self.stream_url.setText(path)

    def on_start_recording(self) -> None:
        rec_path = self.rec_path.text().strip()
        fmt = self.rec_format.currentText().lower()
        self.window.start_recording(rec_path, fmt)

    def on_stop_recording(self) -> None:
        self.window.stop_recording()

    def on_start_stream(self) -> None:
        url = self.stream_url.text().strip()
        if url:
            self.window.start_media_stream(url)

    def on_stop_stream(self) -> None:
        self.window.stop_media_stream()

    def _on_radio_activate(self, *_) -> None:
        row = self.radio_list.currentRow()
        if 0 <= row < len(_RADIO_ENTRIES):
            _, url = _RADIO_ENTRIES[row]
            self.stream_url.setText(url)
            self.window.start_media_stream(url)

    def on_yt_search(self) -> None:
        query = self.yt_search.text().strip()
        source = self.yt_source.currentText()
        if query:
            self.window.yt_search(query, source, self.yt_list)

    def on_yt_play(self) -> None:
        row = self.yt_list.currentRow()
        if row >= 0:
            item = self.yt_list.item(row)
            if item:
                url = item.data(256)  # Qt.UserRole
                if url:
                    self.window.start_media_stream(url)

    def update_stream_progress(self, pct: int) -> None:
        self.stream_progress.setValue(pct)
        self.stream_progress.setVisible(pct < 100)
