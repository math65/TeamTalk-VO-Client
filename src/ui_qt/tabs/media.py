from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Optional, TYPE_CHECKING

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QFormLayout,
    QLabel, QLineEdit, QListWidget, QPushButton, QComboBox,
    QCheckBox, QFileDialog, QTabWidget, QSpinBox, QMessageBox,
)
from PySide6.QtCore import Qt

if TYPE_CHECKING:
    from app_qt import MainWindow

try:
    import requests as _requests
except Exception:
    _requests = None

_RADIO_ENTRIES = [
    ("localradio Aachen und region", "https://stream.dashitradio.de/dashitradio/mp3-128/stream.mp3"),
    ("hitradion1", "https://frontend.streamonkey.net/fhn-hitradion1"),
    ("Ostseewelle - Nord", "https://ostseewelle-nord.cast.addradio.de/ostseewelle/nord/mp3/high"),
    ("Ostseewelle - Ost", "https://ostseewelle-ost.cast.addradio.de/ostseewelle/ost/mp3/high"),
    ("Ostseewelle - West", "https://ostseewelle-west.cast.addradio.de/ostseewelle/west/mp3/high"),
    ("90s90s - 2000er", "https://streams.90s90s.de/90s00s/mp3-128/streams.90s90s.de/"),
    ("90s90s - In the Mix", "https://streams.90s90s.de/inthemix/mp3-192/streams.90s90s.de/"),
    ("90s90s - Trance", "https://streams.90s90s.de/trance/mp3-128/streams.90s90s.de/"),
    ("90s90s - Techno Essentials", "https://streams.90s90s.de/technoessentials/mp3-128/streams.90s90s.de/"),
    ("90s90s - Techno", "https://streams.90s90s.de/techno/mp3-128/streams.90s90s.de/"),
    ("90s90s - Sachsenradio", "https://streams.90s90s.de/sachsenradio/mp3-192/streams.90s90s.de/"),
    ("90s90s - Rock", "https://streams.90s90s.de/rock/mp3-192/streams.90s90s.de/"),
    ("90s90s - Reggae", "https://streams.90s90s.de/reggae/mp3-192/streams.90s90s.de/"),
    ("90s90s - Pop", "https://streams.90s90s.de/pop/mp3-128/streams.90s90s.de/"),
    ("90s90s - NRW", "https://streams.90s90s.de/nrw/mp3-128/streams.90s90s.de/"),
    ("90s90s - Main", "https://streams.90s90s.de/main/mp3-128/streams.90s90s.de/"),
    ("90s90s - House", "https://streams.90s90s.de/house/mp3-192/streams.90s90s.de/"),
    ("90s90s - HipHop", "https://streams.90s90s.de/hiphop/mp3-128/streams.90s90s.de/"),
    ("90s90s - Eurodance", "https://streams.90s90s.de/eurodance/mp3-128/streams.90s90s.de/"),
    ("90s90s - Danceradio", "https://streams.90s90s.de/danceradio/mp3-192/streams.90s90s.de/"),
    ("90s90s - Rave", "https://streams.90s90s.de/RAVE/mp3-192/streams.90s90s.de/"),
    ("80s80s - Dance", "https://streams.80s80s.de/dance/mp3-192/streams.80s80s.de/"),
    ("80s80s - Deutsch", "https://streams.80s80s.de/deutsch/mp3-192/streams.80s80s.de/"),
    ("80s80s - Rock", "https://streams.80s80s.de/rock/mp3-192/streams.80s80s.de/"),
    ("TechnoBase.FM", "http://listen.technobase.fm/tunein-mp3"),
    ("HouseTime.FM", "http://listen.housetime.fm/listen.mp3.m3u"),
    ("HardBase.FM", "http://listen.hardbase.fm/listen.mp3.m3u"),
    ("TranceBase.FM", "http://listen.trancebase.fm/listen.mp3.m3u"),
    ("CoreTime.FM", "http://listen.coretime.fm/listen.mp3.m3u"),
    ("ClubTime.FM", "http://listen.clubtime.fm/listen.mp3.m3u"),
    ("Hoerspiele rund um die Uhr", "https://stream.laut.fm/hoerspiel"),
    ("Musiksender von Radiorobbe", "http://stream.powerradio4u.de:8010/radio.mp3"),
    ("Mechanische Musikinstrumente", "https://global.citrus3.com:2020/stream/mechanicalmusicradio"),
]

_YT_SOURCES = [
    ("YouTube", "ytsearch"),
    ("SoundCloud", "scsearch"),
    ("Twitch", None),
    ("Bandcamp", None),
    ("Vimeo", None),
    ("Mixcloud", None),
]


