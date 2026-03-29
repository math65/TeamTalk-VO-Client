"""HealthCheck – App-Gesundheitsprüfung (v5.8.0).

Prüft wichtige App-Komponenten und gibt Statusberichte zurück.
Kann manuell oder periodisch aufgerufen werden.
"""
from __future__ import annotations

import time
from typing import Callable, Dict, List, Optional


class HealthStatus:
    OK = "ok"
    WARNING = "warning"
    ERROR = "error"


class HealthCheckResult:
    def __init__(self, name: str, status: str, message: str = "", latency_ms: float = 0.0) -> None:
        self.name = name
        self.status = status
        self.message = message
        self.latency_ms = latency_ms

    def is_ok(self) -> bool:
        return self.status == HealthStatus.OK

    def as_dict(self) -> Dict:
        return {
            "name": self.name,
            "status": self.status,
            "message": self.message,
            "latency_ms": round(self.latency_ms, 2),
        }

    def __repr__(self) -> str:
        return f"HealthCheckResult(name={self.name!r}, status={self.status!r}, msg={self.message!r})"


class HealthChecker:
    """Führt registrierte Prüfungen durch und aggregiert Ergebnisse."""

    def __init__(self) -> None:
        self._checks: Dict[str, Callable[[], HealthCheckResult]] = {}
        self._last_results: List[HealthCheckResult] = []

    def register(self, name: str, check_fn: Callable[[], HealthCheckResult]) -> None:
        """Registriert eine Prüffunktion unter ``name``."""
        self._checks[name] = check_fn

    def run_all(self) -> List[HealthCheckResult]:
        """Führt alle registrierten Prüfungen aus."""
        results = []
        for name, fn in self._checks.items():
            t0 = time.monotonic()
            try:
                result = fn()
                result.latency_ms = (time.monotonic() - t0) * 1000
            except Exception as exc:
                result = HealthCheckResult(
                    name=name,
                    status=HealthStatus.ERROR,
                    message=f"Prüfung fehlgeschlagen: {exc}",
                    latency_ms=(time.monotonic() - t0) * 1000,
                )
            results.append(result)
        self._last_results = results
        return results

    def overall_status(self) -> str:
        """Gibt den schlechtesten Status aller letzten Prüfungen zurück."""
        if not self._last_results:
            return HealthStatus.OK
        statuses = {r.status for r in self._last_results}
        if HealthStatus.ERROR in statuses:
            return HealthStatus.ERROR
        if HealthStatus.WARNING in statuses:
            return HealthStatus.WARNING
        return HealthStatus.OK

    def text_report(self) -> str:
        """Gibt einen lesbaren Gesundheitsbericht zurück."""
        if not self._last_results:
            return "Keine Prüfungen durchgeführt."
        lines = [f"Gesamt-Status: {self.overall_status().upper()}"]
        for r in self._last_results:
            icon = {"ok": "✓", "warning": "⚠", "error": "✗"}.get(r.status, "?")
            line = f"  {icon} {r.name}: {r.status}"
            if r.message:
                line += f" – {r.message}"
            line += f" ({r.latency_ms:.0f}ms)"
            lines.append(line)
        return "\n".join(lines)

    @property
    def last_results(self) -> List[HealthCheckResult]:
        return list(self._last_results)


# ---------------------------------------------------------------------------
# Vordefinierte Prüffunktionen
# ---------------------------------------------------------------------------

def check_disk_space(min_mb: int = 50) -> HealthCheckResult:
    """Prüft ob genügend freier Speicher vorhanden ist."""
    try:
        import shutil
        free_bytes = shutil.disk_usage("/").free
        free_mb = free_bytes // (1024 * 1024)
        if free_mb < min_mb:
            return HealthCheckResult(
                "disk_space", HealthStatus.WARNING,
                f"Nur noch {free_mb} MB frei (Minimum: {min_mb} MB)"
            )
        return HealthCheckResult("disk_space", HealthStatus.OK, f"{free_mb} MB frei")
    except Exception as exc:
        return HealthCheckResult("disk_space", HealthStatus.ERROR, str(exc))


def check_event_bus(bus) -> HealthCheckResult:
    """Prüft EventBus-Metriken auf anomale Fehlerrate."""
    try:
        m = bus.metrics()
        errors = m.get("handler_errors", 0)
        total = m.get("total_emitted", 1)
        error_rate = errors / max(total, 1)
        if error_rate > 0.05:
            return HealthCheckResult(
                "event_bus", HealthStatus.WARNING,
                f"Fehlerrate {error_rate:.1%} ({errors}/{total} Events)"
            )
        return HealthCheckResult(
            "event_bus", HealthStatus.OK,
            f"{total} Events, {errors} Fehler"
        )
    except Exception as exc:
        return HealthCheckResult("event_bus", HealthStatus.ERROR, str(exc))


def check_settings_db(db_path) -> HealthCheckResult:
    """Prüft ob die Settings-Datenbank erreichbar ist."""
    import sqlite3
    try:
        conn = sqlite3.connect(str(db_path), timeout=2)
        conn.execute("SELECT 1")
        conn.close()
        return HealthCheckResult("settings_db", HealthStatus.OK, "Datenbank erreichbar")
    except Exception as exc:
        return HealthCheckResult("settings_db", HealthStatus.ERROR, str(exc))
