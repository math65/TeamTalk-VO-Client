from __future__ import annotations

import threading
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import List, Optional, TYPE_CHECKING

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QPushButton, QDialogButtonBox,
)
from PySide6.QtCore import Qt

from ui.models import ServerProfile
from ui_qt.call_after import call_after

if TYPE_CHECKING:
    from app_qt import MainWindow

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


class ServerBrowserDialog(QDialog):
    """Öffentliche Serverliste von bearware.dk abrufen und verbinden/speichern."""

    def __init__(self, parent: "MainWindow") -> None:
        super().__init__(parent)
        self._window = parent
        self._servers: List[_PublicServer] = []

        self.setWindowTitle("Öffentliche Serverliste (bearware.dk)")
        self.setMinimumWidth(680)
        self.resize(720, 520)

        layout = QVBoxLayout(self)

        self._status_lbl = QLabel("Serverliste wird abgerufen…")
        layout.addWidget(self._status_lbl)

        self._list = QListWidget()
        self._list.setAccessibleName("Öffentliche Server")
        self._list.currentRowChanged.connect(self._on_selection)
        self._list.itemActivated.connect(self._on_connect)
        layout.addWidget(self._list, 1)

        self._detail_lbl = QLabel("")
        self._detail_lbl.setWordWrap(True)
        self._detail_lbl.setAccessibleName("Serverdetails")
        layout.addWidget(self._detail_lbl)

        btn_row = QHBoxLayout()
        self._connect_btn = QPushButton("&Verbinden")
        self._connect_btn.setAccessibleName("Mit ausgewähltem Server verbinden")
        self._connect_btn.setEnabled(False)
        self._connect_btn.clicked.connect(self._on_connect)

        self._save_btn = QPushButton("In Liste &speichern")
        self._save_btn.setAccessibleName("Server in eigene Serverliste speichern")
        self._save_btn.setEnabled(False)
        self._save_btn.clicked.connect(self._on_save)

        self._reload_btn = QPushButton("&Aktualisieren")
        self._reload_btn.setAccessibleName("Serverliste neu abrufen")
        self._reload_btn.clicked.connect(self._fetch)

        close_btn = QPushButton("&Schließen")
        close_btn.clicked.connect(self.reject)

        btn_row.addWidget(self._connect_btn)
        btn_row.addWidget(self._save_btn)
        btn_row.addWidget(self._reload_btn)
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        self._fetch()

    def _fetch(self) -> None:
        self._status_lbl.setText("Serverliste wird abgerufen…")
        self._list.clear()
        self._servers.clear()
        self._connect_btn.setEnabled(False)
        self._save_btn.setEnabled(False)
        self._detail_lbl.setText("")
        threading.Thread(target=self._fetch_worker, daemon=True).start()

    def _fetch_worker(self) -> None:
        try:
            servers = _fetch_server_list()
            call_after(lambda: self._on_fetch_done(servers, None))
        except Exception as exc:
            call_after(lambda e=str(exc): self._on_fetch_done([], e))

    def _on_fetch_done(self, servers: List[_PublicServer], error: Optional[str]) -> None:
        if error:
            self._status_lbl.setText(f"Fehler beim Abrufen: {error}")
            return
        self._servers = servers
        if not servers:
            self._status_lbl.setText("Keine Server gefunden.")
            return
        self._status_lbl.setText(f"{len(servers)} Server gefunden.")
        for s in servers:
            enc = " [verschlüsselt]" if s.encrypted else ""
            country = f" [{s.country}]" if s.country else ""
            self._list.addItem(f"{s.name}{country}{enc}, {s.users} Nutzer")

    def _on_selection(self, row: int) -> None:
        if row < 0 or row >= len(self._servers):
            self._connect_btn.setEnabled(False)
            self._save_btn.setEnabled(False)
            self._detail_lbl.setText("")
            return
        srv = self._servers[row]
        enc = "Ja" if srv.encrypted else "Nein"
        parts = [f"Host: {srv.host}", f"Port: {srv.tcp_port}", f"Verschlüsselt: {enc}"]
        if srv.version:
            parts.append(f"Version: {srv.version}")
        detail = ", ".join(parts)
        if srv.motd:
            detail += f"\nMOTD: {srv.motd}"
        self._detail_lbl.setText(detail)
        self._connect_btn.setEnabled(True)
        self._save_btn.setEnabled(True)

    def _get_selected_profile(self) -> Optional[ServerProfile]:
        row = self._list.currentRow()
        if row < 0 or row >= len(self._servers):
            return None
        srv = self._servers[row]
        try:
            nick = self._window.settings_store.settings.nickname or "VoiceOverUser"
        except Exception:
            nick = "VoiceOverUser"
        return ServerProfile(
            name=srv.name,
            host=srv.host,
            tcp_port=srv.tcp_port,
            udp_port=srv.udp_port,
            nickname=nick,
            username="guest",
            password="",
            client_name="TeamTalk VO",
            encrypted=srv.encrypted,
        )

    def _on_connect(self) -> None:
        profile = self._get_selected_profile()
        if not profile:
            return
        self.accept()
        self._window.connect_to_server(profile)

    def _on_save(self) -> None:
        profile = self._get_selected_profile()
        if not profile:
            return
        self._window.server_store.add(profile)
        self._window.set_status(f"Server gespeichert: {profile.name}")
