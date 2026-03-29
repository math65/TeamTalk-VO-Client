"""Thin wrapper für Kanalpasswort- und API-Key-Speicherung in der Betriebssystem-Keychain.

Nutzt die `keyring`-Bibliothek (falls verfügbar). Alle Operationen schlagen
lautlos fehl, damit fehlende keyring-Installation keinen App-Absturz verursacht.

v4.9.0 – API-Key-Speicherung für claude_api_key und gemini_api_key hinzugefügt.
"""
from __future__ import annotations

from typing import Optional

_SERVICE = "TeamTalkVOClient"
_SERVICE_APIKEYS = "TeamTalkVOClient-APIKeys"


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


# ---------------------------------------------------------------------------
# v4.9.0 – API-Key-Speicherung
# ---------------------------------------------------------------------------

def save_api_key(key_name: str, api_key: str) -> bool:
    """Speichert einen API-Key sicher in der OS-Keychain.

    Args:
        key_name: Bezeichner, z. B. ``'claude_api_key'`` oder ``'gemini_api_key'``.
        api_key:  Der zu speichernde Schlüssel (darf nicht leer sein).

    Returns:
        ``True`` bei Erfolg, ``False`` wenn keyring nicht verfügbar oder Fehler.
    """
    kr = _kr()
    if kr is None or not api_key:
        return False
    try:
        kr.set_password(_SERVICE_APIKEYS, key_name, api_key)
        return True
    except Exception:
        return False


def get_api_key(key_name: str) -> Optional[str]:
    """Liest einen API-Key aus der OS-Keychain.

    Args:
        key_name: Bezeichner, z. B. ``'claude_api_key'``.

    Returns:
        Den gespeicherten Schlüssel oder ``None``.
    """
    kr = _kr()
    if kr is None:
        return None
    try:
        return kr.get_password(_SERVICE_APIKEYS, key_name)
    except Exception:
        return None


def delete_api_key(key_name: str) -> None:
    """Löscht einen API-Key aus der OS-Keychain."""
    kr = _kr()
    if kr is None:
        return
    try:
        kr.delete_password(_SERVICE_APIKEYS, key_name)
    except Exception:
        pass
