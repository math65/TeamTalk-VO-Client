from __future__ import annotations

from typing import Optional, TYPE_CHECKING

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGroupBox, QFormLayout,
    QLabel, QLineEdit, QCheckBox, QComboBox, QSpinBox,
    QDialogButtonBox, QScrollArea, QWidget, QListWidget,
)
from PySide6.QtCore import Qt

if TYPE_CHECKING:
    from app_qt import MainWindow


class ChannelDialog(QDialog):
    """Kanal erstellen oder bearbeiten."""

    def __init__(
        self,
        parent: "MainWindow",
        *,
        title: str = "Kanal",
        name: str = "",
        topic: str = "",
        permanent: bool = False,
        allow_password: bool = True,
        channel_type: int = 0,
        disk_quota_mb: int = 0,
        max_users: int = 0,
        op_password: str = "",
        audio_codec_mode: str = "inherit",
        audio_codec_locked: bool = False,
        edit_mode: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(460)
        self.resize(520, 640)
        self._window = parent

        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        root = QVBoxLayout(content)
        root.setContentsMargins(8, 8, 8, 8)
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)

        # ── Grunddaten ────────────────────────────────────────────────
        base_group = QGroupBox("Grunddaten")
        base_form = QFormLayout(base_group)

        self.name_edit = QLineEdit(name)
        self.name_edit.setPlaceholderText("Kanalname (Pflichtfeld)")
        self.name_edit.setAccessibleName("Kanalname")
        base_form.addRow(QLabel("Name"), self.name_edit)

        self.topic_edit = QLineEdit(topic)
        self.topic_edit.setAccessibleName("Kanalthema")
        base_form.addRow(QLabel("Thema"), self.topic_edit)

        if allow_password:
            self.pw_check = QCheckBox("Passwort setzen")
            self.pw_check.setAccessibleName("Passwort setzen")
            base_form.addRow(QLabel(""), self.pw_check)
            self.pw_edit = QLineEdit()
            self.pw_edit.setEchoMode(QLineEdit.EchoMode.Password)
            self.pw_edit.setAccessibleName("Kanalpasswort")
            self.pw_edit.setEnabled(False)
            self.pw_check.stateChanged.connect(
                lambda s: self.pw_edit.setEnabled(bool(s))
            )
            base_form.addRow(QLabel("Passwort"), self.pw_edit)
        else:
            self.pw_check = None
            self.pw_edit = None

        self.perm_check = QCheckBox("Permanent")
        self.perm_check.setChecked(permanent)
        self.perm_check.setAccessibleName("Permanenter Kanal")
        base_form.addRow(QLabel(""), self.perm_check)
        root.addWidget(base_group)

        # ── Limits ────────────────────────────────────────────────────
        limits_group = QGroupBox("Limits")
        limits_form = QFormLayout(limits_group)

        self.quota_spin = QSpinBox()
        self.quota_spin.setRange(0, 1024 * 1024)
        self.quota_spin.setValue(int(disk_quota_mb))
        self.quota_spin.setAccessibleName("Datei-Quota MB")
        limits_form.addRow(QLabel("Datei-Quota (MB, 0=aus)"), self.quota_spin)

        self.maxusers_spin = QSpinBox()
        self.maxusers_spin.setRange(0, 10000)
        self.maxusers_spin.setValue(int(max_users))
        self.maxusers_spin.setAccessibleName("Maximale Nutzerzahl")
        limits_form.addRow(QLabel("Max. Benutzer (0=Server)"), self.maxusers_spin)

        self.op_pw_edit = QLineEdit(op_password)
        self.op_pw_edit.setAccessibleName("Operator-Passwort")
        limits_form.addRow(QLabel("Operator-Passwort"), self.op_pw_edit)
        root.addWidget(limits_group)

        # ── Kanaltyp ──────────────────────────────────────────────────
        type_group = QGroupBox("Kanaltyp")
        type_v = QVBoxLayout(type_group)
        tt = parent.client.tt
        self._type_flags: list[tuple[QCheckBox, int]] = []
        for label, flag_attr in [
            ("Nur ein Sprecher gleichzeitig (Solo)", "CHANNEL_SOLO_TRANSMIT"),
            ("Unterrichtsmodus (Operator steuert Sprecher)", "CHANNEL_CLASSROOM"),
            ("Operator nur Empfang", "CHANNEL_OPERATOR_RECVONLY"),
            ("Keine Sprachaktivierung", "CHANNEL_NO_VOICEACTIVATION"),
            ("Keine Aufnahmen", "CHANNEL_NO_RECORDING"),
            ("Versteckter Kanal", "CHANNEL_HIDDEN"),
        ]:
            flag_val = int(getattr(tt.ChannelType, flag_attr, 0))
            cb = QCheckBox(label)
            cb.setChecked(bool(channel_type & flag_val))
            cb.setAccessibleName(label)
            self._type_flags.append((cb, flag_val))
            type_v.addWidget(cb)
        root.addWidget(type_group)

        # ── Audio-Codec ───────────────────────────────────────────────
        codec_group = QGroupBox("Audio-Codec")
        codec_v = QVBoxLayout(codec_group)
        self._codec_choices = [
            ("Vom Elternkanal übernehmen", "inherit"),
            ("Opus (Standard)", "opus"),
            ("Speex (Standard)", "speex"),
            ("Speex VBR (Standard)", "speex_vbr"),
            ("Kein Audio", "none"),
        ]
        if edit_mode:
            self._codec_choices.insert(0, ("Aktueller Codec beibehalten", "keep"))
        self.codec_combo = QComboBox()
        self.codec_combo.setAccessibleName("Audio-Codec")
        for label, _ in self._codec_choices:
            self.codec_combo.addItem(label)
        # Set initial selection
        for idx, (_, key) in enumerate(self._codec_choices):
            if key == audio_codec_mode:
                self.codec_combo.setCurrentIndex(idx)
                break
        self.codec_combo.setEnabled(not audio_codec_locked)
        codec_v.addWidget(self.codec_combo)
        if audio_codec_locked:
            note = QLabel("Audio-Codec kann nicht geändert werden, wenn Nutzer im Kanal sind.")
            note.setWordWrap(True)
            codec_v.addWidget(note)

        # Opus settings
        self._opus_group = QGroupBox("OPUS Einstellungen")
        opus_form = QFormLayout(self._opus_group)
        self.opus_app = QComboBox()
        self.opus_app.addItems(["VoIP", "Musik"])
        opus_form.addRow(QLabel("Anwendung"), self.opus_app)
        self.opus_sr = QComboBox()
        self.opus_sr.addItems(["8000", "12000", "16000", "24000", "48000"])
        self.opus_sr.setCurrentText("48000")
        opus_form.addRow(QLabel("Samplerate (Hz)"), self.opus_sr)
        self.opus_ch = QComboBox()
        self.opus_ch.addItems(["Mono", "Stereo"])
        opus_form.addRow(QLabel("Kanäle"), self.opus_ch)
        self.opus_br = QSpinBox()
        self.opus_br.setRange(6, 510)
        self.opus_br.setValue(64)
        opus_form.addRow(QLabel("Bitrate (kbps)"), self.opus_br)
        self.opus_vbr = QCheckBox("Variable Bitrate (VBR)")
        self.opus_vbr.setChecked(True)
        opus_form.addRow(QLabel(""), self.opus_vbr)
        self.opus_dtx = QCheckBox("Stille ignorieren (DTX)")
        opus_form.addRow(QLabel(""), self.opus_dtx)
        self.opus_tx = QSpinBox()
        self.opus_tx.setRange(20, 1000)
        self.opus_tx.setValue(40)
        opus_form.addRow(QLabel("Intervall (ms)"), self.opus_tx)
        self.opus_frame = QSpinBox()
        self.opus_frame.setRange(2, 60)
        self.opus_frame.setValue(20)
        opus_form.addRow(QLabel("Framegröße (ms)"), self.opus_frame)
        codec_v.addWidget(self._opus_group)

        # Speex settings
        self._speex_group = QGroupBox("Speex Einstellungen")
        speex_form = QFormLayout(self._speex_group)
        self.spx_sr = QComboBox()
        self.spx_sr.addItems(["8000", "16000", "32000"])
        self.spx_sr.setCurrentText("16000")
        speex_form.addRow(QLabel("Samplerate (Hz)"), self.spx_sr)
        self.spx_quality = QSpinBox()
        self.spx_quality.setRange(0, 10)
        self.spx_quality.setValue(4)
        speex_form.addRow(QLabel("Qualität (0–10)"), self.spx_quality)
        self.spx_tx = QSpinBox()
        self.spx_tx.setRange(20, 1000)
        self.spx_tx.setValue(40)
        speex_form.addRow(QLabel("Intervall (ms)"), self.spx_tx)
        self.spx_maxbr = QSpinBox()
        self.spx_maxbr.setRange(0, 128000)
        self.spx_maxbr.setValue(0)
        self.spx_maxbr.setAccessibleName("Max. Bitrate (nur VBR)")
        speex_form.addRow(QLabel("Max. Bitrate (VBR, 0=aus)"), self.spx_maxbr)
        self.spx_dtx = QCheckBox("Stille ignorieren (DTX)")
        speex_form.addRow(QLabel(""), self.spx_dtx)
        codec_v.addWidget(self._speex_group)
        root.addWidget(codec_group)

        self.codec_combo.currentIndexChanged.connect(self._on_codec_changed)
        self._on_codec_changed(self.codec_combo.currentIndex())

        # ── Buttons ───────────────────────────────────────────────────
        bb = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        bb.accepted.connect(self._on_accept)
        bb.rejected.connect(self.reject)
        outer.addWidget(bb)

        self.name_edit.setFocus()

    # ── Codec visibility ─────────────────────────────────────────────

    def _on_codec_changed(self, idx: int) -> None:
        key = self._codec_choices[idx][1] if idx < len(self._codec_choices) else ""
        self._opus_group.setVisible(key == "opus")
        self._speex_group.setVisible(key in ("speex", "speex_vbr"))

    # ── Accept guard ─────────────────────────────────────────────────

    def _on_accept(self) -> None:
        if not self.name_edit.text().strip():
            self.name_edit.setFocus()
            return
        self.accept()

    # ── Result ───────────────────────────────────────────────────────

    def get_data(self) -> dict:
        idx = self.codec_combo.currentIndex()
        codec_mode = self._codec_choices[idx][1] if idx < len(self._codec_choices) else "inherit"
        channel_type = 0
        for cb, flag in self._type_flags:
            if cb.isChecked():
                channel_type |= flag
        return {
            "name": self.name_edit.text().strip(),
            "topic": self.topic_edit.text().strip(),
            "set_password": self.pw_check.isChecked() if self.pw_check else False,
            "password": self.pw_edit.text() if self.pw_edit else "",
            "permanent": self.perm_check.isChecked(),
            "channel_type": channel_type,
            "disk_quota_mb": self.quota_spin.value(),
            "max_users": self.maxusers_spin.value(),
            "op_password": self.op_pw_edit.text().strip(),
            "audio_codec_mode": codec_mode,
            "opus_app": self.opus_app.currentIndex(),
            "opus_samplerate": int(self.opus_sr.currentText()),
            "opus_channels": self.opus_ch.currentIndex() + 1,
            "opus_bitrate": self.opus_br.value(),
            "opus_vbr": self.opus_vbr.isChecked(),
            "opus_dtx": self.opus_dtx.isChecked(),
            "opus_tx_interval": self.opus_tx.value(),
            "opus_frame_size": self.opus_frame.value(),
            "speex_samplerate": int(self.spx_sr.currentText()),
            "speex_quality": self.spx_quality.value(),
            "speex_tx_interval": self.spx_tx.value(),
            "speex_max_bitrate": self.spx_maxbr.value(),
            "speex_dtx": self.spx_dtx.isChecked(),
        }


