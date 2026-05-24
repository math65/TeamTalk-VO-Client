"""Benachrichtigungs-Engine: regelt TTS + Sound pro Event und Scope."""
from __future__ import annotations

from typing import Dict, List

EVENTS: List[tuple] = [
    ("user_join", "Benutzer betritt Kanal"),
    ("user_leave", "Benutzer verlässt Kanal"),
    ("chat_message", "Kanalnachricht"),
    ("private_msg", "Privatnachricht"),
    ("channel_join", "Ich trete Kanal bei"),
    ("connected", "Verbunden"),
    ("disconnected", "Getrennt"),
]
SCOPES: List[tuple] = [
    ("global", "Global (Standard)"),
    ("server", "Server"),
    ("channel", "Kanal"),
    ("user", "Benutzer"),
]
ACTIONS: List[tuple] = [
    ("both", "TTS + Sound"),
    ("tts", "Nur TTS"),
    ("sound", "Nur Sound"),
    ("none", "Stumm"),
]

_SCOPE_PRIORITY = {s: i for i, (s, _) in enumerate(SCOPES)}
_EVENT_LABELS = {k: v for k, v in EVENTS}
_SCOPE_LABELS = {k: v for k, v in SCOPES}
_ACTION_LABELS = {k: v for k, v in ACTIONS}


class NotificationManager:
    """
    Wertet Regeln aus, um für jedes Event den passenden Action zu bestimmen.

    Jede Regel ist ein Dict mit:
      event  : str  ("user_join" | "" für alle Events)
      scope  : str  ("global" | "server" | "channel" | "user")
      value  : str  (Server- | Kanal- | Benutzername; "" für global)
      action : str  ("both" | "tts" | "sound" | "none")

    Spezifischste Regel gewinnt: user > channel > server > global.
    Fallback ohne passende Regel: "both".
    """

    def __init__(self, rules: List[Dict] | None = None) -> None:
        self._rules: List[Dict] = list(rules or [])

    def update_rules(self, rules: List[Dict]) -> None:
        self._rules = list(rules)

    @property
    def rules(self) -> List[Dict]:
        return list(self._rules)

    def get_action(
        self,
        event: str,
        *,
        server: str = "",
        channel: str = "",
        user: str = "",
        message: str = "",
    ) -> str:
        best_scope = -1
        best_action = "both"

        for rule in self._rules:
            r_event = rule.get("event", "")
            r_scope = rule.get("scope", "global")
            r_value = str(rule.get("value", "")).strip().lower()
            r_action = rule.get("action", "both")
            r_keyword = str(rule.get("keyword", "")).strip()

            if r_event and r_event != event:
                continue

            if r_keyword:
                if not message or r_keyword.lower() not in message.lower():
                    continue

            if r_scope == "global":
                match = True
            elif r_scope == "server":
                match = bool(server and r_value and r_value == server.strip().lower())
            elif r_scope == "channel":
                match = bool(channel and r_value and r_value == channel.strip().lower())
            elif r_scope == "user":
                match = bool(user and r_value and r_value == user.strip().lower())
            else:
                match = False

            if not match:
                continue

            prio = _SCOPE_PRIORITY.get(r_scope, 0)
            if prio > best_scope:
                best_scope = prio
                best_action = r_action

        return best_action

    def allow_tts(self, event: str, **ctx) -> bool:
        return self.get_action(event, **ctx) in ("both", "tts")

    def allow_sound(self, event: str, **ctx) -> bool:
        return self.get_action(event, **ctx) in ("both", "sound")


def rule_label(rule: Dict) -> str:
    event_label = _EVENT_LABELS.get(rule.get("event", ""), "") or "Alle Events"
    scope_label = _SCOPE_LABELS.get(rule.get("scope", "global"), "Global")
    value = rule.get("value", "")
    keyword = str(rule.get("keyword", "")).strip()
    action_label = _ACTION_LABELS.get(rule.get("action", "both"), "TTS + Sound")
    parts = [event_label]
    if keyword:
        parts.append(f"Stichwort: \"{keyword}\"")
    if value:
        parts.append(f"{scope_label}: {value}")
    else:
        parts.append(scope_label)
    parts.append(f"→ {action_label}")
    return " | ".join(parts)
