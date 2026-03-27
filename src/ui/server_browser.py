from __future__ import annotations

import threading
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import List, Optional, TYPE_CHECKING

import wx

from .models import ServerProfile
from .a11y import setup_list_accessible

if TYPE_CHECKING:
    from app import MainFrame

BEARWARE_SERVER_LIST_URL = "https://www.bearware.dk/teamtalk/serverlist5.aspx"
_FETCH_TIMEOUT = 10


@dataclass
class _PublicServer:
    name: str
    host: str
    tcp_port: int
    udp_port: int
    encrypted: bool
    users: int
    channels: int
    country: str
    motd: str
    version: str


def _fetch_server_list() -> List[_PublicServer]:
    req = urllib.request.Request(
        BEARWARE_SERVER_LIST_URL,
        headers={"User-Agent": "TeamTalk VO Client"},
    )
    with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT) as resp:
        data = resp.read()
    root = ET.fromstring(data)
    servers: List[_PublicServer] = []
    for srv in root.findall("server"):

        def _text(tag: str, default: str = "", _el=srv) -> str:
            el = _el.find(tag)
            return el.text.strip() if el is not None and el.text else default

        def _int(tag: str, default: int = 0) -> int:
            try:
                return int(_text(tag, str(default)))
            except ValueError:
                return default

        def _bool(tag: str) -> bool:
            return _text(tag, "false").lower() in ("true", "1", "yes")

        host = _text("hostaddress")
        if not host:
            continue
        servers.append(_PublicServer(
            name=_text("name") or host,
            host=host,
            tcp_port=_int("tcpport", 10333),
            udp_port=_int("udpport", 10333),
            encrypted=_bool("encrypted"),
            users=_int("users"),
            channels=_int("channels"),
            country=_text("country"),
            motd=_text("motd"),
            version=_text("version"),
        ))
    return servers


