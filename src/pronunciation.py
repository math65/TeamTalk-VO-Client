"""PronunciationManager – Aussprache-Wörterbuch für TTS (v2.2.0).

Ersetzt Wörter/Abkürzungen vor der TTS-Ausgabe.
Beispiel: {"TT": "TeamTalk", "bzw.": "beziehungsweise"}
"""
from __future__ import annotations

import re
from typing import Dict


class PronunciationManager:
    """Wendet Ausspracheregeln auf Text an, bevor er vorgelesen wird."""

    def __init__(self, rules: Dict[str, str] | None = None) -> None:
        self._rules: Dict[str, str] = rules or {}
        self._pattern: re.Pattern | None = None
        self._rebuild()

    def update_rules(self, rules: Dict[str, str]) -> None:
        self._rules = dict(rules)
        self._rebuild()

    def _rebuild(self) -> None:
        if not self._rules:
            self._pattern = None
            return
        escaped = [re.escape(k) for k in sorted(self._rules, key=len, reverse=True)]
        self._pattern = re.compile("|".join(escaped))

    def apply(self, text: str) -> str:
        if not self._pattern:
            return text
        return self._pattern.sub(lambda m: self._rules.get(m.group(0), m.group(0)), text)