class MediaTab(QWidget):
    """Tab 5: Aufnahme und Medien."""

    def __init__(self, parent: QWidget, window: "MainWindow") -> None:
        super().__init__(parent)
        self.window = window
        self._recording = False
        self._streaming = False
        self._yt_results: list = []
        self._radio_search_results: list = []
        self._podcast_results: list = []
        self._podcast_episodes: list = []
        self._playlist_tracks: List[str] = []
        self._pl_streaming = False
        self._playlist_current = -1

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)

        self._inner_tabs = QTabWidget()
        root.addWidget(self._inner_tabs)

        self._inner_tabs.addTab(self._build_recording_tab(), "Aufnahme")   # 0
        self._inner_tabs.addTab(self._build_file_tab(), "Datei")            # 1
        self._inner_tabs.addTab(self._build_ytdlp_tab(), "YouTube/yt-dlp") # 2
        self._inner_tabs.addTab(self._build_radio_tab(), "Webradio")        # 3
        self._inner_tabs.addTab(self._build_podcast_tab(), "Podcasts")      # 4
        self._inner_tabs.addTab(self._build_playlist_tab(), "Playlist")     # 5
        inner = self._inner_tabs  # alias kept for legacy uses in this file

    # ------------------------------------------------------------------
    # Tab builders
    # ------------------------------------------------------------------

    def _build_recording_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        rec_group = QGroupBox("Kanal aufnehmen")
        rec_form = QFormLayout(rec_group)
        self.rec_format = QComboBox()
        self.rec_format.addItems(["WAV", "MP3 16k", "MP3 32k", "MP3 64k", "MP3 128k", "MP3 256k", "MP3 320k"])
        rec_form.addRow("Format", self.rec_format)
        layout.addWidget(rec_group)

        rec_btn_row = QHBoxLayout()
        self.rec_start_btn = QPushButton("&Aufnahme starten")
        self.rec_start_btn.clicked.connect(self.on_rec_start)
        self.rec_stop_btn = QPushButton("Aufnahme &stoppen")
        self.rec_stop_btn.clicked.connect(self.on_rec_stop)
        self.rec_stop_btn.setEnabled(False)
        rec_btn_row.addWidget(self.rec_start_btn)
        rec_btn_row.addWidget(self.rec_stop_btn)
        rec_btn_row.addStretch()
        layout.addLayout(rec_btn_row)

        convo_group = QGroupBox("Konversationen aufzeichnen")
        convo_form = QFormLayout(convo_group)
        self.user_rec_enable = QCheckBox("&Automatisch aufzeichnen")
        convo_form.addRow("", self.user_rec_enable)
        self.user_rec_dir = QLineEdit()
        self.user_rec_dir.setPlaceholderText("Zielordner...")
        dir_btn = QPushButton("Wählen…")
        dir_btn.clicked.connect(self._on_browse_user_rec_dir)
        dir_row = QHBoxLayout()
        dir_row.addWidget(self.user_rec_dir, 1)
        dir_row.addWidget(dir_btn)
        convo_form.addRow("Zielordner", dir_row)
        self.user_rec_pattern = QLineEdit("%Y%m%d-%H%M%S #%userid% %username%")
        convo_form.addRow("Dateiname", self.user_rec_pattern)
        self.user_rec_format = QComboBox()
        self.user_rec_format.addItems(["WAV", "MP3 128k", "MP3 256k"])
        convo_form.addRow("Format", self.user_rec_format)
        self.user_rec_include_self = QCheckBox("&Eigene Stimme mit aufnehmen")
        self.user_rec_include_self.setChecked(True)
        convo_form.addRow("", self.user_rec_include_self)
        apply_btn = QPushButton("An&wenden")
        apply_btn.clicked.connect(self.on_user_record_apply)
        convo_form.addRow("", apply_btn)
        layout.addWidget(convo_group)
        layout.addStretch()
        return w

    def _build_file_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        url_group = QGroupBox("URL / Datei streamen")
        url_form = QFormLayout(url_group)
        url_row = QHBoxLayout()
        self.stream_url = QLineEdit()
        self.stream_url.setPlaceholderText("https://... oder Pfad zur Mediendatei")
        browse_btn = QPushButton("Datei…")
        browse_btn.clicked.connect(self._on_browse_stream)
        url_row.addWidget(self.stream_url, 1)
        url_row.addWidget(browse_btn)
        url_form.addRow("URL / Pfad", url_row)
        self.stream_gain = QSpinBox()
        self.stream_gain.setRange(25, 400)
        self.stream_gain.setValue(100)
        url_form.addRow("Lautstärke (25–400)", self.stream_gain)
        layout.addWidget(url_group)

        btn_row = QHBoxLayout()
        self.stream_start_btn = QPushButton("&Streamen starten")
        self.stream_start_btn.clicked.connect(self.on_start_stream)
        self.stream_pause_btn = QPushButton("&Pause")
        self.stream_pause_btn.clicked.connect(self.on_pause_stream)
        self.stream_stop_btn = QPushButton("St&opp")
        self.stream_stop_btn.clicked.connect(self.on_stop_stream)
        btn_row.addWidget(self.stream_start_btn)
        btn_row.addWidget(self.stream_pause_btn)
        btn_row.addWidget(self.stream_stop_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)
        layout.addStretch()
        return w

    def _build_ytdlp_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        src_row = QHBoxLayout()
        src_row.addWidget(QLabel("Quelle:"))
        self.yt_source = QComboBox()
        for name, _ in _YT_SOURCES:
            self.yt_source.addItem(name)
        self.yt_source.currentIndexChanged.connect(self._on_yt_source_changed)
        src_row.addWidget(self.yt_source, 1)
        layout.addLayout(src_row)

        search_group = QGroupBox("Suche")
        search_inner = QVBoxLayout(search_group)
        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("Suche:"))
        self.yt_search = QLineEdit()
        self.yt_search.setPlaceholderText("Suchbegriff eingeben")
        self.yt_search.returnPressed.connect(self.on_yt_search)
        self.yt_search_btn = QPushButton("&Suchen")
        self.yt_search_btn.clicked.connect(self.on_yt_search)
        search_row.addWidget(self.yt_search, 1)
        search_row.addWidget(self.yt_search_btn)
        search_inner.addLayout(search_row)
        self.yt_results = QListWidget()
        search_inner.addWidget(self.yt_results, 1)
        layout.addWidget(search_group, 1)

        url_row = QHBoxLayout()
        url_row.addWidget(QLabel("Link:"))
        self.yt_url = QLineEdit()
        self.yt_url.setPlaceholderText("URL direkt eingeben oder aus Suche übernehmen")
        url_row.addWidget(self.yt_url, 1)
        layout.addLayout(url_row)

        self.yt_status = QLabel("Status: bereit")
        layout.addWidget(self.yt_status)

        ctrl_row = QHBoxLayout()
        self.yt_stream_btn = QPushButton("St&reamen")
        self.yt_stream_btn.clicked.connect(self.on_yt_stream)
        self.yt_stop_btn = QPushButton("St&opp")
        self.yt_stop_btn.clicked.connect(self.on_stop_stream)
        yt_gain_lbl = QLabel("Lautstärke:")
        self.yt_gain = QSpinBox()
        self.yt_gain.setRange(25, 400)
        self.yt_gain.setValue(100)
        ctrl_row.addWidget(self.yt_stream_btn)
        ctrl_row.addWidget(self.yt_stop_btn)
        ctrl_row.addStretch()
        ctrl_row.addWidget(yt_gain_lbl)
        ctrl_row.addWidget(self.yt_gain)
        layout.addLayout(ctrl_row)

        self.yt_results.currentRowChanged.connect(self._on_yt_result_selected)
        self._on_yt_source_changed(0)
        return w

    def _build_radio_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        search_group = QGroupBox("Online-Suche (radio-browser.info)")
        search_inner = QVBoxLayout(search_group)
        s_row = QHBoxLayout()
        s_row.addWidget(QLabel("Suche:"))
        self.radio_search = QLineEdit()
        self.radio_search.setPlaceholderText("Sendername...")
        self.radio_search.returnPressed.connect(self.on_radio_search)
        self.radio_search_btn = QPushButton("&Suchen")
        self.radio_search_btn.clicked.connect(self.on_radio_search)
        s_row.addWidget(self.radio_search, 1)
        s_row.addWidget(self.radio_search_btn)
        search_inner.addLayout(s_row)
        self.radio_search_results = QListWidget()
        self.radio_search_results.currentRowChanged.connect(self._on_radio_search_select)
        search_inner.addWidget(self.radio_search_results, 1)
        layout.addWidget(search_group)

        preset_group = QGroupBox("Senderliste")
        preset_inner = QVBoxLayout(preset_group)
        self.radio_list = QListWidget()
        for name, _ in _RADIO_ENTRIES:
            self.radio_list.addItem(name)
        self.radio_list.currentRowChanged.connect(self._on_radio_preset_select)
        preset_inner.addWidget(self.radio_list, 1)
        layout.addWidget(preset_group, 1)

        url_row = QHBoxLayout()
        url_row.addWidget(QLabel("Stream-URL:"))
        self.radio_url = QLineEdit()
        url_row.addWidget(self.radio_url, 1)
        layout.addLayout(url_row)

        gain_row = QHBoxLayout()
        self.radio_gain = QSpinBox()
        self.radio_gain.setRange(25, 400)
        self.radio_gain.setValue(100)
        self.radio_play_btn = QPushButton("&Abspielen")
        self.radio_play_btn.clicked.connect(self.on_radio_stream)
        self.radio_stop_btn = QPushButton("St&opp")
        self.radio_stop_btn.clicked.connect(self.on_stop_stream)
        gain_row.addWidget(self.radio_play_btn)
        gain_row.addWidget(self.radio_stop_btn)
        gain_row.addStretch()
        gain_row.addWidget(QLabel("Lautstärke:"))
        gain_row.addWidget(self.radio_gain)
        layout.addLayout(gain_row)
        return w

    def _build_podcast_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        search_group = QGroupBox("Podcast-Suche (iTunes)")
        search_inner = QVBoxLayout(search_group)
        s_row = QHBoxLayout()
        s_row.addWidget(QLabel("Suche:"))
        self.podcast_search = QLineEdit()
        self.podcast_search.returnPressed.connect(self.on_podcast_search)
        self.podcast_search_btn = QPushButton("&Suchen")
        self.podcast_search_btn.clicked.connect(self.on_podcast_search)
        s_row.addWidget(self.podcast_search, 1)
        s_row.addWidget(self.podcast_search_btn)
        search_inner.addLayout(s_row)
        self.podcast_list = QListWidget()
        self.podcast_list.currentRowChanged.connect(self._on_podcast_select)
        search_inner.addWidget(self.podcast_list, 1)
        layout.addWidget(search_group)

        feed_group = QGroupBox("Feed-URL")
        feed_inner = QHBoxLayout(feed_group)
        self.podcast_feed = QLineEdit()
        self.podcast_feed.setPlaceholderText("RSS/Atom Feed-URL...")
        self.podcast_feed_btn = QPushButton("&Feed laden")
        self.podcast_feed_btn.clicked.connect(self.on_podcast_feed_load)
        feed_inner.addWidget(self.podcast_feed, 1)
        feed_inner.addWidget(self.podcast_feed_btn)
        layout.addWidget(feed_group)

        episode_group = QGroupBox("Episoden")
        episode_inner = QVBoxLayout(episode_group)
        self.episode_list = QListWidget()
        episode_inner.addWidget(self.episode_list, 1)
        layout.addWidget(episode_group, 1)

        ctrl_row = QHBoxLayout()
        self.episode_stream_btn = QPushButton("&Episode streamen")
        self.episode_stream_btn.clicked.connect(self.on_episode_stream)
        self.podcast_stop_btn = QPushButton("St&opp")
        self.podcast_stop_btn.clicked.connect(self.on_stop_stream)
        self.podcast_gain = QSpinBox()
        self.podcast_gain.setRange(25, 400)
        self.podcast_gain.setValue(100)
        ctrl_row.addWidget(self.episode_stream_btn)
        ctrl_row.addWidget(self.podcast_stop_btn)
        ctrl_row.addStretch()
        ctrl_row.addWidget(QLabel("Lautstärke:"))
        ctrl_row.addWidget(self.podcast_gain)
        layout.addLayout(ctrl_row)
        return w

    def _build_playlist_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        self.pl_list = QListWidget()
        layout.addWidget(self.pl_list, 1)

        edit_row = QHBoxLayout()
        pl_add = QPushButton("&Hinzufügen…")
        pl_add.clicked.connect(self._on_pl_add)
        pl_m3u = QPushButton("M3U &laden…")
        pl_m3u.clicked.connect(self._on_pl_load_m3u)
        pl_remove = QPushButton("&Entfernen")
        pl_remove.clicked.connect(self._on_pl_remove)
        pl_up = QPushButton("Nach &oben")
        pl_up.clicked.connect(self._on_pl_move_up)
        pl_down = QPushButton("Nach &unten")
        pl_down.clicked.connect(self._on_pl_move_down)
        pl_export = QPushButton("Als M3U e&xportieren…")
        pl_export.clicked.connect(self._on_pl_export)
        pl_clear = QPushButton("&Leeren")
        pl_clear.clicked.connect(self._on_pl_clear)
        for btn in (pl_add, pl_m3u, pl_remove, pl_up, pl_down, pl_export, pl_clear):
            edit_row.addWidget(btn)
        layout.addLayout(edit_row)

        self.pl_auto_next = QCheckBox("&Automatisch weiter (nächster Titel nach Ende)")
        self.pl_auto_next.setChecked(True)
        layout.addWidget(self.pl_auto_next)

        ctrl_row = QHBoxLayout()
        self.pl_play_btn = QPushButton("A&bspielen")
        self.pl_play_btn.clicked.connect(self._on_pl_play)
        self.pl_stop_btn = QPushButton("St&opp")
        self.pl_stop_btn.clicked.connect(self.on_stop_stream)
        self.pl_gain = QSpinBox()
        self.pl_gain.setRange(25, 400)
        self.pl_gain.setValue(100)
        ctrl_row.addWidget(self.pl_play_btn)
        ctrl_row.addWidget(self.pl_stop_btn)
        ctrl_row.addStretch()
        ctrl_row.addWidget(QLabel("Lautstärke:"))
        ctrl_row.addWidget(self.pl_gain)
        layout.addLayout(ctrl_row)
        return w

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def _on_browse_user_rec_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Aufnahmeordner wählen")
        if path:
            self.user_rec_dir.setText(path)

    def _get_audio_format(self) -> int:
        idx = self.rec_format.currentIndex()
        formats = [1, 2, 3, 4, 5, 6, 7]  # AFF_WAVE=1, AFF_MP3_16K=2 … AFF_MP3_320K=7
        return formats[idx] if 0 <= idx < len(formats) else 1

    def _get_user_rec_format(self) -> int:
        idx = self.user_rec_format.currentIndex()
        return {0: 1, 1: 5, 2: 6}.get(idx, 1)

    def on_rec_start(self) -> None:
        ext = "mp3" if self.rec_format.currentIndex() > 0 else "wav"
        path, _ = QFileDialog.getSaveFileName(
            self, "Aufnahme speichern unter", "",
            f"{ext.upper()} (*.{ext});;Alle Dateien (*.*)"
        )
        if not path:
            return
        fmt = self._get_audio_format()
        ok = self.window.client.start_recording_muxed(path, fmt)
        if ok:
            self._recording = True
            self.rec_start_btn.setEnabled(False)
            self.rec_stop_btn.setEnabled(True)
            self.window.set_status(f"Aufnahme gestartet: {path}")
        else:
            self.window.set_status("Aufnahme konnte nicht gestartet werden")

    def on_rec_stop(self) -> None:
        self.window.client.stop_recording_muxed()
        self._recording = False
        self.rec_start_btn.setEnabled(True)
        self.rec_stop_btn.setEnabled(False)
        self.window.set_status("Aufnahme gestoppt")

    def on_user_record_apply(self) -> None:
        enabled = self.user_rec_enable.isChecked()
        folder = self.user_rec_dir.text().strip() if enabled else ""
        if enabled and not folder:
            self.window.set_status("Bitte Zielordner wählen")
            return
        pattern = self.user_rec_pattern.text().strip() if enabled else ""
        fmt = self._get_user_rec_format()
        include_self = self.user_rec_include_self.isChecked()
        self.window.configure_user_recording(enabled, folder, pattern, fmt, include_self)

    # ------------------------------------------------------------------
    # File / URL streaming
    # ------------------------------------------------------------------

    def _on_browse_stream(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Mediendatei wählen", "",
            "Mediendateien (*.mp3 *.wav *.ogg *.flac *.aac *.m4a *.mp4);;Alle Dateien (*.*)"
        )
        if path:
            self.stream_url.setText(path)

    def _gain_float(self, spinbox: QSpinBox) -> float:
        return max(0.1, spinbox.value() / 100.0)

    def on_start_stream(self) -> None:
        url = self.stream_url.text().strip()
        if not url:
            return
        ok = self.window.client.start_streaming_media_to_channel(url, preamp_gain=self._gain_float(self.stream_gain))
        if ok:
            self._streaming = True
            self.window.set_status(f"Streaming gestartet: {url}")
        else:
            self.window.set_status("Streaming konnte nicht gestartet werden")

    def on_pause_stream(self) -> None:
        if self._streaming:
            self.window.client.update_streaming_media(paused=True)
            self.window.set_status("Streaming pausiert")

    def on_stop_stream(self) -> None:
        if self._streaming:
            try:
                self.window.client.stop_streaming_media()
            except Exception:
                pass
            self._streaming = False
            self._pl_streaming = False
            self.window.set_status("Streaming gestoppt")

    # ------------------------------------------------------------------
    # YouTube / yt-dlp
    # ------------------------------------------------------------------

    def _on_yt_source_changed(self, idx: int) -> None:
        if 0 <= idx < len(_YT_SOURCES):
            _, prefix = _YT_SOURCES[idx]
            self.yt_search.setEnabled(prefix is not None)
            self.yt_search_btn.setEnabled(prefix is not None)

    def _find_yt_dlp(self) -> Optional[str]:
        exe = "yt-dlp.exe" if sys.platform == "win32" else "yt-dlp"
        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            bundled = Path(sys._MEIPASS) / "yt-dlp" / exe
            if bundled.exists():
                return str(bundled)
        local = Path(__file__).resolve().parents[3] / "third_party" / "yt-dlp" / exe
        if local.exists():
            return str(local)
        return shutil.which(exe) or shutil.which("yt-dlp")

    def on_yt_search(self) -> None:
        term = self.yt_search.text().strip()
        if not term:
            return
        src_idx = self.yt_source.currentIndex()
        if src_idx < 0 or src_idx >= len(_YT_SOURCES):
            return
        _, prefix = _YT_SOURCES[src_idx]
        if not prefix:
            return
        ytdlp = self._find_yt_dlp()
        if not ytdlp:
            self.yt_status.setText("Status: yt-dlp nicht gefunden")
            return
        self.yt_search_btn.setEnabled(False)
        self.yt_status.setText("Status: Suche läuft...")

        def worker():
            from ui_qt.call_after import call_after
            try:
                cmd = [ytdlp, "--dump-json", "--no-playlist", f"{prefix}10:{term}"]
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
                if proc.returncode != 0:
                    err = (proc.stderr or proc.stdout or "Fehler").strip()
                    call_after(self._yt_search_failed, err)
                    return
                items, parsed = [], []
                for line in (proc.stdout or "").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except Exception:
                        continue
                    title = data.get("title") or "Unbekannt"
                    uploader = data.get("uploader") or data.get("channel") or ""
                    duration = data.get("duration")
                    url = data.get("webpage_url") or data.get("url") or ""
                    label = title
                    if uploader:
                        label += f" — {uploader}"
                    if duration:
                        label += f" — {int(duration) // 60}:{int(duration) % 60:02d}"
                    items.append(label)
                    parsed.append({"title": title, "url": url})
                call_after(self._yt_search_ready, items, parsed)
            except Exception as exc:
                from ui_qt.call_after import call_after as _ca
                _ca(self._yt_search_failed, str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _yt_search_ready(self, items: list, parsed: list) -> None:
        self._yt_results = parsed
        self.yt_results.clear()
        for label in items:
            self.yt_results.addItem(label)
        if items:
            self.yt_results.setCurrentRow(0)
        self.yt_search_btn.setEnabled(True)
        self.yt_status.setText(f"Status: {len(items)} Treffer")

    def _yt_search_failed(self, message: str) -> None:
        self.yt_search_btn.setEnabled(True)
        self.yt_status.setText("Status: Suche fehlgeschlagen")
        self.window.set_status(f"yt-dlp Suche fehlgeschlagen: {message}")

    def _on_yt_result_selected(self, row: int) -> None:
        if 0 <= row < len(self._yt_results):
            url = self._yt_results[row].get("url") or ""
            if url:
                self.yt_url.setText(url)

    def on_yt_stream(self) -> None:
        url = self.yt_url.text().strip()
        if not url:
            self.window.set_status("Bitte Link eingeben")
            return
        ytdlp = self._find_yt_dlp()
        if not ytdlp:
            self.yt_status.setText("Status: yt-dlp nicht gefunden")
            return
        self.yt_stream_btn.setEnabled(False)
        self.yt_status.setText("Status: Stream wird vorbereitet...")

        def worker():
            from ui_qt.call_after import call_after
            try:
                cmd = [ytdlp, "-g", "-f", "bestaudio/best", "--no-playlist", url]
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
                if proc.returncode != 0:
                    err = (proc.stderr or proc.stdout or "Fehler").strip()
                    call_after(self._yt_stream_failed, err)
                    return
                stream_url = (proc.stdout or "").splitlines()[0].strip()
                if not stream_url:
                    call_after(self._yt_stream_failed, "Keine Stream-URL gefunden")
                    return
                call_after(self._yt_stream_ready, stream_url)
            except Exception as exc:
                from ui_qt.call_after import call_after as _ca
                _ca(self._yt_stream_failed, str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _yt_stream_ready(self, stream_url: str) -> None:
        self.yt_stream_btn.setEnabled(True)
        ok = self.window.client.start_streaming_media_to_channel(stream_url, preamp_gain=self._gain_float(self.yt_gain))
        if ok:
            self._streaming = True
            self.yt_status.setText("Status: Stream läuft")
            self.window.set_status("yt-dlp Streaming gestartet")
        else:
            self.yt_status.setText("Status: Streaming fehlgeschlagen")

    def _yt_stream_failed(self, message: str) -> None:
        self.yt_stream_btn.setEnabled(True)
        self.yt_status.setText("Status: Fehler")
        self.window.set_status(f"yt-dlp Streaming fehlgeschlagen: {message}")

    # ------------------------------------------------------------------
    # Webradio
    # ------------------------------------------------------------------

    def _on_radio_preset_select(self, row: int) -> None:
        if 0 <= row < len(_RADIO_ENTRIES):
            _, url = _RADIO_ENTRIES[row]
            self.radio_url.setText(url)

    def on_radio_search(self) -> None:
        term = self.radio_search.text().strip()
        if not term:
            return
        self.radio_search_btn.setEnabled(False)
        self.window.set_status("Webradio-Suche läuft...")

        def worker():
            from ui_qt.call_after import call_after
            try:
                params = {"name": term, "limit": 20, "hidebroken": 1, "order": "clickcount", "reverse": 1}
                data = self._fetch_json("https://de1.api.radio-browser.info/json/stations/search", params=params)
                if not isinstance(data, list):
                    data = []
                items, parsed = [], []
                for r in data:
                    name = r.get("name") or "Sender"
                    country = r.get("country") or ""
                    codec = r.get("codec") or ""
                    bitrate = r.get("bitrate") or ""
                    stream = r.get("url_resolved") or r.get("url") or ""
                    meta = " ".join(x for x in (country, codec, f"{bitrate}kbps" if bitrate else "") if x)
                    items.append(f"{name} — {meta}" if meta else name)
                    parsed.append({"name": name, "url": stream})
                call_after(self._radio_search_ready, items, parsed)
            except Exception as exc:
                from ui_qt.call_after import call_after as _ca
                _ca(self._radio_search_done)
                _ca(self.window.set_status, f"Webradio-Suche fehlgeschlagen: {exc}")

        threading.Thread(target=worker, daemon=True).start()

    def _radio_search_ready(self, items: list, parsed: list) -> None:
        self._radio_search_results = parsed
        self.radio_search_results.clear()
        for label in items:
            self.radio_search_results.addItem(label)
        if items:
            self.radio_search_results.setCurrentRow(0)
        self.radio_search_btn.setEnabled(True)
        self.window.set_status(f"Webradio Treffer: {len(items)}")

    def _radio_search_done(self) -> None:
        self.radio_search_btn.setEnabled(True)

    def _on_radio_search_select(self, row: int) -> None:
        if 0 <= row < len(self._radio_search_results):
            url = self._radio_search_results[row].get("url") or ""
            if url:
                self.radio_url.setText(url)

    def on_radio_stream(self) -> None:
        url = self.radio_url.text().strip()
        if not url:
            self.window.set_status("Bitte Stream-URL eingeben")
            return
        ok = self.window.client.start_streaming_media_to_channel(url, preamp_gain=self._gain_float(self.radio_gain))
        if ok:
            self._streaming = True
            self.window.set_status("Webradio-Streaming gestartet")
        else:
            self.window.set_status("Webradio-Streaming konnte nicht gestartet werden")

    # ------------------------------------------------------------------
    # Podcasts
    # ------------------------------------------------------------------

    def on_podcast_search(self) -> None:
        term = self.podcast_search.text().strip()
        if not term:
            return

        def worker():
            from ui_qt.call_after import call_after
            try:
                data = self._fetch_json("https://itunes.apple.com/search", params={
                    "term": term, "media": "podcast", "entity": "podcast", "limit": "20", "country": "us",
                })
                items, parsed = [], []
                for r in data.get("results", []):
                    name = r.get("collectionName") or r.get("trackName") or "Podcast"
                    author = r.get("artistName") or ""
                    feed = r.get("feedUrl") or ""
                    items.append(f"{name} — {author}")
                    parsed.append({"name": name, "feed": feed})
                call_after(self._podcast_search_ready, items, parsed)
            except Exception as exc:
                from ui_qt.call_after import call_after as _ca
                _ca(self.window.set_status, f"Podcast-Suche fehlgeschlagen: {exc}")

        threading.Thread(target=worker, daemon=True).start()

    def _podcast_search_ready(self, items: list, parsed: list) -> None:
        self._podcast_results = parsed
        self.podcast_list.clear()
        for label in items:
            self.podcast_list.addItem(label)
        if items:
            self.podcast_list.setCurrentRow(0)
        self.window.set_status(f"Podcasts gefunden: {len(items)}")

    def _on_podcast_select(self, row: int) -> None:
        if 0 <= row < len(self._podcast_results):
            feed = self._podcast_results[row].get("feed") or ""
            if feed:
                self.podcast_feed.setText(feed)
                self._load_feed(feed)

    def on_podcast_feed_load(self) -> None:
        feed = self.podcast_feed.text().strip()
        if feed:
            self._load_feed(feed)

    def _load_feed(self, feed_url: str) -> None:
        def worker():
            from ui_qt.call_after import call_after
            try:
                status, xml_data, _ = self._fetch_url(feed_url)
                if status in (401, 403, 429):
                    status, xml_data, _ = self._fetch_url(self._proxy_url(feed_url))
                if status >= 400:
                    raise RuntimeError(f"HTTP {status}")
                episodes = self._parse_feed(xml_data)
                call_after(self._update_episode_list, episodes)
            except Exception as exc:
                from ui_qt.call_after import call_after as _ca
                _ca(self.window.set_status, f"Feed laden fehlgeschlagen: {exc}")

        threading.Thread(target=worker, daemon=True).start()

    def _parse_feed(self, xml_data: bytes) -> list:
        episodes = []
        root = ET.fromstring(xml_data)
        for elem in root.iter():
            if "}" in elem.tag:
                elem.tag = elem.tag.split("}", 1)[1]
        for item in root.findall(".//item"):
            title = (item.findtext("title") or "Episode").strip()
            pub = (item.findtext("pubDate") or "").strip()
            duration = ""
            for child in item:
                if child.tag.endswith("duration") and child.text:
                    duration = child.text.strip()
                    break
            enc_url = ""
            for child in item:
                if child.tag.lower().endswith("enclosure") and "url" in child.attrib:
                    enc_url = child.attrib["url"]
                    break
            if not enc_url:
                enc_url = (item.findtext("link") or "").strip()
            label = title
            if pub:
                label += f" — {pub}"
            if duration:
                label += f" — {duration}"
            episodes.append({"label": label, "url": enc_url})
        if not episodes:
            for entry in root.findall(".//entry"):
                title = (entry.findtext("title") or "Episode").strip()
                pub = (entry.findtext("updated") or entry.findtext("published") or "").strip()
                enc_url = ""
                for link in entry.findall("link"):
                    rel = (link.attrib.get("rel") or "").lower()
                    ltype = (link.attrib.get("type") or "").lower()
                    href = link.attrib.get("href") or ""
                    if rel == "enclosure" or ltype.startswith("audio"):
                        enc_url = href
                        break
                    if not enc_url and href:
                        enc_url = href
                label = f"{title} — {pub}" if pub else title
                episodes.append({"label": label, "url": enc_url})
        return episodes

    def _update_episode_list(self, episodes: list) -> None:
        self._podcast_episodes = episodes
        self.episode_list.clear()
        for ep in episodes:
            self.episode_list.addItem(ep["label"])
        if episodes:
            self.episode_list.setCurrentRow(0)
        self.window.set_status(f"Episoden geladen: {len(episodes)}")

    def on_episode_stream(self) -> None:
        row = self.episode_list.currentRow()
        if row < 0 or row >= len(self._podcast_episodes):
            self.window.set_status("Bitte Episode auswählen")
            return
        url = self._podcast_episodes[row].get("url", "")
        if not url:
            self.window.set_status("Keine Audio-URL in der Episode")
            return
        ok = self.window.client.start_streaming_media_to_channel(url, preamp_gain=self._gain_float(self.podcast_gain))
        if ok:
            self._streaming = True
            self.window.set_status("Podcast-Streaming gestartet")
        else:
            self.window.set_status("Podcast-Streaming konnte nicht gestartet werden")

    # ------------------------------------------------------------------
    # Playlist
    # ------------------------------------------------------------------

    def _pl_display_name(self, path: str) -> str:
        return os.path.splitext(os.path.basename(path))[0]

    def _pl_refresh_list(self) -> None:
        self.pl_list.clear()
        for p in self._playlist_tracks:
            self.pl_list.addItem(self._pl_display_name(p))

    def _on_pl_add(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Dateien zur Playlist hinzufügen", "",
            "Audio/Video (*.mp3 *.wav *.ogg *.flac *.m4a *.opus *.mp4);;Alle (*.*)",
        )
        if paths:
            self._playlist_tracks.extend(paths)
            self._pl_refresh_list()
            self.window.set_status(f"{len(paths)} Datei(en) hinzugefügt")

    def _on_pl_load_m3u(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "M3U-Datei laden", "", "M3U-Playlist (*.m3u *.m3u8);;Alle (*.*)"
        )
        if not path:
            return
        tracks = self._parse_m3u(path)
        if not tracks:
            QMessageBox.information(self, "M3U laden", "Keine abspielbaren Pfade gefunden.")
            return
        self._playlist_tracks = tracks
        self._pl_refresh_list()
        if self._playlist_tracks:
            self.pl_list.setCurrentRow(0)
        self.window.set_status(f"M3U geladen: {len(tracks)} Titel")

    def _on_pl_remove(self) -> None:
        row = self.pl_list.currentRow()
        if 0 <= row < len(self._playlist_tracks):
            del self._playlist_tracks[row]
            self._pl_refresh_list()
            new_sel = min(row, len(self._playlist_tracks) - 1)
            if new_sel >= 0:
                self.pl_list.setCurrentRow(new_sel)

    def _on_pl_move_up(self) -> None:
        row = self.pl_list.currentRow()
        if row > 0 and row < len(self._playlist_tracks):
            self._playlist_tracks[row - 1], self._playlist_tracks[row] = \
                self._playlist_tracks[row], self._playlist_tracks[row - 1]
            self._pl_refresh_list()
            self.pl_list.setCurrentRow(row - 1)

    def _on_pl_move_down(self) -> None:
        row = self.pl_list.currentRow()
        if 0 <= row < len(self._playlist_tracks) - 1:
            self._playlist_tracks[row], self._playlist_tracks[row + 1] = \
                self._playlist_tracks[row + 1], self._playlist_tracks[row]
            self._pl_refresh_list()
            self.pl_list.setCurrentRow(row + 1)

    def _on_pl_export(self) -> None:
        if not self._playlist_tracks:
            QMessageBox.information(self, "M3U exportieren", "Playlist ist leer.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Playlist als M3U exportieren", "playlist.m3u", "M3U-Playlist (*.m3u)"
        )
        if path:
            self._export_m3u(path, self._playlist_tracks)
            self.window.set_status(f"Playlist exportiert: {path}")

    def _on_pl_clear(self) -> None:
        if not self._playlist_tracks:
            return
        if QMessageBox.question(self, "Leeren", "Playlist wirklich leeren?") == QMessageBox.StandardButton.Yes:
            self._playlist_tracks = []
            self._pl_refresh_list()
            self.window.set_status("Playlist geleert")

    def _on_pl_play(self) -> None:
        if not self._playlist_tracks:
            self.window.set_status("Playlist ist leer")
            return
        row = self.pl_list.currentRow()
        if row < 0:
            row = 0
        self._pl_streaming = True
        self._pl_play_track(row)

    def _pl_play_track(self, idx: int) -> None:
        if idx < 0 or idx >= len(self._playlist_tracks):
            self._pl_streaming = False
            self.window.set_status("Playlist beendet")
            return
        self._playlist_current = idx
        self.pl_list.setCurrentRow(idx)
        path = self._playlist_tracks[idx]
        ok = self.window.client.start_streaming_media_to_channel(
            path, preamp_gain=self._gain_float(self.pl_gain)
        )
        if ok:
            self._streaming = True
            self.window.set_status(
                f"Playlist [{idx + 1}/{len(self._playlist_tracks)}]: {self._pl_display_name(path)}"
            )
        else:
            self._pl_advance()

    def _pl_advance(self) -> None:
        if self._pl_streaming:
            self._pl_play_track(self._playlist_current + 1)

    @staticmethod
    def _parse_m3u(filepath: str) -> List[str]:
        tracks = []
        base_dir = os.path.dirname(os.path.abspath(filepath))
        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if not os.path.isabs(line) and not line.startswith("http"):
                        line = os.path.join(base_dir, line)
                    tracks.append(line)
        except OSError:
            pass
        return tracks

    @staticmethod
    def _export_m3u(filepath: str, tracks: List[str]) -> None:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n")
            for track in tracks:
                f.write(track + "\n")

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    def _http_headers(self) -> dict:
        return {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/121.0.0.0 Safari/537.36"
            ),
            "Accept": "application/rss+xml, application/xml, text/xml, */*;q=0.9",
        }

    def _proxy_url(self, feed_url: str) -> str:
        stripped = feed_url.strip()
        for prefix in ("https://", "http://"):
            if stripped.startswith(prefix):
                stripped = stripped[len(prefix):]
                break
        return f"https://r.jina.ai/http://{stripped}"

    def _fetch_json(self, url: str, params: Optional[dict] = None) -> dict:
        if _requests is not None:
            resp = _requests.get(url, params=params, headers=self._http_headers(), timeout=(5, 15))
            if resp.status_code != 200:
                raise RuntimeError(f"HTTP {resp.status_code}")
            return resp.json()
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers=self._http_headers())
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"HTTP {exc.code}") from exc

    def _fetch_url(self, url: str):
        if _requests is not None:
            resp = _requests.get(url, headers=self._http_headers(), timeout=(5, 15))
            return resp.status_code, resp.content, resp.url
        req = urllib.request.Request(url, headers=self._http_headers())
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return resp.status, resp.read(), url
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read(), url

    # ------------------------------------------------------------------
    # Mode switching (called from main window menu)
    # ------------------------------------------------------------------

    def switch_to_mode(self, mode: str) -> None:
        _yt_source_map = {
            "url": 0, "youtube": 0,
            "soundcloud": 1,
            "twitch": 2,
            "bandcamp": 3,
            "vimeo": 4,
            "mixcloud": 5,
        }
        _tab_map = {
            "file": 1,
            "radio": 3,
            "podcast": 4,
            "playlist": 5,
        }
        if mode in _yt_source_map:
            self._inner_tabs.setCurrentIndex(2)
            self.yt_source.setCurrentIndex(_yt_source_map[mode])
        elif mode in _tab_map:
            self._inner_tabs.setCurrentIndex(_tab_map[mode])

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def stop_all(self) -> None:
        if self._recording:
            try:
                self.window.client.stop_recording_muxed()
            except Exception:
                pass
            self._recording = False
        if self._streaming:
            try:
                self.window.client.stop_streaming_media()
            except Exception:
                pass
            self._streaming = False
