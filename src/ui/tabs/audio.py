from __future__ import annotations

from typing import TYPE_CHECKING

import wx

if TYPE_CHECKING:
    from app import MainFrame


class AudioTab(wx.Panel):
    """Tab 4: Audio -- devices, VU meter, VA, gain, loopback, effects, preprocessing."""

    def __init__(self, parent: wx.Window, frame: MainFrame) -> None:
        super().__init__(parent)
        self.frame = frame
        self.SetName("Audio")
        self._input_devices = []
        self._output_devices = []
        self._loopback_handle = None
        self._last_device_snapshot = ((), ())
        self._last_default_ids = (None, None)

        sizer = wx.BoxSizer(wx.VERTICAL)

        # --- Device selection ---
        dev_form = wx.FlexGridSizer(cols=2, vgap=6, hgap=12)
        dev_form.AddGrowableCol(1)

        # Create label immediately before control for NVDA association
        lbl_in = wx.StaticText(self, label="Eingabegeraet")
        self.input_device = wx.Choice(self)
        self.input_device.SetName("Eingabegeraet")
        lbl_out = wx.StaticText(self, label="Ausgabegeraet")
        self.output_device = wx.Choice(self)
        self.output_device.SetName("Ausgabegeraet")

        dev_form.Add(lbl_in, 0, wx.ALIGN_CENTER_VERTICAL)
        dev_form.Add(self.input_device, 1, wx.EXPAND)
        dev_form.Add(lbl_out, 0, wx.ALIGN_CENTER_VERTICAL)
        dev_form.Add(self.output_device, 1, wx.EXPAND)

        sizer.Add(dev_form, 0, wx.ALL | wx.EXPAND, 8)

        # --- Voice activation & sliders ---
        ctrl_form = wx.FlexGridSizer(cols=2, vgap=6, hgap=12)
        ctrl_form.AddGrowableCol(1)

        # Each label created right before its control
        lbl_va = wx.StaticText(self, label="Voice Activation")
        self.voice_activation = wx.CheckBox(self, label="Voice Activation")
        self.voice_activation.SetName("Voice Activation")
        self.voice_activation.Bind(wx.EVT_CHECKBOX, self.on_voice_activation)

        lbl_vl = wx.StaticText(self, label="Voice Level")
        self.voice_level = wx.Slider(self, value=30, minValue=0, maxValue=100)
        self.voice_level.SetName("Voice Level")
        self.voice_level.Bind(wx.EVT_SLIDER, self.on_voice_level)

        lbl_ig = wx.StaticText(self, label="Mikrofon Gain")
        self.input_gain = wx.Slider(self, value=2000, minValue=0, maxValue=32000)
        self.input_gain.SetName("Mikrofon Gain")
        self.input_gain.Bind(wx.EVT_SLIDER, self.on_input_gain)

        lbl_ov = wx.StaticText(self, label="Ausgabe Lautstaerke")
        self.output_volume = wx.Slider(self, value=1000, minValue=0, maxValue=32000)
        self.output_volume.SetName("Ausgabe Lautstaerke")
        self.output_volume.Bind(wx.EVT_SLIDER, self.on_output_volume)

        ctrl_form.Add(lbl_va, 0, wx.ALIGN_CENTER_VERTICAL)
        ctrl_form.Add(self.voice_activation, 0)
        ctrl_form.Add(lbl_vl, 0, wx.ALIGN_CENTER_VERTICAL)
        ctrl_form.Add(self.voice_level, 1, wx.EXPAND)
        ctrl_form.Add(lbl_ig, 0, wx.ALIGN_CENTER_VERTICAL)
        ctrl_form.Add(self.input_gain, 1, wx.EXPAND)
        ctrl_form.Add(lbl_ov, 0, wx.ALIGN_CENTER_VERTICAL)
        ctrl_form.Add(self.output_volume, 1, wx.EXPAND)

        sizer.Add(ctrl_form, 0, wx.LEFT | wx.RIGHT | wx.EXPAND, 8)

        # --- VU Meter ---
        vu_box = wx.StaticBox(self, label="VU Meter")
        vu_sizer = wx.StaticBoxSizer(vu_box, wx.VERTICAL)
        self.vu_gauge = wx.Gauge(self, range=100)
        self.vu_gauge.SetName("VU Meter")
        vu_sizer.Add(self.vu_gauge, 0, wx.ALL | wx.EXPAND, 4)
        sizer.Add(vu_sizer, 0, wx.ALL | wx.EXPAND, 8)

        # --- VA stop delay ---
        delay_row = wx.BoxSizer(wx.HORIZONTAL)
        lbl_delay = wx.StaticText(self, label="VA Nachlauf (ms)")
        delay_row.Add(lbl_delay, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.va_delay = wx.Slider(self, value=0, minValue=0, maxValue=5000)
        self.va_delay.SetName("VA Nachlauf")
        self.va_delay.Bind(wx.EVT_SLIDER, self.on_va_delay)
        delay_row.Add(self.va_delay, 1, wx.EXPAND)
        sizer.Add(delay_row, 0, wx.LEFT | wx.RIGHT | wx.EXPAND, 8)

        # --- Output mute ---
        self.output_mute = wx.CheckBox(self, label="Ausgabe stummschalten")
        self.output_mute.SetName("Ausgabe stummschalten")
        self.output_mute.Bind(wx.EVT_CHECKBOX, self.on_output_mute)
        sizer.Add(self.output_mute, 0, wx.ALL, 8)

        # --- Device effects ---
        effects_box = wx.StaticBox(self, label="Geraeteeffekte")
        effects_sizer = wx.StaticBoxSizer(effects_box, wx.VERTICAL)
        self.agc_check = wx.CheckBox(self, label="AGC")
        self.agc_check.SetName("AGC")
        self.denoise_check = wx.CheckBox(self, label="Rauschunterdrueckung")
        self.denoise_check.SetName("Rauschunterdrueckung")
        self.echo_check = wx.CheckBox(self, label="Echounterdrueckung")
        self.echo_check.SetName("Echounterdrueckung")
        self.apply_effects_btn = wx.Button(self, label="Effekte anwenden")
        self.apply_effects_btn.SetName("Effekte anwenden")
        self.apply_effects_btn.Bind(wx.EVT_BUTTON, self.on_apply_effects)
        effects_sizer.Add(self.agc_check, 0, wx.ALL, 4)
        effects_sizer.Add(self.denoise_check, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)
        effects_sizer.Add(self.echo_check, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)
        effects_sizer.Add(self.apply_effects_btn, 0, wx.ALL, 4)
        sizer.Add(effects_sizer, 0, wx.LEFT | wx.RIGHT | wx.EXPAND, 8)

        # --- Preprocessing ---
        preprocess_row = wx.BoxSizer(wx.HORIZONTAL)
        lbl_pp = wx.StaticText(self, label="Vorverarbeitung")
        preprocess_row.Add(lbl_pp, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.preprocess_choice = wx.Choice(self, choices=["Keine", "SpeexDSP", "WebRTC"])
        self.preprocess_choice.SetName("Vorverarbeitung")
        self.preprocess_choice.SetSelection(0)
        self.preprocess_choice.Bind(wx.EVT_CHOICE, self.on_preprocess_changed)
        preprocess_row.Add(self.preprocess_choice, 1, wx.EXPAND)
        sizer.Add(preprocess_row, 0, wx.ALL | wx.EXPAND, 8)

        # --- Buttons row ---
        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        self.refresh_audio_btn = wx.Button(self, label="Geraete aktualisieren")
        self.refresh_audio_btn.SetName("Geraete aktualisieren")
        self.refresh_audio_btn.Bind(wx.EVT_BUTTON, self.on_refresh_audio)
        self.apply_audio_btn = wx.Button(self, label="Audio anwenden")
        self.apply_audio_btn.SetName("Audio anwenden")
        self.apply_audio_btn.Bind(wx.EVT_BUTTON, self.on_apply_audio)
        self.ptt_toggle = wx.ToggleButton(self, label="Push-to-Talk (Leertaste halten)")
        self.ptt_toggle.SetName("Push-to-Talk")
        self.ptt_toggle.Bind(wx.EVT_TOGGLEBUTTON, self.on_ptt_toggle)
        self.loopback_toggle = wx.ToggleButton(self, label="Mikrofontest")
        self.loopback_toggle.SetName("Mikrofontest")
        self.loopback_toggle.Bind(wx.EVT_TOGGLEBUTTON, self.on_loopback_toggle)

        btn_row.Add(self.refresh_audio_btn, 0, wx.RIGHT, 8)
        btn_row.Add(self.apply_audio_btn, 0, wx.RIGHT, 8)
        btn_row.Add(self.ptt_toggle, 0, wx.RIGHT, 8)
        btn_row.Add(self.loopback_toggle, 0)
        sizer.Add(btn_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        self.SetSizer(sizer)
        self._set_tab_order()

        # VU timer
        self._vu_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_vu_timer, self._vu_timer)

        # Polling fallback for OS/device changes when SDK hotplug events are missing
        self._device_poll_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_device_poll_timer, self._device_poll_timer)

        self._timers_active = False

        # Init device list
        self.refresh_audio_devices(announce=False)

    def destroy_timers(self):
        self._vu_timer.Stop()
        self._device_poll_timer.Stop()
        if self._loopback_handle is not None:
            self.frame.client.close_sound_loopback_test(self._loopback_handle)
            self._loopback_handle = None

    def set_active(self, active: bool) -> None:
        if active:
            if not self._timers_active:
                # VU updates are only needed while the audio tab is visible.
                self._vu_timer.Start(250)
                # Device polling is only needed while the tab is visible.
                self._device_poll_timer.Start(5000)
                self._timers_active = True
        else:
            if self._timers_active:
                self._vu_timer.Stop()
                self._device_poll_timer.Stop()
                self._timers_active = False

    # --- VU ---

    def _on_vu_timer(self, _event):
        if not self.frame.client.is_connected():
            self.vu_gauge.SetValue(0)
            return
        level = self.frame.client.get_sound_input_level()
        # SDK returns 0-100 (roughly)
        clamped = max(0, min(100, int(level)))
        self.vu_gauge.SetValue(clamped)

    # --- Device refresh & apply ---

    def on_refresh_audio(self, _event):
        self.refresh_audio_devices(announce=True, prefer_previous=True, auto_apply=False, restart_sound=True)

    def refresh_audio_devices(
        self,
        announce: bool = False,
        prefer_previous: bool = True,
        auto_apply: bool = False,
        restart_sound: bool = True,
        _attempt: int = 0,
    ):
        client = self.frame.client
        tt_str = self.frame.tt_str
        prev_in_idx = self.input_device.GetSelection()
        prev_out_idx = self.output_device.GetSelection()
        prev_in_id = None
        prev_out_id = None
        if 0 <= prev_in_idx < len(self._input_devices):
            prev_in_id = int(self._input_devices[prev_in_idx].nDeviceID)
        if 0 <= prev_out_idx < len(self._output_devices):
            prev_out_id = int(self._output_devices[prev_out_idx].nDeviceID)

        restarted = client.restart_sound_system() if restart_sound else True
        devices = list(client.get_sound_devices())
        if not devices and _attempt < 2:
            # Hotplug events can arrive a bit later after restart.
            wx.CallLater(
                200,
                lambda: self.refresh_audio_devices(
                    announce=announce,
                    prefer_previous=prefer_previous,
                    auto_apply=auto_apply,
                    restart_sound=restart_sound,
                    _attempt=_attempt + 1,
                ),
            )
            return
        inputs = [d for d in devices if d.nMaxInputChannels > 0]
        outputs = [d for d in devices if d.nMaxOutputChannels > 0]
        input_labels = [tt_str(d.szDeviceName) for d in inputs]
        output_labels = [tt_str(d.szDeviceName) for d in outputs]
        input_ids = tuple(int(d.nDeviceID) for d in inputs)
        output_ids = tuple(int(d.nDeviceID) for d in outputs)

        input_list_changed = input_ids != tuple(int(d.nDeviceID) for d in self._input_devices)
        output_list_changed = output_ids != tuple(int(d.nDeviceID) for d in self._output_devices)

        self._input_devices = inputs
        self._output_devices = outputs

        if input_list_changed:
            self.input_device.Set(input_labels)
        if output_list_changed:
            self.output_device.Set(output_labels)

        indev, outdev = client.get_default_sound_devices()
        indev_val = getattr(indev, "value", indev)
        outdev_val = getattr(outdev, "value", outdev)

        if prefer_previous:
            in_candidates = (prev_in_id, indev_val)
            out_candidates = (prev_out_id, outdev_val)
        else:
            in_candidates = (indev_val, prev_in_id)
            out_candidates = (outdev_val, prev_out_id)

        self._select_device(self.input_device, inputs, in_candidates)
        self._select_device(self.output_device, outputs, out_candidates)

        snapshot = (input_ids, output_ids)
        changed = snapshot != self._last_device_snapshot
        self._last_device_snapshot = snapshot
        defaults_changed = (int(indev_val), int(outdev_val)) != self._last_default_ids
        self._last_default_ids = (int(indev_val), int(outdev_val))

        status_ready = "status" in self.frame.__dict__

        if auto_apply and (changed or defaults_changed):
            self.on_apply_audio(None)

        if announce and status_ready:
            text = f"Geraeteliste aktualisiert: {len(inputs)} Eingabe, {len(outputs)} Ausgabe"
            if not restarted:
                text += " (Soundsystem-Reset nicht verfuegbar)"
            elif not changed:
                text += " (keine Aenderung erkannt)"
            self.frame.set_status(text)
        elif changed and status_ready:
            self.frame.set_status(f"Neue Audiogeraete erkannt: {len(inputs)} Eingabe, {len(outputs)} Ausgabe")

    def _select_device(self, choice: wx.Choice, devices: list, targets: tuple) -> None:
        for target in targets:
            if target is None:
                continue
            for idx, dev in enumerate(devices):
                if int(dev.nDeviceID) == int(target):
                    if choice.GetSelection() != idx:
                        choice.SetSelection(idx)
                    return
        if devices:
            if choice.GetSelection() != 0:
                choice.SetSelection(0)

    def _on_device_poll_timer(self, _event):
        self.refresh_audio_devices(
            announce=False,
            prefer_previous=False,
            auto_apply=True,
            restart_sound=False,
        )

    def on_apply_audio(self, _event):
        client = self.frame.client
        in_idx = self.input_device.GetSelection()
        out_idx = self.output_device.GetSelection()
        if in_idx == wx.NOT_FOUND or out_idx == wx.NOT_FOUND:
            self.frame.set_status("Bitte Ein- und Ausgabegeraet waehlen")
            return
        indev = self._input_devices[in_idx]
        outdev = self._output_devices[out_idx]
        indev_id = int(indev.nDeviceID)
        outdev_id = int(outdev.nDeviceID)

        client.close_sound_input_device()
        client.close_sound_output_device()
        client.close_sound_duplex_devices()

        input_ok = client.init_sound_input_device(indev_id)
        if not input_ok:
            indev_def, _ = client.get_default_sound_devices()
            indev_val = getattr(indev_def, "value", indev_def)
            if indev_val != indev_id:
                input_ok = client.init_sound_input_device(int(indev_val))
        if not input_ok:
            sample_rate = int(indev.nDefaultSampleRate) or 48000
            channels = min(int(indev.nMaxInputChannels) or 1, 2)
            frame_size = max(int(sample_rate * 0.04), 480)
            if client.init_sound_input_shared_device(sample_rate, channels, frame_size):
                input_ok = client.init_sound_input_device(indev_id)
        if not input_ok:
            self.frame.set_status("Eingabegeraet konnte nicht initialisiert werden")
            return

        output_ok = client.init_sound_output_device(outdev_id)
        if not output_ok:
            self.frame.set_status("Ausgabegeraet konnte nicht initialisiert werden")
            return

        client.set_sound_input_gain(int(self.input_gain.GetValue()))
        client.set_sound_output_volume(int(self.output_volume.GetValue()))
        client.set_voice_activation_level(int(self.voice_level.GetValue()))

        if self.voice_activation.GetValue() and not self.frame._ptt_enabled:
            client.enable_voice_transmission(True)
        self.frame.set_status("Audiogeraete aktiviert")

    # --- Voice controls ---

    def on_voice_activation(self, event):
        enabled = event.IsChecked()
        self.frame.client.enable_voice_activation(enabled)
        if enabled and not self.frame._ptt_enabled:
            self.frame.client.enable_voice_transmission(True)
        if not enabled and not self.frame._ptt_enabled:
            self.frame.client.enable_voice_transmission(False)
        self.frame.set_status("Voice Activation an" if enabled else "Voice Activation aus")

    def on_voice_level(self, _event):
        self.frame.client.set_voice_activation_level(int(self.voice_level.GetValue()))

    def on_input_gain(self, _event):
        self.frame.client.set_sound_input_gain(int(self.input_gain.GetValue()))

    def on_output_volume(self, _event):
        self.frame.client.set_sound_output_volume(int(self.output_volume.GetValue()))

    def on_va_delay(self, _event):
        self.frame.client.set_voice_activation_stop_delay(int(self.va_delay.GetValue()))

    def on_output_mute(self, event):
        self.frame.client.set_sound_output_mute(event.IsChecked())
        self.frame.set_status("Ausgabe stummgeschaltet" if event.IsChecked() else "Ausgabe aktiv")

    # --- Device effects ---

    def on_apply_effects(self, _event):
        ok = self.frame.client.set_sound_device_effects(
            agc=self.agc_check.GetValue(),
            denoise=self.denoise_check.GetValue(),
            echo_cancel=self.echo_check.GetValue(),
        )
        self.frame.set_status("Effekte angewendet" if ok else "Effekte konnten nicht gesetzt werden")

    def on_preprocess_changed(self, _event):
        sel = self.preprocess_choice.GetSelection()
        client = self.frame.client
        if sel == 0:
            client.set_sound_input_preprocess_none()
            self.frame.set_status("Vorverarbeitung deaktiviert")
        elif sel == 1:
            client.set_sound_input_preprocess_speexdsp()
            self.frame.set_status("SpeexDSP Vorverarbeitung aktiv")
        elif sel == 2:
            client.set_sound_input_preprocess_webrtc()
            self.frame.set_status("WebRTC Vorverarbeitung aktiv")

    # --- PTT ---

    def on_ptt_toggle(self, _event):
        self.frame._ptt_enabled = self.ptt_toggle.GetValue()
        if not self.frame._ptt_enabled:
            self.frame.client.enable_voice_transmission(False)
            self.frame._ptt_active = False
        self.frame.set_status("Push-to-Talk aktiviert" if self.frame._ptt_enabled else "Push-to-Talk deaktiviert")

    # --- Loopback ---

    def on_loopback_toggle(self, _event):
        if self.loopback_toggle.GetValue():
            in_idx = self.input_device.GetSelection()
            out_idx = self.output_device.GetSelection()
            if in_idx == wx.NOT_FOUND or out_idx == wx.NOT_FOUND:
                self.frame.set_status("Bitte zuerst Geraete waehlen")
                self.loopback_toggle.SetValue(False)
                return
            indev_id = int(self._input_devices[in_idx].nDeviceID)
            outdev_id = int(self._output_devices[out_idx].nDeviceID)
            handle = self.frame.client.start_sound_loopback_test(indev_id, outdev_id)
            if handle:
                self._loopback_handle = handle
                self.frame.set_status("Mikrofontest gestartet")
            else:
                self.loopback_toggle.SetValue(False)
                self.frame.set_status("Mikrofontest konnte nicht gestartet werden")
        else:
            if self._loopback_handle is not None:
                self.frame.client.close_sound_loopback_test(self._loopback_handle)
                self._loopback_handle = None
            self.frame.set_status("Mikrofontest beendet")

    def _set_tab_order(self):
        order = [
            self.input_device, self.output_device, self.voice_activation,
            self.voice_level, self.input_gain, self.output_volume,
            self.va_delay, self.output_mute, self.agc_check,
            self.denoise_check, self.echo_check, self.apply_effects_btn,
            self.preprocess_choice, self.refresh_audio_btn, self.apply_audio_btn,
            self.ptt_toggle, self.loopback_toggle,
        ]
        for i in range(1, len(order)):
            order[i].MoveAfterInTabOrder(order[i - 1])
