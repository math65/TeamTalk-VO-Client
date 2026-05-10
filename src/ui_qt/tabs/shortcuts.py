from __future__ import annotations

import json
import dataclasses
import sys
from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QPushButton, QLabel, QFileDialog, QScrollArea,
)
from PySide6.QtCore import Qt

if TYPE_CHECKING:
    from app_qt import MainWindow


class _HotkeyRow(QWidget):
    def __init__(self, parent, label: str, key: str, global_key: bool, window: "MainWindow") -> None:
        super().__init__(parent)
        self._key = key
        self._global = global_key
        self._window = window
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel(label)
        lbl.setMinimumWidth(260)
        self.status = QLabel("(nicht gesetzt)")
        self.status.setObjectName(f"{label} Hotkey")
        btn = QPushButton("&Hotkey aufnehmen")
        if global_key:
            btn.clicked.connect(lambda: window.start_global_hotkey_capture(key))
        else:
            btn.clicked.connect(lambda: window.start_hotkey_capture(key))
        layout.addWidget(lbl)
        layout.addWidget(self.status, 1)
        layout.addWidget(btn)


class ShortcutsTab(QWidget):
    """Tab 11: Tastenkürzel."""

    def __init__(self, parent: QWidget, window: "MainWindow") -> None:
        super().__init__(parent)
        self.window = window
        self._rows: list[_HotkeyRow] = []
        self._global_rows: list[_HotkeyRow] = []
        self._global_enable = None

        root = QVBoxLayout(self)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        inner_layout = QVBoxLayout(inner)

        inapp_group = QGroupBox("App-Hotkeys (nur innerhalb der App)")
        inapp_layout = QVBoxLayout(inapp_group)
        definitions = [
            ("Alles stummschalten", "hotkey_mute_all"),
            ("Sprachaktivierung umschalten", "hotkey_voice_activation"),
            ("Video senden umschalten", "hotkey_video_tx"),
            ("Eingangspegel ansagen", "hotkey_announce_level"),
            ("Nutzerinfo ansagen", "hotkey_announce_user_info"),
            ("Ping ansagen", "hotkey_announce_ping"),
            ("Privatantwort (letzter Absender)", "hotkey_reply_last_sender"),
            ("Sound-Profil wechseln", "hotkey_cycle_sound_profile"),
            ("Braille-Verbosität wechseln", "hotkey_cycle_braille_verbosity"),
            ("KI-Zusammenfassung ansagen", "hotkey_ai_summary"),
            ("Lesezeichen 1 springen", "hotkey_bookmark_1"),
            ("Lesezeichen 2 springen", "hotkey_bookmark_2"),
            ("Lesezeichen 3 springen", "hotkey_bookmark_3"),
            ("Lesezeichen 4 springen", "hotkey_bookmark_4"),
            ("Lesezeichen 5 springen", "hotkey_bookmark_5"),
            ("Lesezeichen 6 springen", "hotkey_bookmark_6"),
            ("Lesezeichen 7 springen", "hotkey_bookmark_7"),
            ("Lesezeichen 8 springen", "hotkey_bookmark_8"),
            ("Lesezeichen 9 springen", "hotkey_bookmark_9"),
            ("Aufnahme umschalten", "hotkey_record_toggle"),
            ("KI-Antwortvorschläge", "hotkey_ai_reply_suggestions"),
            ("Status-Vorlage 1", "hotkey_status_template_1"),
            ("Status-Vorlage 2", "hotkey_status_template_2"),
            ("Status-Vorlage 3", "hotkey_status_template_3"),
            ("Mikrofon-Boost hoch", "hotkey_mic_boost_up"),
            ("Mikrofon-Boost runter", "hotkey_mic_boost_down"),
            ("TTS abbrechen", "hotkey_tts_cancel"),
            ("Braille-Status ansagen", "hotkey_announce_status"),
        ]
        for label, key in definitions:
            row = _HotkeyRow(inapp_group, label, key, False, window)
            self._rows.append(row)
            inapp_layout.addWidget(row)
        inner_layout.addWidget(inapp_group)

        # Global hotkeys (macOS only — on Windows/Linux these don't apply)
        if sys.platform == "darwin":
            global_group = QGroupBox("Globale Hotkeys (systemweit)")
            global_layout = QVBoxLayout(global_group)
            from PySide6.QtWidgets import QCheckBox
            self._global_enable = QCheckBox("&Globale Hotkeys aktivieren")
            self._global_enable.setChecked(bool(window.settings_store.settings.global_hotkeys_enabled))
            self._global_enable.stateChanged.connect(self._on_global_enable_changed)
            global_layout.addWidget(self._global_enable)
            for label, key in [("PTT (Sprechtaste)", "global_hotkey_ptt"),
                                ("Stummschalten umschalten", "global_hotkey_mute")]:
                row = _HotkeyRow(global_group, label, key, True, window)
                self._global_rows.append(row)
                global_layout.addWidget(row)
            inner_layout.addWidget(global_group)

        # Profile import/export
        profile_group = QGroupBox("Profil Import/Export")
        profile_layout = QHBoxLayout(profile_group)
        export_btn = QPushButton("Profil &exportieren")
        export_btn.clicked.connect(self._on_export_profile)
        import_btn = QPushButton("Profil &importieren")
        import_btn.clicked.connect(self._on_import_profile)
        profile_layout.addWidget(export_btn)
        profile_layout.addWidget(import_btn)
        profile_layout.addStretch()
        inner_layout.addWidget(profile_group)
        inner_layout.addStretch()

        scroll.setWidget(inner)
        root.addWidget(scroll)
        self.update_labels()

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
                row.status.setText("(Taste drücken...)" if capturing else "(nicht gesetzt)")
                if not capturing:
                    self.update_labels()
                return

    def set_global_capture_label(self, key: str, capturing: bool) -> None:
        for row in self._global_rows:
            if row._key == key:
                row.status.setText("(Taste drücken...)" if capturing else "(nicht gesetzt)")
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
            return "(nicht gesetzt)"
        key = Qt.Key(keycode)
        if key == Qt.Key.Key_Space:
            return "Leertaste"
        if Qt.Key.Key_F1 <= key <= Qt.Key.Key_F24:
            return f"F{keycode - Qt.Key.Key_F1.value + 1}"
        if 0x20 <= keycode <= 0x7E:
            return chr(keycode).upper()
        return str(keycode)

    def _format_vk(self, vk: int) -> str:
        if not vk:
            return "(nicht gesetzt)"
        try:
            from global_hotkeys import vk_to_name
            return vk_to_name(vk)
        except Exception:
            return f"VK-{vk:#04x}"

    def _on_export_profile(self) -> None:
        s = self.window.settings_store.settings
        profile = {
            f.name: getattr(s, f.name)
            for f in dataclasses.fields(s)
            if f.name.startswith("hotkey_") or f.name.startswith("global_hotkey_")
        }
        path, _ = QFileDialog.getSaveFileName(
            self, "Tastenkürzel-Profil exportieren", "shortcuts_profil.json",
            "JSON-Profil (*.json);;Alle Dateien (*.*)"
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
        path, _ = QFileDialog.getOpenFileName(
            self, "Tastenkürzel-Profil importieren", "",
            "JSON-Profil (*.json);;Alle Dateien (*.*)"
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
