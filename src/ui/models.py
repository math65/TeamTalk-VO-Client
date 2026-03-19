from __future__ import annotations

import dataclasses
import json
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class ServerProfile:
    name: str
    host: str
    tcp_port: int
    udp_port: int
    nickname: str
    username: str
    password: str
    client_name: str
    encrypted: bool = False
    elevenlabs_api_key: str = ""


@dataclass
class ParsedTeamTalkFile:
    profile: ServerProfile
    channel_path: Optional[str] = None
    channel_id: Optional[int] = None
    channel_password: Optional[str] = None
    encrypted: bool = False
    join_last_channel: bool = False
    verify_peer: Optional[bool] = None
    ca_certificate_pem: str = ""
    client_certificate_pem: str = ""
    client_private_key_pem: str = ""


class FileLogger:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, line: str) -> None:
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with self.path.open("a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {line}\n")


class ServerStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._items: List[ServerProfile] = []
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            self._items = []
            return
        try:
            valid_names = {f.name for f in dataclasses.fields(ServerProfile)}
            data = json.loads(self.path.read_text(encoding="utf-8"))
            items = []
            for item in data:
                try:
                    filtered = {k: v for k, v in item.items() if k in valid_names}
                    items.append(ServerProfile(**filtered))
                except Exception:
                    continue
            self._items = items
        except Exception:
            self._items = []

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = [asdict(item) for item in self._items]
        self.path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def items(self) -> List[ServerProfile]:
        return list(self._items)

    def add(self, profile: ServerProfile) -> None:
        self._items.append(profile)
        self.save()

    def update(self, index: int, profile: ServerProfile) -> None:
        self._items[index] = profile
        self.save()

    def remove(self, index: int) -> None:
        self._items.pop(index)
        self.save()

    def import_from(self, path: Path) -> None:
        data = json.loads(path.read_text(encoding="utf-8"))
        self._items = [ServerProfile(**item) for item in data]
        self.save()

    def export_to(self, path: Path) -> None:
        data = [asdict(item) for item in self._items]
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


@dataclass
class AppSettings:
    auto_apply_audio: bool = False
    auto_apply_audio_on_device_change: bool = False
    ptt_hotkey: int = 0
    audio_prefs: Dict[str, Any] = field(default_factory=dict)
    video_device_id: str = ""
    video_format_index: int = 0
    video_bitrate_kbps: int = 256
    video_deadline: str = "realtime"
    hotkey_mute_all: int = 0
    hotkey_voice_activation: int = 0
    hotkey_video_tx: int = 0


class SettingsStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.settings = AppSettings()
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return
        if isinstance(data, dict):
            self.settings.auto_apply_audio = bool(data.get("auto_apply_audio", False))
            self.settings.auto_apply_audio_on_device_change = bool(
                data.get("auto_apply_audio_on_device_change", False)
            )
            self.settings.ptt_hotkey = int(data.get("ptt_hotkey", 0) or 0)
            prefs = data.get("audio_prefs", {})
            self.settings.audio_prefs = prefs if isinstance(prefs, dict) else {}
            self.settings.video_device_id = str(data.get("video_device_id", "") or "")
            self.settings.video_format_index = int(data.get("video_format_index", 0) or 0)
            self.settings.video_bitrate_kbps = int(data.get("video_bitrate_kbps", 256) or 256)
            self.settings.video_deadline = str(data.get("video_deadline", "realtime") or "realtime")
            self.settings.hotkey_mute_all = int(data.get("hotkey_mute_all", 0) or 0)
            self.settings.hotkey_voice_activation = int(data.get("hotkey_voice_activation", 0) or 0)
            self.settings.hotkey_video_tx = int(data.get("hotkey_video_tx", 0) or 0)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "auto_apply_audio": bool(self.settings.auto_apply_audio),
            "auto_apply_audio_on_device_change": bool(self.settings.auto_apply_audio_on_device_change),
            "ptt_hotkey": int(self.settings.ptt_hotkey or 0),
            "audio_prefs": self.settings.audio_prefs or {},
            "video_device_id": str(self.settings.video_device_id or ""),
            "video_format_index": int(self.settings.video_format_index or 0),
            "video_bitrate_kbps": int(self.settings.video_bitrate_kbps or 256),
            "video_deadline": str(self.settings.video_deadline or "realtime"),
            "hotkey_mute_all": int(self.settings.hotkey_mute_all or 0),
            "hotkey_voice_activation": int(self.settings.hotkey_voice_activation or 0),
            "hotkey_video_tx": int(self.settings.hotkey_video_tx or 0),
        }
        self.path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
