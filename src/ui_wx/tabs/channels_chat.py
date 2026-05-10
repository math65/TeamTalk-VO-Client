from __future__ import annotations

from typing import TYPE_CHECKING, List

import wx

from ui_wx.tabs.channels import ChannelsTab
from ui_wx.tabs.chat import ChatTab

if TYPE_CHECKING:
    from app import MainFrame

_MAX_TRANSCRIPT_LINES = 50


class ChannelsChatTab(wx.Panel):
    """Combined tab: channels (tree, always visible) + chat below."""

    def __init__(self, parent: wx.Window, frame: MainFrame) -> None:
        super().__init__(parent)
        self.frame = frame
        self.SetName("Kanäle und Chat")
        self._transcript_lines: List[str] = []

        sizer = wx.BoxSizer(wx.VERTICAL)

        # Kanalbaum – nimmt 60 % der verfügbaren Höhe (proportion=3)
        self.channels_tab = ChannelsTab(self, frame)
        sizer.Add(self.channels_tab, 3, wx.LEFT | wx.RIGHT | wx.TOP | wx.EXPAND, 8)

        # Trennlinie
        sizer.Add(wx.StaticLine(self), 0, wx.LEFT | wx.RIGHT | wx.EXPAND, 8)

        # Chat – nimmt 40 % der verfügbaren Höhe (proportion=2)
        self.chat_tab = ChatTab(self, frame)
        sizer.Add(self.chat_tab, 2, wx.LEFT | wx.RIGHT | wx.EXPAND, 8)

        # --- Transkriptions-Panel (v2.0.1, standardmäßig versteckt) ---
        self._trans_panel = wx.Panel(self)
        self._trans_panel.SetName("Transkription")
        trans_sizer = wx.BoxSizer(wx.VERTICAL)

        trans_header = wx.BoxSizer(wx.HORIZONTAL)
        trans_label = wx.StaticText(self._trans_panel, label="Live-Transkription")
        trans_label.SetName("Transkription")
        self._trans_toggle_btn = wx.Button(self._trans_panel, label="&Ausblenden")
        self._trans_toggle_btn.SetName("Transkription ausblenden")
        self._trans_toggle_btn.Bind(wx.EVT_BUTTON, self._on_trans_toggle)
        self._trans_clear_btn = wx.Button(self._trans_panel, label="&Leeren")
        self._trans_clear_btn.SetName("Transkription leeren")
        self._trans_clear_btn.Bind(wx.EVT_BUTTON, self._on_trans_clear)
        self._trans_export_btn = wx.Button(self._trans_panel, label="&Exportieren")
        self._trans_export_btn.SetName("Transkription exportieren")
        self._trans_export_btn.Bind(wx.EVT_BUTTON, self._on_trans_export)
        trans_header.Add(trans_label, 1, wx.ALIGN_CENTER_VERTICAL)
        trans_header.Add(self._trans_toggle_btn, 0, wx.RIGHT, 4)
        trans_header.Add(self._trans_clear_btn, 0, wx.RIGHT, 4)
        trans_header.Add(self._trans_export_btn, 0)
        trans_sizer.Add(trans_header, 0, wx.ALL | wx.EXPAND, 4)

        self._trans_text = wx.TextCtrl(
            self._trans_panel,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2,
        )
        self._trans_text.SetName("Transkriptions-Text")
        self._trans_text.SetMinSize((-1, 80))
        trans_sizer.Add(self._trans_text, 1, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 4)

        self._trans_panel.SetSizer(trans_sizer)
        self._trans_panel.Show(False)
        sizer.Add(self._trans_panel, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)

        self.SetSizer(sizer)

        # Bus-Event abonnieren sobald Bus verfügbar ist
        wx.CallAfter(self._subscribe_bus)

    def _subscribe_bus(self) -> None:
        """Abonniert transcription_result und transcription_model_loaded auf dem Bus."""
        try:
            self.frame.bus.on("transcription_result", self._on_transcription_result)
            self.frame.bus.on("transcription_model_loaded", self._on_transcription_model_loaded)
        except Exception:
            pass

    def show_transcription_panel(self, show: bool = True) -> None:
        """Blendet das Transkriptions-Panel ein oder aus."""
        self._trans_panel.Show(show)
        self._trans_toggle_btn.SetLabel("&Ausblenden" if show else "&Einblenden")
        self.Layout()

    def _on_trans_toggle(self, _event) -> None:
        visible = self._trans_panel.IsShown()
        self.show_transcription_panel(not visible)

    def _on_trans_clear(self, _event) -> None:
        self._transcript_lines.clear()
        self._trans_text.SetValue("")

    def _on_trans_export(self, _event) -> None:
        """Exportiert alle Transkriptions-Zeilen als TXT-Datei."""
        if not self._transcript_lines:
            self.frame.set_status("Keine Transkription zum Exportieren")
            return
        import time as _time
        default_name = f"transkription_{_time.strftime('%Y%m%d_%H%M%S')}.txt"
        with wx.FileDialog(
            self,
            "Transkription exportieren",
            wildcard="Textdateien (*.txt)|*.txt|Alle Dateien|*.*",
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
            defaultFile=default_name,
        ) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            path = dlg.GetPath()
        try:
            content = "\n".join(self._transcript_lines)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            self.frame.set_status(f"Transkription exportiert: {path}")
        except Exception as exc:
            self.frame.set_status(f"Export fehlgeschlagen: {exc}")

    def _on_transcription_result(self, text: str, language: str = "de") -> None:
        """Empfängt ein Transkriptions-Ergebnis vom Bus (aus Hintergrundthread)."""
        wx.CallAfter(self._append_transcript, text)

    def _on_transcription_model_loaded(self, model: str = "") -> None:
        """Zeigt das Transkriptions-Panel wenn das Modell geladen ist."""
        wx.CallAfter(self.show_transcription_panel, True)

    def _append_transcript(self, text: str) -> None:
        """Fügt eine Zeile zum Transkriptions-Text hinzu."""
        text = text.strip()
        if not text:
            return
        import time as _time
        ts = _time.strftime("%H:%M")
        line = f"[{ts}] {text}"
        self._transcript_lines.append(line)
        # Puffer begrenzen
        if len(self._transcript_lines) > _MAX_TRANSCRIPT_LINES:
            self._transcript_lines = self._transcript_lines[-_MAX_TRANSCRIPT_LINES:]
        self._trans_text.SetValue("\n".join(self._transcript_lines))
        self._trans_text.SetInsertionPointEnd()
        # Panel einblenden wenn versteckt
        if not self._trans_panel.IsShown():
            self.show_transcription_panel(True)
