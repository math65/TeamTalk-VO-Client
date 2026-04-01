"""PlatformInfo – Plattform-Release Metadaten.

Stellt konsistente Versionsinformationen, Feature-Flags und
Plattform-Capabilities für die gesamte App bereit.
"""
from __future__ import annotations

import platform
import sys
from typing import Dict, List

from i18n import _, current_language


APP_NAME = "TeamTalk VoiceOver Client"
APP_VERSION = "6.2.0"
APP_CODENAME = "Libero"
APP_AUTHOR = "Florian Lichteblau (Flarion)"
APP_URL = "https://git.garogaming.xyz/flarion/TeamTalk-VO-Client"
APP_LICENSE = "MIT"

# Minimum macOS-Version für alle v6 Features
MIN_MACOS_VERSION = (11, 0)


def platform_info() -> Dict:
    """Gibt Plattform-Informationen zurück."""
    uname = platform.uname()
    return {
        "app_name": APP_NAME,
        "app_version": APP_VERSION,
        "codename": APP_CODENAME,
        "python_version": sys.version.split()[0],
        "platform": uname.system,
        "platform_version": uname.release,
        "machine": uname.machine,
    }


def capabilities() -> Dict[str, bool]:
    """Gibt verfügbare Plattform-Features zurück.

    Jede Capability gibt an, ob das Feature auf der aktuellen Plattform
    verfügbar ist.
    """
    is_mac = sys.platform == "darwin"
    has_objc = _has_module("objc")
    has_keyring = _has_module("keyring")
    has_anthropic = _has_module("anthropic")
    has_google_ai = _has_module("google.generativeai")
    has_wx = _has_module("wx")

    return {
        "platform_macos": is_mac,
        "voiceover": is_mac and has_objc,
        "native_notifications": is_mac,
        "dock_badge": is_mac,
        "dark_mode_detection": is_mac,
        "keychain": has_keyring,
        "ai_claude": has_anthropic,
        "ai_gemini": has_google_ai,
        "ai_ollama": True,  # Ollama via localhost – immer versuchbar
        "companion_server": True,
        "plugin_marketplace": True,
        "multi_server": True,
        "analytics": True,
        "health_check": True,
        "tls_fingerprint": True,
        "audit_log": True,
    }


def _has_module(name: str) -> bool:
    import importlib.util
    try:
        return importlib.util.find_spec(name.split(".")[0]) is not None
    except Exception:
        return False


def feature_summary(lang: str | None = None) -> str:
    """Gibt einen lesbaren Feature-Status-Bericht zurück."""
    effective_lang = lang or current_language()
    caps = capabilities()
    info = platform_info()
    lines = [
        f"{APP_NAME} v{APP_VERSION} '{APP_CODENAME}'",
        f"{_('Plattform', effective_lang)}: {info['platform']} {info['platform_version']} ({info['machine']})",
        f"{_('Python', effective_lang)}: {info['python_version']}",
        "",
        f"{_('Feature-Status', effective_lang)}:",
    ]
    labels = {
        "platform_macos": _("macOS", effective_lang),
        "voiceover": _("VoiceOver/Braille", effective_lang),
        "native_notifications": _("Native Benachrichtigungen", effective_lang),
        "dock_badge": _("Dock-Badge", effective_lang),
        "keychain": _("Keychain", effective_lang),
        "ai_claude": _("KI: Claude", effective_lang),
        "ai_gemini": _("KI: Gemini", effective_lang),
        "ai_ollama": _("KI: Ollama", effective_lang),
        "companion_server": _("Companion-Server", effective_lang),
        "plugin_marketplace": _("Plugin-Marktplatz", effective_lang),
        "multi_server": _("Multi-Server", effective_lang),
        "analytics": _("Analytics", effective_lang),
        "health_check": _("Health-Check", effective_lang),
        "tls_fingerprint": _("TLS-Fingerprint", effective_lang),
        "audit_log": _("Audit-Log", effective_lang),
    }
    for key, label in labels.items():
        icon = "✓" if caps.get(key, False) else "✗"
        lines.append(f"  {icon} {label}")
    return "\n".join(lines)


def version_tuple() -> tuple:
    """Gibt die Version als (major, minor, patch) Tupel zurück."""
    parts = APP_VERSION.split(".")
    return tuple(int(p) for p in parts)


def is_newer_than(version_str: str) -> bool:
    """Gibt True zurück wenn die App-Version neuer als ``version_str`` ist."""
    try:
        other = tuple(int(p) for p in version_str.split(".")[:3])
        return version_tuple() > other
    except Exception:
        return False
