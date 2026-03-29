"""TLS-Zertifikats-Fingerprint-Verifizierung (v4.9.0).

Erlaubt das Pinnen eines TLS-Zertifikat-Fingerprints (SHA-256) für eine
Server-Adresse. Beim Verbindungsaufbau wird der tatsächliche Fingerprint
gegen den gespeicherten verglichen.

Nur Python-Standardbibliothek: ssl, hashlib, socket.
"""
from __future__ import annotations

import hashlib
import json
import socket
import ssl
from pathlib import Path
from typing import Dict, Optional


def get_cert_fingerprint(host: str, port: int = 443, timeout: float = 5.0) -> Optional[str]:
    """Verbindet sich zu ``host:port`` und gibt den SHA-256-Fingerprint des
    Serverzertifikats zurück (hex-String, Großbuchstaben, Doppelpunkt-getrennt).

    Gibt ``None`` zurück bei Fehler.
    """
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with socket.create_connection((host, port), timeout=timeout) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as tls:
                der = tls.getpeercert(binary_form=True)
        if der is None:
            return None
        digest = hashlib.sha256(der).hexdigest().upper()
        return ":".join(digest[i:i+2] for i in range(0, len(digest), 2))
    except Exception:
        return None


class CertPinStore:
    """Verwaltet gespeicherte Zertifikat-Fingerprints pro Host.

    Fingerprints werden in ``cert_pins.json`` im App-Verzeichnis gespeichert.
    """

    def __init__(self, app_dir: Path) -> None:
        self._path = app_dir / "cert_pins.json"
        self._pins: Dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self._pins = {str(k): str(v) for k, v in data.items()}
        except Exception:
            self._pins = {}

    def _save(self) -> None:
        try:
            self._path.write_text(
                json.dumps(self._pins, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    def pin(self, host: str, fingerprint: str) -> None:
        """Speichert den Fingerprint für ``host`` (überschreibt vorhandenen)."""
        self._pins[host] = fingerprint.upper()
        self._save()

    def unpin(self, host: str) -> None:
        """Entfernt den gespeicherten Fingerprint für ``host``."""
        self._pins.pop(host, None)
        self._save()

    def get_pinned(self, host: str) -> Optional[str]:
        """Gibt den gespeicherten Fingerprint für ``host`` zurück oder ``None``."""
        return self._pins.get(host)

    def verify(self, host: str, port: int = 443, timeout: float = 5.0) -> "VerifyResult":
        """Verbindet zu ``host:port`` und prüft Fingerprint gegen gespeicherten Pin.

        Returns:
            :class:`VerifyResult` mit Feldern ``ok``, ``actual``, ``expected``, ``error``.
        """
        expected = self._pins.get(host)
        actual = get_cert_fingerprint(host, port, timeout)
        if actual is None:
            return VerifyResult(ok=False, actual=None, expected=expected,
                                error="Verbindung fehlgeschlagen")
        if expected is None:
            return VerifyResult(ok=True, actual=actual, expected=None,
                                error=None)  # Kein Pin gesetzt → immer OK
        if actual == expected.upper():
            return VerifyResult(ok=True, actual=actual, expected=expected, error=None)
        return VerifyResult(
            ok=False,
            actual=actual,
            expected=expected,
            error=f"Fingerprint-Mismatch: erwartet {expected}, gefunden {actual}",
        )

    @property
    def all_pins(self) -> Dict[str, str]:
        return dict(self._pins)


class VerifyResult:
    """Ergebnis einer Fingerprint-Verifizierung."""

    __slots__ = ("ok", "actual", "expected", "error")

    def __init__(
        self,
        ok: bool,
        actual: Optional[str],
        expected: Optional[str],
        error: Optional[str],
    ) -> None:
        self.ok = ok
        self.actual = actual
        self.expected = expected
        self.error = error

    def __repr__(self) -> str:
        return (
            f"VerifyResult(ok={self.ok}, actual={self.actual!r}, "
            f"expected={self.expected!r}, error={self.error!r})"
        )
