"""PronunciationManager – Aussprache-Wörterbuch für TTS (v7.0).

Regelformat (pronunciation_rules in AppSettings):
  [
    {"find": "tt5sdk",  "replace": "TeamTalk SDK",
     "whole_word": True, "use_regex": False,
     "case_sensitive": False, "enabled": True},
    {"find": r"\bvo\b", "replace": "VoiceOver",
     "use_regex": True, "case_sensitive": False, "enabled": True},
  ]

Rückwärtskompatibilität: pronunciation_dict (Dict[str, str]) wird automatisch
als einfache Regeln migriert.
"""
from __future__ import annotations

import re
from typing import Dict, List, Union


class PronunciationManager:
    """Wendet Ausspracheregeln auf Text an, bevor er vorgelesen wird."""

    def __init__(self, rules: Union[Dict[str, str], List[Dict], None] = None) -> None:
        self._rules_raw: List[Dict] = []
        self._compiled: List[tuple] = []
        if rules:
            self.update_rules(rules)

    # ------------------------------------------------------------------
    # Öffentliche API
    # ------------------------------------------------------------------

    def update_rules(self, rules: Union[Dict[str, str], List[Dict]]) -> None:
        """Akzeptiert altes Dict-Format oder neues Listen-Format."""
        if isinstance(rules, dict):
            self._rules_raw = _migrate_dict(rules)
        else:
            self._rules_raw = list(rules or [])
        self._compile()

    def get_rules(self) -> List[Dict]:
        return list(self._rules_raw)

    def apply(self, text: str) -> str:
        for pattern, replacement in self._compiled:
            try:
                text = pattern.sub(replacement, text)
            except Exception:
                pass
        return text

    # ------------------------------------------------------------------
    # Intern
    # ------------------------------------------------------------------

    def _compile(self) -> None:
        self._compiled = []
        for rule in self._rules_raw:
            if not rule.get("enabled", True):
                continue
            find = rule.get("find", "").strip()
            if not find:
                continue
            replace = rule.get("replace", "")
            flags = 0 if rule.get("case_sensitive", False) else re.IGNORECASE
            if rule.get("use_regex"):
                pattern_str = find
            else:
                pattern_str = re.escape(find)
                if rule.get("whole_word", False):
                    pattern_str = r"\b" + pattern_str + r"\b"
            try:
                self._compiled.append((re.compile(pattern_str, flags), replace))
            except re.error:
                pass


def _migrate_dict(d: Dict[str, str]) -> List[Dict]:
    """Konvertiert altes {suche: ersatz}-Dict in strukturierte Regeln."""
    return [
        {
            "find": k,
            "replace": v,
            "whole_word": False,
            "use_regex": False,
            "case_sensitive": True,
            "enabled": True,
        }
        for k, v in d.items()
        if k
    ]
