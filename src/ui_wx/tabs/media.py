from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional

import os
import shutil
import subprocess
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

from ui_wx.a11y import setup_list_accessible

if TYPE_CHECKING:
    from app import MainFrame


class MediaTab(wx.Panel):
    """Tab 5: Aufnahme und Medien -- recording and media file streaming."""

    # yt-dlp sources: (display name, search prefix or None)
    # Sources with a search prefix support "prefix10:query" search via yt-dlp.
    YT_SOURCES: list = [
        ("YouTube",    "ytsearch"),
        ("SoundCloud", "scsearch"),
        ("Twitch",     None),
        ("Bandcamp",   None),
        ("Vimeo",      None),
        ("Mixcloud",   None),
    ]

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
        self.SetName("Aufnahme und Medien")
        self._recording = False
        self._streaming = False
        self._stream_duration_ms = 0
        self._yt_tempdir: Optional[Path] = None
        self._yt_output_path: Optional[Path] = None
        self._yt_results = []
        self._radio_entries = []
        self._radio_search_results = []
        self._podcast_results = []
        self._podcast_episodes = []
        self._twitch_stream_url: Optional[str] = None
        self._playlist_tracks: List[str] = []
        self._playlist_current: int = -1
        self._pl_streaming: bool = False

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
        self.rec_start_btn = wx.Button(self, label="&Aufnahme starten")
        self.rec_start_btn.SetName("Aufnahme starten")
        self.rec_start_btn.Bind(wx.EVT_BUTTON, self.on_rec_start)
        self.rec_stop_btn = wx.Button(self, label="Aufnahme &stoppen")
        self.rec_stop_btn.SetName("Aufnahme stoppen")
        self.rec_stop_btn.Bind(wx.EVT_BUTTON, self.on_rec_stop)
        self.rec_stop_btn.Disable()
        rec_btn_row.Add(self.rec_start_btn, 0, wx.RIGHT, 8)
        rec_btn_row.Add(self.rec_stop_btn, 0)
        rec_sizer.Add(rec_btn_row, 0, wx.ALL, 4)

        sizer.Add(rec_sizer, 0, wx.ALL | wx.EXPAND, 8)

        # --- Conversation Recording ---
        convo_box = wx.StaticBox(self, label="Konversationen aufzeichnen")
        convo_sizer = wx.StaticBoxSizer(convo_box, wx.VERTICAL)

        self.user_rec_enable = wx.CheckBox(self, label="Auto&matisch aufzeichnen")
        self.user_rec_enable.SetName("Konversationen aufzeichnen")
        self.user_rec_enable.SetValue(False)
        convo_sizer.Add(self.user_rec_enable, 0, wx.ALL, 4)

        dir_row = wx.BoxSizer(wx.HORIZONTAL)
        dir_row.Add(wx.StaticText(self, label="Zielordner"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.user_rec_dir = wx.DirPickerCtrl(self, message="Ordner für Aufnahmen wählen")
        self.user_rec_dir.SetName("Zielordner")
        dir_row.Add(self.user_rec_dir, 1, wx.EXPAND)
        convo_sizer.Add(dir_row, 0, wx.ALL | wx.EXPAND, 4)

        pattern_row = wx.BoxSizer(wx.HORIZONTAL)
        pattern_row.Add(wx.StaticText(self, label="Dateiname"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.user_rec_pattern = wx.TextCtrl(self)
        self.user_rec_pattern.SetName("Dateiname")
        self.user_rec_pattern.SetValue("%Y%m%d-%H%M%S #%userid% %username%")
        pattern_row.Add(self.user_rec_pattern, 1, wx.EXPAND)
        convo_sizer.Add(pattern_row, 0, wx.ALL | wx.EXPAND, 4)

        format_row = wx.BoxSizer(wx.HORIZONTAL)
        format_row.Add(wx.StaticText(self, label="Format"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.user_rec_format = wx.Choice(self, choices=["WAV", "MP3 128k", "MP3 256k"])
        self.user_rec_format.SetName("Konversationsformat")
        self.user_rec_format.SetSelection(0)
        format_row.Add(self.user_rec_format, 1, wx.EXPAND)
        convo_sizer.Add(format_row, 0, wx.ALL | wx.EXPAND, 4)

        self.user_rec_include_self = wx.CheckBox(self, label="&Eigene Stimme mit aufnehmen")
        self.user_rec_include_self.SetName("Eigene Stimme mit aufnehmen")
        self.user_rec_include_self.SetValue(True)
        convo_sizer.Add(self.user_rec_include_self, 0, wx.ALL, 4)

        self.user_rec_apply = wx.Button(self, label="An&wenden")
        self.user_rec_apply.SetName("Aufzeichnung anwenden")
        self.user_rec_apply.Bind(wx.EVT_BUTTON, self.on_user_record_apply)
        convo_sizer.Add(self.user_rec_apply, 0, wx.ALL, 4)

        sizer.Add(convo_sizer, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)

        # --- Streaming section ---
        streaming_box = wx.StaticBox(self, label="Medien-Streaming")
        streaming_sizer = wx.StaticBoxSizer(streaming_box, wx.VERTICAL)

        # Source selector row
        mode_row = wx.BoxSizer(wx.HORIZONTAL)
        mode_row.Add(wx.StaticText(self, label="Streaming-Quelle"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        _yt_names = [name for name, _ in self.YT_SOURCES]
        self.stream_mode = wx.Choice(self, choices=["Datei"] + _yt_names + ["Webradio", "Podcasts", "Playlist"])
        self.stream_mode.SetName("Streaming-Quelle")
        self.stream_mode.SetSelection(0)
        self.stream_mode.Bind(wx.EVT_CHOICE, self.on_stream_mode)
        mode_row.Add(self.stream_mode, 1, wx.EXPAND)
        streaming_sizer.Add(mode_row, 0, wx.ALL | wx.EXPAND, 4)

        # --- Media streaming (File) ---
        self.stream_panel = wx.Panel(self)
        stream_box = wx.StaticBox(self.stream_panel, label="Datei")
        stream_sizer = wx.StaticBoxSizer(stream_box, wx.VERTICAL)

        file_row = wx.BoxSizer(wx.HORIZONTAL)
        file_row.Add(wx.StaticText(self.stream_panel, label="Mediendatei Pfad"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.media_path = wx.TextCtrl(self.stream_panel)
        self.media_path.SetName("Mediendatei Pfad")
        self.browse_btn = wx.Button(self.stream_panel, label="&Durchsuchen...")
        self.browse_btn.SetName("Mediendatei auswählen")
        self.browse_btn.Bind(wx.EVT_BUTTON, self.on_browse)
        file_row.Add(self.media_path, 1, wx.RIGHT | wx.EXPAND, 8)
        file_row.Add(self.browse_btn, 0)
        stream_sizer.Add(file_row, 0, wx.ALL | wx.EXPAND, 4)

        self.media_info = wx.StaticText(self.stream_panel, label="Dauer: --")
        self.media_info.SetName("Medieninfo")
        stream_sizer.Add(self.media_info, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)

        ctrl_row = wx.BoxSizer(wx.HORIZONTAL)
        self.play_btn = wx.Button(self.stream_panel, label="&Abspielen")
        self.play_btn.SetName("Abspielen")
        self.play_btn.Bind(wx.EVT_BUTTON, self.on_play)
        self.pause_btn = wx.Button(self.stream_panel, label="&Pause")
        self.pause_btn.SetName("Pause")
        self.pause_btn.Bind(wx.EVT_BUTTON, self.on_pause)
        self.stop_btn = wx.Button(self.stream_panel, label="&Stopp")
        self.stop_btn.SetName("Stopp")
        self.stop_btn.Bind(wx.EVT_BUTTON, self.on_stop)
        for btn in (self.play_btn, self.pause_btn, self.stop_btn):
            ctrl_row.Add(btn, 0, wx.RIGHT, 8)
        stream_sizer.Add(ctrl_row, 0, wx.ALL, 4)

        stream_sizer.Add(wx.StaticText(self.stream_panel, label="Position (0–1000)"), 0, wx.ALL, 4)
        self.seek_slider = wx.SpinCtrl(self.stream_panel, value="0", min=0, max=1000)
        self.seek_slider.SetName("Position")
        self.seek_slider.Bind(wx.EVT_SPINCTRL, self.on_seek)
        stream_sizer.Add(self.seek_slider, 0, wx.ALL | wx.EXPAND, 4)

        gain_row = wx.BoxSizer(wx.HORIZONTAL)
        gain_row.Add(wx.StaticText(self.stream_panel, label="Streaming-Lautstärke (25–400)"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.stream_gain = wx.SpinCtrl(self.stream_panel, value="100", min=25, max=400)
        self.stream_gain.SetName("Streaming-Lautstärke")
        self.stream_gain.Bind(wx.EVT_SPINCTRL, self.on_stream_gain)
        gain_row.Add(self.stream_gain, 1, wx.EXPAND)
        stream_sizer.Add(gain_row, 0, wx.ALL | wx.EXPAND, 4)

        self.stream_panel.SetSizer(stream_sizer)
        streaming_sizer.Add(self.stream_panel, 0, wx.ALL | wx.EXPAND, 4)

        # --- Unified yt-dlp streaming panel ---
        self.ytdlp_panel = wx.Panel(self)
        ytdlp_box = wx.StaticBox(self.ytdlp_panel, label="Streaming (yt-dlp)")
        ytdlp_sizer = wx.StaticBoxSizer(ytdlp_box, wx.VERTICAL)

        # Search section — shown only for sources with search support
        self.ytdlp_search_box = wx.Panel(self.ytdlp_panel)
        ytdlp_search_inner = wx.BoxSizer(wx.VERTICAL)

        ytdlp_search_row = wx.BoxSizer(wx.HORIZONTAL)
        ytdlp_search_row.Add(wx.StaticText(self.ytdlp_search_box, label="Suche"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.ytdlp_search = wx.TextCtrl(self.ytdlp_search_box)
        self.ytdlp_search.SetName("Suche")
        self.ytdlp_search_btn = wx.Button(self.ytdlp_search_box, label="&Suchen")
        self.ytdlp_search_btn.SetName("Suchen")
        self.ytdlp_search_btn.Bind(wx.EVT_BUTTON, self.on_ytdlp_search)
        ytdlp_search_row.Add(self.ytdlp_search, 1, wx.RIGHT | wx.EXPAND, 8)
        ytdlp_search_row.Add(self.ytdlp_search_btn, 0)
        ytdlp_search_inner.Add(ytdlp_search_row, 0, wx.BOTTOM | wx.EXPAND, 4)

        self.ytdlp_results = wx.ListBox(self.ytdlp_search_box)
        self.ytdlp_results.SetName("Suchergebnisse")
        setup_list_accessible(self.ytdlp_results)
        self.ytdlp_results.Bind(wx.EVT_LISTBOX, self.on_ytdlp_select)
        self.ytdlp_results.SetMinSize((-1, 120))
        ytdlp_search_inner.Add(self.ytdlp_results, 0, wx.BOTTOM | wx.EXPAND, 4)

        self.ytdlp_search_box.SetSizer(ytdlp_search_inner)
        ytdlp_sizer.Add(self.ytdlp_search_box, 0, wx.LEFT | wx.RIGHT | wx.TOP | wx.EXPAND, 4)

        # URL row — always visible
        ytdlp_url_row = wx.BoxSizer(wx.HORIZONTAL)
        ytdlp_url_row.Add(wx.StaticText(self.ytdlp_panel, label="Link"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.ytdlp_url = wx.TextCtrl(self.ytdlp_panel)
        self.ytdlp_url.SetName("Link")
        self.ytdlp_stream_btn = wx.Button(self.ytdlp_panel, label="St&reamen")
        self.ytdlp_stream_btn.SetName("Streamen")
        self.ytdlp_stream_btn.Bind(wx.EVT_BUTTON, self.on_ytdlp_stream)
        ytdlp_url_row.Add(self.ytdlp_url, 1, wx.RIGHT | wx.EXPAND, 8)
        ytdlp_url_row.Add(self.ytdlp_stream_btn, 0)
        ytdlp_sizer.Add(ytdlp_url_row, 0, wx.ALL | wx.EXPAND, 4)

        self.ytdlp_status = wx.StaticText(self.ytdlp_panel, label="Status: bereit")
        self.ytdlp_status.SetName("Streaming-Status")
        ytdlp_sizer.Add(self.ytdlp_status, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)

        ytdlp_ctrl_row = wx.BoxSizer(wx.HORIZONTAL)
        self.ytdlp_pause_btn = wx.Button(self.ytdlp_panel, label="&Pause")
        self.ytdlp_pause_btn.SetName("Streaming Pause")
        self.ytdlp_pause_btn.Bind(wx.EVT_BUTTON, self.on_pause)
        self.ytdlp_stop_btn = wx.Button(self.ytdlp_panel, label="St&opp")
        self.ytdlp_stop_btn.SetName("Streaming Stopp")
        self.ytdlp_stop_btn.Bind(wx.EVT_BUTTON, self.on_stop)
        ytdlp_ctrl_row.Add(self.ytdlp_pause_btn, 0, wx.RIGHT, 8)
        ytdlp_ctrl_row.Add(self.ytdlp_stop_btn, 0)
        ytdlp_sizer.Add(ytdlp_ctrl_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)

        ytdlp_gain_row = wx.BoxSizer(wx.HORIZONTAL)
        ytdlp_gain_row.Add(wx.StaticText(self.ytdlp_panel, label="Streaming-Lautstärke (25–400)"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.ytdlp_stream_gain = wx.SpinCtrl(self.ytdlp_panel, value="100", min=25, max=400)
        self.ytdlp_stream_gain.SetName("Streaming-Lautstärke")
        self.ytdlp_stream_gain.Bind(wx.EVT_SPINCTRL, self.on_stream_gain)
        ytdlp_gain_row.Add(self.ytdlp_stream_gain, 1, wx.EXPAND)
        ytdlp_sizer.Add(ytdlp_gain_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 4)

        self.ytdlp_panel.SetSizer(ytdlp_sizer)
        streaming_sizer.Add(self.ytdlp_panel, 0, wx.ALL | wx.EXPAND, 4)

        # --- Webradio ---
        self.radio_panel = wx.Panel(self)
        radio_box = wx.StaticBox(self.radio_panel, label="Webradio")
        radio_sizer = wx.StaticBoxSizer(radio_box, wx.VERTICAL)

        radio_search_row = wx.BoxSizer(wx.HORIZONTAL)
        radio_search_row.Add(wx.StaticText(self.radio_panel, label="Webradio Suche"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.radio_search = wx.TextCtrl(self.radio_panel)
        self.radio_search.SetName("Webradio Suche")
        self.radio_search_btn = wx.Button(self.radio_panel, label="&Suchen")
        self.radio_search_btn.SetName("Webradio suchen")
        self.radio_search_btn.Bind(wx.EVT_BUTTON, self.on_radio_search)
        radio_search_row.Add(self.radio_search, 1, wx.RIGHT | wx.EXPAND, 8)
        radio_search_row.Add(self.radio_search_btn, 0)
        radio_sizer.Add(radio_search_row, 0, wx.ALL | wx.EXPAND, 4)

        self.radio_results = wx.ListBox(self.radio_panel)
        self.radio_results.SetName("Webradio Ergebnisse")
        setup_list_accessible(self.radio_results)
        self.radio_results.Bind(wx.EVT_LISTBOX, self.on_radio_search_select)
        radio_sizer.Add(self.radio_results, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 4)
        self.radio_results.SetMinSize((-1, 100))

        radio_sizer.Add(wx.StaticText(self.radio_panel, label="Webradio Senderliste"), 0, wx.ALL | wx.EXPAND, 4)
        self.radio_choice = wx.Choice(self.radio_panel)
        self.radio_choice.SetName("Webradio Senderliste")
        self.radio_choice.Bind(wx.EVT_CHOICE, self.on_radio_selected)
        radio_sizer.Add(self.radio_choice, 0, wx.ALL | wx.EXPAND, 4)

        radio_url_row = wx.BoxSizer(wx.HORIZONTAL)
        radio_url_row.Add(wx.StaticText(self.radio_panel, label="Webradio Stream-URL"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.radio_url = wx.TextCtrl(self.radio_panel)
        self.radio_url.SetName("Webradio Stream-URL")
        self.radio_play_btn = wx.Button(self.radio_panel, label="&Webradio streamen")
        self.radio_play_btn.SetName("Webradio streamen")
        self.radio_play_btn.Bind(wx.EVT_BUTTON, self.on_radio_stream)
        radio_url_row.Add(self.radio_url, 1, wx.RIGHT | wx.EXPAND, 8)
        radio_url_row.Add(self.radio_play_btn, 0)
        radio_sizer.Add(radio_url_row, 0, wx.ALL | wx.EXPAND, 4)

        radio_ctrl_row = wx.BoxSizer(wx.HORIZONTAL)
        self.radio_pause_btn = wx.Button(self.radio_panel, label="&Pause")
        self.radio_pause_btn.SetName("Webradio Pause")
        self.radio_pause_btn.Bind(wx.EVT_BUTTON, self.on_pause)
        self.radio_stop_btn = wx.Button(self.radio_panel, label="S&topp")
        self.radio_stop_btn.SetName("Webradio Stopp")
        self.radio_stop_btn.Bind(wx.EVT_BUTTON, self.on_stop)
        radio_ctrl_row.Add(self.radio_pause_btn, 0, wx.RIGHT, 8)
        radio_ctrl_row.Add(self.radio_stop_btn, 0)
        radio_sizer.Add(radio_ctrl_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)

        radio_gain_row = wx.BoxSizer(wx.HORIZONTAL)
        radio_gain_row.Add(wx.StaticText(self.radio_panel, label="Streaming-Lautstärke (25–400)"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.radio_stream_gain = wx.SpinCtrl(self.radio_panel, value="100", min=25, max=400)
        self.radio_stream_gain.SetName("Webradio-Lautstärke")
        self.radio_stream_gain.Bind(wx.EVT_SPINCTRL, self.on_stream_gain)
        radio_gain_row.Add(self.radio_stream_gain, 1, wx.EXPAND)
        radio_sizer.Add(radio_gain_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 4)

        self.radio_panel.SetSizer(radio_sizer)
        streaming_sizer.Add(self.radio_panel, 0, wx.ALL | wx.EXPAND, 4)

        # --- Podcasts ---
        self.podcast_panel = wx.Panel(self)
        podcast_box = wx.StaticBox(self.podcast_panel, label="Podcasts")
        podcast_sizer = wx.StaticBoxSizer(podcast_box, wx.VERTICAL)

        search_row = wx.BoxSizer(wx.HORIZONTAL)
        search_row.Add(wx.StaticText(self.podcast_panel, label="Podcast Suche"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.podcast_search = wx.TextCtrl(self.podcast_panel)
        self.podcast_search.SetName("Podcast Suche")
        self.podcast_search_btn = wx.Button(self.podcast_panel, label="&Suchen")
        self.podcast_search_btn.SetName("Podcast suchen")
        self.podcast_search_btn.Bind(wx.EVT_BUTTON, self.on_podcast_search)
        search_row.Add(self.podcast_search, 1, wx.RIGHT | wx.EXPAND, 8)
        search_row.Add(self.podcast_search_btn, 0)
        podcast_sizer.Add(search_row, 0, wx.ALL | wx.EXPAND, 4)

        feed_row = wx.BoxSizer(wx.HORIZONTAL)
        feed_row.Add(wx.StaticText(self.podcast_panel, label="Podcast Feed URL"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.podcast_feed = wx.TextCtrl(self.podcast_panel)
        self.podcast_feed.SetName("Podcast Feed URL")
        self.podcast_feed_btn = wx.Button(self.podcast_panel, label="&Feed laden")
        self.podcast_feed_btn.SetName("Podcast Feed laden")
        self.podcast_feed_btn.Bind(wx.EVT_BUTTON, self.on_podcast_feed_load)
        feed_row.Add(self.podcast_feed, 1, wx.RIGHT | wx.EXPAND, 8)
        feed_row.Add(self.podcast_feed_btn, 0)
        podcast_sizer.Add(feed_row, 0, wx.ALL | wx.EXPAND, 4)

        self.podcast_list = wx.ListBox(self.podcast_panel)
        self.podcast_list.SetName("Podcast Ergebnisse")
        setup_list_accessible(self.podcast_list)
        self.podcast_list.Bind(wx.EVT_LISTBOX, self.on_podcast_select)
        podcast_sizer.Add(self.podcast_list, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 4)
        self.podcast_list.SetMinSize((-1, 120))

        self.episode_list = wx.ListBox(self.podcast_panel)
        self.episode_list.SetName("Podcast Episoden")
        setup_list_accessible(self.episode_list)
        podcast_sizer.Add(self.episode_list, 1, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 4)
        self.episode_list.SetMinSize((-1, 160))

        pod_ctrl_row = wx.BoxSizer(wx.HORIZONTAL)
        self.episode_stream_btn = wx.Button(self.podcast_panel, label="&Episode streamen")
        self.episode_stream_btn.SetName("Episode streamen")
        self.episode_stream_btn.Bind(wx.EVT_BUTTON, self.on_episode_stream)
        self.podcast_pause_btn = wx.Button(self.podcast_panel, label="&Pause")
        self.podcast_pause_btn.SetName("Podcast Pause")
        self.podcast_pause_btn.Bind(wx.EVT_BUTTON, self.on_pause)
        self.podcast_stop_btn = wx.Button(self.podcast_panel, label="S&topp")
        self.podcast_stop_btn.SetName("Podcast Stopp")
        self.podcast_stop_btn.Bind(wx.EVT_BUTTON, self.on_stop)
        pod_ctrl_row.Add(self.episode_stream_btn, 0, wx.RIGHT, 8)
        pod_ctrl_row.Add(self.podcast_pause_btn, 0, wx.RIGHT, 8)
        pod_ctrl_row.Add(self.podcast_stop_btn, 0)
        podcast_sizer.Add(pod_ctrl_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)

        pod_gain_row = wx.BoxSizer(wx.HORIZONTAL)
        pod_gain_row.Add(wx.StaticText(self.podcast_panel, label="Streaming-Lautstärke (25–400)"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.podcast_stream_gain = wx.SpinCtrl(self.podcast_panel, value="100", min=25, max=400)
        self.podcast_stream_gain.SetName("Podcast-Lautstärke")
        self.podcast_stream_gain.Bind(wx.EVT_SPINCTRL, self.on_stream_gain)
        pod_gain_row.Add(self.podcast_stream_gain, 1, wx.EXPAND)
        podcast_sizer.Add(pod_gain_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 4)

        self.podcast_panel.SetSizer(podcast_sizer)
        streaming_sizer.Add(self.podcast_panel, 0, wx.ALL | wx.EXPAND, 4)

        # --- Playlist ---
        self.playlist_panel = wx.Panel(self)
        pl_box = wx.StaticBox(self.playlist_panel, label="Playlist")
        pl_sizer = wx.StaticBoxSizer(pl_box, wx.VERTICAL)

        pl_list_lbl = wx.StaticText(self.playlist_panel, label="Titel, Pfad")
        pl_list_lbl.SetName("Playlist Kopfzeile")
        pl_sizer.Add(pl_list_lbl, 0, wx.LEFT | wx.RIGHT | wx.TOP, 4)

        self.pl_list = wx.ListBox(self.playlist_panel, style=wx.LB_SINGLE)
        self.pl_list.SetName("Playlist")
        setup_list_accessible(self.pl_list)
        self.pl_list.SetMinSize((-1, 140))
        pl_sizer.Add(self.pl_list, 1, wx.ALL | wx.EXPAND, 4)

        pl_edit_row = wx.BoxSizer(wx.HORIZONTAL)
        self.pl_add_btn = wx.Button(self.playlist_panel, label="&Hinzufügen...")
        self.pl_add_btn.SetName("Dateien zur Playlist hinzufügen")
        self.pl_add_btn.Bind(wx.EVT_BUTTON, self._on_pl_add)
        self.pl_load_btn = wx.Button(self.playlist_panel, label="M3U &laden...")
        self.pl_load_btn.SetName("M3U-Datei laden")
        self.pl_load_btn.Bind(wx.EVT_BUTTON, self._on_pl_load_m3u)
        self.pl_remove_btn = wx.Button(self.playlist_panel, label="&Entfernen")
        self.pl_remove_btn.SetName("Ausgewählten Titel entfernen")
        self.pl_remove_btn.Bind(wx.EVT_BUTTON, self._on_pl_remove)
        self.pl_up_btn = wx.Button(self.playlist_panel, label="Nach &oben")
        self.pl_up_btn.SetName("Titel nach oben verschieben")
        self.pl_up_btn.Bind(wx.EVT_BUTTON, self._on_pl_move_up)
        self.pl_down_btn = wx.Button(self.playlist_panel, label="Nach &unten")
        self.pl_down_btn.SetName("Titel nach unten verschieben")
        self.pl_down_btn.Bind(wx.EVT_BUTTON, self._on_pl_move_down)
        self.pl_export_btn = wx.Button(self.playlist_panel, label="Als M3U e&xportieren...")
        self.pl_export_btn.SetName("Playlist als M3U exportieren")
        self.pl_export_btn.Bind(wx.EVT_BUTTON, self._on_pl_export)
        self.pl_clear_btn = wx.Button(self.playlist_panel, label="&Leeren")
        self.pl_clear_btn.SetName("Playlist leeren")
        self.pl_clear_btn.Bind(wx.EVT_BUTTON, self._on_pl_clear)
        for btn in (self.pl_add_btn, self.pl_load_btn, self.pl_remove_btn,
                    self.pl_up_btn, self.pl_down_btn, self.pl_export_btn, self.pl_clear_btn):
            pl_edit_row.Add(btn, 0, wx.RIGHT, 4)
        pl_sizer.Add(pl_edit_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)

        self.pl_auto_next = wx.CheckBox(self.playlist_panel, label="&Automatisch weiter (nächster Titel nach Ende)")
        self.pl_auto_next.SetName("Automatisch weiter")
        self.pl_auto_next.SetValue(True)
        pl_sizer.Add(self.pl_auto_next, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)

        pl_ctrl_row = wx.BoxSizer(wx.HORIZONTAL)
        self.pl_play_btn = wx.Button(self.playlist_panel, label="A&bspielen")
        self.pl_play_btn.SetName("Playlist abspielen")
        self.pl_play_btn.Bind(wx.EVT_BUTTON, self._on_pl_play)
        self.pl_pause_btn = wx.Button(self.playlist_panel, label="Pa&use")
        self.pl_pause_btn.SetName("Playlist pausieren")
        self.pl_pause_btn.Bind(wx.EVT_BUTTON, self.on_pause)
        self.pl_stop_btn = wx.Button(self.playlist_panel, label="St&opp")
        self.pl_stop_btn.SetName("Playlist stoppen")
        self.pl_stop_btn.Bind(wx.EVT_BUTTON, self.on_stop)
        pl_ctrl_row.Add(self.pl_play_btn, 0, wx.RIGHT, 8)
        pl_ctrl_row.Add(self.pl_pause_btn, 0, wx.RIGHT, 8)
        pl_ctrl_row.Add(self.pl_stop_btn, 0)
        pl_sizer.Add(pl_ctrl_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)

        pl_gain_row = wx.BoxSizer(wx.HORIZONTAL)
        pl_gain_row.Add(wx.StaticText(self.playlist_panel, label="Streaming-Lautstärke (25–400)"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.pl_stream_gain = wx.SpinCtrl(self.playlist_panel, value="100", min=25, max=400)
        self.pl_stream_gain.SetName("Playlist-Lautstärke")
        self.pl_stream_gain.Bind(wx.EVT_SPINCTRL, self.on_stream_gain)
        pl_gain_row.Add(self.pl_stream_gain, 1, wx.EXPAND)
        pl_sizer.Add(pl_gain_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 4)

        self.playlist_panel.SetSizer(pl_sizer)
        streaming_sizer.Add(self.playlist_panel, 0, wx.ALL | wx.EXPAND, 4)

        sizer.Add(streaming_sizer, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)

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

    def _get_user_rec_format(self) -> int:
        tt = self.frame.client.tt
        mapping = {
            0: tt.AudioFileFormat.AFF_WAVE_FORMAT,
            1: tt.AudioFileFormat.AFF_MP3_128KBIT_FORMAT,
            2: tt.AudioFileFormat.AFF_MP3_256KBIT_FORMAT,
        }
        return int(mapping.get(self.user_rec_format.GetSelection(), tt.AudioFileFormat.AFF_WAVE_FORMAT))

    def on_user_record_apply(self, _event):
        enabled = self.user_rec_enable.GetValue()
        folder = self.user_rec_dir.GetPath() if enabled else ""
        if enabled and not folder:
            self.frame.set_status("Bitte Zielordner wählen")
            return
        pattern = self.user_rec_pattern.GetValue().strip() if enabled else ""
        fmt = self._get_user_rec_format()
        include_self = self.user_rec_include_self.GetValue()
        self.frame.configure_user_recording(enabled, folder, pattern, fmt, include_self)

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
            self, "Mediendatei auswählen",
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
            self.frame.set_status("Bitte zuerst eine Datei auswählen")
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
        self._pl_streaming = False
        self._cleanup_ytdlp_tempdir()

    def on_seek(self, _event):
        if self._streaming:
            pos_sec = self.seek_slider.GetValue()
            self.frame.client.update_streaming_media(paused=False, offset_ms=pos_sec * 1000, preamp_gain=self._get_stream_gain())

    def on_stream_update(self, media_file_info):
        elapsed = int(media_file_info.uElapsedMSec)
        duration = int(media_file_info.uDurationMSec)
        if duration > 0:
            if self.stream_panel.IsShown():
                secs = elapsed // 1000
                self.seek_slider.SetValue(min(secs, self.seek_slider.GetMax()))
            if elapsed >= duration and self._streaming:
                self._streaming = False
                if self._pl_streaming and self.pl_auto_next.GetValue():
                    wx.CallAfter(self._pl_advance)
                else:
                    self._pl_streaming = False
                    self.frame.set_status("Streaming beendet")
                    self._cleanup_ytdlp_tempdir()

    def on_stream_gain(self, _event):
        if self._streaming:
            self.frame.client.update_streaming_media(paused=False, offset_ms=None, preamp_gain=self._get_stream_gain())

    def _get_stream_gain(self) -> float:
        if self.ytdlp_panel.IsShown():
            val = self.ytdlp_stream_gain.GetValue()
        elif self.radio_panel.IsShown():
            val = self.radio_stream_gain.GetValue()
        elif self.podcast_panel.IsShown():
            val = self.podcast_stream_gain.GetValue()
        elif self.playlist_panel.IsShown():
            val = self.pl_stream_gain.GetValue()
        else:
            val = self.stream_gain.GetValue()
        return max(0.1, float(val) / 100.0)

    def _set_tab_order(self):
        try:
            self._do_set_tab_order()
        except Exception:
            pass  # Tab order is cosmetic; don't let it prevent the tab from loading.

    def _do_set_tab_order(self):
        # Top-level controls (direct children of self)
        top_order = [
            self.rec_format, self.rec_start_btn, self.rec_stop_btn,
            self.user_rec_enable, self.user_rec_dir, self.user_rec_pattern,
            self.user_rec_format, self.user_rec_include_self, self.user_rec_apply,
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
        ytdlp_order = [
            self.ytdlp_search, self.ytdlp_search_btn, self.ytdlp_results,
            self.ytdlp_url, self.ytdlp_stream_btn, self.ytdlp_pause_btn, self.ytdlp_stop_btn, self.ytdlp_stream_gain,
        ]
        for i in range(1, len(ytdlp_order)):
            ytdlp_order[i].MoveAfterInTabOrder(ytdlp_order[i - 1])
        radio_order = [
            self.radio_search, self.radio_search_btn, self.radio_results, self.radio_choice,
            self.radio_url, self.radio_play_btn, self.radio_pause_btn, self.radio_stop_btn, self.radio_stream_gain,
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
        pl_order = [
            self.pl_list, self.pl_add_btn, self.pl_load_btn, self.pl_remove_btn,
            self.pl_up_btn, self.pl_down_btn, self.pl_export_btn, self.pl_clear_btn,
            self.pl_auto_next, self.pl_play_btn, self.pl_pause_btn, self.pl_stop_btn,
            self.pl_stream_gain,
        ]
        for i in range(1, len(pl_order)):
            pl_order[i].MoveAfterInTabOrder(pl_order[i - 1])

    def on_stream_mode(self, _event):
        self._update_stream_mode()

    def _update_stream_mode(self):
        mode = self.stream_mode.GetSelection()
        n_yt = len(self.YT_SOURCES)
        is_ytdlp = 1 <= mode <= n_yt
        radio_idx = n_yt + 1
        podcast_idx = n_yt + 2
        playlist_idx = n_yt + 3

        self.stream_panel.Show(mode == 0)
        self.ytdlp_panel.Show(is_ytdlp)
        self.radio_panel.Show(mode == radio_idx)
        self.podcast_panel.Show(mode == podcast_idx)
        self.playlist_panel.Show(mode == playlist_idx)

        if is_ytdlp:
            _, search_prefix = self.YT_SOURCES[mode - 1]
            has_search = search_prefix is not None
            self.ytdlp_search_box.Show(has_search)
            self.ytdlp_panel.Layout()

        self.Layout()
        self.GetParent().Layout()

        if mode == 0:
            self.media_path.SetFocus()
        elif is_ytdlp:
            _, search_prefix = self.YT_SOURCES[mode - 1]
            (self.ytdlp_search if search_prefix else self.ytdlp_url).SetFocus()
        elif mode == radio_idx:
            self.radio_choice.SetFocus()
        elif mode == podcast_idx:
            self.podcast_search.SetFocus()
        elif mode == playlist_idx:
            self.pl_list.SetFocus()

    # --- Unified yt-dlp search ---

    def _current_ytdlp_source(self):
        """Returns (source_name, search_prefix) for the active yt-dlp mode."""
        mode = self.stream_mode.GetSelection()
        idx = mode - 1
        if 0 <= idx < len(self.YT_SOURCES):
            return self.YT_SOURCES[idx]
        return ("Stream", None)

    def on_ytdlp_search(self, _event):
        term = self.ytdlp_search.GetValue().strip()
        if not term:
            self.frame.set_status("Bitte Suchbegriff eingeben")
            return
        ytdlp = self._find_yt_dlp()
        if not ytdlp:
            self.frame.set_status("yt-dlp nicht gefunden (binary fehlt)")
            self.ytdlp_status.SetLabel("Status: yt-dlp fehlt")
            return
        source_name, search_prefix = self._current_ytdlp_source()
        if not search_prefix:
            return

        self.ytdlp_search_btn.Disable()
        self.ytdlp_status.SetLabel("Status: Suche läuft...")

        def worker():
            try:
                cmd = [ytdlp, "--dump-json", "--no-playlist", f"{search_prefix}10:{term}"]
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
                if proc.returncode != 0:
                    err = (proc.stderr or proc.stdout or "Unbekannter Fehler").strip()
                    wx.CallAfter(self._ytdlp_search_failed, err, source_name)
                    return
                items = []
                parsed = []
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
                        mins = int(duration) // 60
                        secs = int(duration) % 60
                        label += f" — {mins}:{secs:02d}"
                    items.append(label)
                    parsed.append({"title": title, "uploader": uploader, "duration": duration, "url": url})
                wx.CallAfter(self._ytdlp_search_ready, items, parsed, source_name)
            except Exception as exc:
                wx.CallAfter(self._ytdlp_search_failed, str(exc), source_name)

        threading.Thread(target=worker, daemon=True).start()

    def _ytdlp_search_ready(self, items, parsed, source_name: str):
        self.ytdlp_search_btn.Enable()
        self._yt_results = parsed
        self.ytdlp_results.Set(items)
        if items:
            self.ytdlp_results.SetSelection(0)
            self.on_ytdlp_select(None)
        self.ytdlp_status.SetLabel(f"Status: {len(items)} Treffer")

    def _ytdlp_search_failed(self, message: str, source_name: str):
        self.ytdlp_search_btn.Enable()
        self.ytdlp_status.SetLabel("Status: Suche fehlgeschlagen")
        self.frame.set_status(f"{source_name}-Suche fehlgeschlagen: {message}")

    def on_ytdlp_select(self, _event):
        idx = self.ytdlp_results.GetSelection()
        if idx == wx.NOT_FOUND or idx >= len(self._yt_results):
            return
        url = self._yt_results[idx].get("url") or ""
        if url:
            self.ytdlp_url.SetValue(url)

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
                    wx.CallAfter(self.frame.set_status, "Feed über Proxy geladen")
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
            self.frame.set_status("Bitte Episode auswählen")
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

    # --- Unified yt-dlp streaming ---

    def _find_yt_dlp(self) -> Optional[str]:
        exe_name = "yt-dlp.exe" if sys.platform == "win32" else "yt-dlp"
        # 1) Bundled binary (PyInstaller)
        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            bundled = Path(sys._MEIPASS) / "yt-dlp" / exe_name
            if bundled.exists():
                return str(bundled)
        # 2) Repo binary
        root = Path(__file__).resolve().parents[2]
        local = root / "third_party" / "yt-dlp" / exe_name
        if local.exists():
            return str(local)
        # 3) PATH
        return shutil.which(exe_name) or shutil.which("yt-dlp")

    def on_ytdlp_stream(self, _event):
        url = self.ytdlp_url.GetValue().strip()
        if not url:
            self.frame.set_status("Bitte einen Link eingeben")
            return
        ytdlp = self._find_yt_dlp()
        if not ytdlp:
            self.frame.set_status("yt-dlp nicht gefunden (binary fehlt)")
            self.ytdlp_status.SetLabel("Status: yt-dlp fehlt")
            return

        source_name, _ = self._current_ytdlp_source()
        self.ytdlp_stream_btn.Disable()
        self.ytdlp_status.SetLabel("Status: Stream wird vorbereitet...")
        self.frame.set_status(f"{source_name}-Stream wird gestartet")

        def worker():
            try:
                cmd = [ytdlp, "-g", "-f", "bestaudio/best", "--no-playlist", url]
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
                if proc.returncode != 0:
                    err = (proc.stderr or proc.stdout or "Unbekannter Fehler").strip()
                    wx.CallAfter(self._ytdlp_failed, err, source_name)
                    return
                stream_url = (proc.stdout or "").splitlines()[0].strip()
                if not stream_url:
                    wx.CallAfter(self._ytdlp_failed, "Keine Stream-URL gefunden", source_name)
                    return
                wx.CallAfter(self._ytdlp_ready, stream_url, source_name)
            except Exception as exc:
                wx.CallAfter(self._ytdlp_failed, str(exc), source_name)

        threading.Thread(target=worker, daemon=True).start()

    def _ytdlp_failed(self, message: str, source_name: str = "Stream"):
        self.ytdlp_stream_btn.Enable()
        self.ytdlp_status.SetLabel("Status: Fehler")
        self.frame.set_status(f"{source_name}-Streaming fehlgeschlagen: {message}")

    def _ytdlp_ready(self, stream_url: str, source_name: str = "Stream"):
        self.ytdlp_stream_btn.Enable()
        self.ytdlp_status.SetLabel("Status: Stream bereit")
        ok = self.frame.client.start_streaming_media_to_channel(stream_url, preamp_gain=self._get_stream_gain())
        if ok:
            self._streaming = True
            self.media_path.SetValue(stream_url)
            self.media_info.SetLabel("Dauer: Live-Stream")
            self.frame.set_status(f"{source_name}-Streaming gestartet")
        else:
            self.frame.set_status(f"{source_name}-Streaming konnte nicht gestartet werden")

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

    def on_radio_search(self, _event):
        term = self.radio_search.GetValue().strip()
        if not term:
            self.frame.set_status("Bitte Suchbegriff eingeben")
            return
        self.radio_search_btn.Disable()
        self.frame.set_status("Webradio-Suche läuft...")

        def worker():
            try:
                params = {"name": term, "limit": 20, "hidebroken": 1, "order": "clickcount", "reverse": 1}
                url = "https://de1.api.radio-browser.info/json/stations/search"
                data = self._fetch_json(url, params=params)
                if not isinstance(data, list):
                    data = []
                items = []
                parsed = []
                for r in data:
                    name = r.get("name") or "Sender"
                    country = r.get("country") or ""
                    codec = r.get("codec") or ""
                    bitrate = r.get("bitrate") or ""
                    stream = r.get("url_resolved") or r.get("url") or ""
                    label = name
                    meta = " ".join([x for x in (country, codec, f"{bitrate}kbps" if bitrate else "") if x])
                    if meta:
                        label += f" — {meta}"
                    items.append(label)
                    parsed.append({"name": name, "url": stream, "meta": meta})
                wx.CallAfter(self._radio_search_ready, items, parsed)
            except Exception as exc:
                wx.CallAfter(self._radio_search_failed, str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _radio_search_ready(self, items, parsed):
        self.radio_search_btn.Enable()
        self._radio_search_results = parsed
        self.radio_results.Set(items)
        if items:
            self.radio_results.SetSelection(0)
            self.on_radio_search_select(None)
        self.frame.set_status(f"Webradio Treffer: {len(items)}")

    def _radio_search_failed(self, message: str):
        self.radio_search_btn.Enable()
        self.frame.set_status(f"Webradio-Suche fehlgeschlagen: {message}")

    def on_radio_search_select(self, _event):
        idx = self.radio_results.GetSelection()
        if idx == wx.NOT_FOUND or idx >= len(self._radio_search_results):
            return
        url = self._radio_search_results[idx].get("url") or ""
        if url:
            self.radio_url.SetValue(url)

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

    # ------------------------------------------------------------------
    # Playlist
    # ------------------------------------------------------------------

    def _pl_display_name(self, path: str) -> str:
        return os.path.splitext(os.path.basename(path))[0]

    def _pl_refresh_list(self):
        self.pl_list.Set([self._pl_display_name(p) for p in self._playlist_tracks])

    def _on_pl_add(self, _event):
        with wx.FileDialog(
            self, "Dateien zur Playlist hinzufügen",
            wildcard="Audio/Video|*.mp3;*.wav;*.ogg;*.flac;*.m4a;*.opus;*.mp4;*.avi;*.mkv|Alle|*.*",
            style=wx.FD_OPEN | wx.FD_MULTIPLE | wx.FD_FILE_MUST_EXIST,
        ) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            paths = dlg.GetPaths()
        for p in paths:
            self._playlist_tracks.append(p)
        self._pl_refresh_list()
        self.frame.set_status(f"{len(paths)} Datei(en) hinzugefügt, {len(self._playlist_tracks)} in Playlist")

    def _on_pl_load_m3u(self, _event):
        with wx.FileDialog(
            self, "M3U-Datei laden",
            wildcard="M3U-Playlist (*.m3u;*.m3u8)|*.m3u;*.m3u8|Alle|*.*",
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        ) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            path = dlg.GetPath()
        tracks = self._parse_m3u(path)
        if not tracks:
            wx.MessageBox("Keine abspielbaren Pfade in der M3U-Datei gefunden.",
                          "M3U laden", wx.OK | wx.ICON_INFORMATION, self)
            return
        self._playlist_tracks = tracks
        self._pl_refresh_list()
        if self._playlist_tracks:
            self.pl_list.SetSelection(0)
        self.frame.set_status(f"M3U geladen: {len(tracks)} Titel")

    def _on_pl_remove(self, _event):
        idx = self.pl_list.GetSelection()
        if idx == wx.NOT_FOUND or idx >= len(self._playlist_tracks):
            return
        del self._playlist_tracks[idx]
        self._pl_refresh_list()
        new_sel = min(idx, len(self._playlist_tracks) - 1)
        if new_sel >= 0:
            self.pl_list.SetSelection(new_sel)
        self.frame.set_status(f"Titel entfernt, {len(self._playlist_tracks)} verbleibend")

    def _on_pl_move_up(self, _event):
        idx = self.pl_list.GetSelection()
        if idx <= 0 or idx >= len(self._playlist_tracks):
            return
        self._playlist_tracks[idx - 1], self._playlist_tracks[idx] = \
            self._playlist_tracks[idx], self._playlist_tracks[idx - 1]
        self._pl_refresh_list()
        self.pl_list.SetSelection(idx - 1)

    def _on_pl_move_down(self, _event):
        idx = self.pl_list.GetSelection()
        if idx == wx.NOT_FOUND or idx >= len(self._playlist_tracks) - 1:
            return
        self._playlist_tracks[idx], self._playlist_tracks[idx + 1] = \
            self._playlist_tracks[idx + 1], self._playlist_tracks[idx]
        self._pl_refresh_list()
        self.pl_list.SetSelection(idx + 1)

    def _on_pl_export(self, _event):
        if not self._playlist_tracks:
            wx.MessageBox("Playlist ist leer.", "M3U exportieren", wx.OK | wx.ICON_INFORMATION, self)
            return
        with wx.FileDialog(
            self, "Playlist als M3U exportieren",
            wildcard="M3U-Playlist (*.m3u)|*.m3u",
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
            defaultFile="playlist.m3u",
        ) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            path = dlg.GetPath()
        self._export_m3u(path, self._playlist_tracks)
        self.frame.set_status(f"Playlist exportiert: {path}")

    def _on_pl_clear(self, _event):
        if not self._playlist_tracks:
            return
        dlg = wx.MessageDialog(self, "Playlist wirklich leeren?", "Leeren",
                               wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION)
        dlg.SetYesNoLabels("Ja", "Nein")
        if dlg.ShowModal() == wx.ID_YES:
            self._playlist_tracks = []
            self._pl_refresh_list()
            self.frame.set_status("Playlist geleert")
        dlg.Destroy()

    def _on_pl_play(self, _event):
        if not self._playlist_tracks:
            self.frame.set_status("Playlist ist leer")
            return
        idx = self.pl_list.GetSelection()
        if idx == wx.NOT_FOUND:
            idx = 0
        self._pl_streaming = True
        self._pl_play_track(idx)

    def _pl_play_track(self, idx: int):
        if idx < 0 or idx >= len(self._playlist_tracks):
            self._pl_streaming = False
            self.frame.set_status("Playlist beendet")
            return
        self._playlist_current = idx
        self.pl_list.SetSelection(idx)
        path = self._playlist_tracks[idx]
        name = self._pl_display_name(path)
        ok = self.frame.client.start_streaming_media_to_channel(
            path, preamp_gain=self._get_stream_gain()
        )
        if ok:
            self._streaming = True
            self.frame.set_status(f"Playlist [{idx + 1}/{len(self._playlist_tracks)}]: {name}")
        else:
            self.frame.set_status(f"Fehler bei: {name} – überspringe")
            self._pl_advance()

    def _pl_advance(self):
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
