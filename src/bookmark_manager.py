"""BookmarkManager – Kanal-Lesezeichen (v2.2.0).

Bis zu 9 benannte Lesezeichen mit optionalen Hotkeys.
Jedes Lesezeichen enthält: name, channel_id, server_key.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Dict, List, Optional

if TYPE_CHECKING:
    from ui.models import SettingsStore


class BookmarkManager:
    """Verwaltet Kanal-Lesezeichen und springt bei Hotkey zum Kanal."""

    MAX_BOOKMARKS = 9

    def __init__(self, settings_store: "SettingsStore") -> None:
        self._store = settings_store

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def get_all(self) -> List[Dict]:
        return list(self._store.settings.channel_bookmarks or [])

    def add(self, name: str, channel_id: int, server_key: str) -> None:
        bm = self.get_all()
        if len(bm) >= self.MAX_BOOKMARKS:
            return
        bm.append({"name": name, "channel_id": channel_id, "server_key": server_key})
        self._store.settings.channel_bookmarks = bm
        self._store.save()

    def remove(self, idx: int) -> None:
        bm = self.get_all()
        if 0 <= idx < len(bm):
            bm.pop(idx)
            self._store.settings.channel_bookmarks = bm
            self._store.save()

    def update(self, idx: int, name: str, channel_id: int, server_key: str) -> None:
        bm = self.get_all()
        if 0 <= idx < len(bm):
            bm[idx] = {"name": name, "channel_id": channel_id, "server_key": server_key}
            self._store.settings.channel_bookmarks = bm
            self._store.save()

    def get(self, idx: int) -> Optional[Dict]:
        bm = self.get_all()
        return bm[idx] if 0 <= idx < len(bm) else None

    # ------------------------------------------------------------------
    # Hotkey 1-3 sind in AppSettings als hotkey_bookmark_1/2/3 gespeichert.
    # Slot 0 = index 0 in channel_bookmarks etc.
    # ------------------------------------------------------------------

    def jump(self, frame, idx: int) -> None:
        """Springt zum Lesezeichen idx (0-basiert) wenn verbunden."""
        bm = self.get(idx)
        if bm is None:
            try:
                frame.tts.speak(f"Lesezeichen {idx + 1} nicht gesetzt", kind="system")
            except Exception:
                pass
            return
        try:
            server_key = self._store.settings.active_server_session or ""
            bm_key = bm.get("server_key", "")
            if bm_key and server_key and bm_key != server_key:
                frame.tts.speak(f"Lesezeichen {bm.get('name', '')} gehört zu anderem Server", kind="system")
                return
            chan_id = int(bm.get("channel_id", 0))
            if chan_id:
                frame.join_channel(chan_id)
                frame.tts.speak(f"Lesezeichen {bm.get('name', '')}", kind="system")
            else:
                frame.tts.speak(f"Lesezeichen {bm.get('name', '')} – Kanal-ID fehlt", kind="system")
        except Exception as exc:
            print(f"[Bookmark] Sprung fehlgeschlagen: {exc}")
