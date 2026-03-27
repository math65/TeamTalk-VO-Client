"""Thin wrapper für Kanalpasswort-Speicherung in der Betriebssystem-Keychain.

Nutzt die `keyring`-Bibliothek (falls verfügbar). Alle Operationen schlagen
lautlos fehl, damit fehlende keyring-Installation keinen App-Absturz verursacht.
"""
from __future__ import annotations

from typing import Optional

_SERVICE = "TeamTalkVOClient"


def _kr():
    """Gibt keyring-Modul oder None zurück."""
    try:
        import keyring
        return keyring
    except ImportError:
        return None


def _account_key(server_key: str, channel_id: int) -> str:
    return f"{server_key}::{channel_id}"


def save_channel_password(server_key: str, channel_id: int, password: str) -> bool:
    """Speichert Kanalpasswort in Keychain. Gibt True bei Erfolg zurück."""
    kr = _kr()
    if kr is None or not password:
        return False
    try:
        kr.set_password(_SERVICE, _account_key(server_key, channel_id), password)
        return True
    except Exception:
        return False


def get_channel_password(server_key: str, channel_id: int) -> Optional[str]:
    """Liest Kanalpasswort aus Keychain. Gibt None zurück wenn nicht gespeichert."""
    kr = _kr()
    if kr is None:
        return None
    try:
        return kr.get_password(_SERVICE, _account_key(server_key, channel_id))
    except Exception:
        return None


def delete_channel_password(server_key: str, channel_id: int) -> None:
    """Löscht Kanalpasswort aus Keychain."""
    kr = _kr()
    if kr is None:
        return
    try:
        kr.delete_password(_SERVICE, _account_key(server_key, channel_id))
    except Exception:
        pass
