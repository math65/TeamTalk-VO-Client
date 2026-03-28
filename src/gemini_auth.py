"""GeminiAuthManager – OAuth2-Authentifizierung für Google Gemini (v2.0.2).

Zwei Authentifizierungswege:
  1. API-Key  – einfach, aus https://aistudio.google.com/app/apikey
  2. OAuth    – Browser-Login, braucht client_secrets.json aus Google Cloud Console

OAuth-Ablauf:
  1. Nutzer klickt "Via Google anmelden" in den Einstellungen
  2. Browser öffnet sich mit Google-Login
  3. Nach Bestätigung: Token wird in <AppData>/gemini_token.json gespeichert
  4. Folgestarts: Token wird automatisch erneuert, kein Login mehr nötig

client_secrets.json:
  Wird aus <AppData>/gemini_client_secrets.json geladen.
  Download: Google Cloud Console → APIs & Dienste → Anmeldedaten →
  "OAuth 2.0-Client-IDs" → Typ "Desktop-App" → JSON herunterladen.
"""
from __future__ import annotations

import json
import threading
import webbrowser
from pathlib import Path
from typing import Optional


_SCOPES = ["https://www.googleapis.com/auth/generative-language.retriever"]
_REDIRECT_URI = "http://localhost"


def _has_deps() -> bool:
    try:
        import google.auth  # noqa: F401
        import google_auth_oauthlib.flow  # noqa: F401
        return True
    except ImportError:
        return False


class GeminiAuthManager:
    """Verwaltet Authentifizierungsstatus und Token für Google Gemini."""

    def __init__(self, app_data_dir: Path) -> None:
        self._dir = app_data_dir
        self._token_path = app_data_dir / "gemini_token.json"
        self._secrets_path = app_data_dir / "gemini_client_secrets.json"
        self._credentials = None  # google.oauth2.credentials.Credentials
        self._available = _has_deps()
        if self._available:
            self._load_saved_token()

    # ------------------------------------------------------------------
    # Öffentliche API
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        """True wenn google-auth-oauthlib installiert ist."""
        return self._available

    def has_client_secrets(self) -> bool:
        return self._secrets_path.exists()

    def is_authenticated(self) -> bool:
        """True wenn ein gültiges (oder erneuerbares) Token vorhanden ist."""
        if self._credentials is None:
            return False
        if self._credentials.valid:
            return True
        # Kann erneuert werden?
        return bool(self._credentials.refresh_token)

    def get_credentials(self):
        """Gibt erneuerte Credentials zurück (oder None bei Fehler)."""
        if self._credentials is None:
            return None
        if not self._credentials.valid and self._credentials.refresh_token:
            try:
                import google.auth.transport.requests
                self._credentials.refresh(google.auth.transport.requests.Request())
                self._save_token()
            except Exception as exc:
                print(f"[GeminiAuth] Token-Erneuerung fehlgeschlagen: {exc}")
                return None
        return self._credentials if self._credentials.valid else None

    def start_oauth_flow(self, on_success=None, on_error=None) -> None:
        """Startet den OAuth-Flow in einem Hintergrundthread.

        on_success(credentials): wird nach erfolgreichem Login aufgerufen
        on_error(message: str): wird bei Fehler aufgerufen
        """
        if not self._available:
            if on_error:
                on_error("google-auth-oauthlib nicht installiert.")
            return
        if not self.has_client_secrets():
            if on_error:
                on_error(
                    f"client_secrets.json nicht gefunden.\n"
                    f"Bitte herunterladen und als speichern:\n"
                    f"{self._secrets_path}"
                )
            return
        threading.Thread(
            target=self._run_flow,
            args=(on_success, on_error),
            daemon=True,
        ).start()

    def revoke(self) -> None:
        """Widerruft das Token und löscht die lokale Datei."""
        try:
            if self._credentials and self._credentials.token:
                import google.auth.transport.requests
                self._credentials.revoke(google.auth.transport.requests.Request())
        except Exception:
            pass
        self._credentials = None
        if self._token_path.exists():
            self._token_path.unlink()

    def auth_status_label(self) -> str:
        """Kurztext für UI-Statusanzeige."""
        if not self._available:
            return "google-auth-oauthlib nicht installiert"
        if not self.has_client_secrets():
            return "client_secrets.json fehlt"
        if self.is_authenticated():
            email = getattr(getattr(self._credentials, "id_token", None) or {}, "get", lambda *_: None)("email") or ""
            return f"Angemeldet{' als ' + email if email else ''}"
        return "Nicht angemeldet"

    # ------------------------------------------------------------------
    # Internes
    # ------------------------------------------------------------------

    def _load_saved_token(self) -> None:
        if not self._token_path.exists():
            return
        try:
            from google.oauth2.credentials import Credentials
            self._credentials = Credentials.from_authorized_user_file(
                str(self._token_path), _SCOPES
            )
        except Exception as exc:
            print(f"[GeminiAuth] Gespeichertes Token konnte nicht geladen werden: {exc}")

    def _save_token(self) -> None:
        if self._credentials is None:
            return
        try:
            self._token_path.write_text(self._credentials.to_json(), encoding="utf-8")
        except Exception as exc:
            print(f"[GeminiAuth] Token speichern fehlgeschlagen: {exc}")

    def _run_flow(self, on_success, on_error) -> None:
        """OAuth-Flow: läuft in Hintergrundthread, öffnet Browser."""
        try:
            from google_auth_oauthlib.flow import InstalledAppFlow
            flow = InstalledAppFlow.from_client_secrets_file(
                str(self._secrets_path), _SCOPES
            )
            # Lokalen Server starten (Port 0 = zufälliger freier Port)
            credentials = flow.run_local_server(
                port=0,
                open_browser=True,
                success_message=(
                    "Authentifizierung erfolgreich! "
                    "Du kannst dieses Fenster schließen."
                ),
            )
            self._credentials = credentials
            self._save_token()
            if on_success:
                on_success(credentials)
        except Exception as exc:
            print(f"[GeminiAuth] OAuth-Flow fehlgeschlagen: {exc}")
            if on_error:
                on_error(str(exc))
