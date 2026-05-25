"""AiReplyManager – KI-Antwortvorschläge und KI-Integration (v5.2.0).

Analysiert Chat-Nachrichten und bietet:
- suggest_replies():    2–3 kurze Antwortvorschläge (kontextbewusst, v5.2.0)
- summarize():          Kanal-Zusammenfassung aus Nachrichtenliste (v5.2.0)
- classify_intent():    Absichtsklassifikation für intelligentes Routing (v5.2.0)

API-Keys werden jetzt bevorzugt aus der OS-Keychain gelesen (v5.2.0/v4.9.0).
Gleiche Backend-Reihenfolge wie ChatSummaryManager: Claude → Gemini → Ollama.
"""
from __future__ import annotations

import json
import os
import urllib.request
from typing import List, Optional

_SYSTEM_PROMPT = (
    "Du bist ein Assistent der kurze, natürliche Antworten auf Chat-Nachrichten vorschlägt. "
    "Schlage genau 3 kurze Antworten auf die folgende Nachricht vor. "
    "Jede Antwort soll in einer eigenen Zeile stehen, ohne Nummerierung oder Aufzählungszeichen. "
    "Antworte in der Sprache der empfangenen Nachricht."
)

_SUMMARY_PROMPT = (
    "Du bist ein Assistent, der Kanal-Chatverlauf zusammenfasst. "
    "Fasse die folgenden Chat-Nachrichten in 2–4 prägnanten Sätzen zusammen. "
    "Antworte nur mit der Zusammenfassung, keine Einleitung."
)

_INTENT_PROMPT = (
    "Klassifiziere die Absicht der folgenden Chat-Nachricht in eine der Kategorien: "
    "frage, antwort, begruessung, verabschiedung, ankuendigung, hilfe, sonstiges. "
    "Antworte nur mit dem Kategorie-Namen, ohne Erklärung."
)

_IMPROVE_PROMPT = (
    "Verbessere den folgenden Text: Mache ihn klarer, präziser und natürlicher. "
    "Behalte die Sprache und den Ton bei. "
    "Antworte NUR mit dem verbesserten Text, ohne Erklärung oder Einleitung."
)


