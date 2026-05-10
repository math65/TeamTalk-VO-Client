"""Thread-safe equivalent of wx.CallAfter for PySide6."""
from __future__ import annotations

import functools
from typing import Callable, Any

from PySide6.QtCore import QObject, Signal, Qt


class _Dispatcher(QObject):
    _dispatch = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._dispatch.connect(self._run, Qt.ConnectionType.QueuedConnection)

    def _run(self, fn: Callable) -> None:
        try:
            fn()
        except Exception:
            import traceback
            traceback.print_exc()


_dispatcher: _Dispatcher | None = None


def _get_dispatcher() -> _Dispatcher:
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = _Dispatcher()
    return _dispatcher


def call_after(fn: Callable, *args: Any, **kwargs: Any) -> None:
    """Schedule *fn* to run on the main Qt thread (safe from any thread)."""
    _get_dispatcher()._dispatch.emit(functools.partial(fn, *args, **kwargs))
