"""BrailleOutputManager – Optimierte Braillezeilen-Ausgabe (v2.0.0).

Baut auf dem existierenden braille_compact_mode auf und erweitert ihn um:
- Drei Verbositätsstufen: compact / normal / verbose
- Fokus-Tracking: automatische Kurz-Ansagen bei Fokuswechseln
- Intelligentes Textformatieren (Abkürzungen, Sonderzeichen entfernen)
- Hotkey zum Durchschalten der Verbositätsstufen

Verwendung:
    braille = BrailleOutputManager(frame.tts)
    braille.set_verbosity("compact")
    label = braille.format_channel_entry("Allgemein", level=1, user_count=3)
    braille.on_focus_changed("Kanäle", "Allgemein")
"""
from __future__ import annotations

import re
import unicodedata
from typing import List, Optional


_VERBOSITY_LABELS = {
    "compact": "Braille: kompakt",
    "normal": "Braille: normal",
    "verbose": "Braille: ausführlich",
}
_CYCLE = ["compact", "normal", "verbose"]


class BrailleOutputManager:
    """Formatiert Texte für Braillezeilen und steuert Verbositätsstufen."""

    COMPACT = "compact"
    NORMAL = "normal"
    VERBOSE = "verbose"

    def __init__(self, tts_manager) -> None:
        self._tts = tts_manager
        self.verbosity: str = self.NORMAL
        self._last_focus_label: str = ""
        self._focus_announcements: bool = True

    # ------------------------------------------------------------------
    # Verbosität
    # ------------------------------------------------------------------

    def set_verbosity(self, level: str) -> None:
        """Setzt die Verbositätsstufe und bestätigt via TTS."""
        if level not in _CYCLE:
            return
        self.verbosity = level
        label = _VERBOSITY_LABELS.get(level, level)
        try:
            self._tts.speak(label, kind="system")
        except Exception:
            pass

    def cycle_verbosity(self) -> str:
        """Schaltet zyklisch durch alle Stufen und gibt die neue zurück."""
        idx = _CYCLE.index(self.verbosity) if self.verbosity in _CYCLE else 0
        next_idx = (idx + 1) % len(_CYCLE)
        self.verbosity = _CYCLE[next_idx]
        label = _VERBOSITY_LABELS.get(self.verbosity, self.verbosity)
        try:
            self._tts.speak(label, kind="system")
        except Exception:
            pass
        return self.verbosity

    # ------------------------------------------------------------------
    # Formatierung: Kanaleinträge
    # ------------------------------------------------------------------

    def format_channel_entry(
        self,
        name: str,
        level: int = 0,
        user_count: int = 0,
        has_password: bool = False,
    ) -> str:
        indent = "  " * level
        if self.verbosity == self.COMPACT:
            suffix = f", {user_count}N" if user_count else ""
            return f"{indent}{name}{suffix}"
        elif self.verbosity == self.NORMAL:
            suffix = f", {user_count} Nutzer" if user_count else ""
            pw = " [P]" if has_password else ""
            return f"{indent}{name}{suffix}{pw}"
        else:  # verbose
            suffix = f", {user_count} Nutzer anwesend" if user_count else ", leer"
            pw = " [Passwort]" if has_password else ""
            return f"{indent}{name}{suffix}{pw}"

    # ------------------------------------------------------------------
    # Formatierung: Nutzereinträge
    # ------------------------------------------------------------------

    def format_user_entry(self, name: str, flags: Optional[List[str]] = None) -> str:
        flags = flags or []
        if self.verbosity == self.COMPACT:
            suffix = f", {flags[0]}" if flags else ""
            return f"{name}{suffix}"
        else:
            suffix = f", {', '.join(flags)}" if flags else ""
            return f"{name}{suffix}"

    # ------------------------------------------------------------------
    # Formatierung: Nachrichten
    # ------------------------------------------------------------------

    def format_message(
        self,
        sender: str,
        text: str,
        private: bool = False,
    ) -> str:
        if self.verbosity == self.COMPACT:
            short = text[:60] + ("..." if len(text) > 60 else "")
            return f"{sender}: {short}"
        elif self.verbosity == self.NORMAL:
            prefix = "[P] " if private else ""
            return f"{prefix}{sender}: {text}"
        else:  # verbose
            prefix = "Privat von " if private else "Von "
            return f"{prefix}{sender}: {text}"

    # ------------------------------------------------------------------
    # Fokus-Tracking
    # ------------------------------------------------------------------

    def on_focus_changed(self, area_label: str, item_text: str = "") -> None:
        """Kündigt Gebiets- oder Item-Wechsel via TTS an.

        Verhindert doppelte Ansagen desselben Gebiets.
        """
        if not self._focus_announcements:
            return
        if area_label != self._last_focus_label:
            self._last_focus_label = area_label
            if self.verbosity in (self.NORMAL, self.VERBOSE):
                try:
                    self._tts.speak(area_label, kind="system")
                except Exception:
                    pass
        if item_text:
            try:
                self._tts.speak(item_text, kind="system")
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Textbereinigung
    # ------------------------------------------------------------------

    def strip_for_braille(self, text: str) -> str:
        """Entfernt Zeichen die auf Braillezeilen schlecht aussehen.

        Entfernt: Emojis, Pipe-Zeichen, Pfeile und andere Sonderzeichen.
        """
        # Emojis (Unicode-Kategorien So, Sm, Sk – Symbole) entfernen
        cleaned = "".join(
            ch for ch in text
            if unicodedata.category(ch) not in ("So", "Cs")
            and ord(ch) < 0x2600  # Technische Symbole
            or ch.isalpha()
            or ch.isdigit()
            or ch in " .,;:!?-_()/\\\"'[]{}@#%&+=<>\n\t"
        )
        # Explizite Sonderzeichen ersetzen
        cleaned = cleaned.replace("|", ", ")
        cleaned = re.sub(r"[→←↑↓⟶⟵]", " -> ", cleaned)
        # Mehrfache Leerzeichen normalisieren
        cleaned = re.sub(r"  +", " ", cleaned).strip()
        return cleaned
