"""Per-app audio capture dialog (Windows only).

Hosts a checkable list of audio-producing processes (via ``pycaw``), a
refresh button, a volume slider, a status label, and Apply/Stop/Close
buttons. The mixer it drives feeds captured PCM as a MEDIAFILE stream
through the SDK wrapper.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QSlider, QMessageBox, QDialogButtonBox,
)

from i18n import _
from app_audio_capture import (
    list_audio_processes,
    pycaw_available,
)

if TYPE_CHECKING:
    from app_audio_capture import AppAudioMixer


class AppAudioDialog(QDialog):
    """Dialog for selecting which Windows apps to capture and stream."""

    def __init__(self, parent, mixer: "AppAudioMixer", settings_store) -> None:
        super().__init__(parent)
        self._mixer = mixer
        self._store = settings_store
        self._processes: list[tuple[int, str]] = []

        self.setWindowTitle(_("App-Audio aufnehmen"))
        self.setAccessibleName(_("App-Audio aufnehmen"))
        self.resize(460, 420)

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel(_("Anwendung auswählen") + ":"))

        self._list = QListWidget()
        self._list.setAccessibleName(_("Anwendung auswählen"))
        layout.addWidget(self._list, 1)

        self._hint_label = QLabel("")
        self._hint_label.setWordWrap(True)
        layout.addWidget(self._hint_label)

        refresh_row = QHBoxLayout()
        self._refresh_btn = QPushButton(_("Aktualisieren"))
        self._refresh_btn.setAccessibleName(_("Aktualisieren"))
        self._refresh_btn.clicked.connect(self._on_refresh)
        refresh_row.addWidget(self._refresh_btn)
        refresh_row.addStretch()
        layout.addLayout(refresh_row)

        vol_row = QHBoxLayout()
        vol_label = QLabel(_("Lautstärke") + ":")
        vol_row.addWidget(vol_label)
        self._volume = QSlider(Qt.Horizontal)
        self._volume.setMinimum(0)
        self._volume.setMaximum(200)
        initial_vol = int(getattr(self._store.settings, "app_audio_volume_pct", 100) or 100)
        self._volume.setValue(max(0, min(200, initial_vol)))
        self._volume.setAccessibleName(_("Lautstärke"))
        self._volume.valueChanged.connect(self._on_volume_changed)
        vol_row.addWidget(self._volume, 1)
        layout.addLayout(vol_row)

        self._status_label = QLabel("")
        self._status_label.setAccessibleName(_("Status"))
        layout.addWidget(self._status_label)

        btn_row = QHBoxLayout()
        self._apply_btn = QPushButton(_("Anwenden"))
        self._apply_btn.setAccessibleName(_("Anwenden"))
        self._apply_btn.clicked.connect(self._on_apply)
        btn_row.addWidget(self._apply_btn)

        self._stop_btn = QPushButton(_("Stoppen"))
        self._stop_btn.setAccessibleName(_("Stoppen"))
        self._stop_btn.clicked.connect(self._on_stop)
        btn_row.addWidget(self._stop_btn)

        btn_row.addStretch()

        close_btns = QDialogButtonBox(QDialogButtonBox.Close)
        close_btns.rejected.connect(self.reject)
        btn_row.addWidget(close_btns)

        layout.addLayout(btn_row)

        # Apply current volume to the mixer so live changes work immediately.
        self._mixer.set_volume(self._volume.value() / 100.0)
        self._populate(initial=True)
        self._update_status()
        self._list.setFocus()

    # ── List management ────────────────────────────────────────────────

    def _populate(self, initial: bool = False) -> None:
        # Preserve currently checked PIDs (by name) so a refresh keeps the
        # user's selection even when a process restarts and gets a new PID.
        checked_names: set[str] = set()
        if not initial:
            for i in range(self._list.count()):
                it = self._list.item(i)
                if it.checkState() == Qt.Checked:
                    checked_names.add(it.data(Qt.UserRole + 1) or "")

        active_pids = self._mixer.active_pids

        self._list.clear()
        self._processes = list_audio_processes()

        if not self._processes:
            if pycaw_available():
                self._hint_label.setText(_("Keine Audio-Anwendung gefunden"))
            else:
                self._hint_label.setText(
                    _("Für die App-Liste wird das Paket 'pycaw' benötigt.")
                )
            return

        self._hint_label.setText(
            _("Hinweis: Konflikt möglich mit aktivem Medien-Streaming.")
        )

        for pid, name in self._processes:
            label = f"{name} (PID {pid})"
            it = QListWidgetItem(label)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setData(Qt.UserRole, pid)
            it.setData(Qt.UserRole + 1, name)
            checked = pid in active_pids or name in checked_names
            it.setCheckState(Qt.Checked if checked else Qt.Unchecked)
            self._list.addItem(it)

        if self._list.count() > 0:
            self._list.setCurrentRow(0)

    def _checked_pids(self) -> list[int]:
        pids: list[int] = []
        for i in range(self._list.count()):
            it = self._list.item(i)
            if it.checkState() == Qt.Checked:
                pid = it.data(Qt.UserRole)
                if isinstance(pid, int):
                    pids.append(pid)
        return pids

    # ── Handlers ───────────────────────────────────────────────────────

    def _on_refresh(self) -> None:
        self._populate()

    def _on_volume_changed(self, value: int) -> None:
        self._mixer.set_volume(value / 100.0)
        try:
            self._store.settings.app_audio_volume_pct = int(value)
            self._store.save()
        except Exception:
            pass

    def _on_apply(self) -> None:
        pids = self._checked_pids()
        try:
            ok_pids, errors = self._mixer.set_captures(pids)
        except Exception as e:
            QMessageBox.warning(
                self,
                _("App-Audio aufnehmen"),
                f"{_('Fehler beim Aktivieren der App-Audio-Erfassung')}\n{e}",
            )
            return

        if errors:
            names = {pid: name for pid, name in self._processes}
            lines = [
                f"{names.get(pid, pid)} (PID {pid}): {msg}"
                for pid, msg in errors
            ]
            QMessageBox.warning(
                self,
                _("App-Audio aufnehmen"),
                _("Fehler beim Aktivieren der App-Audio-Erfassung")
                + "\n\n" + "\n".join(lines),
            )

        self._update_status()
        self._announce(_("App-Audio aktiv: {n} Anwendung(en)").format(n=len(ok_pids)))

    def _on_stop(self) -> None:
        self._mixer.stop_all()
        for i in range(self._list.count()):
            self._list.item(i).setCheckState(Qt.Unchecked)
        self._update_status()
        self._announce(_("App-Audio gestoppt"))

    def _update_status(self) -> None:
        n = len(self._mixer.active_pids)
        if n == 0:
            self._status_label.setText(_("App-Audio gestoppt"))
        else:
            self._status_label.setText(
                _("App-Audio aktiv: {n} Anwendung(en)").format(n=n)
            )

    def _announce(self, text: str) -> None:
        """Send a short status to the parent's NVDA live-region helper."""
        parent = self.parent()
        if parent is None:
            return
        announce = getattr(parent, "_sr_announce", None)
        if announce is None:
            return
        try:
            announce(text[:80])
        except Exception:
            pass
