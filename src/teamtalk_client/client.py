from __future__ import annotations

import ctypes
import ipaddress
import socket
import time
import threading
from dataclasses import dataclass
from typing import Any, Callable, List, Optional, Tuple

from .tt import load_teamtalk_module

TTMessage = Any



@dataclass
class ConnectResult:
    ok: bool
    message: str


class TeamTalkClient:
    def __init__(self) -> None:
        self.tt = load_teamtalk_module()
        self.client = self.tt.TeamTalk()
        self._connect_lock = threading.Lock()
        self._event_thread: Optional[threading.Thread] = None
        self._event_stop = threading.Event()
        self._last_connect: Optional[Tuple[str, int, int, str, str, str, str, bool, Optional[bool], bool]] = None
        self._last_transport_encrypted: Optional[bool] = None
        self._connected = False
        self._last_encryption_context_info = "ctx=none"

    def _timestamp_ms(self) -> int:
        return int(round(time.time() * 1000))

    def _wait_for_event(self, event, timeout_ms: int) -> Tuple[bool, "TTMessage"]:
        end = self._timestamp_ms() + timeout_ms
        msg = self.client.getMessage(timeout_ms)
        while msg.nClientEvent != event:
            if self._timestamp_ms() >= end:
                return False, self.tt.TTMessage()
            msg = self.client.getMessage(timeout_ms)
        return True, msg

    def _wait_for_events(self, events, timeout_ms: int) -> Tuple[bool, "TTMessage"]:
        end = self._timestamp_ms() + timeout_ms
        msg = self.client.getMessage(timeout_ms)
        while msg.nClientEvent not in events:
            if self._timestamp_ms() >= end:
                return False, self.tt.TTMessage()
            msg = self.client.getMessage(timeout_ms)
        return True, msg

    def _wait_for_cmd_success(self, cmdid: int, timeout_ms: int) -> Tuple[bool, "TTMessage"]:
        result = True
        while result:
            result, msg = self._wait_for_event(self.tt.ClientEvent.CLIENTEVENT_CMD_SUCCESS, timeout_ms)
            if result and msg.nSource == cmdid:
                return result, msg
        return False, self.tt.TTMessage()

    def _wait_for_cmd_result(self, cmdid: int, timeout_ms: int) -> Tuple[bool, "TTMessage"]:
        end = self._timestamp_ms() + timeout_ms
        while self._timestamp_ms() < end:
            msg = self.client.getMessage(timeout_ms)
            if msg.nClientEvent == self.tt.ClientEvent.CLIENTEVENT_CMD_SUCCESS and msg.nSource == cmdid:
                return True, msg
            if msg.nClientEvent == self.tt.ClientEvent.CLIENTEVENT_CMD_ERROR and msg.nSource == cmdid:
                return False, msg
        return False, self.tt.TTMessage()

    def _drain_message_queue(self, max_messages: int = 200) -> None:
        """Drop stale SDK events before starting a new connect sequence."""
        for _ in range(max_messages):
            msg = self.client.getMessage(0)
            if msg.nClientEvent == self.tt.ClientEvent.CLIENTEVENT_NONE:
                break

    def _build_connect_hosts(self, host: str) -> List[str]:
        """Return host candidates, including resolved IPs for DNS fallback."""
        candidates: List[str] = [host]
        try:
            ipaddress.ip_address(host)
            return candidates
        except ValueError:
            pass
        try:
            infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
            for info in infos:
                ip = info[4][0]
                if ip and ip not in candidates:
                    candidates.append(ip)
        except Exception:
            pass
        return candidates

    def _disconnect_and_drain(self) -> None:
        try:
            self.client.disconnect()
        except Exception:
            pass
        self._connected = False
        self._drain_message_queue()

    def _recreate_client(self) -> None:
        try:
            self.client.closeTeamTalk()
        except Exception:
            pass
        self.client = self.tt.TeamTalk()
        self._connected = False
        self._drain_message_queue()

    def _apply_encryption_context(
        self,
        encrypted: bool,
        verify_peer: Optional[bool] = None,
        tls_has_custom_material: bool = False,
        force_default_context: bool = False,
    ) -> None:
        try:
            if encrypted:
                effective_verify_peer = bool(verify_peer) if verify_peer is not None else False
                should_apply_context = effective_verify_peer or tls_has_custom_material or force_default_context
                if not should_apply_context:
                    self._last_encryption_context_info = (
                        "ctx=encrypted skipped verify_peer=False custom_material=False"
                    )
                    return
                ctx = self.tt.EncryptionContext()
                ctx.bVerifyPeer = effective_verify_peer
                ctx.bVerifyClientOnce = False
                ctx.nVerifyDepth = 1 if effective_verify_peer else 0
                applied = self.client.setEncryptionContext(ctx)
                self._last_encryption_context_info = (
                    f"ctx=encrypted verify_peer={effective_verify_peer} "
                    f"custom_material={tls_has_custom_material} "
                    f"forced_default={force_default_context} "
                    f"verify_client_once=False depth={ctx.nVerifyDepth} applied={bool(applied)}"
                )
            else:
                # Clear any leftover TLS verification context before plain connect.
                applied = self.client.setEncryptionContext(self.tt.EncryptionContext())
                self._last_encryption_context_info = f"ctx=plain reset applied={bool(applied)}"
        except Exception as exc:
            self._last_encryption_context_info = f"ctx=error {exc}"

    def _connect_transport(
        self,
        host: str,
        tcp_port: int,
        udp_port: int,
        encrypted: bool,
        timeout_ms: int,
        verify_peer: Optional[bool] = None,
        tls_has_custom_material: bool = False,
        force_default_tls_context: bool = False,
    ) -> ConnectResult:
        self._apply_encryption_context(
            encrypted,
            verify_peer=verify_peer,
            tls_has_custom_material=tls_has_custom_material,
            force_default_context=force_default_tls_context,
        )
        if not self.client.connect(self.tt.ttstr(host), tcp_port, udp_port, 0, 0, encrypted):
            detail = self._get_connect_start_error_detail()
            if detail:
                return ConnectResult(False, f"Verbindung konnte nicht gestartet werden: {detail} ({self._last_encryption_context_info})")
            return ConnectResult(False, f"Verbindung konnte nicht gestartet werden ({self._last_encryption_context_info})")

        ok, msg = self._wait_for_events(
            (
                self.tt.ClientEvent.CLIENTEVENT_CON_SUCCESS,
                self.tt.ClientEvent.CLIENTEVENT_CON_FAILED,
                self.tt.ClientEvent.CLIENTEVENT_CON_CRYPT_ERROR,
            ),
            timeout_ms,
        )
        if not ok:
            return ConnectResult(False, f"Verbindung fehlgeschlagen ({self._last_encryption_context_info})")
        if msg.nClientEvent == self.tt.ClientEvent.CLIENTEVENT_CON_FAILED:
            detail = self._message_error_detail(msg)
            if detail:
                return ConnectResult(False, f"Verbindung fehlgeschlagen: {detail} ({self._last_encryption_context_info})")
            return ConnectResult(False, f"Verbindung fehlgeschlagen ({self._last_encryption_context_info})")
        if msg.nClientEvent == self.tt.ClientEvent.CLIENTEVENT_CON_CRYPT_ERROR:
            detail = self._message_error_detail(msg)
            if detail:
                return ConnectResult(False, f"Verschluesselungsfehler: {detail} ({self._last_encryption_context_info})")
            return ConnectResult(False, f"Verschluesselungsfehler ({self._last_encryption_context_info})")
        return ConnectResult(True, "ok")

    def _get_connect_start_error_detail(self, timeout_ms: int = 400) -> str:
        """Try to extract immediate SDK error details right after connect() returned false."""
        end = self._timestamp_ms() + timeout_ms
        while self._timestamp_ms() < end:
            msg = self.client.getMessage(50)
            event = msg.nClientEvent
            if event == self.tt.ClientEvent.CLIENTEVENT_NONE:
                continue
            if event == self.tt.ClientEvent.CLIENTEVENT_CON_CRYPT_ERROR:
                return "Verschluesselungsfehler"
            if event == self.tt.ClientEvent.CLIENTEVENT_CON_FAILED:
                return "Verbindung fehlgeschlagen"
            if event in (
                self.tt.ClientEvent.CLIENTEVENT_INTERNAL_ERROR,
                self.tt.ClientEvent.CLIENTEVENT_CMD_ERROR,
            ):
                try:
                    err_no = int(getattr(msg.clienterrormsg, "nErrorNo", 0) or 0)
                    err_text = self.tt.ttstr(getattr(msg.clienterrormsg, "szErrorMsg", "")).strip()
                except Exception:
                    err_no = 0
                    err_text = ""
                if err_text and err_no:
                    return f"{err_text} (Fehler {err_no})"
                if err_text:
                    return err_text
                if err_no:
                    return f"Fehler {err_no}"
        return ""

    def _message_error_detail(self, msg) -> str:
        try:
            err_no = int(getattr(msg.clienterrormsg, "nErrorNo", 0) or 0)
            err_text = self.tt.ttstr(getattr(msg.clienterrormsg, "szErrorMsg", "")).strip()
        except Exception:
            err_no = 0
            err_text = ""
        if err_text and err_no:
            return f"{err_text} (Fehler {err_no})"
        if err_text:
            return err_text
        if err_no:
            return f"Fehler {err_no}"
        return ""

    def connect_and_login(
        self,
        host: str,
        tcp_port: int,
        udp_port: int,
        nickname: str,
        username: str,
        password: str,
        client_name: str,
        encrypted: bool = False,
        verify_peer: Optional[bool] = None,
        tls_has_custom_material: bool = False,
        remember_last_connect: bool = True,
        timeout_ms: int = 8000,
    ) -> ConnectResult:
        with self._connect_lock:
            if remember_last_connect:
                self._last_connect = (
                    host,
                    tcp_port,
                    udp_port,
                    nickname,
                    username,
                    password,
                    client_name,
                    encrypted,
                    verify_peer,
                    tls_has_custom_material,
                )
            hosts_to_try = self._build_connect_hosts(host)
            attempt_log: List[str] = []

            transport_result = ConnectResult(False, "Verbindung fehlgeschlagen")
            for connect_host in hosts_to_try:
                # Fresh SDK instance per host to avoid TLS/transport residue.
                self._recreate_client()
                transport_result = self._connect_transport(
                    connect_host,
                    tcp_port,
                    udp_port,
                    encrypted,
                    timeout_ms,
                    verify_peer=verify_peer,
                    tls_has_custom_material=tls_has_custom_material,
                )
                attempt_log.append(f"{connect_host}:{tcp_port}/{udp_port} -> {transport_result.message}")
                if not transport_result.ok:
                    # Second attempt: full SDK client re-init to recover from poisoned TLS/connect state.
                    self._recreate_client()
                    transport_result = self._connect_transport(
                        connect_host,
                        tcp_port,
                        udp_port,
                        encrypted,
                        timeout_ms,
                        verify_peer=verify_peer,
                        tls_has_custom_material=tls_has_custom_material,
                    )
                    attempt_log.append(f"{connect_host}:{tcp_port}/{udp_port} reinit -> {transport_result.message}")
                if not transport_result.ok and encrypted and not tls_has_custom_material and verify_peer is not True:
                    # Additional encrypted fallback: force a default TLS context in case
                    # servers require explicit context setup.
                    self._recreate_client()
                    transport_result = self._connect_transport(
                        connect_host,
                        tcp_port,
                        udp_port,
                        encrypted,
                        timeout_ms,
                        verify_peer=verify_peer,
                        tls_has_custom_material=tls_has_custom_material,
                        force_default_tls_context=True,
                    )
                    attempt_log.append(f"{connect_host}:{tcp_port}/{udp_port} forced-ctx -> {transport_result.message}")
                if not transport_result.ok and encrypted and udp_port > 0:
                    # Third attempt for encrypted sessions: TCP-only fallback.
                    self._recreate_client()
                    transport_result = self._connect_transport(
                        connect_host,
                        tcp_port,
                        0,
                        encrypted,
                        timeout_ms,
                        verify_peer=verify_peer,
                        tls_has_custom_material=tls_has_custom_material,
                    )
                    attempt_log.append(f"{connect_host}:{tcp_port}/0 tcp-only -> {transport_result.message}")
                if not transport_result.ok and not encrypted and udp_port > 0:
                    # TCP-only fallback for plain sessions in case UDP is blocked.
                    self._recreate_client()
                    transport_result = self._connect_transport(
                        connect_host,
                        tcp_port,
                        0,
                        encrypted,
                        timeout_ms,
                        verify_peer=verify_peer,
                        tls_has_custom_material=tls_has_custom_material,
                    )
                    attempt_log.append(f"{connect_host}:{tcp_port}/0 tcp-only -> {transport_result.message}")
                if transport_result.ok:
                    self._last_transport_encrypted = encrypted
                    break
            if not transport_result.ok and not encrypted:
                # Some servers require TLS even if the entry is stored as plain.
                self._recreate_client()
                tls_result = self._connect_transport(
                    hosts_to_try[0],
                    tcp_port,
                    udp_port,
                    True,
                    timeout_ms,
                    verify_peer=verify_peer,
                    tls_has_custom_material=tls_has_custom_material,
                )
                attempt_log.append(f"{hosts_to_try[0]}:{tcp_port}/{udp_port} tls-fallback -> {tls_result.message}")
                if not tls_result.ok and udp_port > 0:
                    self._recreate_client()
                    tls_result = self._connect_transport(
                        hosts_to_try[0],
                        tcp_port,
                        0,
                        True,
                        timeout_ms,
                        verify_peer=verify_peer,
                        tls_has_custom_material=tls_has_custom_material,
                    )
                    attempt_log.append(f"{hosts_to_try[0]}:{tcp_port}/0 tls-fallback tcp-only -> {tls_result.message}")
                if tls_result.ok:
                    self._last_transport_encrypted = True
                    encrypted = True
                    transport_result = tls_result

            if not transport_result.ok:
                attempts_text = " | ".join(attempt_log[:8])
                if attempts_text:
                    return ConnectResult(False, f"{transport_result.message} | {attempts_text}")
                return transport_result

            cmdid = self.client.doLogin(
                self.tt.ttstr(nickname),
                self.tt.ttstr(username),
                self.tt.ttstr(password),
                self.tt.ttstr(client_name),
            )

            ok, msg = self._wait_for_cmd_result(cmdid, timeout_ms)
            if not ok:
                self._disconnect_and_drain()
                if msg.nClientEvent == self.tt.ClientEvent.CLIENTEVENT_CMD_ERROR:
                    err = self.tt.ttstr(msg.clienterrormsg.szErrorMsg)
                    return ConnectResult(False, f"Login fehlgeschlagen: {err}")
                return ConnectResult(False, "Server antwortet nicht auf Login")

            # We already have CMD_SUCCESS for login; MYSELF_LOGGEDIN may arrive slightly later.
            self._wait_for_event(self.tt.ClientEvent.CLIENTEVENT_CMD_MYSELF_LOGGEDIN, min(3000, timeout_ms))
            self._connected = True
            return ConnectResult(True, f"Eingeloggt in Kanal: {self.tt.ttstr(msg.channel.szName)}")

    def join_root_channel(self, timeout_ms: int = 2000) -> ConnectResult:
        cmdid = self.client.doJoinChannelByID(self.client.getRootChannelID(), self.tt.ttstr(""))
        ok, _ = self._wait_for_cmd_success(cmdid, timeout_ms)
        if not ok:
            return ConnectResult(False, "Kanalbeitritt fehlgeschlagen")
        return ConnectResult(True, "Kanalbeitritt erfolgreich")

    def join_channel_by_id(self, channel_id: int, password: str = "", timeout_ms: int = 2000) -> ConnectResult:
        cmdid = self.client.doJoinChannelByID(channel_id, self.tt.ttstr(password))
        ok, msg = self._wait_for_cmd_result(cmdid, timeout_ms)
        if not ok:
            if msg.nClientEvent == self.tt.ClientEvent.CLIENTEVENT_CMD_ERROR:
                err = self.tt.ttstr(msg.clienterrormsg.szErrorMsg)
                return ConnectResult(False, f"Kanalbeitritt fehlgeschlagen: {err}")
            if msg.nClientEvent == self.tt.ClientEvent.CLIENTEVENT_NONE:
                return ConnectResult(False, "Kanalbeitritt fehlgeschlagen: Timeout")
            return ConnectResult(False, "Kanalbeitritt fehlgeschlagen")
        return ConnectResult(True, "Kanalbeitritt erfolgreich")

    def join_channel_by_path(self, path: str, password: str = "", timeout_ms: int = 4000) -> ConnectResult:
        normalized = path.strip()
        normalized = normalized.strip()
        if not normalized.startswith("/"):
            normalized = "/" + normalized
        alt_normalized = normalized
        if alt_normalized.endswith("/") and len(alt_normalized) > 1:
            alt_normalized = alt_normalized[:-1]

        segments = [seg for seg in alt_normalized.split("/") if seg]
        if not segments:
            return ConnectResult(False, "Ungueltiger Kanalpfad")

        current_path = ""
        parent_id = self.get_root_channel_id()
        for idx, segment in enumerate(segments):
            current_path += "/" + segment
            candidates = [current_path, current_path + "/"]
            chan_id = 0
            for candidate in candidates:
                chan_id = self.get_channel_id_from_path(candidate)
                if chan_id:
                    break
            is_last = idx == len(segments) - 1
            if chan_id and chan_id > 0:
                if is_last:
                    return self.join_channel_by_id(chan_id, password=password, timeout_ms=timeout_ms)
                if self.get_my_channel_id() != chan_id:
                    res = self.join_channel_by_id(chan_id, password="", timeout_ms=timeout_ms)
                    if not res.ok:
                        return res
                parent_id = chan_id
                continue

            ch = self.tt.Channel()
            ch.nParentID = parent_id
            ch.szName = self.tt.ttstr(segment)
            if is_last and password:
                ch.szPassword = self.tt.ttstr(password)
                ch.bPassword = True

            cmdid = self.client.doJoinChannel(ch)
            ok, msg = self._wait_for_cmd_result(cmdid, timeout_ms)
            if not ok:
                if msg.nClientEvent == self.tt.ClientEvent.CLIENTEVENT_CMD_ERROR:
                    err = self.tt.ttstr(msg.clienterrormsg.szErrorMsg)
                    return ConnectResult(False, f"Kanalbeitritt fehlgeschlagen: {err}")
                if msg.nClientEvent == self.tt.ClientEvent.CLIENTEVENT_NONE:
                    return ConnectResult(False, "Kanalbeitritt fehlgeschlagen: Timeout")
                return ConnectResult(False, "Kanalbeitritt fehlgeschlagen")

            if is_last:
                return ConnectResult(True, "Kanalbeitritt erfolgreich")

            parent_id = self.get_my_channel_id()

        return ConnectResult(False, "Kanalbeitritt fehlgeschlagen")

    def make_channel(
        self,
        name: str,
        parent_id: int,
        topic: str = "",
        password: str = "",
        permanent: bool = False,
        channel_type: Optional[int] = None,
        audio_codec: Optional[Any] = None,
        disk_quota: Optional[int] = None,
        max_users: Optional[int] = None,
        op_password: str = "",
        timeout_ms: int = 4000,
    ) -> ConnectResult:
        ch = self.tt.Channel()
        ch.nParentID = int(parent_id)
        ch.nChannelID = 0
        ch.szName = self.tt.ttstr(name)
        ch.szTopic = self.tt.ttstr(topic)
        if password:
            ch.szPassword = self.tt.ttstr(password)
            ch.bPassword = True
        if channel_type is None:
            ch.uChannelType = (
                self.tt.ChannelType.CHANNEL_PERMANENT if permanent else self.tt.ChannelType.CHANNEL_DEFAULT
            )
        else:
            ch.uChannelType = int(channel_type)
        if audio_codec is not None:
            ch.audiocodec = audio_codec
        if disk_quota is not None:
            ch.nDiskQuota = int(disk_quota)
        if max_users is not None:
            ch.nMaxUsers = int(max_users)
        if op_password:
            ch.szOpPassword = self.tt.ttstr(op_password)
        cmdid = self.client.doMakeChannel(ch)
        ok, msg = self._wait_for_cmd_result(cmdid, timeout_ms)
        if not ok:
            if msg.nClientEvent == self.tt.ClientEvent.CLIENTEVENT_CMD_ERROR:
                err = self.tt.ttstr(msg.clienterrormsg.szErrorMsg)
                return ConnectResult(False, f"Kanal erstellen fehlgeschlagen: {err}")
            if msg.nClientEvent == self.tt.ClientEvent.CLIENTEVENT_NONE:
                return ConnectResult(False, "Kanal erstellen fehlgeschlagen: Timeout")
            return ConnectResult(False, "Kanal erstellen fehlgeschlagen")
        return ConnectResult(True, "Kanal erstellt")

    def build_default_opus_codec(self) -> Any:
        codec = self.tt.AudioCodec()
        codec.nCodec = int(self.tt.Codec.OPUS_CODEC)
        codec.opus.nSampleRate = 48000
        codec.opus.nChannels = 1
        codec.opus.nApplication = int(self.tt.OPUS_APPLICATION_VOIP)
        codec.opus.nComplexity = 10
        codec.opus.bFEC = True
        codec.opus.bDTX = False
        codec.opus.nBitRate = 32000
        codec.opus.bVBR = True
        codec.opus.bVBRConstraint = False
        codec.opus.nTxIntervalMSec = 40
        codec.opus.nFrameSizeMSec = 0
        return codec

    def build_no_audio_codec(self) -> Any:
        codec = self.tt.AudioCodec()
        codec.nCodec = int(self.tt.Codec.NO_CODEC)
        return codec

    def build_default_speex_codec(self) -> Any:
        codec = self.tt.AudioCodec()
        codec.nCodec = int(self.tt.Codec.SPEEX_CODEC)
        codec.speex.nBandmode = 1
        codec.speex.nQuality = 4
        codec.speex.nTxIntervalMSec = 40
        codec.speex.bStereoPlayback = False
        return codec

    def build_default_speex_vbr_codec(self) -> Any:
        codec = self.tt.AudioCodec()
        codec.nCodec = int(self.tt.Codec.SPEEX_VBR_CODEC)
        codec.speex_vbr.nBandmode = 1
        codec.speex_vbr.nQuality = 4
        codec.speex_vbr.nBitRate = 0
        codec.speex_vbr.nMaxBitRate = 0
        codec.speex_vbr.bDTX = True
        codec.speex_vbr.nTxIntervalMSec = 40
        codec.speex_vbr.bStereoPlayback = False
        return codec

    def build_default_video_codec(self, bitrate_kbps: int = 256, deadline: Optional[int] = None) -> Any:
        codec = self.tt.VideoCodec()
        codec.nCodec = int(self.tt.Codec.WEBM_VP8_CODEC)
        codec.webm_vp8.nRcTargetBitrate = int(bitrate_kbps)
        codec.webm_vp8.nEncodeDeadline = int(
            deadline if deadline is not None else self.tt.WEBM_VPX_DL_REALTIME
        )
        return codec

    def make_temporary_channel(
        self,
        name: str,
        parent_id: int,
        topic: str = "",
        password: str = "",
        channel_type: Optional[int] = None,
        audio_codec: Optional[Any] = None,
        timeout_ms: int = 4000,
    ) -> ConnectResult:
        ch = self.tt.Channel()
        ch.nParentID = int(parent_id)
        ch.nChannelID = 0
        ch.szName = self.tt.ttstr(name)
        ch.szTopic = self.tt.ttstr(topic)
        if password:
            ch.szPassword = self.tt.ttstr(password)
            ch.bPassword = True
        if channel_type is not None:
            ch.uChannelType = int(channel_type)
        if audio_codec is not None:
            ch.audiocodec = audio_codec
        cmdid = self.client.doJoinChannel(ch)
        ok, msg = self._wait_for_cmd_result(cmdid, timeout_ms)
        if not ok:
            if msg.nClientEvent == self.tt.ClientEvent.CLIENTEVENT_CMD_ERROR:
                err = self.tt.ttstr(msg.clienterrormsg.szErrorMsg)
                return ConnectResult(False, f"Kanal erstellen fehlgeschlagen: {err}")
            if msg.nClientEvent == self.tt.ClientEvent.CLIENTEVENT_NONE:
                return ConnectResult(False, "Kanal erstellen fehlgeschlagen: Timeout")
            return ConnectResult(False, "Kanal erstellen fehlgeschlagen")
        return ConnectResult(True, "Kanal erstellt (temporaer)")

    def update_channel(self, channel, timeout_ms: int = 4000) -> ConnectResult:
        cmdid = self.client.doUpdateChannel(channel)
        ok, msg = self._wait_for_cmd_result(cmdid, timeout_ms)
        if not ok:
            if msg.nClientEvent == self.tt.ClientEvent.CLIENTEVENT_CMD_ERROR:
                err = self.tt.ttstr(msg.clienterrormsg.szErrorMsg)
                return ConnectResult(False, f"Kanal aktualisieren fehlgeschlagen: {err}")
            if msg.nClientEvent == self.tt.ClientEvent.CLIENTEVENT_NONE:
                return ConnectResult(False, "Kanal aktualisieren fehlgeschlagen: Timeout")
            return ConnectResult(False, "Kanal aktualisieren fehlgeschlagen")
        return ConnectResult(True, "Kanal aktualisiert")

    def remove_channel(self, channel_id: int, timeout_ms: int = 4000) -> ConnectResult:
        cmdid = self.client.doRemoveChannel(int(channel_id))
        ok, msg = self._wait_for_cmd_result(cmdid, timeout_ms)
        if not ok:
            if msg.nClientEvent == self.tt.ClientEvent.CLIENTEVENT_CMD_ERROR:
                err = self.tt.ttstr(msg.clienterrormsg.szErrorMsg)
                return ConnectResult(False, f"Kanal löschen fehlgeschlagen: {err}")
            if msg.nClientEvent == self.tt.ClientEvent.CLIENTEVENT_NONE:
                return ConnectResult(False, "Kanal löschen fehlgeschlagen: Timeout")
            return ConnectResult(False, "Kanal löschen fehlgeschlagen")
        return ConnectResult(True, "Kanal geloescht")

    def leave_channel(self, timeout_ms: int = 2000) -> ConnectResult:
        cmdid = self.client.doLeaveChannel()
        ok, _ = self._wait_for_cmd_success(cmdid, timeout_ms)
        if not ok:
            return ConnectResult(False, "Kanal verlassen fehlgeschlagen")
        return ConnectResult(True, "Kanal verlassen")

    def logout(self, timeout_ms: int = 2000) -> ConnectResult:
        cmdid = self.client.doLogout()
        ok, _ = self._wait_for_cmd_success(cmdid, timeout_ms)
        if not ok:
            return ConnectResult(False, "Logout fehlgeschlagen")
        self._connected = False
        return ConnectResult(True, "Logout erfolgreich")

    def get_server_channels(self):
        return self.client.getServerChannels()

    def get_server_users(self):
        return self.client.getServerUsers()

    def get_channel_users(self, channel_id: int):
        return self.client.getChannelUsers(channel_id)

    def get_channel(self, channel_id: int):
        return self.client.getChannel(channel_id)

    def get_channel_path(self, channel_id: int):
        return self.client.getChannelPath(channel_id)

    def get_root_channel_id(self) -> int:
        return self.client.getRootChannelID()

    def get_channel_id_from_path(self, path: str) -> int:
        return self.client.getChannelIDFromPath(self.tt.ttstr(path))

    def get_my_channel_id(self) -> int:
        return self.client.getMyChannelID()

    def restart_sound_system(self) -> bool:
        fn = getattr(self.tt, "_RestartSoundSystem", None)
        if fn:
            return fn()
        return False

    def get_sound_devices(self):
        return self.client.getSoundDevices()

    def get_default_sound_devices(self):
        return self.client.getDefaultSoundDevices()

    def init_sound_input_device(self, device_id: int) -> bool:
        return self.client.initSoundInputDevice(device_id)

    def init_sound_input_shared_device(self, sample_rate: int, channels: int, frame_size: int) -> bool:
        fn = getattr(self.tt, "_InitSoundInputSharedDevice", None)
        if not fn:
            return False
        return fn(sample_rate, channels, frame_size)

    def init_sound_output_device(self, device_id: int) -> bool:
        return self.client.initSoundOutputDevice(device_id)

    def init_sound_duplex_devices(self, input_device_id: int, output_device_id: int) -> bool:
        fn = getattr(self.tt, "_InitSoundDuplexDevices", None)
        if not fn:
            return False
        return fn(self.client._tt, input_device_id, output_device_id)

    def close_sound_input_device(self) -> bool:
        fn = getattr(self.tt, "_CloseSoundInputDevice", None)
        if not fn:
            return False
        return fn(self.client._tt)

    def close_sound_output_device(self) -> bool:
        fn = getattr(self.tt, "_CloseSoundOutputDevice", None)
        if not fn:
            return False
        return fn(self.client._tt)

    def close_sound_duplex_devices(self) -> bool:
        fn = getattr(self.tt, "_CloseSoundDuplexDevices", None)
        if not fn:
            return False
        return fn(self.client._tt)

    def enable_voice_transmission(self, enable: bool) -> bool:
        return self.client.enableVoiceTransmission(enable)

    def enable_voice_activation(self, enable: bool) -> bool:
        return self.tt._EnableVoiceActivation(self.client._tt, enable)

    def set_voice_activation_level(self, level: int) -> bool:
        return self.tt._SetVoiceActivationLevel(self.client._tt, level)

    def set_sound_input_gain(self, level: int) -> bool:
        return self.tt._SetSoundInputGainLevel(self.client._tt, level)

    def set_sound_output_volume(self, level: int) -> bool:
        return self.tt._SetSoundOutputVolume(self.client._tt, level)

    def set_sound_output_mute(self, enabled: bool) -> bool:
        return self.tt._SetSoundOutputMute(self.client._tt, bool(enabled))

    def set_user_media_storage_dir(
        self,
        user_id: int,
        folder_path: str,
        filename_vars: str,
        audio_format: int,
    ) -> bool:
        return self.client.setUserMediaStorageDir(
            int(user_id),
            self.tt.ttstr(folder_path),
            self.tt.ttstr(filename_vars),
            audio_format,
        )

    def get_video_capture_devices(self) -> List[Any]:
        max_devices = 64
        devices = (self.tt.VideoCaptureDevice * max_devices)()
        count = ctypes.c_int32(max_devices)
        ok = self.tt._GetVideoCaptureDevices(devices, ctypes.byref(count))
        if not ok:
            return []
        return list(devices)[: max(0, int(count.value))]

    def init_video_capture_device(self, device_id: str, video_format) -> bool:
        fmt = video_format if video_format is not None else self.tt.VideoFormat()
        return self.tt._InitVideoCaptureDevice(self.client._tt, self.tt.ttstr(device_id), ctypes.byref(fmt))

    def close_video_capture_device(self) -> bool:
        return self.tt._CloseVideoCaptureDevice(self.client._tt)

    def start_video_capture_transmission(self, codec=None) -> bool:
        if codec is None:
            codec = self.build_default_video_codec()
        return self.tt._StartVideoCaptureTransmission(self.client._tt, ctypes.byref(codec))

    def stop_video_capture_transmission(self) -> bool:
        return self.tt._StopVideoCaptureTransmission(self.client._tt)

    def send_channel_message(self, channel_id: int, message: str) -> bool:
        msgs = self.tt.buildTextMessage(message, self.tt.TextMsgType.MSGTYPE_CHANNEL, nChannelID=channel_id)
        ok = True
        for msg in msgs:
            ok = ok and (self.client.doTextMessage(msg) >= 0)
        return ok

    def send_user_message(self, user_id: int, message: str) -> bool:
        msgs = self.tt.buildTextMessage(message, self.tt.TextMsgType.MSGTYPE_USER, nToUserID=user_id)
        ok = True
        for msg in msgs:
            ok = ok and (self.client.doTextMessage(msg) >= 0)
        return ok

    def send_broadcast_message(self, message: str) -> bool:
        msgs = self.tt.buildTextMessage(message, self.tt.TextMsgType.MSGTYPE_BROADCAST)
        ok = True
        for msg in msgs:
            ok = ok and (self.client.doTextMessage(msg) >= 0)
        return ok

    def change_nickname(self, nickname: str) -> int:
        return self.client.doChangeNickname(self.tt.ttstr(nickname))

    def change_status(self, mode: int, message: str) -> int:
        return self.client.doChangeStatus(int(mode), self.tt.ttstr(message))

    # ------------------------------------------------------------------
    # Error & Statistics
    # ------------------------------------------------------------------

    def get_error_message(self, error_no: int) -> str:
        return self.client.getErrorMessage(error_no)

    def get_client_statistics(self) -> Any:
        stats = self.tt.ClientStatistics()
        if self.tt._GetClientStatistics(self.client._tt, ctypes.byref(stats)):
            return stats
        return None

    def do_query_server_stats(self) -> int:
        return self.client.doQueryServerStats()

    # ------------------------------------------------------------------
    # Audio Preprocessing & Effects
    # ------------------------------------------------------------------

    def set_sound_device_effects(self, agc: bool = False, denoise: bool = False, echo_cancel: bool = False) -> bool:
        if not hasattr(self.tt, "SoundDeviceEffects"):
            return False
        try:
            effects = self.tt.SoundDeviceEffects()
        except Exception:
            return False
        effects.bEnableAGC = agc
        effects.bEnableDenoise = denoise
        effects.bEnableEchoCancellation = echo_cancel
        return self.tt._SetSoundDeviceEffects(self.client._tt, ctypes.byref(effects))

    def get_sound_device_effects(self) -> Any:
        if not hasattr(self.tt, "SoundDeviceEffects"):
            return None
        try:
            effects = self.tt.SoundDeviceEffects()
        except Exception:
            return None
        if self.tt._GetSoundDeviceEffects(self.client._tt, ctypes.byref(effects)):
            return effects
        return None

    def set_sound_input_preprocess_webrtc(
        self,
        echo_cancel: bool = True,
        denoise: bool = True,
        agc: bool = True,
        gain_level: int = 0,
    ) -> bool:
        ap = self.tt.AudioPreprocessor()
        ap.nPreprocessor = self.tt.AudioPreprocessorType.WEBRTC_AUDIOPREPROCESSOR
        ap.u.webrtc.bEnable = True
        ap.u.webrtc.preamplifier.bEnable = False
        ap.u.webrtc.echocanceller.bEnable = echo_cancel
        ap.u.webrtc.noisesuppression.bEnable = denoise
        ap.u.webrtc.gaincontroller2.bEnable = agc
        if gain_level:
            ap.u.webrtc.gaincontroller2.fixeddigital.fGainDB = float(gain_level)
        return self.tt._SetSoundInputPreprocessEx(self.client._tt, ctypes.byref(ap))

    def set_sound_input_preprocess_speexdsp(
        self,
        agc: bool = True,
        denoise: bool = True,
        echo_cancel: bool = False,
        agc_gain: int = 8000,
        denoise_suppress: int = -30,
    ) -> bool:
        ap = self.tt.AudioPreprocessor()
        ap.nPreprocessor = self.tt.AudioPreprocessorType.SPEEXDSP_AUDIOPREPROCESSOR
        ap.u.speexdsp.bEnableAGC = agc
        ap.u.speexdsp.nGainLevel = agc_gain
        ap.u.speexdsp.nMaxIncDBSec = 12
        ap.u.speexdsp.nMaxDecDBSec = -40
        ap.u.speexdsp.nMaxGainDB = 30
        ap.u.speexdsp.bEnableDenoise = denoise
        ap.u.speexdsp.nMaxNoiseSuppressDB = denoise_suppress
        ap.u.speexdsp.bEnableEchoCancellation = echo_cancel
        ap.u.speexdsp.nEchoSuppress = -40
        ap.u.speexdsp.nEchoSuppressActive = -15
        return self.tt._SetSoundInputPreprocessEx(self.client._tt, ctypes.byref(ap))

    def set_sound_input_preprocess_none(self) -> bool:
        ap = self.tt.AudioPreprocessor()
        ap.nPreprocessor = self.tt.AudioPreprocessorType.NO_AUDIOPREPROCESSOR
        return self.tt._SetSoundInputPreprocessEx(self.client._tt, ctypes.byref(ap))

    # ------------------------------------------------------------------
    # VU Meter, Voice Activation, Output
    # ------------------------------------------------------------------

    def get_sound_input_level(self) -> int:
        return self.tt._GetSoundInputLevel(self.client._tt)

    def set_voice_activation_stop_delay(self, delay_ms: int) -> bool:
        return self.tt._SetVoiceActivationStopDelay(self.client._tt, delay_ms)

    def get_voice_activation_stop_delay(self) -> int:
        return self.tt._GetVoiceActivationStopDelay(self.client._tt)

    # ------------------------------------------------------------------
    # Sound Loopback
    # ------------------------------------------------------------------

    def start_sound_loopback_test(self, indev_id: int, outdev_id: int, sample_rate: int = 48000, channels: int = 1) -> int:
        ap = self.tt.AudioPreprocessor()
        ap.nPreprocessor = self.tt.AudioPreprocessorType.NO_AUDIOPREPROCESSOR
        effects = self.tt.SoundDeviceEffects()
        handle = self.tt._StartSoundLoopbackTestEx(indev_id, outdev_id, sample_rate, channels, False, ctypes.byref(ap), ctypes.byref(effects))
        return handle

    def close_sound_loopback_test(self, handle) -> bool:
        return self.tt._CloseSoundLoopbackTest(handle)

    # ------------------------------------------------------------------
    # Per-User Audio
    # ------------------------------------------------------------------

    def set_user_volume(self, user_id: int, stream_type: int, volume: int) -> bool:
        return self.tt._SetUserVolume(self.client._tt, user_id, stream_type, volume)

    def set_user_mute(self, user_id: int, stream_type: int, mute: bool) -> bool:
        return self.tt._SetUserMute(self.client._tt, user_id, stream_type, mute, 0)

    # ------------------------------------------------------------------
    # Subscriptions
    # ------------------------------------------------------------------

    def do_subscribe(self, user_id: int, subscriptions: int) -> int:
        return self.client.doSubscribe(user_id, subscriptions)

    def do_unsubscribe(self, user_id: int, subscriptions: int) -> int:
        return self.client.doUnsubscribe(user_id, subscriptions)

    # ------------------------------------------------------------------
    # Channel Operator
    # ------------------------------------------------------------------

    def do_channel_op(self, channel_id: int, user_id: int, make_op: bool) -> int:
        return self.client.doChannelOp(user_id, channel_id, make_op)

    def is_channel_operator(self, channel_id: int, user_id: int) -> bool:
        return self.tt._IsChannelOperator(self.client._tt, channel_id, user_id)

    # ------------------------------------------------------------------
    # Kick
    # ------------------------------------------------------------------

    def do_kick_user(self, user_id: int, channel_id: int) -> int:
        return self.client.doKickUser(user_id, channel_id)

    def do_channel_user_transmit(self, user_id: int, channel_id: int, stream_types: int) -> int:
        """Togglet die Sende-Erlaubnis eines Benutzers im Kanal (Sendekontrolle)."""
        return self.client.doChannelUserTransmit(int(user_id), int(channel_id), int(stream_types))

    def do_ban_user_ex(self, user_id: int, ban_types: int) -> int:
        return self.client.doBanUserEx(user_id, int(ban_types))

    def do_move_user(self, user_id: int, channel_id: int) -> int:
        return self.client.doMoveUser(int(user_id), int(channel_id))

    # ------------------------------------------------------------------
    # Recording (Muxed)
    # ------------------------------------------------------------------

    def start_recording_muxed(self, filename: str, audio_format: int) -> bool:
        codec = self.tt.AudioCodec()
        return self.tt._StartRecordingMuxedAudioFile(
            self.client._tt, ctypes.byref(codec), self.tt.ttstr(filename), audio_format
        )

    def stop_recording_muxed(self) -> bool:
        return self.tt._StopRecordingMuxedAudioFile(self.client._tt)

    # ------------------------------------------------------------------
    # Media File Streaming
    # ------------------------------------------------------------------

    def get_media_file_info(self, filepath: str) -> Any:
        info = self.tt.MediaFileInfo()
        if self.tt._GetMediaFileInfo(self.tt.ttstr(filepath), ctypes.byref(info)):
            return info
        return None

    def start_streaming_media_to_channel(self, filepath: str, offset_ms: int = 0, preamp_gain: float = 1.0) -> bool:
        playback = self.tt.MediaFilePlayback()
        playback.uOffsetMSec = offset_ms
        playback.bPaused = False
        playback.audioPreprocessor = self._build_stream_preprocessor(preamp_gain)
        codec = self.tt.VideoCodec()
        return self.tt._StartStreamingMediaFileToChannelEx(
            self.client._tt, self.tt.ttstr(filepath), ctypes.byref(playback), ctypes.byref(codec)
        )

    def update_streaming_media(self, paused: bool = False, offset_ms: Optional[int] = 0, preamp_gain: float = 1.0) -> bool:
        playback = self.tt.MediaFilePlayback()
        if offset_ms is None:
            playback.uOffsetMSec = self.tt.TT_MEDIAPLAYBACK_OFFSET_IGNORE
        else:
            playback.uOffsetMSec = offset_ms
        playback.bPaused = paused
        playback.audioPreprocessor = self._build_stream_preprocessor(preamp_gain)
        codec = self.tt.VideoCodec()
        return self.tt._UpdateStreamingMediaFileToChannel(
            self.client._tt, ctypes.byref(playback), ctypes.byref(codec)
        )

    def _build_stream_preprocessor(self, preamp_gain: float):
        ap = self.tt.AudioPreprocessor()
        ap.nPreprocessor = self.tt.AudioPreprocessorType.WEBRTC_AUDIOPREPROCESSOR
        ap.webrtc.preamplifier_bEnable = True
        ap.webrtc.preamplifier_fFixedGainFactor = float(preamp_gain)
        ap.webrtc.echocanceller_bEnable = False
        ap.webrtc.noisesuppression_bEnable = False
        ap.webrtc.gaincontroller2_bEnable = False
        return ap

    # ------------------------------------------------------------------
    # Desktop / Screen Share
    # ------------------------------------------------------------------

    def send_desktop_frame(self, width: int, height: int, bytes_per_line: int, frame: bytes) -> int:
        self._ensure_desktop_api()
        buf = ctypes.create_string_buffer(frame)
        wnd = self.tt.DesktopWindow()
        wnd.nWidth = int(width)
        wnd.nHeight = int(height)
        wnd.bmpFormat = self.tt.BitmapFormat.BMP_RGB32
        wnd.nBytesPerLine = int(bytes_per_line)
        wnd.nSessionID = 0
        wnd.nProtocol = self.tt.DesktopProtocol.DESKTOPPROTOCOL_ZLIB_1
        wnd.frameBuffer = ctypes.cast(buf, ctypes.c_void_p)
        wnd.nFrameBufferSize = int(len(frame))
        return int(self.tt._SendDesktopWindow(self.client._tt, ctypes.byref(wnd), self.tt.BitmapFormat.BMP_RGB32))

    def close_desktop_window(self) -> bool:
        self._ensure_desktop_api()
        return bool(self.tt._CloseDesktopWindow(self.client._tt))

    def send_desktop_click(self, button: str = "left") -> int:
        self._ensure_desktop_api()
        return int(self._send_desktop_click(button))

    def _ensure_desktop_api(self) -> None:
        if hasattr(self.tt, "_SendDesktopWindow"):
            return
        self.tt._SendDesktopWindow = self.tt.function_factory(
            self.tt.dll.TT_SendDesktopWindow,
            [self.tt.INT32, [self.tt._TTInstance, ctypes.POINTER(self.tt.DesktopWindow), self.tt.INT32]],
        )
        self.tt._CloseDesktopWindow = self.tt.function_factory(
            self.tt.dll.TT_CloseDesktopWindow,
            [self.tt.BOOL, [self.tt._TTInstance]],
        )
        self.tt._SendDesktopInput = self.tt.function_factory(
            self.tt.dll.TT_SendDesktopInput,
            [self.tt.BOOL, [self.tt._TTInstance, ctypes.POINTER(self.tt.DesktopInput), self.tt.INT32]],
        )

    def _send_desktop_click(self, button: str) -> bool:
        keycodes = {
            "left": 0x1000,
            "right": 0x1001,
            "middle": 0x1002,
        }
        keycode = keycodes.get(button, 0x1000)
        ignore_pos = 0xFFFF
        inputs = (self.tt.DesktopInput * 2)()
        inputs[0].uMousePosX = ignore_pos
        inputs[0].uMousePosY = ignore_pos
        inputs[0].uKeyCode = keycode
        inputs[0].uKeyState = int(self.tt.DesktopKeyState.DESKTOPKEYSTATE_DOWN)
        inputs[1].uMousePosX = ignore_pos
        inputs[1].uMousePosY = ignore_pos
        inputs[1].uKeyCode = keycode
        inputs[1].uKeyState = int(self.tt.DesktopKeyState.DESKTOPKEYSTATE_UP)
        return bool(self.tt._SendDesktopInput(self.client._tt, inputs, 2))

    # ------------------------------------------------------------------
    # Audio injection (app audio)
    # ------------------------------------------------------------------

    def insert_audio_block_bytes(self, pcm: bytes, sample_rate: int, channels: int) -> bool:
        if not pcm:
            return False
        block = self.tt.AudioBlock()
        block.nStreamID = 0
        block.nSampleRate = int(sample_rate)
        block.nChannels = int(channels)
        block.nSamples = int(len(pcm) // (2 * max(1, channels)))
        block.uSampleIndex = 0
        block.uStreamTypes = int(self.tt.StreamType.STREAMTYPE_MEDIAFILE_AUDIO)
        buf = ctypes.create_string_buffer(pcm)
        block.lpRawAudio = ctypes.cast(buf, ctypes.c_void_p)
        return bool(self.tt._InsertAudioBlock(self.client._tt, ctypes.byref(block)))

    def stop_streaming_media(self) -> bool:
        return self.tt._StopStreamingMediaFileToChannel(self.client._tt)

    # ------------------------------------------------------------------
    # File Transfer
    # ------------------------------------------------------------------

    def get_channel_files(self, channel_id: int) -> List:
        return list(self.client.getChannelFiles(channel_id))

    def send_file(self, channel_id: int, local_path: str) -> int:
        return self.client.doSendFile(channel_id, self.tt.ttstr(local_path))

    def recv_file(self, channel_id: int, file_id: int, local_path: str) -> int:
        return self.client.doRecvFile(channel_id, file_id, self.tt.ttstr(local_path))

    def delete_file(self, channel_id: int, file_id: int) -> int:
        return self.client.doDeleteFile(channel_id, file_id)

    def get_file_transfer_info(self, transfer_id: int) -> Any:
        ft = self.tt.FileTransfer()
        if self.tt._GetFileTransferInfo(self.client._tt, transfer_id, ctypes.byref(ft)):
            return ft
        return None

    def cancel_file_transfer(self, transfer_id: int) -> bool:
        return self.tt._CancelFileTransfer(self.client._tt, transfer_id)

    # ------------------------------------------------------------------
    # Admin
    # ------------------------------------------------------------------

    def do_list_user_accounts(self, offset: int = 0, count: int = 100) -> int:
        return self.client.doListUserAccounts(offset, count)

    def do_new_user_account(self, username: str, password: str, user_type: int, user_rights: int = 0, note: str = "") -> int:
        account = self.tt.UserAccount()
        account.szUsername = self.tt.ttstr(username)
        account.szPassword = self.tt.ttstr(password)
        account.uUserType = user_type
        account.uUserRights = user_rights
        account.szNote = self.tt.ttstr(note)
        return self.client.doNewUserAccount(account)

    def do_delete_user_account(self, username: str) -> int:
        return self.client.doDeleteUserAccount(self.tt.ttstr(username))

    def do_ban_user(self, channel_id: int, user_id: int) -> int:
        return self.client.doBanUser(user_id, channel_id)

    def do_unban_user(self, ip_addr: str, ban_type: int = 0) -> int:
        return self.client.doUnBanUser(self.tt.ttstr(ip_addr), ban_type)

    def do_list_bans(self, channel_id: int = 0, offset: int = 0, count: int = 100) -> int:
        return self.client.doListBans(channel_id, offset, count)

    def do_update_server(self, server_name: str = "", motd: str = "", max_users: int = 0) -> int:
        props = self.client.getServerProperties()
        if server_name:
            props.szServerName = self.tt.ttstr(server_name)
        if motd:
            props.szMOTDRaw = self.tt.ttstr(motd)
        if max_users > 0:
            props.nMaxUsers = max_users
        return self.client.doUpdateServer(props)

    def do_save_config(self) -> int:
        return self.client.doSaveConfig()

    def get_server_properties(self) -> Any:
        return self.client.getServerProperties()

    def get_my_user_type(self) -> int:
        return self.tt._GetMyUserType(self.client._tt)

    def get_my_user_rights(self) -> int:
        return int(self.tt._GetMyUserRights(self.client._tt))

    def get_my_user_id(self) -> int:
        return self.client.getMyUserID()

    def get_user(self, user_id: int) -> Any:
        return self.client.getUser(user_id)

    def start_event_loop(self, handler: Callable[["TTMessage"], None], poll_ms: int = 200) -> None:
        if self._event_thread and self._event_thread.is_alive():
            return

        self._event_stop.clear()

        def loop():
            while not self._event_stop.is_set():
                msg = self.client.getMessage(min(poll_ms, 100))
                if msg.nClientEvent == self.tt.ClientEvent.CLIENTEVENT_NONE:
                    continue
                handler(msg)

        self._event_thread = threading.Thread(target=loop, daemon=True)
        self._event_thread.start()

    def stop_event_loop(self) -> None:
        self._event_stop.set()

    def stop_event_loop_and_wait(self, timeout: float = 0.4) -> None:
        """Stop the event loop and wait for the thread to finish."""
        self._event_stop.set()
        if self._event_thread and self._event_thread.is_alive():
            self._event_thread.join(timeout)
        self._event_thread = None

    def reconnect(self, timeout_ms: int = 8000) -> ConnectResult:
        if not self._last_connect:
            return ConnectResult(False, "Keine gespeicherten Verbindungsdaten")
        return self.connect_and_login(*self._last_connect, timeout_ms=timeout_ms)

    def is_connected(self) -> bool:
        return self._connected

    def disconnect_transport(self) -> None:
        self._disconnect_and_drain()

    def close(self) -> None:
        self._connected = False
        self.stop_event_loop()
        self.client.closeTeamTalk()
