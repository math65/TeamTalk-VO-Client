from __future__ import annotations

import sys
from pathlib import Path


def ensure_teamtalk_sdk_on_path() -> None:
    here = Path(__file__).resolve()
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        sdk_py = Path(sys._MEIPASS) / "TeamTalkPy"
    else:
        root = here.parents[2]
        if sys.platform == "win32":
            sdk_py = root / "third_party" / "teamtalk" / "tt5sdk_v5.19a_win64" / "Library" / "TeamTalkPy"
        else:
            sdk_py = root / "third_party" / "teamtalk" / "tt5sdk_v5.19a_macos_universal" / "Library" / "TeamTalkPy"
    if str(sdk_py) not in sys.path:
        sys.path.insert(0, str(sdk_py))


def load_teamtalk_module():
    ensure_teamtalk_sdk_on_path()
    import importlib
    return importlib.import_module("TeamTalk5")
