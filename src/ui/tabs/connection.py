from __future__ import annotations

import threading
from typing import List, Optional, TYPE_CHECKING

import wx

from ..tt_file_parser import build_teamtalk_url, build_teamtalk_xml, parse_teamtalk_file

from ..models import ServerProfile

if TYPE_CHECKING:
    from app import MainFrame


class ConnectionTab(wx.Panel):
    """Tab 1: Verbindung -- server list, form, connect buttons, stats."""

    def __init__(self, parent: wx.Window, frame: MainFrame) -> None:
        super().__init__(parent)
        self.frame = frame
        self.SetName("Verbindung")

        sizer = wx.BoxSizer(wx.VERTICAL)

        # --- Server list ---
        server_box = wx.StaticBox(self, label="Server")
        server_sizer = wx.StaticBoxSizer(server_box, wx.VERTICAL)

        self._all_server_names: List[str] = [p.name for p in frame.store.items()]
        self._filtered_indices: List[int] = list(range(len(self._all_server_names)))

        # Filter row
        filter_row = wx.BoxSizer(wx.HORIZONTAL)
        filter_lbl = wx.StaticText(self, label="Filter:")
        self.server_filter = wx.TextCtrl(self, value="")
        self.server_filter.SetName("Serverfilter")
        self.server_filter.Bind(wx.EVT_TEXT, self._on_filter_changed)
        filter_row.Add(filter_lbl, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        filter_row.Add(self.server_filter, 1, wx.EXPAND)
        server_sizer.Add(filter_row, 0, wx.LEFT | wx.RIGHT | wx.TOP | wx.EXPAND, 8)

        self.server_list = wx.ListBox(self, choices=self._all_server_names)
        self.server_list.SetName("Serverliste")
        self.server_list.Bind(wx.EVT_LISTBOX, self.on_server_selected)
        self.server_list.Bind(wx.EVT_LISTBOX_DCLICK, self.on_server_dclick)
        self.server_list.Bind(wx.EVT_RIGHT_DOWN, self.on_server_list_context)
        self.server_list.Bind(wx.EVT_KEY_DOWN, self.on_server_list_key)

        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        self.server_add = wx.Button(self, label="Neu")
        self.server_add.SetName("Server hinzufügen")
        self.server_add.Bind(wx.EVT_BUTTON, self.on_server_add)
        self.server_edit = wx.Button(self, label="Bearbeiten")
        self.server_edit.SetName("Server bearbeiten")
        self.server_edit.Bind(wx.EVT_BUTTON, self.on_server_edit)
        self.server_remove = wx.Button(self, label="Entfernen")
        self.server_remove.SetName("Server entfernen")
        self.server_remove.Bind(wx.EVT_BUTTON, self.on_server_remove)
        self.join_code_btn = wx.Button(self, label="Beitrittscode eingeben")
        self.join_code_btn.SetName("Beitrittscode eingeben")
        self.join_code_btn.Bind(wx.EVT_BUTTON, self.on_enter_join_code)
        btn_row.Add(self.server_add, 0, wx.RIGHT, 8)
        btn_row.Add(self.server_edit, 0, wx.RIGHT, 8)
        btn_row.Add(self.server_remove, 0, wx.RIGHT, 8)
        btn_row.Add(self.join_code_btn, 0)

        server_sizer.Add(self.server_list, 0, wx.ALL | wx.EXPAND, 8)
        server_sizer.Add(btn_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # --- Form fields ---
        form = wx.FlexGridSizer(cols=2, vgap=6, hgap=12)
        form.AddGrowableCol(1)

        self.host = self._add_field(form, "Server", "127.0.0.1")
        self.tcp_port = self._add_field(form, "TCP Port", "10333")
        self.udp_port = self._add_field(form, "UDP Port", "10333")
        self.nickname = self._add_field(form, "Nickname", "VoiceOverUser")
        self.username = self._add_field(form, "Benutzername", "guest")
        self.password = self._add_field(form, "Passwort", "guest", style=wx.TE_PASSWORD)
        self.client_name = self._add_field(form, "Client-Name", "TeamTalk VO")
        self.elevenlabs_key = self._add_field(form, "ElevenLabs API Key", "", style=wx.TE_PASSWORD)

        self.encrypted = wx.CheckBox(self, label="Verschlüsselt (Encrypted)")
        self.encrypted.SetName("Verschlüsselt")
        form.AddSpacer(0)
        form.Add(self.encrypted, 0)

        form_box = wx.StaticBox(self, label="Verbindungsdaten")
        form_sizer = wx.StaticBoxSizer(form_box, wx.VERTICAL)
        form_sizer.Add(form, 0, wx.ALL | wx.EXPAND, 8)
        server_sizer.Add(form_sizer, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)

        # --- Action buttons ---
        action_box = wx.StaticBox(self, label="Aktionen")
        action_sizer = wx.StaticBoxSizer(action_box, wx.VERTICAL)
        action_row = wx.BoxSizer(wx.HORIZONTAL)
        self.connect_btn = wx.Button(self, label="Verbinden")
        self.connect_btn.SetName("Verbinden")
        self.connect_btn.Bind(wx.EVT_BUTTON, self.on_connect)
        self.reconnect_btn = wx.Button(self, label="Neu verbinden")
        self.reconnect_btn.SetName("Neu verbinden")
        self.reconnect_btn.Bind(wx.EVT_BUTTON, self.on_reconnect)
        self.server_check_btn = wx.Button(self, label="Server checken")
        self.server_check_btn.SetName("Server checken")
        self.server_check_btn.Bind(wx.EVT_BUTTON, self.on_server_check)
        self.join_root_btn = wx.Button(self, label="Root-Kanal beitreten")
        self.join_root_btn.SetName("Root-Kanal beitreten")
        self.join_root_btn.Bind(wx.EVT_BUTTON, self.on_join_root)
        self.leave_btn = wx.Button(self, label="Kanal verlassen")
        self.leave_btn.SetName("Kanal verlassen")
        self.leave_btn.Bind(wx.EVT_BUTTON, self.on_leave_channel)
        self.logout_btn = wx.Button(self, label="Abmelden")
        self.logout_btn.SetName("Abmelden")
        self.logout_btn.Bind(wx.EVT_BUTTON, self.on_logout)
        self.share_url_btn = wx.Button(self, label="TT-URL kopieren")
        self.share_url_btn.SetName("TT-URL kopieren")
        self.share_url_btn.Bind(wx.EVT_BUTTON, self.on_copy_tt_url)
        self.share_file_btn = wx.Button(self, label="TT-Datei speichern")
        self.share_file_btn.SetName("TT-Datei speichern")
        self.share_file_btn.Bind(wx.EVT_BUTTON, self.on_save_tt_file)
        self.auto_reconnect = wx.CheckBox(self, label="Auto-Reconnect")
        self.auto_reconnect.SetName("Auto-Reconnect")
        self.auto_reconnect.Bind(wx.EVT_CHECKBOX, self.on_auto_reconnect)

        for btn in (
            self.connect_btn, self.reconnect_btn, self.server_check_btn, self.join_root_btn,
            self.leave_btn, self.logout_btn, self.share_url_btn, self.share_file_btn,
        ):
            action_row.Add(btn, 0, wx.RIGHT, 8)
        action_row.Add(self.auto_reconnect, 0)

        action_sizer.Add(action_row, 0, wx.ALL, 8)
        server_sizer.Add(action_sizer, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)

        # --- Connection stats ---
        stats_box = wx.StaticBox(self, label="Verbindungsstatus")
        stats_sizer = wx.StaticBoxSizer(stats_box, wx.VERTICAL)
        self.stats_label = wx.StaticText(self, label="UDP Ping: -- ms  |  TCP Ping: -- ms")
        self.stats_label.SetName("Verbindungsstatistik")
        stats_sizer.Add(self.stats_label, 0, wx.ALL, 8)
        server_sizer.Add(stats_sizer, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)

        sizer.Add(server_sizer, 1, wx.ALL | wx.EXPAND, 8)
        self.SetSizer(sizer)



        # Stats timer
        self._stats_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_stats_timer, self._stats_timer)
        self._stats_timer.Start(5000)

    def destroy_timers(self):
        self._stats_timer.Stop()

    # --- helpers ---

    def _add_field(self, sizer, label, value, style=0):
        lbl = wx.StaticText(self, label=label)
        lbl.SetName(label)
        ctrl = wx.TextCtrl(self, value=value, style=style)
        ctrl.SetName(label)
        ctrl.SetHelpText(label)
        sizer.Add(lbl, 0, wx.ALIGN_CENTER_VERTICAL)
        sizer.Add(ctrl, 1, wx.EXPAND)
        return ctrl

    def fill_form(self, profile: ServerProfile) -> None:
        self.host.SetValue(profile.host)
        self.tcp_port.SetValue(str(profile.tcp_port))
        self.udp_port.SetValue(str(profile.udp_port))
        self.nickname.SetValue(profile.nickname)
        self.username.SetValue(profile.username)
        self.password.SetValue(profile.password)
        self.client_name.SetValue(profile.client_name)
        self.elevenlabs_key.SetValue(profile.elevenlabs_api_key)
        self.encrypted.SetValue(profile.encrypted)

    def profile_from_form(self) -> Optional[ServerProfile]:
        host = self.host.GetValue().strip()
        try:
            tcp_port = int(self.tcp_port.GetValue().strip())
            udp_port = int(self.udp_port.GetValue().strip())
        except ValueError:
            self.frame.set_status("Port muss eine Zahl sein")
            return None
        nickname = self.nickname.GetValue().strip()
        username = self.username.GetValue().strip()
        password = self.password.GetValue().strip()
        client_name = self.client_name.GetValue().strip()
        elevenlabs_api_key = self.elevenlabs_key.GetValue().strip()
        if not host:
            self.frame.set_status("Server darf nicht leer sein")
            return None
        encrypted = self.encrypted.GetValue()
        return ServerProfile(
            name=host, host=host, tcp_port=tcp_port, udp_port=udp_port,
            nickname=nickname, username=username, password=password,
            client_name=client_name, encrypted=encrypted,
            elevenlabs_api_key=elevenlabs_api_key,
        )

    def reload_server_list(self):
        self._all_server_names = [p.name for p in self.frame.store.items()]
        self._filtered_indices = list(range(len(self._all_server_names)))
        filt = self.server_filter.GetValue().strip().lower() if hasattr(self, "server_filter") else ""
        if filt:
            self._filtered_indices = [i for i, n in enumerate(self._all_server_names) if filt in n.lower()]
        self.server_list.Set([self._all_server_names[i] for i in self._filtered_indices])

    # --- events ---

    def _get_real_index(self) -> Optional[int]:
        """Return real store index from current filtered listbox selection."""
        idx = self.server_list.GetSelection()
        if idx == wx.NOT_FOUND:
            return None
        if idx < len(self._filtered_indices):
            return self._filtered_indices[idx]
        return None

    def on_server_selected(self, _event):
        real_idx = self._get_real_index()
        if real_idx is None:
            return
        self.fill_form(self.frame.store.items()[real_idx])

    def on_server_add(self, _event):
        profile = self.profile_from_form()
        if not profile:
            return
        self.frame.store.add(profile)
        self.reload_server_list()
        self.frame.set_status(f"Server gespeichert: {profile.name}")

    def on_server_edit(self, _event):
        real_idx = self._get_real_index()
        if real_idx is None:
            self.frame.set_status("Bitte einen Server auswählen")
            return
        profile = self.profile_from_form()
        if not profile:
            return
        self.frame.store.update(real_idx, profile)
        self.reload_server_list()
        self.frame.set_status(f"Server aktualisiert: {profile.name}")

    def on_server_remove(self, _event):
        real_idx = self._get_real_index()
        if real_idx is None:
            self.frame.set_status("Bitte einen Server auswählen")
            return
        name = self.frame.store.items()[real_idx].name
        dlg = wx.MessageDialog(
            self, f"Server '{name}' wirklich entfernen?",
            "Server entfernen", wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION,
        )
        dlg.SetYesNoLabels("Ja", "Nein")
        if dlg.ShowModal() != wx.ID_YES:
            dlg.Destroy()
            return
        dlg.Destroy()
        self.frame.store.remove(real_idx)
        self.reload_server_list()
        self.frame.set_status(f"Server entfernt: {name}")

    def on_connect(self, _event):
        self.frame.connect_with_form()

    def on_reconnect(self, _event):
        self.frame.set_status("Neu verbinden...")

        def worker():
            self.frame.client.stop_event_loop_and_wait()
            result = self.frame.client.reconnect()
            wx.CallAfter(self.frame.handle_connect_result, result)

        threading.Thread(target=worker, daemon=True).start()

    def on_server_check(self, _event):
        message = (
            "Der Server-Check baut kurzzeitig Verbindungen zu allen Servern in der Liste auf, "
            "um die aktiven Nutzer abzufragen.\n\n"
            "Wenn du gerade verbunden bist, wird die Verbindung für den Check kurz getrennt "
            "und danach automatisch wiederhergestellt.\n\n"
            "Möchtest du den Server-Check jetzt starten?"
        )
        with wx.MessageDialog(
            self,
            message,
            "Server-Check starten",
            style=wx.YES_NO | wx.YES_DEFAULT | wx.ICON_QUESTION,
        ) as dlg:
            dlg.SetYesNoLabels("Ja", "Nein")
            if dlg.ShowModal() != wx.ID_YES:
                self.frame.set_status("Server-Check abgebrochen")
                return
        self.frame.scan_saved_servers_presence()

    def on_join_root(self, _event):
        self.frame.join_channel(self.frame.client.get_root_channel_id())

    def on_leave_channel(self, _event):
        def worker():
            self.frame.client.stop_event_loop_and_wait()
            result = self.frame.client.leave_channel()
            self.frame.client.start_event_loop(self.frame.handle_tt_message)
            wx.CallAfter(self.frame.set_status, result.message)

        threading.Thread(target=worker, daemon=True).start()

    def on_logout(self, _event):
        def worker():
            self.frame.client.stop_event_loop_and_wait()
            result = self.frame.client.logout()
            wx.CallAfter(self.frame.set_status, result.message)

        threading.Thread(target=worker, daemon=True).start()

    def _get_channel_path_for_share(self) -> Optional[str]:
        if not self.frame.client.is_connected():
            return None
        try:
            ch_id = self.frame.client.get_my_channel_id()
            if not ch_id:
                return None
            path = self.frame.client.get_channel_path(int(ch_id))
            return self.frame.tt_str(path) if path else None
        except Exception:
            return None

    def on_copy_tt_url(self, _event):
        profile = self.profile_from_form()
        if not profile:
            return
        channel_path = self._get_channel_path_for_share()
        url = build_teamtalk_url(profile, channel_path=channel_path)
        if wx.TheClipboard.Open():
            wx.TheClipboard.SetData(wx.TextDataObject(url))
            wx.TheClipboard.Close()
            self.frame.set_status("TT-URL kopiert")
        else:
            self.frame.set_status("Zwischenablage konnte nicht geöffnet werden")

    def on_save_tt_file(self, _event):
        profile = self.profile_from_form()
        if not profile:
            return
        channel_path = self._get_channel_path_for_share()
        default_name = f"{profile.name or profile.host}.tt"
        with wx.FileDialog(
            self,
            "TT-Datei speichern",
            wildcard="TeamTalk Datei (*.tt)|*.tt|Alle Dateien|*.*",
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
            defaultFile=default_name,
        ) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            path = dlg.GetPath()
        try:
            xml_text = build_teamtalk_xml(profile, channel_path=channel_path)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(xml_text)
            self.frame.set_status("TT-Datei gespeichert")
        except Exception as exc:
            self.frame.set_status(f"TT-Datei speichern fehlgeschlagen: {exc}")

    def on_auto_reconnect(self, event):
        self.frame._auto_reconnect = event.IsChecked()

    def _on_stats_timer(self, _event):
        stats = self.frame.client.get_client_statistics()
        if stats is None:
            return
        udp_ms = int(stats.nUdpPingTimeMs)
        tcp_ms = int(stats.nTcpPingTimeMs)
        self.stats_label.SetLabel(f"UDP Ping: {udp_ms} ms  |  TCP Ping: {tcp_ms} ms")

    def _set_tab_order(self):
        order = [
            self.server_list, self.server_add, self.server_edit, self.server_remove,
            self.host, self.tcp_port, self.udp_port, self.nickname, self.username,
            self.password, self.client_name, self.elevenlabs_key, self.encrypted,
            self.connect_btn, self.reconnect_btn, self.server_check_btn,
            self.join_root_btn, self.leave_btn, self.logout_btn, self.auto_reconnect,
        ]
        for i in range(1, len(order)):
            order[i].MoveAfterInTabOrder(order[i - 1])

    # --- Filter ---

    def _on_filter_changed(self, _event):
        filt = self.server_filter.GetValue().strip().lower()
        all_names = self._all_server_names
        if filt:
            self._filtered_indices = [i for i, n in enumerate(all_names) if filt in n.lower()]
        else:
            self._filtered_indices = list(range(len(all_names)))
        self.server_list.Set([all_names[i] for i in self._filtered_indices])

    # --- Context menu and keyboard ---

    def on_server_dclick(self, _event):
        self.on_connect(None)

    def on_server_list_key(self, event):
        key = event.GetKeyCode()
        if key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            self.on_connect(None)
            return
        event.Skip()

    def on_server_list_context(self, _event):
        real_idx = self._get_real_index()
        menu = wx.Menu()
        connect_item = menu.Append(wx.ID_ANY, "Verbinden")
        edit_item = menu.Append(wx.ID_ANY, "Bearbeiten")
        dup_item = menu.Append(wx.ID_ANY, "Duplizieren")
        gen_tt_item = menu.Append(wx.ID_ANY, "TT-Datei generieren")
        remove_item = menu.Append(wx.ID_ANY, "Entfernen")
        menu.AppendSeparator()
        join_code_item = menu.Append(wx.ID_ANY, "Beitrittscode eingeben")

        connect_item.Enable(real_idx is not None)
        edit_item.Enable(real_idx is not None)
        dup_item.Enable(real_idx is not None)
        gen_tt_item.Enable(real_idx is not None)
        remove_item.Enable(real_idx is not None)

        self.Bind(wx.EVT_MENU, lambda e: self.on_connect(None), connect_item)
        self.Bind(wx.EVT_MENU, lambda e: self.on_server_edit(None), edit_item)
        self.Bind(wx.EVT_MENU, lambda e: self.on_server_duplicate(None), dup_item)
        self.Bind(wx.EVT_MENU, lambda e: self.on_server_generate_tt(None), gen_tt_item)
        self.Bind(wx.EVT_MENU, lambda e: self.on_server_remove(None), remove_item)
        self.Bind(wx.EVT_MENU, lambda e: self.on_enter_join_code(None), join_code_item)

        self.PopupMenu(menu)
        menu.Destroy()

    def on_server_duplicate(self, _event):
        real_idx = self._get_real_index()
        if real_idx is None:
            self.frame.set_status("Bitte einen Server auswählen")
            return
        import dataclasses
        original = self.frame.store.items()[real_idx]
        copy = dataclasses.replace(original, name=original.name + " (Kopie)")
        self.frame.store.add(copy)
        self.reload_server_list()
        self.frame.set_status(f"Server dupliziert: {copy.name}")

    def on_server_generate_tt(self, _event):
        real_idx = self._get_real_index()
        if real_idx is None:
            self.frame.set_status("Bitte einen Server auswählen")
            return
        profile = self.frame.store.items()[real_idx]
        default_name = f"{profile.name or profile.host}.tt"
        with wx.FileDialog(
            self,
            "TT-Datei generieren",
            wildcard="TeamTalk Datei (*.tt)|*.tt|Alle Dateien|*.*",
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
            defaultFile=default_name,
        ) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            path = dlg.GetPath()
        try:
            xml_text = build_teamtalk_xml(profile)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(xml_text)
            self.frame.set_status("TT-Datei gespeichert")
        except Exception as exc:
            self.frame.set_status(f"TT-Datei speichern fehlgeschlagen: {exc}")

    def on_enter_join_code(self, _event):
        dlg = wx.TextEntryDialog(self, "tt:// URL oder TT-Dateipfad eingeben:", "Beitrittscode eingeben", "")
        if dlg.ShowModal() != wx.ID_OK:
            dlg.Destroy()
            return
        raw = dlg.GetValue().strip()
        dlg.Destroy()
        if not raw:
            return

        parsed = None
        if raw.startswith("tt://"):
            try:
                from urllib.parse import urlparse, parse_qs
                pr = urlparse(raw)
                qs = parse_qs(pr.query)
                def _first(k):
                    return qs.get(k, [""])[0]
                host = pr.hostname or ""
                tcp_port = int(_first("tcpport") or 10333)
                udp_port = int(_first("udpport") or tcp_port)
                name = host
                username = _first("username")
                password = _first("password")
                channel_path = _first("channel") or None
                encrypted = _first("encrypted").lower() in ("1", "true")
                profile = ServerProfile(
                    name=name, host=host, tcp_port=tcp_port, udp_port=udp_port,
                    nickname="VoiceOverUser", username=username, password=password,
                    client_name="TeamTalk VO", encrypted=encrypted,
                )
                from ..models import ParsedTeamTalkFile
                parsed = ParsedTeamTalkFile(profile=profile, channel_path=channel_path)
            except Exception as exc:
                self.frame.set_status(f"URL konnte nicht geparst werden: {exc}")
                return
        else:
            from pathlib import Path
            try:
                parsed = parse_teamtalk_file(Path(raw))
            except Exception as exc:
                self.frame.set_status(f"Datei konnte nicht geparst werden: {exc}")
                return

        if parsed is None:
            self.frame.set_status("Beitrittscode konnte nicht verarbeitet werden")
            return

        self.fill_form(parsed.profile)
        confirm = wx.MessageDialog(
            self,
            f"Server '{parsed.profile.name}' wurde eingetragen.\nJetzt verbinden?",
            "Verbinden?",
            wx.YES_NO | wx.YES_DEFAULT | wx.ICON_QUESTION,
        )
        confirm.SetYesNoLabels("Ja", "Nein")
        if confirm.ShowModal() == wx.ID_YES:
            self.on_connect(None)
        confirm.Destroy()