class MoveUserDialog(QDialog):
    """Benutzer in einen anderen Kanal verschieben."""

    def __init__(self, parent: "MainWindow") -> None:
        super().__init__(parent)
        self.setWindowTitle("Benutzer verschieben")
        self.setMinimumWidth(320)
        self.resize(360, 400)
        self._window = parent
        self._channel_ids: list[int] = []

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Zielkanal wählen:"))
        self.channel_list = QListWidget()
        self.channel_list.setAccessibleName("Kanalliste")
        self.channel_list.itemActivated.connect(self._on_activate)
        layout.addWidget(self.channel_list, 1)

        bb = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        bb.accepted.connect(self._on_accept)
        bb.rejected.connect(self.reject)
        layout.addWidget(bb)

        self._load_channels()
        self.channel_list.setFocus()

    def _load_channels(self) -> None:
        self.channel_list.clear()
        self._channel_ids = []
        try:
            client = self._window.client
            tt_str = self._window.tt_str

            def _add_channel(ch_id: int, depth: int = 0) -> None:
                ch = client.get_channel(ch_id)
                if ch is None:
                    return
                indent = "  " * depth
                name = tt_str(ch.szName) or f"Kanal {ch_id}"
                self.channel_list.addItem(f"{indent}{name}")
                self._channel_ids.append(ch_id)
                try:
                    subs = list(client.get_channel_children(ch_id))
                    for sub in subs:
                        _add_channel(int(sub.nChannelID), depth + 1)
                except Exception:
                    pass

            root_id = client.get_root_channel_id()
            if root_id:
                _add_channel(int(root_id))
        except Exception:
            pass

    def _on_activate(self) -> None:
        self.accept()

    def _on_accept(self) -> None:
        if self.channel_list.currentRow() >= 0:
            self.accept()

    def get_channel_id(self) -> Optional[int]:
        row = self.channel_list.currentRow()
        if 0 <= row < len(self._channel_ids):
            return self._channel_ids[row]
        return None
