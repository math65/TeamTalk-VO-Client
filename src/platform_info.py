"""PlatformInfo – Plattform-Release Metadaten (v6.0.0).

Stellt konsistente Versionsinformationen, Feature-Flags und
Plattform-Capabilities für die gesamte App bereit.
"""
from __future__ import annotations

import platform
import sys
from typing import Dict, List


APP_NAME = "TeamTalk VoiceOver Client"
APP_VERSION = "6.0.0"
APP_CODENAME = "Libero"  # v6.0.0 Codename
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


def feature_summary() -> str:
    """Gibt einen lesbaren Feature-Status-Bericht zurück."""
    caps = capabilities()
    info = platform_info()
    lines = [
        f"{APP_NAME} v{APP_VERSION} '{APP_CODENAME}'",
        f"Plattform: {info['platform']} {info['platform_version']} ({info['machine']})",
        f"Python: {info['python_version']}",
        "",
        "Feature-Status:",
    ]
    labels = {
        "platform_macos": "macOS",
        "voiceover": "VoiceOver/Braille",
        "native_notifications": "Native Benachrichtigungen",
        "dock_badge": "Dock-Badge",
        "keychain": "Keychain",
        "ai_claude": "KI: Claude",
        "ai_gemini": "KI: Gemini",
        "ai_ollama": "KI: Ollama",
        "companion_server": "Companion-Server",
        "plugin_marketplace": "Plugin-Marktplatz",
        "multi_server": "Multi-Server",
        "analytics": "Analytics",
        "health_check": "Health-Check",
        "tls_fingerprint": "TLS-Fingerprint",
        "audit_log": "Audit-Log",
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