class AiReplyManager:
    """Generiert Antwortvorschläge via verfügbares KI-Backend."""

    def __init__(self, settings_store) -> None:
        self._settings = settings_store

    def suggest_replies(self, message: str, context: Optional[List[str]] = None) -> List[str]:
        """Gibt bis zu 3 Antwortvorschläge zurück (leere Liste bei Fehler).

        v5.2.0 – ``context`` kann bis zu 5 vorherige Nachrichten enthalten, die
        als Gesprächskontext mitgesendet werden (neueste zuletzt).
        """
        if not message.strip():
            return []

        # Kontext aufbauen
        if context:
            ctx_text = "\n".join(f"- {m}" for m in context[-5:])
            prompt = f"Gesprächskontext (neueste zuletzt):\n{ctx_text}\n\nLetzte Nachricht:\n{message}"
        else:
            prompt = message

        raw: Optional[str] = None
        key = self._claude_key()
        if key:
            raw = self._with_claude(prompt, key)
        if raw is None:
            raw = self._with_gemini(prompt)
        if raw is None:
            raw = self._with_ollama(prompt)
        if not raw:
            return []
        lines = [l.strip().lstrip("•-0123456789.) ") for l in raw.splitlines() if l.strip()]
        return lines[:3]

    def summarize(self, messages: List[str]) -> Optional[str]:
        """Fasst eine Liste von Chat-Nachrichten in 2–4 Sätzen zusammen.

        v5.2.0 – Für Kanal-Zusammenfassungen.
        Gibt None zurück wenn kein KI-Backend verfügbar oder bei Fehler.
        """
        if not messages:
            return None
        combined = "\n".join(f"- {m}" for m in messages[-50:])  # max 50 Nachrichten
        prompt = combined

        raw: Optional[str] = None
        key = self._claude_key()
        if key:
            raw = self._with_claude(prompt, key, system=_SUMMARY_PROMPT)
        if raw is None:
            raw = self._with_gemini(prompt, system=_SUMMARY_PROMPT)
        if raw is None:
            raw = self._with_ollama(prompt, system=_SUMMARY_PROMPT)
        return raw

    def classify_intent(self, message: str) -> str:
        """Klassifiziert die Absicht einer Chat-Nachricht.

        v5.2.0 – Gibt eine der Kategorien zurück:
        frage, antwort, begruessung, verabschiedung, ankuendigung, hilfe, sonstiges.
        Bei Fehler wird 'sonstiges' zurückgegeben.
        """
        if not message.strip():
            return "sonstiges"

        raw: Optional[str] = None
        key = self._claude_key()
        if key:
            raw = self._with_claude(message, key, system=_INTENT_PROMPT, max_tokens=20)
        if raw is None:
            raw = self._with_gemini(message, system=_INTENT_PROMPT)
        if raw is None:
            raw = self._with_ollama(message, system=_INTENT_PROMPT)

        if not raw:
            return "sonstiges"
        result = raw.strip().lower().split()[0] if raw.strip() else "sonstiges"
        valid = {"frage", "antwort", "begruessung", "verabschiedung", "ankuendigung", "hilfe", "sonstiges"}
        return result if result in valid else "sonstiges"

    def improve_text(self, text: str) -> Optional[str]:
        """Verbessert einen Text via KI. Gibt verbesserten Text oder None zurück.

        Gleiche Backend-Reihenfolge wie suggest_replies: Claude → Gemini → Ollama.
        Gibt None zurück wenn kein KI-Backend verfügbar oder bei Fehler.
        """
        if not text.strip():
            return None

        raw: Optional[str] = None
        key = self._claude_key()
        if key:
            raw = self._with_claude(text, key, system=_IMPROVE_PROMPT, max_tokens=500)
        if raw is None:
            raw = self._with_gemini(text, system=_IMPROVE_PROMPT)
        if raw is None:
            raw = self._with_ollama(text, system=_IMPROVE_PROMPT)
        return raw or None

    # ------------------------------------------------------------------
    # Backends
    # ------------------------------------------------------------------

    def _claude_key(self) -> str:
        key = os.environ.get("ANTHROPIC_API_KEY", "")
        if key:
            return key
        # v5.2.0 – Keychain bevorzugt vor Settings
        try:
            from keychain import get_api_key
            kc_key = get_api_key("claude_api_key")
            if kc_key:
                return kc_key
        except Exception:
            pass
        try:
            return getattr(self._settings.settings, "claude_api_key", "") or ""
        except Exception:
            return ""

    def _gemini_key(self) -> str:
        key = os.environ.get("GOOGLE_API_KEY", "")
        if key:
            return key
        # v5.2.0 – Keychain
        try:
            from keychain import get_api_key
            kc_key = get_api_key("gemini_api_key")
            if kc_key:
                return kc_key
        except Exception:
            pass
        try:
            return getattr(self._settings.settings, "gemini_api_key", "") or ""
        except Exception:
            return ""

    def _with_claude(
        self, message: str, api_key: str,
        system: str = _SYSTEM_PROMPT, max_tokens: int = 200
    ) -> Optional[str]:
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
            resp = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": message}],
            )
            return resp.content[0].text.strip()
        except ImportError:
            pass
        except Exception:
            pass
        # HTTP fallback
        try:
            payload = {
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": max_tokens,
                "system": system,
                "messages": [{"role": "user", "content": message}],
            }
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                "https://api.anthropic.com/v1/messages",
                data=data,
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=12) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                return result["content"][0]["text"].strip()
        except Exception:
            return None

    def _with_gemini(
        self, message: str,
        system: str = _SYSTEM_PROMPT
    ) -> Optional[str]:
        key = self._gemini_key()
        if not key:
            return None
        try:
            import google.generativeai as genai
            genai.configure(api_key=key)
            model = genai.GenerativeModel("gemini-1.5-flash")
            resp = model.generate_content(f"{system}\n\n{message}")
            return resp.text.strip() if resp.text else None
        except Exception:
            return None

    def _with_ollama(
        self, message: str,
        system: str = _SYSTEM_PROMPT
    ) -> Optional[str]:
        for model_name in ("llama3.2", "llama3", "phi3", "mistral"):
            try:
                payload = {
                    "model": model_name,
                    "prompt": f"{system}\n\n{message}",
                    "stream": False,
                }
                data = json.dumps(payload).encode("utf-8")
                req = urllib.request.Request(
                    "http://localhost:11434/api/generate",
                    data=data,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=12) as resp:
                    result = json.loads(resp.read().decode("utf-8"))
                    return result.get("response", "").strip() or None
            except Exception:
                continue
        return None
