"""StartupProfiler – Misst und protokolliert die App-Startphasen (v4.6.0).

Schreibt Einträge in startup.jsonl und gibt eine Zusammenfassung in stdout aus.

Verwendung::

    prof = StartupProfiler()
    with prof.phase("import_modules"):
        import wx  # ...
    with prof.phase("init_db"):
        db = SettingsDB(...)
    prof.finish()   # schreibt Gesamtzeit + JSON-Log
"""
from __future__ import annotations

import contextlib
import json
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple


class StartupProfiler:
    """Einfaches Phasen-Timing für den App-Start."""

    def __init__(self, log_path: Optional[Path] = None) -> None:
        self._start_total: float = time.perf_counter()
        self._phases: List[Tuple[str, float]] = []   # (name, duration_ms)
        self._current_phase: Optional[str] = None
        self._current_start: float = 0.0
        self._log_path = log_path

    @contextlib.contextmanager
    def phase(self, name: str):
        """Context-Manager für eine einzelne Start-Phase."""
        t0 = time.perf_counter()
        try:
            yield
        finally:
            dt_ms = (time.perf_counter() - t0) * 1000
            self._phases.append((name, dt_ms))

    def mark(self, name: str) -> None:
        """Setzt einen Zeitmesser-Stempel ohne Context-Manager."""
        self._phases.append((name + ":mark", 0.0))

    def finish(self) -> float:
        """Beendet die Messung, gibt Gesamtdauer in ms zurück und loggt."""
        total_ms = (time.perf_counter() - self._start_total) * 1000
        self._phases.append(("__total__", total_ms))

        # stdout-Zusammenfassung
        print(f"[Startup] Gesamtzeit: {total_ms:.1f} ms")
        for name, dur in self._phases[:-1]:
            if dur > 0:
                print(f"  {name}: {dur:.1f} ms")

        # JSONL-Eintrag
        if self._log_path:
            try:
                entry = {
                    "event": "startup_profile",
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "total_ms": round(total_ms, 2),
                    "phases": [
                        {"name": n, "ms": round(d, 2)}
                        for n, d in self._phases
                    ],
                }
                with self._log_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            except Exception:
                pass

        return total_ms

    @property
    def phases(self) -> List[Tuple[str, float]]:
        """Gibt alle gemessenen Phasen zurück."""
        return list(self._phases)

    def slowest(self, n: int = 3) -> List[Tuple[str, float]]:
        """Gibt die n langsamsten Phasen zurück."""
        return sorted(
            [(name, dur) for name, dur in self._phases if dur > 0 and name != "__total__"],
            key=lambda x: x[1],
            reverse=True,
        )[:n]
