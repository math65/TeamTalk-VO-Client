from __future__ import annotations

from typing import TYPE_CHECKING, Optional

import os
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
import sys
import urllib.parse
import urllib.request
import urllib.error
import json
import xml.etree.ElementTree as ET

import wx
try:
    import requests
except Exception:
    requests = None

if TYPE_CHECKING:
    from app import MainFrame


class MediaTab(wx.Panel):
    """Tab 5: Aufnahme & Medien -- recording and media file streaming."""

    RADIO_ENTRIES = [
        ("localradio Aachen und region", "https://stream.dashitradio.de/dashitradio/mp3-128/stream.mp3"),
        ("hitradion1", "https://frontend.streamonkey.net/fhn-hitradion1"),
        ("Ostseewelle - Nord", "https://ostseewelle-nord.cast.addradio.de/ostseewelle/nord/mp3/high"),
        ("Ostseewelle - Ost", "https://ostseewelle-ost.cast.addradio.de/ostseewelle/ost/mp3/high"),
        ("Ostseewelle - West", "https://ostseewelle-west.cast.addradio.de/ostseewelle/west/mp3/high"),
        ("Ostseewelle - Mecklenburg", "https://www.ostseewelle.de/audiothek/Livestream-amp-Regionalstreams--ostseewelle_347911/detail/Region-Mecklenburg-364506"),
        ("Ostseewelle - Mueritz/Usedom", "https://www.ostseewelle.de/audiothek/Livestream-amp-Regionalstreams--ostsewelle_347911/detail/Region-MuritzUsedom-364503"),
        ("Ostseewelle - Ostseekueste", "https://www.ostseewelle.de/audiothek/Livestream-amp-Regionalstreams--ostseewelle_347911/detail/Region-Ostseekuste-364499"),
        ("90s90s - 2000er", "https://streams.90s90s.de/90s00s/mp3-128/streams.90s90s.de/"),
        ("90s90s - In the Mix", "https://streams.90s90s.de/inthemix/mp3-192/streams.90s90s.de/"),
        ("90s90s - Trance", "https://streams.90s90s.de/trance/mp3-128/streams.90s90s.de/"),
        ("90s90s - Techno Essentials", "https://streams.90s90s.de/technoessentials/mp3-128/streams.90s90s.de/play.m3u"),
        ("90s90s - Techno", "https://streams.90s90s.de/techno/mp3-128/streams.90s90s.de/"),
        ("90s90s - Sachsenradio", "https://streams.90s90s.de/sachsenradio/mp3-192/streams.90s90s.de/"),
        ("90s90s - Rock", "https://streams.90s90s.de/rock/mp3-192/streams.90s90s.de/"),
        ("90s90s - Reggae", "https://streams.90s90s.de/reggae/mp3-192/streams.90s90s.de/"),
        ("90s90s - Pop", "https://streams.90s90s.de/pop/mp3-128/streams.90s90s.de/"),
        ("90s90s - NRW", "https://streams.90s90s.de/nrw/mp3-128/streams.90s90s.de/"),
        ("90s90s - Mayday", "https://streams.90s90s.de/mayday/mp3-128/streams.90s90s.de/"),
        ("90s90s - Main", "https://streams.90s90s.de/main/mp3-128/streams.90s90s.de/"),
        ("90s90s - Loveparade", "https://streams.90s90s.de/loveparade/mp3-128/streams.90s90s.de/"),
        ("90s90s - House", "https://streams.90s90s.de/house/mp3-192/streams.90s90s.de/"),
        ("90s90s - HipHop German", "https://streams.90s90s.de/hiphop-german/mp3-128/streams.90s90s.de/"),
        ("90s90s - HipHop", "https://streams.90s90s.de/hiphop/mp3-128/streams.90s90s.de/"),
        ("90s90s - Eurodance", "https://streams.90s90s.de/eurodance/mp3-128/streams.90s90s.de/"),
        ("90s90s - Danceradio", "https://streams.90s90s.de/danceradio/mp3-192/streams.90s90s.de/"),
        ("90s90s - Rave", "https://streams.90s90s.de/RAVE/mp3-192/streams.90s90s.de/"),
        ("90s90s - Sommerhits", "https://streams.90s90s.de/90s90s-sommerhits/mp3-128/streams.90s90s.de/"),
        ("90s90s - Xmas", "https://streams.90s90s.de/xmas/mp3-192/streams.90s90s.de/"),
        ("90s90s - Trance HQ", "https://streams.90s90s.de/trance/mp3-192/streams.90s90s.de/"),
        ("90s90s - RnB", "https://streams.90s90s.de/rnb/mp3-192/streams.90s90s.de/"),
        ("80s80s - Christmas", "https://streams.80s80s.de/christmas/mp3-128/streams.80s80s.de/"),
        ("80s80s - Dance", "https://streams.80s80s.de/dance/mp3-192/streams.80s80s.de/"),
        ("80s80s - Deutsch", "https://streams.80s80s.de/deutsch/mp3-192/streams.80s80s.de/"),
        ("80s80s - Maxis", "https://streams.80s80s.de/maxis/mp3-192/streams.80s80s.de/"),
        ("80s80s - NDW", "https://streams.80s80s.de/ndw/mp3-128/streams.80s80s.de/"),
        ("80s80s - Party", "https://streams.80s80s.de/party/mp3-192/streams.80s80s.de/"),
        ("80s80s - Reggae", "https://streams.80s80s.de/reggae/mp3-192/streams.80s80s.de/"),
        ("80s80s - Rock", "https://streams.80s80s.de/rock/mp3-192/streams.80s80s.de/"),
        ("80s80s - Romantic Rock", "https://streams.80s80s.de/romanticrock/mp3-192/streams.80s80s.de/"),
        ("80s80s - Summerhits", "https://streams.80s80s.de/summerhits/mp3-192/streams.80s80s.de/"),
        ("80s80s - Techno", "https://streams.80s80s.de/techno/mp3-192/streams.80s80s.de/"),
        ("TechnoBase.FM", "http://listen.technobase.fm/tunein-mp3"),
        ("HouseTime.FM", "http://listen.housetime.fm/listen.mp3.m3u"),
        ("HardBase.FM", "http://listen.hardbase.fm/listen.mp3.m3u"),
        ("TranceBase.FM", "http://listen.trancebase.fm/listen.mp3.m3u"),
        ("CoreTime.FM", "http://listen.coretime.fm/listen.mp3.m3u"),
        ("ClubTime.FM", "http://listen.clubtime.fm/listen.mp3.m3u"),
        ("TeaTime.FM", "http://listen.teatime.fm/listen.mp3.m3u"),
        ("Replay.FM", "http://listen.replay.fm/listen.mp3.m3u"),
        ("Hoerspiele rund um die Uhr", "https://stream.laut.fm/hoerspiel"),
        ("Musiksender von Radiorobbe", "http://stream.powerradio4u.de:8010/radio.mp3"),
        ("Aussenstream von Radiorobbe", "http://stream.powerradio4u.de:8000/opr_outside"),
        ("Mechanische Musikinstrumente", "https://global.citrus3.com:2020/stream/mechanicalmusicradio"),
    ]

    def __init__(self, parent: wx.Window, frame: MainFrame) -> None:
        super().__init__(parent)
        self.frame = frame
        self.SetName("Aufnahme & Medien")
        self._recording = False
        self._streaming = False
        self._stream_duration_ms = 0
        self._yt_tempdir: Optional[Path] = None
        self._yt_output_path: Optional[Path] = None
        self._radio_entries = []
        self._podcast_results = []
        self._podcast_episodes = []

        sizer = wx.BoxSizer(wx.VERTICAL)

        # --- Recording ---
        rec_box = wx.StaticBox(self, label="Aufnahme")
        rec_sizer = wx.StaticBoxSizer(rec_box, wx.VERTICAL)

        fmt_row = wx.BoxSizer(wx.HORIZONTAL)
        fmt_row.Add(wx.StaticText(self, label="Format"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.rec_format = wx.Choice(self, choices=[
            "WAV", "MP3 16k", "MP3 32k", "MP3 64k",
            "MP3 128k", "MP3 256k", "MP3 320k",
        ])
        self.rec_format.SetName("Aufnahmeformat")
        self.rec_format.SetSelection(0)
        fmt_row.Add(self.rec_format, 1, wx.EXPAND)
        rec_sizer.Add(fmt_row, 0, wx.ALL | wx.EXPAND, 4)

        rec_btn_row = wx.BoxSizer(wx.HORIZONTAL)
        self.rec_start_btn = wx.Button(self, label="Aufnahme starten")
        self.rec_start_btn.SetName("Aufnahme starten")
        self.rec_start_btn.Bind(wx.EVT_BUTTON, self.on_rec_start)
        self.rec_stop_btn = wx.Button(self, label="Aufnahme stoppen")
        self.rec_stop_btn.SetName("Aufnahme stoppen")
        self.rec_stop_btn.Bind(wx.EVT_BUTTON, self.on_rec_stop)
        self.rec_stop_btn.Disable()
        rec_btn_row.Add(self.rec_start_btn, 0, wx.RIGHT, 8)
        rec_btn_row.Add(self.rec_stop_btn, 0)
        rec_sizer.Add(rec_btn_row, 0, wx.ALL, 4)

        sizer.Add(rec_sizer, 0, wx.ALL | wx.EXPAND, 8)

        # --- Streaming source selector ---
        mode_row = wx.BoxSizer(wx.HORIZONTAL)
        mode_row.Add(wx.StaticText(self, label="Streaming-Quelle"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.stream_mode = wx.Choice(self, choices=["Datei", "YouTube", "Webradio", "Podcasts"])
        self.stream_mode.SetName("Streaming-Quelle")
        self.stream_mode.SetSelection(0)
        self.stream_mode.Bind(wx.EVT_CHOICE, self.on_stream_mode)
        mode_row.Add(self.stream_mode, 1, wx.EXPAND)
        sizer.Add(mode_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)

        # --- Media streaming (File) ---
        self.stream_panel = wx.Panel(self)
        stream_box = wx.StaticBox(self.stream_panel, label="Medien-Streaming")
        stream_sizer = wx.StaticBoxSizer(stream_box, wx.VERTICAL)

        file_row = wx.BoxSizer(wx.HORIZONTAL)
        lbl_media_path = wx.StaticText(self.stream_panel, label="Mediendatei Pfad")
        self.media_path = wx.TextCtrl(self.stream_panel)
        self.media_path.SetName("Mediendatei Pfad")
        self.browse_btn = wx.Button(self.stream_panel, label="Durchsuchen...")
        self.browse_btn.SetName("Mediendatei auswaehlen")
        self.browse_btn.Bind(wx.EVT_BUTTON, self.on_browse)
        file_row.Add(self.media_path, 1, wx.RIGHT | wx.EXPAND, 8)
        file_row.Add(self.browse_btn, 0)
        stream_sizer.Add(file_row, 0, wx.ALL | wx.EXPAND, 4)

        self.media_info = wx.StaticText(self.stream_panel, label="Dauer: --")
        self.media_info.SetName("Medieninfo")
        stream_sizer.Add(self.media_info, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)

        ctrl_row = wx.BoxSizer(wx.HORIZONTAL)
        self.play_btn = wx.Button(self.stream_panel, label="Abspielen")
        self.play_btn.SetName("Abspielen")
        self.play_btn.Bind(wx.EVT_BUTTON, self.on_play)
        self.pause_btn = wx.Button(self.stream_panel, label="Pause")
        self.pause_btn.SetName("Pause")
        self.pause_btn.Bind(wx.EVT_BUTTON, self.on_pause)
        self.stop_btn = wx.Button(self.stream_panel, label="Stopp")
        self.stop_btn.SetName("Stopp")
        self.stop_btn.Bind(wx.EVT_BUTTON, self.on_stop)
        for btn in (self.play_btn, self.pause_btn, self.stop_btn):
            ctrl_row.Add(btn, 0, wx.RIGHT, 8)
        stream_sizer.Add(ctrl_row, 0, wx.ALL, 4)

        lbl_seek = wx.StaticText(self.stream_panel, label="Position")
        self.seek_slider = wx.Slider(self.stream_panel, value=0, minValue=0, maxValue=1000)
        self.seek_slider.SetName("Position")
        self.seek_slider.Bind(wx.EVT_SLIDER, self.on_seek)
        stream_sizer.Add(self.seek_slider, 0, wx.ALL | wx.EXPAND, 4)

        gain_row = wx.BoxSizer(wx.HORIZONTAL)
        gain_row.Add(wx.StaticText(self.stream_panel, label="Streaming Lautstaerke"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.stream_gain = wx.Slider(self.stream_panel, value=100, minValue=25, maxValue=400)
        self.stream_gain.SetName("Streaming Lautstaerke")
        self.stream_gain.Bind(wx.EVT_SLIDER, self.on_stream_gain)
        gain_row.Add(self.stream_gain, 1, wx.EXPAND)
        stream_sizer.Add(gain_row, 0, wx.ALL | wx.EXPAND, 4)

        self.stream_panel.SetSizer(stream_sizer)
        sizer.Add(self.stream_panel, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)

        # --- YouTube (yt-dlp) ---
        self.yt_panel = wx.Panel(self)
        yt_box = wx.StaticBox(self.yt_panel, label="YouTube-Streaming (yt-dlp)")
        yt_sizer = wx.StaticBoxSizer(yt_box, wx.VERTICAL)

        yt_row = wx.BoxSizer(wx.HORIZONTAL)
        lbl_yt_url = wx.StaticText(self.yt_panel, label="YouTube-Link")
        self.yt_url = wx.TextCtrl(self.yt_panel)
        self.yt_url.SetName("YouTube-Link")
        self.yt_btn = wx.Button(self.yt_panel, label="Download & streamen")
        self.yt_btn.SetName("YouTube streamen")
        self.yt_btn.Bind(wx.EVT_BUTTON, self.on_ytdlp_stream)
        yt_row.Add(self.yt_url, 1, wx.RIGHT | wx.EXPAND, 8)
        yt_row.Add(self.yt_btn, 0)
        yt_sizer.Add(yt_row, 0, wx.ALL | wx.EXPAND, 4)

        self.yt_status = wx.StaticText(self.yt_panel, label="Status: bereit")
        self.yt_status.SetName("YouTube-Status")
        yt_sizer.Add(self.yt_status, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)

        yt_ctrl_row = wx.BoxSizer(wx.HORIZONTAL)
        self.yt_pause_btn = wx.Button(self.yt_panel, label="Pause")
        self.yt_pause_btn.SetName("YouTube Pause")
        self.yt_pause_btn.Bind(wx.EVT_BUTTON, self.on_pause)
        self.yt_stop_btn = wx.Button(self.yt_panel, label="Stopp")
        self.yt_stop_btn.SetName("YouTube Stopp")
        self.yt_stop_btn.Bind(wx.EVT_BUTTON, self.on_stop)
        yt_ctrl_row.Add(self.yt_pause_btn, 0, wx.RIGHT, 8)
        yt_ctrl_row.Add(self.yt_stop_btn, 0)
        yt_sizer.Add(yt_ctrl_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)

        yt_gain_row = wx.BoxSizer(wx.HORIZONTAL)
        yt_gain_row.Add(wx.StaticText(self.yt_panel, label="Streaming Lautstaerke"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.yt_stream_gain = wx.Slider(self.yt_panel, value=100, minValue=25, maxValue=400)
        self.yt_stream_gain.SetName("YouTube Lautstaerke")
        self.yt_stream_gain.Bind(wx.EVT_SLIDER, self.on_stream_gain)
        yt_gain_row.Add(self.yt_stream_gain, 1, wx.EXPAND)
        yt_sizer.Add(yt_gain_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 4)

        self.yt_panel.SetSizer(yt_sizer)
        sizer.Add(self.yt_panel, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)

        # --- Webradio ---
        self.radio_panel = wx.Panel(self)
        radio_box = wx.StaticBox(self.radio_panel, label="Webradio")
        radio_sizer = wx.StaticBoxSizer(radio_box, wx.VERTICAL)

        lbl_radio_choice = wx.StaticText(self.radio_panel, label="Webradio Senderliste")
        self.radio_choice = wx.Choice(self.radio_panel)
        self.radio_choice.SetName("Webradio Senderliste")
        self.radio_choice.Bind(wx.EVT_CHOICE, self.on_radio_selected)
        radio_sizer.Add(self.radio_choice, 0, wx.ALL | wx.EXPAND, 4)

        radio_url_row = wx.BoxSizer(wx.HORIZONTAL)
        lbl_radio_url = wx.StaticText(self.radio_panel, label="Webradio Stream-URL")
        self.radio_url = wx.TextCtrl(self.radio_panel)
        self.radio_url.SetName("Webradio Stream-URL")
        self.radio_play_btn = wx.Button(self.radio_panel, label="Webradio streamen")
        self.radio_play_btn.SetName("Webradio streamen")
        self.radio_play_btn.Bind(wx.EVT_BUTTON, self.on_radio_stream)
        radio_url_row.Add(self.radio_url, 1, wx.RIGHT | wx.EXPAND, 8)
        radio_url_row.Add(self.radio_play_btn, 0)
        radio_sizer.Add(radio_url_row, 0, wx.ALL | wx.EXPAND, 4)

        radio_ctrl_row = wx.BoxSizer(wx.HORIZONTAL)
        self.radio_pause_btn = wx.Button(self.radio_panel, label="Pause")
        self.radio_pause_btn.SetName("Webradio Pause")
        self.radio_pause_btn.Bind(wx.EVT_BUTTON, self.on_pause)
        self.radio_stop_btn = wx.Button(self.radio_panel, label="Stopp")
        self.radio_stop_btn.SetName("Webradio Stopp")
        self.radio_stop_btn.Bind(wx.EVT_BUTTON, self.on_stop)
        radio_ctrl_row.Add(self.radio_pause_btn, 0, wx.RIGHT, 8)
        radio_ctrl_row.Add(self.radio_stop_btn, 0)
        radio_sizer.Add(radio_ctrl_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)

        radio_gain_row = wx.BoxSizer(wx.HORIZONTAL)
        radio_gain_row.Add(wx.StaticText(self.radio_panel, label="Streaming Lautstaerke"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.radio_stream_gain = wx.Slider(self.radio_panel, value=100, minValue=25, maxValue=400)
        self.radio_stream_gain.SetName("Webradio Lautstaerke")
        self.radio_stream_gain.Bind(wx.EVT_SLIDER, self.on_stream_gain)
        radio_gain_row.Add(self.radio_stream_gain, 1, wx.EXPAND)
        radio_sizer.Add(radio_gain_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 4)

        self.radio_panel.SetSizer(radio_sizer)
        sizer.Add(self.radio_panel, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)

        # --- Podcasts ---
        self.podcast_panel = wx.Panel(self)
        podcast_box = wx.StaticBox(self.podcast_panel, label="Podcasts")
        podcast_sizer = wx.StaticBoxSizer(podcast_box, wx.VERTICAL)

        search_row = wx.BoxSizer(wx.HORIZONTAL)
        lbl_podcast_search = wx.StaticText(self.podcast_panel, label="Podcast Suche")
        self.podcast_search = wx.TextCtrl(self.podcast_panel)
        self.podcast_search.SetName("Podcast Suche")
        self.podcast_search_btn = wx.Button(self.podcast_panel, label="Suchen")
        self.podcast_search_btn.SetName("Podcast suchen")
        self.podcast_search_btn.Bind(wx.EVT_BUTTON, self.on_podcast_search)
        search_row.Add(self.podcast_search, 1, wx.RIGHT | wx.EXPAND, 8)
        search_row.Add(self.podcast_search_btn, 0)
        podcast_sizer.Add(search_row, 0, wx.ALL | wx.EXPAND, 4)

        feed_row = wx.BoxSizer(wx.HORIZONTAL)
        lbl_podcast_feed = wx.StaticText(self.podcast_panel, label="Podcast Feed URL")
        self.podcast_feed = wx.TextCtrl(self.podcast_panel)
        self.podcast_feed.SetName("Podcast Feed URL")
        self.podcast_feed_btn = wx.Button(self.podcast_panel, label="Feed laden")
        self.podcast_feed_btn.SetName("Podcast Feed laden")
        self.podcast_feed_btn.Bind(wx.EVT_BUTTON, self.on_podcast_feed_load)
        feed_row.Add(self.podcast_feed, 1, wx.RIGHT | wx.EXPAND, 8)
        feed_row.Add(self.podcast_feed_btn, 0)
        podcast_sizer.Add(feed_row, 0, wx.ALL | wx.EXPAND, 4)

        self.podcast_list = wx.ListBox(self.podcast_panel)
        self.podcast_list.SetName("Podcast Ergebnisse")
        self.podcast_list.Bind(wx.EVT_LISTBOX, self.on_podcast_select)
        podcast_sizer.Add(self.podcast_list, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 4)
        self.podcast_list.SetMinSize((-1, 120))

        self.episode_list = wx.ListBox(self.podcast_panel)
        self.episode_list.SetName("Podcast Episoden")
        podcast_sizer.Add(self.episode_list, 1, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 4)
        self.episode_list.SetMinSize((-1, 160))

        pod_ctrl_row = wx.BoxSizer(wx.HORIZONTAL)
        self.episode_stream_btn = wx.Button(self.podcast_panel, label="Episode streamen")
        self.episode_stream_btn.SetName("Episode streamen")
        self.episode_stream_btn.Bind(wx.EVT_BUTTON, self.on_episode_stream)
        self.podcast_pause_btn = wx.Button(self.podcast_panel, label="Pause")
        self.podcast_pause_btn.SetName("Podcast Pause")
        self.podcast_pause_btn.Bind(wx.EVT_BUTTON, self.on_pause)
        self.podcast_stop_btn = wx.Button(self.podcast_panel, label="Stopp")
        self.podcast_stop_btn.SetName("Podcast Stopp")
        self.podcast_stop_btn.Bind(wx.EVT_BUTTON, self.on_stop)
        pod_ctrl_row.Add(self.episode_stream_btn, 0, wx.RIGHT, 8)
        pod_ctrl_row.Add(self.podcast_pause_btn, 0, wx.RIGHT, 8)
        pod_ctrl_row.Add(self.podcast_stop_btn, 0)
        podcast_sizer.Add(pod_ctrl_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)

        pod_gain_row = wx.BoxSizer(wx.HORIZONTAL)
        pod_gain_row.Add(wx.StaticText(self.podcast_panel, label="Streaming Lautstaerke"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.podcast_stream_gain = wx.Slider(self.podcast_panel, value=100, minValue=25, maxValue=400)
        self.podcast_stream_gain.SetName("Podcast Lautstaerke")
        self.podcast_stream_gain.Bind(wx.EVT_SLIDER, self.on_stream_gain)
        pod_gain_row.Add(self.podcast_stream_gain, 1, wx.EXPAND)
        podcast_sizer.Add(pod_gain_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 4)

        self.podcast_panel.SetSizer(podcast_sizer)
        sizer.Add(self.podcast_panel, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)

        self.SetSizer(sizer)
        self._load_radio_list()
        self._update_stream_mode()
        self._set_tab_order()

    def stop_all(self):
        if self._recording:
            self.frame.client.stop_recording_muxed()
            self._recording = False
        if self._streaming:
            self.frame.client.stop_streaming_media()
            self._streaming = False

    # --- Recording ---

    def _get_audio_format(self) -> int:
        tt = self.frame.client.tt
        mapping = {
            0: tt.AudioFileFormat.AFF_WAVE_FORMAT,
            1: tt.AudioFileFormat.AFF_MP3_16KBIT_FORMAT,
            2: tt.AudioFileFormat.AFF_MP3_32KBIT_FORMAT,
            3: tt.AudioFileFormat.AFF_MP3_64KBIT_FORMAT,
            4: tt.AudioFileFormat.AFF_MP3_128KBIT_FORMAT,
            5: tt.AudioFileFormat.AFF_MP3_256KBIT_FORMAT,
            6: tt.AudioFileFormat.AFF_MP3_320KBIT_FORMAT,
        }
        return int(mapping.get(self.rec_format.GetSelection(), tt.AudioFileFormat.AFF_WAVE_FORMAT))

    def on_rec_start(self, _event):
        ext = "wav" if self.rec_format.GetSelection() == 0 else "mp3"
        with wx.FileDialog(
            self, "Aufnahme speichern unter", wildcard=f"{ext.upper()} (*.{ext})|*.{ext}",
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
        ) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            path = dlg.GetPath()

        fmt = self._get_audio_format()
        ok = self.frame.client.start_recording_muxed(path, fmt)
        if ok:
            self._recording = True
            self.rec_start_btn.Disable()
            self.rec_stop_btn.Enable()
            self.frame.set_status(f"Aufnahme gestartet: {path}")
        else:
            self.frame.set_status("Aufnahme konnte nicht gestartet werden")

    def on_rec_stop(self, _event):
        self.frame.client.stop_recording_muxed()
        self._recording = False
        self.rec_start_btn.Enable()
        self.rec_stop_btn.Disable()
        self.frame.set_status("Aufnahme gestoppt")

    # --- Streaming ---

    def on_browse(self, _event):
        with wx.FileDialog(
            self, "Mediendatei auswaehlen",
            wildcard="Audio/Video|*.wav;*.mp3;*.ogg;*.opus;*.mp4;*.avi;*.mkv|Alle|*.*",
        ) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            path = dlg.GetPath()
        self.media_path.SetValue(path)
        info = self.frame.client.get_media_file_info(path)
        if info:
            secs = int(info.uDurationMSec) // 1000
            minutes = secs // 60
            self.media_info.SetLabel(f"Dauer: {minutes}:{secs % 60:02d}")
            self._stream_duration_ms = int(info.uDurationMSec)
            self.seek_slider.SetMax(max(1, secs))
        else:
            self.media_info.SetLabel("Dauer: unbekannt")

    def on_play(self, _event):
        path = self.media_path.GetValue().strip()
        if not path:
            self.frame.set_status("Bitte zuerst eine Datei auswaehlen")
            return
        if self._streaming:
            self.frame.client.update_streaming_media(paused=False, offset_ms=None, preamp_gain=self._get_stream_gain())
            self.frame.set_status("Wiedergabe fortgesetzt")
        else:
            ok = self.frame.client.start_streaming_media_to_channel(path, preamp_gain=self._get_stream_gain())
            if ok:
                self._streaming = True
                self.frame.set_status("Streaming gestartet")
            else:
                self.frame.set_status("Streaming konnte nicht gestartet werden")

    def on_pause(self, _event):
        if self._streaming:
            self.frame.client.update_streaming_media(paused=True, offset_ms=None, preamp_gain=self._get_stream_gain())
            self.frame.set_status("Streaming pausiert")

    def on_stop(self, _event):
        if self._streaming:
            self.frame.client.stop_streaming_media()
            self._streaming = False
            self.seek_slider.SetValue(0)
            self.frame.set_status("Streaming gestoppt")
        self._cleanup_ytdlp_tempdir()

    def on_seek(self, _event):
        if self._streaming:
            pos_sec = self.seek_slider.GetValue()
            self.frame.client.update_streaming_media(paused=False, offset_ms=pos_sec * 1000, preamp_gain=self._get_stream_gain())

    def on_stream_update(self, media_file_info):
        elapsed = int(media_file_info.uElapsedMSec)
        duration = int(media_file_info.uDurationMSec)
        if duration > 0:
            secs = elapsed // 1000
            self.seek_slider.SetValue(min(secs, self.seek_slider.GetMax()))
            if elapsed >= duration and self._streaming:
                self._streaming = False
                self.frame.set_status("Streaming beendet")
                self._cleanup_ytdlp_tempdir()

    def on_stream_gain(self, _event):
        if self._streaming:
            self.frame.client.update_streaming_media(paused=False, offset_ms=None, preamp_gain=self._get_stream_gain())

    def _get_stream_gain(self) -> float:
        if self.yt_panel.IsShown():
            val = self.yt_stream_gain.GetValue()
        elif self.radio_panel.IsShown():
            val = self.radio_stream_gain.GetValue()
        elif self.podcast_panel.IsShown():
            val = self.podcast_stream_gain.GetValue()
        else:
            val = self.stream_gain.GetValue()
        return max(0.1, float(val) / 100.0)

    def _set_tab_order(self):
        # Top-level controls (direct children of self)
        top_order = [
            self.rec_format, self.rec_start_btn, self.rec_stop_btn,
            self.stream_mode,
        ]
        for i in range(1, len(top_order)):
            top_order[i].MoveAfterInTabOrder(top_order[i - 1])
        # Each sub-panel has its own tab order (children are siblings within their panel)
        file_order = [
            self.media_path, self.browse_btn, self.play_btn,
            self.pause_btn, self.stop_btn, self.seek_slider, self.stream_gain,
        ]
        for i in range(1, len(file_order)):
            file_order[i].MoveAfterInTabOrder(file_order[i - 1])
        yt_order = [self.yt_url, self.yt_btn, self.yt_pause_btn, self.yt_stop_btn, self.yt_stream_gain]
        for i in range(1, len(yt_order)):
            yt_order[i].MoveAfterInTabOrder(yt_order[i - 1])
        radio_order = [
            self.radio_choice, self.radio_url, self.radio_play_btn,
            self.radio_pause_btn, self.radio_stop_btn, self.radio_stream_gain,
        ]
        for i in range(1, len(radio_order)):
            radio_order[i].MoveAfterInTabOrder(radio_order[i - 1])
        pod_order = [
            self.podcast_search, self.podcast_search_btn, self.podcast_feed, self.podcast_feed_btn,
            self.podcast_list, self.episode_list, self.episode_stream_btn,
            self.podcast_pause_btn, self.podcast_stop_btn, self.podcast_stream_gain,
        ]
        for i in range(1, len(pod_order)):
            pod_order[i].MoveAfterInTabOrder(pod_order[i - 1])

    def on_stream_mode(self, _event):
        self._update_stream_mode()

    def _update_stream_mode(self):
        mode = self.stream_mode.GetSelection()
        show_file = mode == 0
        show_yt = mode == 1
        show_radio = mode == 2
        show_podcast = mode == 3
        self.stream_panel.Show(show_file)
        self.yt_panel.Show(show_yt)
        self.radio_panel.Show(show_radio)
        self.podcast_panel.Show(show_podcast)
        self.Layout()
        self.GetParent().Layout()
        # Move focus to the first control in the visible panel
        focus_targets = {
            0: self.media_path,
            1: self.yt_url,
            2: self.radio_choice,
            3: self.podcast_search,
        }
        target = focus_targets.get(mode)
        if target:
            target.SetFocus()

    # --- Podcasts ---

    def on_podcast_search(self, _event):
        term = self.podcast_search.GetValue().strip()
        if not term:
            self.frame.set_status("Bitte Suchbegriff eingeben")
            return

        def worker():
            try:
                params = {
                    "term": term,
                    "media": "podcast",
                    "entity": "podcast",
                    "limit": "20",
                    "country": "us",
                }
                payload = self._fetch_json("https://itunes.apple.com/search", params=params)
                results = payload.get("results", [])
                items = []
                parsed = []
                for r in results:
                    name = r.get("collectionName") or r.get("trackName") or "Podcast"
                    author = r.get("artistName") or ""
                    feed = r.get("feedUrl") or ""
                    items.append(f"{name} — {author}")
                    parsed.append({"name": name, "author": author, "feed": feed})
                wx.CallAfter(self._update_podcast_results, items, parsed)
            except Exception as exc:
                wx.CallAfter(self.frame.set_status, f"Podcast-Suche fehlgeschlagen: {exc}")

        threading.Thread(target=worker, daemon=True).start()

    def _update_podcast_results(self, items, parsed):
        self._podcast_results = parsed
        self.podcast_list.Set(items)
        if items:
            self.podcast_list.SetSelection(0)
            self.on_podcast_select(None)
        self.frame.set_status(f"Podcasts gefunden: {len(items)}")

    def on_podcast_select(self, _event):
        idx = self.podcast_list.GetSelection()
        if idx == wx.NOT_FOUND or idx >= len(self._podcast_results):
            return
        feed = self._podcast_results[idx].get("feed") or ""
        if feed:
            self.podcast_feed.SetValue(feed)
            self._load_feed(feed)
        else:
            self.frame.set_status("Kein Feed-URL für diesen Podcast")

    def on_podcast_feed_load(self, _event):
        feed = self.podcast_feed.GetValue().strip()
        if not feed:
            self.frame.set_status("Bitte Feed-URL eingeben")
            return
        self._load_feed(feed)

    def _http_headers(self) -> dict:
        return {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/121.0.0.0 Safari/537.36"
            ),
            "Accept": "application/rss+xml, application/xml, text/xml, */*;q=0.9",
            "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
            "Cache-Control": "no-cache",
        }

    def _proxy_url(self, feed_url: str) -> str:
        stripped = feed_url.strip()
        if stripped.startswith("http://"):
            stripped = stripped[len("http://"):]
        elif stripped.startswith("https://"):
            stripped = stripped[len("https://"):]
        return f"https://r.jina.ai/http://{stripped}"

    def _fetch_json(self, url: str, params: Optional[dict] = None) -> dict:
        if requests is not None:
            resp = requests.get(url, params=params, headers=self._http_headers(), timeout=(5, 15))
            if resp.status_code != 200:
                raise RuntimeError(f"HTTP {resp.status_code}")
            return resp.json()

        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers=self._http_headers())
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"HTTP {exc.code}") from exc
        return json.loads(data)

    def _fetch_url(self, url: str):
        if requests is not None:
            resp = requests.get(url, headers=self._http_headers(), timeout=(5, 15))
            return resp.status_code, resp.content, resp.url
        req = urllib.request.Request(url, headers=self._http_headers())
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return resp.status, resp.read(), url
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read(), url

    def _load_feed(self, feed_url: str):
        def worker():
            try:
                status, xml_data, final_url = self._fetch_url(feed_url)
                if status in (401, 403, 429):
                    proxy_url = self._proxy_url(feed_url)
                    status2, xml_data2, final_url2 = self._fetch_url(proxy_url)
                    if status2 >= 400:
                        raise RuntimeError(f"HTTP {status2}")
                    xml_data = xml_data2
                    wx.CallAfter(self.frame.set_status, "Feed ueber Proxy geladen")
                elif status >= 400:
                    raise RuntimeError(f"HTTP {status}")
                items = self._parse_feed(xml_data)
                wx.CallAfter(self._update_episode_list, items)
            except Exception as exc:
                wx.CallAfter(self.frame.set_status, f"Feed laden fehlgeschlagen: {exc}")

        threading.Thread(target=worker, daemon=True).start()

    def _parse_feed(self, xml_data: bytes):
        episodes = []
        root = ET.fromstring(xml_data)

        # Strip namespaces to make lookups robust across RSS/Atom variants.
        for elem in root.iter():
            if "}" in elem.tag:
                elem.tag = elem.tag.split("}", 1)[1]

        # RSS items
        for item in root.findall(".//item"):
            title = (item.findtext("title") or "Episode").strip()
            pub = (item.findtext("pubDate") or "").strip()
            duration = ""
            for child in item:
                if child.tag.endswith("duration") and child.text:
                    duration = child.text.strip()
                    break
            enclosure_url = ""
            for child in item:
                tag = child.tag.lower()
                if tag.endswith("enclosure") and "url" in child.attrib:
                    enclosure_url = child.attrib.get("url", "")
                    break
                if tag.endswith("content") and "url" in child.attrib:
                    enclosure_url = child.attrib.get("url", "")
            if not enclosure_url:
                link = item.findtext("link")
                enclosure_url = (link or "").strip()
            label = title
            if pub:
                label += f" — {pub}"
            if duration:
                label += f" — {duration}"
            episodes.append({"label": label, "url": enclosure_url})

        # Atom entries (fallback)
        if not episodes:
            for entry in root.findall(".//entry"):
                title = (entry.findtext("title") or "Episode").strip()
                pub = (entry.findtext("updated") or entry.findtext("published") or "").strip()
                enclosure_url = ""
                for link in entry.findall("link"):
                    rel = (link.attrib.get("rel") or "").lower()
                    href = link.attrib.get("href") or ""
                    ltype = (link.attrib.get("type") or "").lower()
                    if rel == "enclosure" or ltype.startswith("audio"):
                        enclosure_url = href
                        break
                    if not enclosure_url and href:
                        enclosure_url = href
                label = title
                if pub:
                    label += f" — {pub}"
                episodes.append({"label": label, "url": enclosure_url})

        return episodes

    def _update_episode_list(self, episodes):
        self._podcast_episodes = episodes
        labels = [e["label"] for e in episodes]
        self.episode_list.Set(labels)
        if labels:
            self.episode_list.SetSelection(0)
        self.frame.set_status(f"Episoden geladen: {len(labels)}")

    def on_episode_stream(self, _event):
        idx = self.episode_list.GetSelection()
        if idx == wx.NOT_FOUND or idx >= len(self._podcast_episodes):
            self.frame.set_status("Bitte Episode auswaehlen")
            return
        url = self._podcast_episodes[idx].get("url", "")
        if not url:
            self.frame.set_status("Keine Audio-URL in der Episode")
            return
        ok = self.frame.client.start_streaming_media_to_channel(url, preamp_gain=self._get_stream_gain())
        if ok:
            self._streaming = True
            self.media_path.SetValue(url)
            self.media_info.SetLabel("Dauer: Podcast")
            self.frame.set_status("Podcast-Streaming gestartet")
        else:
            self.frame.set_status("Podcast-Streaming konnte nicht gestartet werden")

    # --- YouTube streaming (yt-dlp) ---

    def _find_yt_dlp(self) -> Optional[str]:
        # 1) Bundled binary (PyInstaller)
        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            bundled = Path(sys._MEIPASS) / "yt-dlp" / "yt-dlp"
            if bundled.exists():
                return str(bundled)
        # 2) Repo binary
        root = Path(__file__).resolve().parents[2]
        local = root / "third_party" / "yt-dlp" / "yt-dlp"
        if local.exists():
            return str(local)
        # 3) PATH
        return shutil.which("yt-dlp")

    def on_ytdlp_stream(self, _event):
        url = self.yt_url.GetValue().strip()
        if not url:
            self.frame.set_status("Bitte einen YouTube-Link eingeben")
            return
        ytdlp = self._find_yt_dlp()
        if not ytdlp:
            self.frame.set_status("yt-dlp nicht gefunden (binary fehlt)")
            self.yt_status.SetLabel("Status: yt-dlp fehlt")
            return

        self.yt_btn.Disable()
        self.yt_status.SetLabel("Status: Download läuft...")
        self.frame.set_status("YouTube-Download gestartet")

        def worker():
            try:
                if self._yt_tempdir is None:
                    self._yt_tempdir = Path(tempfile.mkdtemp(prefix="tt_ytdlp_"))
                out_template = str(self._yt_tempdir / "ytstream.%(ext)s")
                env = os.environ.copy()
                cmd = [
                    ytdlp,
                    "-f", "bestaudio/best",
                    "--no-playlist",
                    "--no-progress",
                    "-o", out_template,
                    url,
                ]
                proc = subprocess.run(cmd, capture_output=True, text=True)
                if proc.returncode != 0:
                    err = (proc.stderr or proc.stdout or "Unbekannter Fehler").strip()
                    wx.CallAfter(self._ytdlp_failed, err)
                    return

                # find output file
                candidates = sorted(self._yt_tempdir.glob("ytstream.*"), key=lambda p: p.stat().st_mtime, reverse=True)
                if not candidates:
                    wx.CallAfter(self._ytdlp_failed, "Keine Ausgabedatei gefunden")
                    return
                self._yt_output_path = candidates[0]
                wx.CallAfter(self._ytdlp_ready, str(self._yt_output_path))
            except Exception as exc:
                wx.CallAfter(self._ytdlp_failed, str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _ytdlp_failed(self, message: str):
        self.yt_btn.Enable()
        self.yt_status.SetLabel("Status: Fehler")
        self.frame.set_status(f"YouTube-Download fehlgeschlagen: {message}")

    def _ytdlp_ready(self, path: str):
        self.yt_btn.Enable()
        self.yt_status.SetLabel("Status: Download fertig")
        self.media_path.SetValue(path)
        info = self.frame.client.get_media_file_info(path)
        if info:
            secs = int(info.uDurationMSec) // 1000
            minutes = secs // 60
            self.media_info.SetLabel(f"Dauer: {minutes}:{secs % 60:02d}")
            self._stream_duration_ms = int(info.uDurationMSec)
            self.seek_slider.SetMax(max(1, secs))
        ok = self.frame.client.start_streaming_media_to_channel(path, preamp_gain=self._get_stream_gain())
        if ok:
            self._streaming = True
            self.frame.set_status("YouTube-Streaming gestartet")
        else:
            self.frame.set_status("YouTube-Streaming konnte nicht gestartet werden")

    def _cleanup_ytdlp_tempdir(self):
        if not self._yt_tempdir:
            return
        try:
            shutil.rmtree(self._yt_tempdir, ignore_errors=True)
        finally:
            self._yt_tempdir = None
            self._yt_output_path = None

    # --- Webradio ---

    def _load_radio_list(self):
        self._radio_entries = list(self.RADIO_ENTRIES)
        if self._radio_entries:
            labels = [name for name, _ in self._radio_entries]
            self.radio_choice.Set(labels)
            self.radio_choice.SetSelection(0)
            self.radio_url.SetValue(self._radio_entries[0][1])

    def on_radio_selected(self, _event):
        idx = self.radio_choice.GetSelection()
        if idx == wx.NOT_FOUND or idx >= len(self._radio_entries):
            return
        self.radio_url.SetValue(self._radio_entries[idx][1])

    def on_radio_stream(self, _event):
        url = self.radio_url.GetValue().strip()
        if not url:
            self.frame.set_status("Bitte eine Stream-URL eingeben")
            return
        ok = self.frame.client.start_streaming_media_to_channel(url, preamp_gain=self._get_stream_gain())
        if ok:
            self._streaming = True
            self.media_path.SetValue(url)
            self.media_info.SetLabel("Dauer: Live-Stream")
            self.frame.set_status("Webradio-Streaming gestartet")
        else:
            self.frame.set_status("Webradio-Streaming konnte nicht gestartet werden")
