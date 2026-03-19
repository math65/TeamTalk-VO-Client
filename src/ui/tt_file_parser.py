from __future__ import annotations

import configparser
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlencode, quote
from typing import Optional

from .models import ParsedTeamTalkFile, ServerProfile


def _to_bool(value, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _to_optional_bool(value) -> Optional[bool]:
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return None


def parse_teamtalk_file(path: Path) -> Optional[ParsedTeamTalkFile]:
    data = path.read_bytes()
    for encoding in ("utf-8", "latin-1"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        return None

    text_stripped = text.strip()
    if not text_stripped:
        return None

    if text_stripped.startswith("{") or text_stripped.startswith("["):
        try:
            payload = json.loads(text_stripped)
            if isinstance(payload, list) and payload:
                payload = payload[0]
            return _profile_from_mapping(payload, path)
        except Exception:
            pass

    if "<" in text_stripped and ">" in text_stripped:
        try:
            root = ET.fromstring(text_stripped)
            if root.tag.lower() == "teamtalk" or root.find("host") is not None:
                parsed = _parse_teamtalk_xml(root, path)
                if parsed:
                    return parsed
            payload = {child.tag.lower(): (child.text or "") for child in root.iter() if child is not root}
            return _profile_from_mapping(payload, path)
        except Exception:
            pass

    try:
        parser = configparser.ConfigParser()
        if "[" not in text_stripped:
            text_stripped = "[server]\n" + text_stripped
        parser.read_string(text_stripped)
        section = parser[parser.sections()[0]] if parser.sections() else {}
        payload = {k.lower(): v for k, v in section.items()}
        return _profile_from_mapping(payload, path)
    except Exception:
        return None


def _profile_from_mapping(payload: dict, path: Path) -> Optional[ParsedTeamTalkFile]:
    def pick(*keys, default=""):
        for key in keys:
            if key in payload and str(payload[key]).strip():
                return str(payload[key]).strip()
        return default

    host = pick("host", "server", "address", "ip")
    tcp = pick("tcpport", "tcp_port", "port", default="10333")
    udp = pick("udpport", "udp_port", default="10333")
    nickname = pick("nickname", "nick", default="VoiceOverUser")
    username = pick("username", "user", default="")
    password = pick("password", "pass", default="")
    client_name = pick("clientname", "client_name", default="TeamTalk VO")
    name = pick("name", default=path.stem)

    channel_path = pick("channelpath", "channel_path", "channel") or None
    channel_id = pick("channelid", "channel_id")
    channel_id_int = int(channel_id) if channel_id.isdigit() else None
    encrypted_flag = _to_bool(
        pick("encrypted", "encryption", "tls", "ssl", "secure", default="false"),
        default=False,
    )

    verify_peer = None
    for key in ("verify-peer", "verify_peer", "verifypeer"):
        if key in payload:
            verify_peer = _to_optional_bool(payload.get(key))
            break

    if not host:
        return None
    try:
        tcp_port = int(tcp)
        udp_port = int(udp)
    except ValueError:
        return None

    profile = ServerProfile(
        name=name, host=host, tcp_port=tcp_port, udp_port=udp_port,
        nickname=nickname, username=username, password=password, client_name=client_name,
        encrypted=encrypted_flag,
    )
    return ParsedTeamTalkFile(
        profile=profile, channel_path=channel_path, channel_id=channel_id_int, encrypted=encrypted_flag,
        verify_peer=verify_peer,
    )


def _parse_teamtalk_xml(root: ET.Element, path: Path) -> Optional[ParsedTeamTalkFile]:
    host_node = root.find("host") if root.tag.lower() == "teamtalk" else root.find(".//host")
    if host_node is None:
        return None

    def text_of(node, default=""):
        if node is None or node.text is None:
            return default
        return node.text.strip()

    name = text_of(host_node.find("name"), path.stem)
    host = text_of(host_node.find("address"), "")
    tcp = text_of(host_node.find("tcpport"), "10333")
    udp = text_of(host_node.find("udpport"), "10333")

    auth = host_node.find("auth")
    username = text_of(auth.find("username") if auth is not None else None, "")
    password = text_of(auth.find("password") if auth is not None else None, "")
    nickname = text_of(auth.find("nickname") if auth is not None else None, "VoiceOverUser")

    join = host_node.find("join")
    channel_path = text_of(join.find("channel") if join is not None else None, "") or None
    channel_password = text_of(join.find("password") if join is not None else None, "") or None
    join_last_channel = text_of(join.find("join-last-channel") if join is not None else None, "false").lower() == "true"

    trusted = host_node.find("trusted-certificate")
    verify_peer = _to_optional_bool(text_of(trusted.find("verify-peer") if trusted is not None else None, ""))
    ca_certificate_pem = text_of(trusted.find("certificate-authority-pem") if trusted is not None else None, "")
    client_certificate_pem = text_of(trusted.find("client-certificate-pem") if trusted is not None else None, "")
    client_private_key_pem = text_of(trusted.find("client-private-key-pem") if trusted is not None else None, "")

    if not host:
        return None
    try:
        tcp_port = int(tcp)
        udp_port = int(udp)
    except ValueError:
        return None
    if not nickname:
        nickname = "VoiceOverUser"

    encrypted_flag = _to_bool(text_of(host_node.find("encrypted"), "false"), default=False)

    profile = ServerProfile(
        name=name or host, host=host, tcp_port=tcp_port, udp_port=udp_port,
        nickname=nickname, username=username, password=password, client_name="TeamTalk VO",
        encrypted=encrypted_flag,
    )
    return ParsedTeamTalkFile(
        profile=profile, channel_path=channel_path, channel_id=None,
        channel_password=channel_password, encrypted=encrypted_flag,
        join_last_channel=join_last_channel, verify_peer=verify_peer,
        ca_certificate_pem=ca_certificate_pem,
        client_certificate_pem=client_certificate_pem,
        client_private_key_pem=client_private_key_pem,
    )


def build_teamtalk_url(
    profile: ServerProfile,
    channel_path: Optional[str] = None,
    channel_password: Optional[str] = None,
    encrypted: Optional[bool] = None,
) -> str:
    params = {
        "tcpport": str(profile.tcp_port),
        "udpport": str(profile.udp_port),
        "encrypted": "true" if (profile.encrypted if encrypted is None else encrypted) else "false",
    }
    if profile.username:
        params["username"] = profile.username
    if profile.password:
        params["password"] = profile.password
    if channel_path:
        params["channel"] = channel_path
    if channel_password:
        params["chanpasswd"] = channel_password
    query = urlencode(params, quote_via=quote)
    return f"tt://{profile.host}?{query}"


def build_teamtalk_xml(
    profile: ServerProfile,
    channel_path: Optional[str] = None,
    channel_password: Optional[str] = None,
) -> str:
    root = ET.Element("teamtalk", {"version": "5.0"})
    host = ET.SubElement(root, "host")
    ET.SubElement(host, "name").text = profile.name or profile.host
    ET.SubElement(host, "address").text = profile.host
    ET.SubElement(host, "tcpport").text = str(profile.tcp_port)
    ET.SubElement(host, "udpport").text = str(profile.udp_port)
    ET.SubElement(host, "encrypted").text = "true" if profile.encrypted else "false"

    auth = ET.SubElement(host, "auth")
    ET.SubElement(auth, "username").text = profile.username or ""
    ET.SubElement(auth, "password").text = profile.password or ""
    ET.SubElement(auth, "nickname").text = profile.nickname or "VoiceOverUser"

    if channel_path or channel_password:
        join = ET.SubElement(host, "join")
        if channel_path:
            ET.SubElement(join, "channel").text = channel_path
        if channel_password:
            ET.SubElement(join, "password").text = channel_password

    return ET.tostring(root, encoding="utf-8", xml_declaration=True).decode("utf-8")