class ServerBrowserDialog(wx.Dialog):
    """Dialog zum Anzeigen und Importieren öffentlicher TeamTalk-Server von bearware.dk."""

    def __init__(self, parent: wx.Window, frame: "MainFrame") -> None:
        super().__init__(
            parent,
            title="Öffentliche Serverliste (bearware.dk)",
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.frame = frame
        self._servers: List[_PublicServer] = []

        sizer = wx.BoxSizer(wx.VERTICAL)

        self._status_lbl = wx.StaticText(self, label="Serverliste wird abgerufen…")
        self._status_lbl.SetName("Status")
        sizer.Add(self._status_lbl, 0, wx.ALL, 8)

        self._list = wx.ListBox(self, choices=[], style=wx.LB_SINGLE)
        self._list.SetName("Öffentliche Server")
        setup_list_accessible(self._list)
        self._list.Bind(wx.EVT_LISTBOX, self._on_selection)
        self._list.Bind(wx.EVT_LISTBOX_DCLICK, self._on_connect)
        sizer.Add(self._list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        self._detail_lbl = wx.StaticText(self, label="")
        self._detail_lbl.SetName("Serverdetails")
        sizer.Add(self._detail_lbl, 0, wx.ALL, 8)

        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        self._connect_btn = wx.Button(self, label="&Verbinden")
        self._connect_btn.SetName("Verbinden")
        self._connect_btn.Bind(wx.EVT_BUTTON, self._on_connect)
        self._connect_btn.Enable(False)

        self._save_btn = wx.Button(self, label="In Liste &speichern")
        self._save_btn.SetName("In Serverliste speichern")
        self._save_btn.Bind(wx.EVT_BUTTON, self._on_save)
        self._save_btn.Enable(False)

        self._reload_btn = wx.Button(self, label="&Aktualisieren")
        self._reload_btn.SetName("Liste aktualisieren")
        self._reload_btn.Bind(wx.EVT_BUTTON, lambda _e: self._fetch())

        cancel_btn = wx.Button(self, wx.ID_CANCEL, label="&Schließen")
        cancel_btn.SetName("Schließen")

        btn_row.Add(self._connect_btn, 0, wx.RIGHT, 8)
        btn_row.Add(self._save_btn, 0, wx.RIGHT, 8)
        btn_row.Add(self._reload_btn, 0, wx.RIGHT, 8)
        btn_row.Add(cancel_btn, 0)
        sizer.Add(btn_row, 0, wx.ALL, 8)

        self.SetSizer(sizer)
        self.SetSize((720, 520))
        self.Centre()

        self._fetch()

    # ------------------------------------------------------------------

    def _fetch(self) -> None:
        self._status_lbl.SetLabel("Serverliste wird abgerufen…")
        self._list.Clear()
        self._servers.clear()
        self._connect_btn.Enable(False)
        self._save_btn.Enable(False)
        self._detail_lbl.SetLabel("")
        threading.Thread(target=self._fetch_worker, daemon=True).start()

    def _fetch_worker(self) -> None:
        try:
            servers = _fetch_server_list()
            wx.CallAfter(self._on_fetch_done, servers, None)
        except Exception as exc:
            wx.CallAfter(self._on_fetch_done, [], str(exc))

    def _on_fetch_done(self, servers: List[_PublicServer], error: Optional[str]) -> None:
        if error:
            self._status_lbl.SetLabel(f"Fehler beim Abrufen: {error}")
            return
        self._servers = servers
        if not servers:
            self._status_lbl.SetLabel("Keine Server gefunden.")
            return
        self._status_lbl.SetLabel(f"{len(servers)} Server gefunden.")
        choices = []
        for s in servers:
            enc = " [verschlüsselt]" if s.encrypted else ""
            country = f" [{s.country}]" if s.country else ""
            choices.append(f"{s.name}{country}{enc}, {s.users} Nutzer")
        self._list.Set(choices)

    # ------------------------------------------------------------------

    def _on_selection(self, _event) -> None:
        idx = self._list.GetSelection()
        if idx == wx.NOT_FOUND or idx >= len(self._servers):
            self._connect_btn.Enable(False)
            self._save_btn.Enable(False)
            self._detail_lbl.SetLabel("")
            return
        srv = self._servers[idx]
        enc = "Ja" if srv.encrypted else "Nein"
        parts = [
            f"Host: {srv.host}",
            f"Port: {srv.tcp_port}",
            f"Verschlüsselt: {enc}",
        ]
        if srv.version:
            parts.append(f"Version: {srv.version}")
        detail = ", ".join(parts)
        if srv.motd:
            detail += f"\nMOTD: {srv.motd}"
        self._detail_lbl.SetLabel(detail)
        self._connect_btn.Enable(True)
        self._save_btn.Enable(True)

    def _get_selected_profile(self) -> Optional[ServerProfile]:
        idx = self._list.GetSelection()
        if idx == wx.NOT_FOUND or idx >= len(self._servers):
            return None
        srv = self._servers[idx]
        nickname = self.frame.connection_tab.nickname.GetValue().strip() or "VoiceOverUser"
        return ServerProfile(
            name=srv.name,
            host=srv.host,
            tcp_port=srv.tcp_port,
            udp_port=srv.udp_port,
            nickname=nickname,
            username="guest",
            password="",
            client_name="TeamTalk VO",
            encrypted=srv.encrypted,
        )

    def _on_connect(self, _event) -> None:
        profile = self._get_selected_profile()
        if not profile:
            return
        self.frame.connection_tab.fill_form(profile)
        self.EndModal(wx.ID_OK)
        self.frame.connect_with_form()

    def _on_save(self, _event) -> None:
        profile = self._get_selected_profile()
        if not profile:
            return
        self.frame.store.add(profile)
        self.frame.connection_tab.reload_server_list()
        self.frame.set_status(f"Server gespeichert: {profile.name}")
