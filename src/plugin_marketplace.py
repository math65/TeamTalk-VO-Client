"""PluginMarketplace – In-App-Plugin-Browser (v4.10.0).

Lädt einen JSON-Katalog von einem konfigurierbaren Repository-URL und stellt
Plugins zum In-App-Installieren bereit.

Katalog-JSON-Schema::

    {
        "version": "1",
        "plugins": [
            {
                "name": "example_plugin",
                "display_name": "Beispiel-Plugin",
                "version": "1.0.0",
                "description": "...",
                "author": "Autor",
                "download_url": "https://example.com/example_plugin.ttplugin",
                "sha256": "<optional, Prüfsumme der .ttplugin-Datei>"
            }
        ]
    }
"""
from __future__ import annotations

import hashlib
import json
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional


DEFAULT_CATALOG_URL = "https://plugins.teamtalk-vo.example.com/catalog.json"


class MarketplaceEntry:
    """Ein Eintrag im Plugin-Katalog."""

    def __init__(self, data: Dict) -> None:
        self.name: str = str(data.get("name", ""))
        self.display_name: str = str(data.get("display_name", self.name))
        self.version: str = str(data.get("version", ""))
        self.description: str = str(data.get("description", ""))
        self.author: str = str(data.get("author", ""))
        self.download_url: str = str(data.get("download_url", ""))
        self.sha256: Optional[str] = data.get("sha256")

    def as_dict(self) -> Dict:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "version": self.version,
            "description": self.description,
            "author": self.author,
            "download_url": self.download_url,
            "sha256": self.sha256,
        }


class PluginMarketplace:
    """Verwaltet den Plugin-Katalog und ermöglicht Downloads."""

    def __init__(
        self,
        catalog_url: str = DEFAULT_CATALOG_URL,
        plugins_dir: Optional[Path] = None,
        timeout: float = 10.0,
    ) -> None:
        self._url = catalog_url
        self._plugins_dir = plugins_dir
        self._timeout = timeout
        self._catalog: List[MarketplaceEntry] = []
        self._last_error: Optional[str] = None

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error

    def fetch_catalog(self) -> bool:
        """Lädt den Katalog vom Server. Gibt True bei Erfolg zurück."""
        self._last_error = None
        try:
            req = urllib.request.Request(
                self._url,
                headers={"User-Agent": "TeamTalkVOClient/6.1.6"},
            )
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                raw = resp.read()
            data = json.loads(raw.decode("utf-8"))
            entries = data.get("plugins", []) if isinstance(data, dict) else data
            self._catalog = [MarketplaceEntry(e) for e in entries if isinstance(e, dict)]
            return True
        except urllib.error.URLError as exc:
            self._last_error = f"Netzwerkfehler: {exc.reason}"
            return False
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            self._last_error = f"Katalog-Format ungültig: {exc}"
            return False
        except Exception as exc:
            self._last_error = str(exc)
            return False

    def search(self, query: str) -> List[MarketplaceEntry]:
        """Durchsucht den Katalog nach ``query`` (Name, Beschreibung, Autor)."""
        q = query.lower()
        return [
            e for e in self._catalog
            if q in e.name.lower()
            or q in e.display_name.lower()
            or q in e.description.lower()
            or q in e.author.lower()
        ]

    def all_entries(self) -> List[MarketplaceEntry]:
        return list(self._catalog)

    def download_package(self, entry: MarketplaceEntry) -> Optional[Path]:
        """Lädt ein Plugin-Paket herunter und gibt den Pfad zurück.

        Wenn ``sha256`` im Eintrag gesetzt ist, wird die Prüfsumme verifiziert.
        Gibt ``None`` bei Fehler zurück (Fehler in ``last_error``).
        """
        if not entry.download_url:
            self._last_error = "Kein Download-URL im Eintrag"
            return None
        self._last_error = None
        try:
            req = urllib.request.Request(
                entry.download_url,
                headers={"User-Agent": "TeamTalkVOClient/6.1.6"},
            )
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                data = resp.read()
        except Exception as exc:
            self._last_error = f"Download fehlgeschlagen: {exc}"
            return None

        # Prüfsumme verifizieren
        if entry.sha256:
            actual = hashlib.sha256(data).hexdigest()
            if actual.lower() != entry.sha256.lower():
                self._last_error = (
                    f"SHA-256-Prüfsumme ungültig: erwartet {entry.sha256}, "
                    f"berechnet {actual}"
                )
                return None

        # In temporäre Datei schreiben
        try:
            tmp = tempfile.NamedTemporaryFile(
                suffix=".ttplugin",
                delete=False,
                prefix=f"tt_{entry.name}_",
            )
            tmp.write(data)
            tmp.close()
            return Path(tmp.name)
        except Exception as exc:
            self._last_error = f"Fehler beim Schreiben: {exc}"
            return None

    def install(self, entry: MarketplaceEntry) -> Optional[List[Path]]:
        """Lädt ein Plugin herunter und installiert es in ``plugins_dir``.

        Gibt Liste installierter Dateien zurück, oder ``None`` bei Fehler.
        """
        from plugin_package import read_package, install_package, PluginManifestError

        if self._plugins_dir is None:
            self._last_error = "Kein plugins_dir konfiguriert"
            return None

        pkg_path = self.download_package(entry)
        if pkg_path is None:
            return None

        try:
            pkg = read_package(pkg_path)
            installed = install_package(pkg, self._plugins_dir)
            return installed
        except PluginManifestError as exc:
            self._last_error = f"Paket-Fehler: {exc}"
            return None
        except Exception as exc:
            self._last_error = str(exc)
            return None
        finally:
            try:
                pkg_path.unlink()
            except Exception:
                pass
