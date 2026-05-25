from __future__ import annotations

import json
import dataclasses
import sys
from typing import TYPE_CHECKING, List, Tuple

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QPushButton, QLabel, QFileDialog, QScrollArea,
    QLineEdit, QMessageBox,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from i18n import _

if TYPE_CHECKING:
    from app_qt import MainWindow

_INAPP_CATEGORIES: List[Tuple[str, List[Tuple[str, str]]]] = [
    ("Audio & Aufnahme", [
        ("Alles stummschalten", "hotkey_mute_all"),
        ("Sprachaktivierung umschalten", "hotkey_voice_activation"),
        ("Video senden umschalten", "hotkey_video_tx"),
        ("Ausgabelautstärke hoch", "hotkey_volume_up"),
        ("Ausgabelautstärke runter", "hotkey_volume_down"),
        ("Mikrofon-Boost hoch", "hotkey_mic_boost_up"),
        ("Mikrofon-Boost runter", "hotkey_mic_boost_down"),
        ("Aufnahme umschalten", "hotkey_record_toggle"),
    ]),
    ("Ansagen & TTS", [
        ("Eingangspegel ansagen", "hotkey_announce_level"),
        ("Nutzerinfo ansagen", "hotkey_announce_user_info"),
        ("Ping ansagen", "hotkey_announce_ping"),
        ("Braille-Status ansagen", "hotkey_announce_status"),
        ("TTS abbrechen", "hotkey_tts_cancel"),
        ("Braille-Verbosität wechseln", "hotkey_cycle_braille_verbosity"),
        ("Sound-Profil wechseln", "hotkey_cycle_sound_profile"),
    ]),
    ("Navigation & Chat", [
        ("Privatantwort (letzter Absender)", "hotkey_reply_last_sender"),
        ("Lesezeichen 1 springen", "hotkey_bookmark_1"),
        ("Lesezeichen 2 springen", "hotkey_bookmark_2"),
        ("Lesezeichen 3 springen", "hotkey_bookmark_3"),
        ("Lesezeichen 4 springen", "hotkey_bookmark_4"),
        ("Lesezeichen 5 springen", "hotkey_bookmark_5"),
        ("Lesezeichen 6 springen", "hotkey_bookmark_6"),
        ("Lesezeichen 7 springen", "hotkey_bookmark_7"),
        ("Lesezeichen 8 springen", "hotkey_bookmark_8"),
        ("Lesezeichen 9 springen", "hotkey_bookmark_9"),
    ]),
    ("KI & Automatisierung", [
        ("KI-Zusammenfassung ansagen", "hotkey_ai_summary"),
        ("KI-Antwortvorschläge", "hotkey_ai_reply_suggestions"),
        ("Status-Vorlage 1", "hotkey_status_template_1"),
        ("Status-Vorlage 2", "hotkey_status_template_2"),
        ("Status-Vorlage 3", "hotkey_status_template_3"),
    ]),
]


class _HotkeyRow(QWidget):
    def __init__(self, parent: QWidget, label: str, key: str, global_key: bool, window: "MainWindow") -> None:
        super().__init__(parent)
        self._key = key
        self._label_text = label
        self._global = global_key
        self._window = window
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel(_(label))
        lbl.setMinimumWidth(260)
        self.status = QLabel(_("(nicht gesetzt)"))
        self.status.setAccessibleName(f"{_(label)} Hotkey")
        btn = QPushButton(_("&Hotkey aufnehmen"))
        btn.setAccessibleName(f"{_(label)} Hotkey aufnehmen")
        if global_key:
            btn.clicked.connect(lambda: window.start_global_hotkey_capture(key))
        else:
            btn.clicked.connect(lambda: window.start_hotkey_capture(key))
        layout.addWidget(lbl)
        layout.addWidget(self.status, 1)
        layout.addWidget(btn)


