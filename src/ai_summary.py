"""ChatSummaryManager – KI-gestützte Chat-Zusammenfassung (v2.0.2).

Fasst verpasste Chat-Nachrichten zusammen wenn der Nutzer zurückkommt
oder per Hotkey. Backends werden der Reihe nach versucht:

  1. Claude  – via offizielles `anthropic` SDK (API-Key aus Settings/Env)
  2. Gemini  – via `google-genai` SDK (API-Key oder OAuth-Token)
  3. Ollama  – lokale Modelle (llama3.2, phi3, mistral …)
  4. Extraktion – immer verfügbar, kein KI-Backend nötig

Verwendung:
    mgr = ChatSummaryManager(settings_store, chat_history, gemini_auth)
    text = mgr.summarize_missed(server_key, since_ts=time.time()-3600)
    frame.tts.speak(text)
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
import urllib.error
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from chat_history import ChatHistoryManager
    from gemini_auth import GeminiAuthManager


_OLLAMA_URL = "http://localhost:11434/api/generate"
_OLLAMA_MODELS = ["llama3.2", "llama3", "phi3", "mistral", "gemma"]

_SYSTEM_PROMPT = (
    "Du bist ein Assistent der Chat-Nachrichten kurz zusammenfasst. "
    "Fasse die folgenden Nachrichten auf Deutsch in maximal 3 Sätzen zusammen. "
    "Nenne die wichtigsten Themen und wer etwas gesagt hat. "
    "Antworte nur mit der Zusammenfassung, ohne Einleitung."
)


class ChatSummaryManager:
    """Fasst verpasste Chat-Nachrichten via KI oder Extraktion zusammen."""

    def __init__(
        self,
        settings_store,
        chat_history_manager: "ChatHistoryManager",
        gemini_auth: Optional["GeminiAuthManager"] = None,
    ) -> None:
        self._settings = settings_store
        self._history = chat_history_manager
        self._gemini_auth = gemini_auth

    # ------------------------------------------------------------------
    # Öffentliche API
    # ------------------------------------------------------------------

    def summarize_missed(
        self,
        server_key: str,
        since_ts: float,
        max_messages: int = 50,
        channel: str = "channel",
    ) -> str:
        """Gibt eine Zusammenfassung der Nachrichten seit since_ts zurück."""
        messages = self._get_messages(server_key, since_ts, max_messages, channel)
        if not messages:
            return "Keine neuen Nachrichten."

        summary: Optional[str] = None

        # 1. Claude (Anthropic SDK)
        claude_key = self._get_claude_api_key()
        if claude_key:
            summary = self._summarize_with_claude_sdk(messages, claude_key)
            if summary is None:
                # Fallback auf manuelles HTTP wenn SDK fehlt
                summary = self._summarize_with_claude_http(messages, claude_key)

        # 2. Gemini
        if summary is None:
            summary = self._summarize_with_gemini(messages)

        # 3. Ollama
        if summary is None:
            summary = self._summarize_with_ollama(messages)

        # 4. Einfache Extraktion
        if summary is None:
            summary = self._summarize_fallback(messages)

        return summary

    def _get_claude_api_key(self) -> str:
        key = os.environ.get("ANTHROPIC_API_KEY", "")
        if key:
            return key
        try:
            return getattr(self._settings.settings, "claude_api_key", "") or ""
        except Exception:
            return ""

    def _get_gemini_api_key(self) -> str:
        key = os.environ.get("GOOGLE_API_KEY", "")
        if key:
            return key
        try:
            return getattr(self._settings.settings, "gemini_api_key", "") or ""
        except Exception:
            return ""

    # ------------------------------------------------------------------
    # Nachrichten aus dem Verlauf holen
    # ------------------------------------------------------------------

    def _get_messages(
        self,
        server_key: str,
        since_ts: float,
        max_messages: int,
        channel: str,
    ) -> List[dict]:
        try:
            history = self._history.get_history(server_key, channel)
            filtered = [m for m in history if m.get("ts", 0) >= since_ts]
            return filtered[-max_messages:]
        except Exception:
            return []

    # ------------------------------------------------------------------
    # Backend 1: Claude via anthropic SDK
    # ------------------------------------------------------------------

    def _summarize_with_claude_sdk(
        self, messages: List[dict], api_key: str
    ) -> Optional[str]:
        """Fasst Nachrichten via offizielles anthropic SDK zusammen."""
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=300,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": self._messages_to_text(messages)}],
            )
            return response.content[0].text.strip()
        except ImportError:
            return None  # SDK nicht installiert → HTTP-Fallback
        except Exception as exc:
            print(f"[AISummary] Claude SDK fehlgeschlagen: {exc}")
            return None

    def _summarize_with_claude_http(
        self, messages: List[dict], api_key: str
    ) -> Optional[str]:
        """HTTP-Fallback wenn anthropic SDK nicht installiert ist."""
        payload = {
            "model": "claude-haiku-4-5-20251001",
            "max_tokens": 300,
            "system": _SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": self._messages_to_text(messages)}],
        }
        try:
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
            with urllib.request.urlopen(req, timeout=15) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                return result["content"][0]["text"].strip()
        except Exception as exc:
            print(f"[AISummary] Claude HTTP fehlgeschlagen: {exc}")
            return None

    # ------------------------------------------------------------------
    # Backend 2: Google Gemini
    # ------------------------------------------------------------------

    def _summarize_with_gemini(self, messages: List[dict]) -> Optional[str]:
        """Fasst Nachrichten via Google Gemini zusammen (API-Key oder OAuth)."""
        try:
            import google.genai as genai
        except ImportError:
            return None

        api_key = self._get_gemini_api_key()
        credentials = None

        # OAuth-Token bevorzugen wenn kein API-Key gesetzt
        if not api_key and self._gemini_auth is not None:
            credentials = self._gemini_auth.get_credentials()

        if not api_key and credentials is None:
            return None

        prompt = f"{_SYSTEM_PROMPT}\n\n{self._messages_to_text(messages)}"
        try:
            if api_key:
                client = genai.Client(api_key=api_key)
            else:
                client = genai.Client(credentials=credentials)

            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=prompt,
            )
            text = (response.text or "").strip()
            return text if text else None
        except Exception as exc:
            print(f"[AISummary] Gemini fehlgeschlagen: {exc}")
            return None

    # ------------------------------------------------------------------
    # Backend 3: Ollama
    # ------------------------------------------------------------------

    def _summarize_with_ollama(self, messages: List[dict]) -> Optional[str]:
        prompt = f"{_SYSTEM_PROMPT}\n\n{self._messages_to_text(messages)}"
        for model in _OLLAMA_MODELS:
            try:
                payload = {
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"num_predict": 300},
                }
                data = json.dumps(payload).encode("utf-8")
                req = urllib.request.Request(
                    _OLLAMA_URL,
                    data=data,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=20) as resp:
                    result = json.loads(resp.read().decode("utf-8"))
                    text = (result.get("response") or "").strip()
                    if text:
                        return text
            except urllib.error.URLError:
                return None
            except Exception as exc:
                print(f"[AISummary] Ollama ({model}) fehlgeschlagen: {exc}")
                continue
        return None

    # ------------------------------------------------------------------
    # Backend 4: Einfache Extraktion
    # ------------------------------------------------------------------

    def _summarize_fallback(self, messages: List[dict]) -> str:
        senders: dict = {}
        for m in messages:
            sender = m.get("sender") or m.get("from") or "Unbekannt"
            senders[sender] = senders.get(sender, 0) + 1
        count = len(messages)
        sender_parts = ", ".join(
            f"{name} ({n})" for name, n in sorted(senders.items(), key=lambda x: -x[1])
        )
        last = messages[-1]
        last_sender = last.get("sender") or last.get("from") or "?"
        last_text = (last.get("text") or last.get("message") or "")[:80]
        return (
            f"{count} Nachrichten: {sender_parts}. "
            f"Letzte von {last_sender}: {last_text}"
        )

    # ------------------------------------------------------------------
    # Hilfsfunktionen
    # ------------------------------------------------------------------

    def _messages_to_text(self, messages: List[dict]) -> str:
        lines = []
        for m in messages:
            sender = m.get("sender") or m.get("from") or "?"
            text = m.get("text") or m.get("message") or ""
            ts = m.get("ts") or m.get("timestamp") or 0
            time_str = time.strftime("%H:%M", time.localtime(ts)) if ts else ""
            prefix = f"[{time_str}] " if time_str else ""
            lines.append(f"{prefix}{sender}: {text}")
        return "\n".join(lines)
