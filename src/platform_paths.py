"""Cross-platform path helpers for TeamTalk VO Client."""
from __future__ import annotations

import os
import sys
from pathlib import Path

_APP_NAME = "TeamTalkVOClient"


def app_data_dir() -> Path:
    """Return the per-user application data directory."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / _APP_NAME


def log_dir() -> Path:
    """Return the per-user log directory."""
    if sys.platform == "win32":
        return app_data_dir() / "Logs"
    elif sys.platform == "darwin":
        return Path.home() / "Library" / "Logs" / _APP_NAME
    else:
        return app_data_dir() / "logs"
