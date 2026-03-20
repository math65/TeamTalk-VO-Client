from __future__ import annotations

from typing import TYPE_CHECKING

import wx

from ui.a11y import setup_list_accessible

if TYPE_CHECKING:
    from app import MainFrame


class SystemTab(wx.Panel):
    """Systemmeldungen + TTS Einstellungen."""

    def __init__(self, parent: wx.Window, frame: MainFrame) -> None:
        super().__init__(parent)
        self.frame = frame
        self.SetName("System & TTS")
        self._voice_labels = []
        self._voice_label_to_id = {}

        sizer = wx.BoxSizer(wx.VERTICAL)

        # System log
        sys_box = wx.StaticBox(self, label="Systemmeldungen")
        sys_sizer = wx.StaticBoxSizer(sys_box, wx.VERTICAL)
        self.system_log = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2)
        self.system_log.SetName("Systemmeldungen")
        sys_sizer.Add(self.system_log, 1, wx.ALL | wx.EXPAND, 6)
        sizer.Add(sys_sizer, 1, wx.ALL | wx.EXPAND, 8)

        # TTS settings
        tts_box = wx.StaticBox(self, label="Sprachausgabe (espeak-ng)")
        tts_sizer = wx.StaticBoxSizer(tts_box, wx.VERTICAL)

        row1 = wx.BoxSizer(wx.HORIZONTAL)
        self.tts_enabled = wx.CheckBox(self, label="TTS aktiv")
        self.tts_enabled.SetName("TTS aktiv")
        self.tts_interrupt = wx.CheckBox(self, label="Neue Meldung unterbricht")
        self.tts_interrupt.SetName("TTS unterbrechen")
        row1.Add(self.tts_enabled, 0, wx.RIGHT, 12)
        row1.Add(self.tts_interrupt, 0)
        tts_sizer.Add(row1, 0, wx.ALL, 6)

        row2 = wx.BoxSizer(wx.HORIZONTAL)
        self.tts_chat = wx.CheckBox(self, label="Chat vorlesen")
        self.tts_chat.SetName("Chat vorlesen")
        self.tts_private = wx.CheckBox(self, label="Privat vorlesen")
        self.tts_private.SetName("Privat vorlesen")
        self.tts_system = wx.CheckBox(self, label="System vorlesen")
        self.tts_system.SetName("System vorlesen")
        self.tts_own = wx.CheckBox(self, label="Eigene Nachrichten vorlesen")
        self.tts_own.SetName("Eigene Nachrichten vorlesen")
        row2.Add(self.tts_chat, 0, wx.RIGHT, 12)
        row2.Add(self.tts_private, 0, wx.RIGHT, 12)
        row2.Add(self.tts_system, 0, wx.RIGHT, 12)
        row2.Add(self.tts_own, 0)
        tts_sizer.Add(row2, 0, wx.ALL, 6)

        grid = wx.FlexGridSizer(cols=2, vgap=6, hgap=8)
        grid.AddGrowableCol(1)

        grid.Add(wx.StaticText(self, label="Sprache"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.tts_language = wx.Choice(self)
        self.tts_language.SetName("TTS Sprache")
        grid.Add(self.tts_language, 1, wx.EXPAND)

        grid.Add(wx.StaticText(self, label="Stimmenfilter"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.tts_voice_filter = wx.TextCtrl(self)
        self.tts_voice_filter.SetName("TTS Stimme Filter")
        grid.Add(self.tts_voice_filter, 1, wx.EXPAND)

        grid.Add(wx.StaticText(self, label="Stimme"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.tts_voice = wx.ListBox(self)
        self.tts_voice.SetName("TTS Stimme")
        setup_list_accessible(self.tts_voice)
        grid.Add(self.tts_voice, 1, wx.EXPAND)

        grid.Add(wx.StaticText(self, label="Sprechtempo (80–400)"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.tts_rate = wx.SpinCtrl(self, value="175", min=80, max=400)
        self.tts_rate.SetName("TTS Sprechtempo")
        grid.Add(self.tts_rate, 1, wx.EXPAND)

        grid.Add(wx.StaticText(self, label="Lautstärke (0–200)"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.tts_volume = wx.SpinCtrl(self, value="100", min=0, max=200)
        self.tts_volume.SetName("TTS Lautstärke")
        grid.Add(self.tts_volume, 1, wx.EXPAND)

        grid.Add(wx.StaticText(self, label="espeak-ng Pfad"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.tts_path = wx.TextCtrl(self)
        self.tts_path.SetName("espeak-ng Pfad")
        grid.Add(self.tts_path, 1, wx.EXPAND)

        tts_sizer.Add(grid, 0, wx.ALL | wx.EXPAND, 6)

        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        self.tts_refresh = wx.Button(self, label="Stimmen aktualisieren")
        self.tts_refresh.SetName("Stimmen aktualisieren")
        self.tts_test = wx.Button(self, label="Test vorlesen")
        self.tts_test.SetName("TTS Test")
        btn_row.Add(self.tts_refresh, 0, wx.RIGHT, 8)
        btn_row.Add(self.tts_test, 0)
        tts_sizer.Add(btn_row, 0, wx.ALL, 6)

        sizer.Add(tts_sizer, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)

        self.SetSizer(sizer)


        self._bind_events()
        self._sync_from_manager()

    def _bind_events(self):
        self.tts_enabled.Bind(wx.EVT_CHECKBOX, self._on_enable_changed)
        self.tts_interrupt.Bind(wx.EVT_CHECKBOX, self._apply_settings)
        self.tts_chat.Bind(wx.EVT_CHECKBOX, self._apply_settings)
        self.tts_private.Bind(wx.EVT_CHECKBOX, self._apply_settings)
        self.tts_system.Bind(wx.EVT_CHECKBOX, self._apply_settings)
        self.tts_own.Bind(wx.EVT_CHECKBOX, self._apply_settings)
        self.tts_language.Bind(wx.EVT_CHOICE, self._refresh_voices)
        self.tts_voice_filter.Bind(wx.EVT_TEXT, self._refresh_voices)
        self.tts_voice.Bind(wx.EVT_LISTBOX, self._apply_settings)
        self.tts_rate.Bind(wx.EVT_SPINCTRL, self._apply_settings)
        self.tts_volume.Bind(wx.EVT_SPINCTRL, self._apply_settings)
        self.tts_path.Bind(wx.EVT_TEXT, self._apply_settings)
        self.tts_refresh.Bind(wx.EVT_BUTTON, lambda e: self._refresh_voices(e, force=True))
        self.tts_test.Bind(wx.EVT_BUTTON, self._on_test)

    def _sync_from_manager(self):
        s = self.frame.tts.settings
        self.tts_enabled.SetValue(s.enabled)
        self.tts_interrupt.SetValue(s.interrupt)
        self.tts_chat.SetValue(s.speak_chat)
        self.tts_private.SetValue(s.speak_private)
        self.tts_system.SetValue(s.speak_system)
        self.tts_own.SetValue(s.speak_own)
        if s.enabled:
            self._refresh_languages(force=True)
            # Default to "Alle" if language not set
            self._set_language_value(s.language)
            self._refresh_voices(None, force=True)
            self._set_voice_value(s.voice)
        else:
            # Avoid touching voice data until user enables TTS
            self.tts_language.Set(["Alle", "de"])
            self._set_language_value(s.language or "de")
            self.tts_voice.Set([])
        self.tts_rate.SetValue(s.rate)
        self.tts_volume.SetValue(s.volume)
        self.tts_path.SetValue(s.espeak_path)

    def _apply_settings(self, _event):
        s = self.frame.tts.settings
        s.enabled = self.tts_enabled.GetValue()
        s.interrupt = self.tts_interrupt.GetValue()
        s.speak_chat = self.tts_chat.GetValue()
        s.speak_private = self.tts_private.GetValue()
        s.speak_system = self.tts_system.GetValue()
        s.speak_own = self.tts_own.GetValue()
        s.language = self._get_language_value() or "de"
        s.voice = self._get_voice_value()
        s.rate = self.tts_rate.GetValue()
        s.volume = self.tts_volume.GetValue()
        s.espeak_path = self.tts_path.GetValue().strip()

    def _refresh_voices(self, _event, force: bool = False):
        if not self.tts_enabled.GetValue() and not force:
            return
        voices = self.frame.tts.list_voices()
        if not voices:
            voices = [
                {"language": "de", "age_gender": "--/M", "voice": "de", "file": "de"},
                {"language": "en", "age_gender": "--/M", "voice": "en", "file": "en"},
                {"language": "en-us", "age_gender": "--/M", "voice": "en-us", "file": "en-us"},
            ]
        self._voice_items = voices
        lang = self._get_language_value()
        labels = []
        self._voice_label_to_id = {}
        for v in voices:
            if lang in ("de", "de+variant"):
                if v["language"] not in ("de", "variant"):
                    continue
            elif lang and v["language"] != lang:
                continue
            tag = v.get("tag", "")
            tag_txt = f" {tag}" if tag else ""
            label = f"{v['voice']} [{v['language']}] ({v['age_gender']}){tag_txt}"
            labels.append(label)
            self._voice_label_to_id[label] = v["voice"]
        filt = self.tts_voice_filter.GetValue().strip().lower()
        if filt:
            labels = [label_item for label_item in labels if filt in label_item.lower()]
        self._voice_labels = labels
        self.tts_voice.Set(labels)
        if not labels and self._get_language_value():
            self._set_language_value("")
            return self._refresh_voices(None)
        self._set_voice_value(self.frame.tts.settings.voice)

    def _refresh_languages(self, force: bool = False):
        if not self.tts_enabled.GetValue() and not force:
            return
        langs = self.frame.tts.list_languages()
        if not langs:
            langs = ["de", "en", "en-us"]
        langs = sorted(set(langs))
        # Add helper entries
        all_label = "Alle"
        variant_label = "Varianten"
        de_all_label = "de + Varianten"
        if "variant" in langs:
            langs = [all_label, variant_label, de_all_label] + [lang_item for lang_item in langs if lang_item != "variant"]
        else:
            langs = [all_label, de_all_label] + langs
        self._lang_items = langs
        current = self.tts_language.GetStringSelection().strip()
        self.tts_language.Set(langs)
        if current in langs:
            self.tts_language.SetStringSelection(current)
        else:
            self._set_language_value(self.frame.tts.settings.language)

    def _get_language_value(self) -> str:
        val = self.tts_language.GetStringSelection().strip()
        if val == "Alle":
            return ""
        if val == "Varianten":
            return "variant"
        if val == "de + Varianten":
            return "de+variant"
        return val

    def _set_language_value(self, lang: str) -> None:
        if not lang:
            self.tts_language.SetStringSelection("Alle")
        elif lang == "variant":
            self.tts_language.SetStringSelection("Varianten")
        elif lang == "de+variant":
            self.tts_language.SetStringSelection("de + Varianten")
        else:
            self.tts_language.SetStringSelection(lang)

    def _on_enable_changed(self, event):
        self._apply_settings(event)
        if self.tts_enabled.GetValue():
            # Copy bundled espeak-ng into App Support once to avoid repeated prompts
            self.frame.tts.ensure_local_espeak()
            self._refresh_languages(force=True)
            self._refresh_voices(None, force=True)

    def _get_voice_value(self) -> str:
        idx = self.tts_voice.GetSelection()
        if idx == wx.NOT_FOUND or idx >= len(self._voice_labels):
            return ""
        label = self._voice_labels[idx]
        return self._voice_label_to_id.get(label, label)

    def _set_voice_value(self, voice: str) -> None:
        if not voice:
            return
        for idx, label in enumerate(self._voice_labels):
            vid = self._voice_label_to_id.get(label)
            if vid == voice:
                self.tts_voice.SetSelection(idx)
                return
        # Fallback: select first item if available
        if self._voice_labels:
            self.tts_voice.SetSelection(0)

    def _on_test(self, _event):
        self.frame.tts.speak("Das ist ein TTS Test", kind="system")

    def append_system(self, text: str) -> None:
        self.system_log.AppendText(text + "\n")