class ShortcutsTab(QWidget):
    """Tab 11: Tastenkürzel – kategorisiert, durchsuchbar, mit Alle-zurücksetzen."""

    def __init__(self, parent: QWidget, window: "MainWindow") -> None:
        super().__init__(parent)
        self.window = window
        self._rows: list[_HotkeyRow] = []
        self._global_rows: list[_HotkeyRow] = []
        self._global_enable = None
        self._sections: List[Tuple] = []  # (QGroupBox, [_HotkeyRow])

        root = QVBoxLayout(self)

        # --- Search field ---
        search_row = QHBoxLayout()
        search_lbl = QLabel(_("Suche:"))
        self._search = QLineEdit()
        self._search.setPlaceholderText(_("Stichwort zum Filtern…"))
        self._search.setAccessibleName(_("Tastenkürzel suchen"))
        self._search.textChanged.connect(self._on_search_changed)
        clear_btn = QPushButton(_("Such&e löschen"))
        clear_btn.setAccessibleName(_("Suche löschen"))
        clear_btn.clicked.connect(self._search.clear)
        search_row.addWidget(search_lbl)
        search_row.addWidget(self._search, 1)
        search_row.addWidget(clear_btn)
        root.addLayout(search_row)

        # --- Scrolled content ---
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        inner_layout = QVBoxLayout(inner)

        for cat_name, entries in _INAPP_CATEGORIES:
            tr_cat = _(cat_name)
            group = QGroupBox(tr_cat)
            group.setAccessibleName(tr_cat)
            group_layout = QVBoxLayout(group)
            cat_rows = []
            for label, key in entries:
                row = _HotkeyRow(group, label, key, False, window)
                group_layout.addWidget(row)
                cat_rows.append(row)
                self._rows.append(row)
            inner_layout.addWidget(group)
            self._sections.append((group, cat_rows))

        # --- Global hotkeys (macOS only) ---
        if sys.platform == "darwin":
            from PySide6.QtWidgets import QCheckBox
            global_group = QGroupBox(_("Globale Hotkeys (systemweit, auch wenn App im Hintergrund)"))
            global_layout = QVBoxLayout(global_group)
            self._global_enable = QCheckBox(_("&Globale Hotkeys aktivieren"))
            self._global_enable.setChecked(bool(window.settings_store.settings.global_hotkeys_enabled))
            self._global_enable.stateChanged.connect(self._on_global_enable_changed)
            global_layout.addWidget(self._global_enable)
            for label, key in [(_("PTT (Sprechtaste)"), "global_hotkey_ptt"),
                                (_("Stummschalten umschalten"), "global_hotkey_mute")]:
                row = _HotkeyRow(global_group, label, key, True, window)
                global_layout.addWidget(row)
                self._global_rows.append(row)
            inner_layout.addWidget(global_group)

        inner_layout.addStretch()
        scroll.setWidget(inner)
        root.addWidget(scroll, 1)

        # --- Bottom toolbar ---
        bottom_row = QHBoxLayout()
        export_btn = QPushButton(_("Profil &exportieren"))
        export_btn.setAccessibleName(_("Tastenkürzel-Profil exportieren"))
        export_btn.clicked.connect(self._on_export_profile)
        import_btn = QPushButton(_("Profil &importieren"))
        import_btn.setAccessibleName(_("Tastenkürzel-Profil importieren"))
        import_btn.clicked.connect(self._on_import_profile)
        reset_all_btn = QPushButton(_("A&lle zurücksetzen"))
        reset_all_btn.setAccessibleName(_("Alle Tastenkürzel zurücksetzen"))
        reset_all_btn.clicked.connect(self._on_reset_all)
        bottom_row.addWidget(export_btn)
        bottom_row.addWidget(import_btn)
        bottom_row.addWidget(reset_all_btn)
        bottom_row.addStretch()
        root.addLayout(bottom_row)

        self.update_labels()

    def _on_search_changed(self, text: str) -> None:
        q = text.strip().lower()
        for group, cat_rows in self._sections:
            any_visible = False
            for row in cat_rows:
                visible = not q or q in row._label_text.lower()
                row.setVisible(visible)
                if visible:
                    any_visible = True
            group.setVisible(any_visible)

    def update_labels(self) -> None:
        settings = self.window.settings_store.settings
        for row in self._rows:
            keycode = int(getattr(settings, row._key, 0) or 0)
            row.status.setText(self._format_keycode(keycode))
        for row in self._global_rows:
            vk = int(getattr(settings, row._key, 0) or 0)
            row.status.setText(self._format_vk(vk))

    def set_capture_label(self, key: str, capturing: bool) -> None:
        for row in self._rows:
            if row._key == key:
                row.status.setText(_("(Taste drücken...)") if capturing else _("(nicht gesetzt)"))
                if not capturing:
                    self.update_labels()
                return

    def set_global_capture_label(self, key: str, capturing: bool) -> None:
        for row in self._global_rows:
            if row._key == key:
                row.status.setText(_("(Taste drücken...)") if capturing else _("(nicht gesetzt)"))
                if not capturing:
                    self.update_labels()
                return

    def _on_global_enable_changed(self, *_) -> None:
        if self._global_enable:
            self.window.settings_store.settings.global_hotkeys_enabled = self._global_enable.isChecked()
            self.window.settings_store.save()
            self.window.apply_global_hotkeys()

    def _format_keycode(self, keycode: int) -> str:
        if not keycode:
            return _("(nicht gesetzt)")
        key = Qt.Key(keycode)
        if key == Qt.Key.Key_Space:
            return _("Leertaste")
        if Qt.Key.Key_F1 <= key <= Qt.Key.Key_F24:
            return f"F{keycode - Qt.Key.Key_F1.value + 1}"
        if 0x20 <= keycode <= 0x7E:
            return chr(keycode).upper()
        return str(keycode)

    def _format_vk(self, vk: int) -> str:
        if not vk:
            return _("(nicht gesetzt)")
        if sys.platform == "win32":
            try:
                from win32_hotkeys import win32_vk_to_name
                return win32_vk_to_name(vk)
            except Exception:
                return f"VK-{vk:#04x}"
        try:
            from global_hotkeys import vk_to_name
            return vk_to_name(vk)
        except Exception:
            return f"VK-{vk:#04x}"

    def _on_reset_all(self) -> None:
        answer = QMessageBox.question(
            self, _("Alle zurücksetzen"),
            _("Alle Tastenkürzel auf '(nicht gesetzt)' zurücksetzen?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        s = self.window.settings_store.settings
        for f in dataclasses.fields(s):
            if f.name.startswith("hotkey_") or f.name.startswith("global_hotkey_"):
                setattr(s, f.name, 0)
        self.window.settings_store.save()
        self.update_labels()
        self.window.set_status(_("Alle Tastenkürzel zurückgesetzt"))

    def _on_export_profile(self) -> None:
        s = self.window.settings_store.settings
        profile = {
            f.name: getattr(s, f.name)
            for f in dataclasses.fields(s)
            if f.name.startswith("hotkey_") or f.name.startswith("global_hotkey_")
        }
        path, _flt = QFileDialog.getSaveFileName(
            self, _("Tastenkürzel-Profil exportieren"), "shortcuts_profil.json",
            _("JSON-Profil (*.json);;Alle Dateien (*.*)")
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(profile, f, indent=2, ensure_ascii=False)
            self.window.set_status(f"Profil exportiert: {path}")
        except Exception as exc:
            self.window.set_status(f"Export fehlgeschlagen: {exc}")

    def _on_import_profile(self) -> None:
        path, _flt = QFileDialog.getOpenFileName(
            self, _("Tastenkürzel-Profil importieren"), "",
            _("JSON-Profil (*.json);;Alle Dateien (*.*)")
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                profile = json.load(f)
        except Exception as exc:
            self.window.set_status(f"Import fehlgeschlagen: {exc}")
            return
        s = self.window.settings_store.settings
        valid_keys = {
            f.name for f in dataclasses.fields(s)
            if f.name.startswith("hotkey_") or f.name.startswith("global_hotkey_")
        }
        count = 0
        for key, value in profile.items():
            if key in valid_keys:
                try:
                    setattr(s, key, int(value or 0))
                    count += 1
                except Exception:
                    pass
        self.window.settings_store.save()
        self.update_labels()
        self.window.set_status(f"Profil importiert: {count} Tastenkürzel übernommen")
