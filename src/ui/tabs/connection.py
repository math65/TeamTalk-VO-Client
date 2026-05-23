from __future__ import annotations

import threading
from typing import List, Optional, TYPE_CHECKING, Dict

import wx

from ..tt_file_parser import build_teamtalk_url, build_teamtalk_xml, parse_teamtalk_file
from ..models import ServerProfile
from ..a11y import setup_list_accessible
from ..server_browser import ServerBrowserDialog
from tls_verify import get_cert_fingerprint

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
        self._server_status: Dict[int, Optional[bool]] = {}

        # v3.0.0 – Gruppen-Filter
        group_row = wx.BoxSizer(wx.HORIZONTAL)
        group_lbl = wx.StaticText(self, label="Gruppe:")
        self._group_choices: List[str] = ["(Alle)"]
        self.server_group_choice = wx.Choice(self, choices=self._group_choices)
        self.server_group_choice.SetName("Server-Gruppe")
        self.server_group_choice.SetSelection(0)
        self.server_group_choice.Bind(wx.EVT_CHOICE, self._on_group_filter_changed)
        manage_groups_btn = wx.Button(self, label="Gruppe &verwalten...")
        manage_groups_btn.SetName("Server-Gruppen verwalten")
        manage_groups_btn.Bind(wx.EVT_BUTTON, self._on_manage_groups)
        group_row.Add(group_lbl, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        group_row.Add(self.server_group_choice, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        group_row.Add(manage_groups_btn, 0)
        server_sizer.Add(group_row, 0, wx.LEFT | wx.RIGHT | wx.TOP | wx.EXPAND, 8)
        self._refresh_group_choices()

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
        setup_list_accessible(self.server_list)
        self.server_list.Bind(wx.EVT_LISTBOX, self.on_server_selected)
        self.server_list.Bind(wx.EVT_LISTBOX_DCLICK, self.on_server_dclick)
        self.server_list.Bind(wx.EVT_RIGHT_DOWN, self.on_server_list_context)
        self.server_list.Bind(wx.EVT_KEY_DOWN, self.on_server_list_key)

        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        self.server_add = wx.Button(self, label="&Neu")
        self.server_add.SetName("Server hinzufügen")
        self.server_add.Bind(wx.EVT_BUTTON, self.on_server_add)
        self.server_edit = wx.Button(self, label="&Bearbeiten")
        self.server_edit.SetName("Server bearbeiten")
        self.server_edit.Bind(wx.EVT_BUTTON, self.on_server_edit)
        self.server_remove = wx.Button(self, label="&Entfernen")
        self.server_remove.SetName("Server entfernen")
        self.server_remove.Bind(wx.EVT_BUTTON, self.on_server_remove)
        self.join_code_btn = wx.Button(self, label="Bei&trittscode eingeben")
        self.join_code_btn.SetName("Beitrittscode eingeben")
        self.join_code_btn.Bind(wx.EVT_BUTTON, self.on_enter_join_code)
        self.public_servers_btn = wx.Button(self, label="Öffentliche &Server…")
        self.public_servers_btn.SetName("Öffentliche Serverliste öffnen")
        self.public_servers_btn.Bind(wx.EVT_BUTTON, self.on_open_server_browser)
        btn_row.Add(self.server_add, 0, wx.RIGHT, 8)
        btn_row.Add(self.server_edit, 0, wx.RIGHT, 8)
        btn_row.Add(self.server_remove, 0, wx.RIGHT, 8)
        self.status_check_btn = wx.Button(self, label="Status &prüfen")
        self.status_check_btn.SetName("Server-Status prüfen")
        self.status_check_btn.Bind(wx.EVT_BUTTON, self._on_check_server_status)
        self.import_tt_btn = wx.Button(self, label=".tt &importieren")
        self.import_tt_btn.SetName("Server aus TT-Datei importieren")
        self.import_tt_btn.Bind(wx.EVT_BUTTON, self._on_import_tt_file)
        self.export_tt_btn = wx.Button(self, label=".tt &exportieren")
        self.export_tt_btn.SetName("Server als TT-Datei exportieren")
        self.export_tt_btn.Bind(wx.EVT_BUTTON, self._on_export_selected_tt)
        self.tls_pin_btn = wx.Button(self, label="TLS-&Fingerprint...")
        self.tls_pin_btn.SetName("TLS-Fingerprint")
        self.tls_pin_btn.Bind(wx.EVT_BUTTON, self._on_tls_fingerprint)
        btn_row.Add(self.join_code_btn, 0, wx.RIGHT, 8)
        btn_row.Add(self.public_servers_btn, 0, wx.RIGHT, 8)
        btn_row.Add(self.status_check_btn, 0, wx.RIGHT, 8)
        btn_row.Add(self.import_tt_btn, 0, wx.RIGHT, 8)
        btn_row.Add(self.export_tt_btn, 0, wx.RIGHT, 8)
        btn_row.Add(self.tls_pin_btn, 0)

        server_sizer.Add(self.server_list, 0, wx.ALL | wx.EXPAND, 8)
        server_sizer.Add(btn_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # --- Form fields ---
        form = wx.FlexGridSizer(cols=2, vgap=6, hgap=12)
        form.AddGrowableCol(1)

        self.display_name = self._add_field(form, "Profilname", "")
        self.host = self._add_field(form, "Server", "127.0.0.1")
        self.tcp_port = self._add_field(form, "TCP Port", "10333")
        self.udp_port = self._add_field(form, "UDP Port", "10333")
        self.nickname = self._add_field(form, "Nickname", "VoiceOverUser")
        self.username = self._add_field(form, "Benutzername", "guest")
        self.password = self._add_field(form, "Passwort", "guest", style=wx.TE_PASSWORD)
        self.client_name = self._add_field(form, "Client-Name", "TeamTalk VO")

        self.encrypted = wx.CheckBox(self, label="Versc&hlüsselt (Encrypted)")
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
        self.connect_btn = wx.Button(self, label="&Verbinden")
        self.connect_btn.SetName("Verbinden")
        self.connect_btn.Bind(wx.EVT_BUTTON, self.on_connect)
        self.reconnect_btn = wx.Button(self, label="Neu verbin&den")
        self.reconnect_btn.SetName("Neu verbinden")
        self.reconnect_btn.Bind(wx.EVT_BUTTON, self.on_reconnect)
        self.server_check_btn = wx.Button(self, label="&Server prüfen")
        self.server_check_btn.SetName("Server prüfen")
        self.server_check_btn.Bind(wx.EVT_BUTTON, self.on_server_check)
        self.join_root_btn = wx.Button(self, label="&Root-Kanal beitreten")
        self.join_root_btn.SetName("Root-Kanal beitreten")
        self.join_root_btn.Bind(wx.EVT_BUTTON, self.on_join_root)
        self.leave_btn = wx.Button(self, label="&Kanal verlassen")
        self.leave_btn.SetName("Kanal verlassen")
        self.leave_btn.Bind(wx.EVT_BUTTON, self.on_leave_channel)
        self.logout_btn = wx.Button(self, label="&Abmelden")
        self.logout_btn.SetName("Abmelden")
        self.logout_btn.Bind(wx.EVT_BUTTON, self.on_logout)
        self.share_url_btn = wx.Button(self, label="TT-&URL kopieren")
        self.share_url_btn.SetName("TT-URL kopieren")
        self.share_url_btn.Bind(wx.EVT_BUTTON, self.on_copy_tt_url)
        self.share_file_btn = wx.Button(self, label="TT-Datei s&peichern")
        self.share_file_btn.SetName("TT-Datei speichern")
        self.share_file_btn.Bind(wx.EVT_BUTTON, self.on_save_tt_file)
        self.qr_btn = wx.Button(self, label="QR-Code")
        self.qr_btn.SetName("Server als QR-Code anzeigen")
        self.qr_btn.Bind(wx.EVT_BUTTON, self.on_show_qr)
        self.auto_reconnect = wx.CheckBox(self, label="Auto&matisch neu verbinden")
        self.auto_reconnect.SetName("Automatisch neu verbinden")
        self.auto_reconnect.Bind(wx.EVT_CHECKBOX, self.on_auto_reconnect)

        for btn in (
            self.connect_btn, self.reconnect_btn, self.server_check_btn, self.join_root_btn,
            self.leave_btn, self.logout_btn, self.share_url_btn, self.share_file_btn,
            self.qr_btn,
        ):
            action_row.Add(btn, 0, wx.RIGHT, 8)
        action_row.Add(self.auto_reconnect, 0)

        action_sizer.Add(action_row, 0, wx.ALL, 8)
        server_sizer.Add(action_sizer, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)

        # --- Connection stats ---
        stats_box = wx.StaticBox(self, label="Verbindungsstatus")
        stats_sizer = wx.StaticBoxSizer(stats_box, wx.VERTICAL)
        self.stats_label = wx.StaticText(self, label="UDP Ping: -- ms, TCP Ping: -- ms")
        self.stats_label.SetName("Verbindungsstatistik")
        stats_sizer.Add(self.stats_label, 0, wx.ALL, 8)
        server_sizer.Add(stats_sizer, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)

        sizer.Add(server_sizer, 1, wx.ALL | wx.EXPAND, 8)
        self.SetSizer(sizer)



        # Stats timer
        self._stats_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_stats_timer, self._stats_timer)
        self._stats_timer.Start(5000)
        self._ping_history: list = []  # rolling last-10 UDP pings

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
        self.display_name.SetValue(profile.display_name or profile.name or "")
        self.host.SetValue(profile.host)
        self.tcp_port.SetValue(str(profile.tcp_port))
        self.udp_port.SetValue(str(profile.udp_port))
        self.nickname.SetValue(profile.nickname)
        self.username.SetValue(profile.username)
        self.password.SetValue(profile.password)
        self.client_name.SetValue(profile.client_name)
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
        if not host:
            self.frame.set_status("Server darf nicht leer sein")
            return None
        encrypted = self.encrypted.GetValue()
        display_name = self.display_name.GetValue().strip()
        name = display_name or host
        return ServerProfile(
            name=name, host=host, tcp_port=tcp_port, udp_port=udp_port,
            nickname=nickname, username=username, password=password,
            client_name=client_name, encrypted=encrypted,
            display_name=display_name,
        )

    def reload_server_list(self):
        self._all_server_names = [p.name for p in self.frame.store.items()]
        self._filtered_indices = list(range(len(self._all_server_names)))
        filt = self.server_filter.GetValue().strip().lower() if hasattr(self, "server_filter") else ""
        if filt:
            self._filtered_indices = [i for i, n in enumerate(self._all_server_names) if filt in n.lower()]

        def _label(i: int) -> str:
            st = self._server_status.get(i)
            prefix = "✓ " if st is True else "✗ " if st is False else ""
            return prefix + self._all_server_names[i]

        self.server_list.Set([_label(i) for i in self._filtered_indices])

    def _on_tls_fingerprint(self, _event) -> None:
        host = self.host.GetValue().strip()
        if not host:
            self.frame.set_status("Server darf nicht leer sein")
            return
        try:
            port = int(self.tcp_port.GetValue().strip() or "0")
        except ValueError:
            self.frame.set_status("Port muss eine Zahl sein")
            return
        if port <= 0:
            self.frame.set_status("TCP-Port ungültig")
            return

        dlg = wx.Dialog(self, title="TLS-Fingerprint", style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        dlg.SetMinSize((720, 420))
        root = wx.BoxSizer(wx.VERTICAL)
        info = wx.StaticText(dlg, label=f"Server: {host}:{port}")
        root.Add(info, 0, wx.ALL, 10)
        text = wx.TextCtrl(dlg, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2)
        text.SetName("TLS-Fingerprint")
        text.SetMinSize((-1, 220))
        root.Add(text, 1, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 10)

        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        refresh_btn = wx.Button(dlg, label="Prüfen")
        pin_btn = wx.Button(dlg, label="Pinnen")
        unpin_btn = wx.Button(dlg, label="Pin entfernen")
        close_btn = wx.Button(dlg, wx.ID_OK, "Schließen")
        btn_row.Add(refresh_btn, 0, wx.RIGHT, 8)
        btn_row.Add(pin_btn, 0, wx.RIGHT, 8)
        btn_row.Add(unpin_btn, 0, wx.RIGHT, 8)
        btn_row.Add(close_btn, 0)
        root.Add(btn_row, 0, wx.ALL | wx.ALIGN_RIGHT, 10)

        def _render(current: str | None = None) -> None:
            pinned = self.frame._cert_pins.get_pinned(host)
            lines = [
                f"Host: {host}",
                f"Port: {port}",
                f"Gepinnt: {pinned or '-'}",
                f"Aktuell: {current or '-'}",
            ]
            if pinned and current:
                lines.append("Status: OK" if pinned.upper() == current.upper() else "Status: Fingerprint-Mismatch")
            text.SetValue("\n".join(lines))

        def _refresh(_evt=None) -> None:
            text.SetValue("Fingerprint wird geladen...")
            wx.YieldIfNeeded()
            current = get_cert_fingerprint(host, port=port, timeout=5.0)
            if not current:
                self.frame.set_status("TLS-Fingerprint konnte nicht geladen werden")
                _render(None)
                return
            self.frame.set_status("TLS-Fingerprint geladen")
            _render(current)

        def _pin(_evt) -> None:
            current = get_cert_fingerprint(host, port=port, timeout=5.0)
            if not current:
                self.frame.set_status("TLS-Fingerprint konnte nicht geladen werden")
                return
            self.frame._cert_pins.pin(host, current)
            self.frame.set_status(f"TLS-Fingerprint gespeichert: {host}")
            _render(current)

        def _unpin(_evt) -> None:
            self.frame._cert_pins.unpin(host)
            self.frame.set_status(f"TLS-Pin entfernt: {host}")
            _render(None)

        refresh_btn.Bind(wx.EVT_BUTTON, _refresh)
        pin_btn.Bind(wx.EVT_BUTTON, _pin)
        unpin_btn.Bind(wx.EVT_BUTTON, _unpin)
        dlg.SetSizerAndFit(root)
        dlg.CentreOnParent()
        _render(None)
        dlg.ShowModal()
        dlg.Destroy()

    def _on_check_server_status(self, _event) -> None:
        import socket
        profiles = self.frame.store.items()
        if not profiles:
            return
        self._server_status = {}
        self.status_check_btn.Disable()
        self.frame.set_status("Server-Status wird geprüft…")

        def worker():
            for i, profile in enumerate(profiles):
                try:
                    conn = socket.create_connection(
                        (profile.host, int(profile.tcp_port or 10333)), timeout=3
                    )
                    conn.close()
                    self._server_status[i] = True
                except Exception:
                    self._server_status[i] = False
            reachable = sum(1 for v in self._server_status.values() if v)
            total = len(self._server_status)
            wx.CallAfter(self.reload_server_list)
            wx.CallAfter(self.status_check_btn.Enable)
            wx.CallAfter(self.frame.set_status, f"Server-Status: {reachable}/{total} erreichbar")

        threading.Thread(target=worker, daemon=True).start()

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
            if self.frame._closing:
                return
            try:
                self.frame.client.stop_event_loop_and_wait()
                result = self.frame.client.reconnect()
                if not self.frame._closing:
                    wx.CallAfter(self.frame.handle_connect_result, result)
            except Exception as exc:
                if not self.frame._closing:
                    wx.CallAfter(self.frame.set_status, f"Neu verbinden fehlgeschlagen: {exc}")

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
            if self.frame._closing:
                return
            self.frame.client.stop_event_loop_and_wait()
            result = self.frame.client.leave_channel()
            if not self.frame._closing:
                self.frame.client.start_event_loop(self.frame.handle_tt_message)
            if result.ok:
                se = self.frame.settings_store.settings.sound_events
                self.frame.sound_manager.play("user_leave", se.get("user_leave"))
            if not self.frame._closing:
                wx.CallAfter(self.frame.set_status, result.message)

        threading.Thread(target=worker, daemon=True).start()

    def on_logout(self, _event):
        def worker():
            if self.frame._closing:
                return
            self.frame.client.stop_event_loop_and_wait()
            se = self.frame.settings_store.settings.sound_events
            self.frame.sound_manager.play("server_disconnect", se.get("server_disconnect"))
            result = self.frame.client.logout()
            if not self.frame._closing:
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

    def on_show_qr(self, _event) -> None:
        """Zeigt den Server als QR-Code (tt://-URL)."""
        profile = self.profile_from_form()
        if not profile:
            self.frame.set_status("Bitte Serverformular ausfüllen")
            return
        channel_path = self._get_channel_path_for_share()
        url = build_teamtalk_url(profile, channel_path=channel_path)

        dlg = wx.Dialog(self, title="Server QR-Code", style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        dlg.SetMinSize((480, 340))
        accel = wx.AcceleratorTable([(wx.ACCEL_CMD, ord("W"), wx.ID_CLOSE)])
        dlg.SetAcceleratorTable(accel)
        dlg.Bind(wx.EVT_MENU, lambda e: dlg.EndModal(wx.ID_CANCEL), id=wx.ID_CLOSE)

        root = wx.BoxSizer(wx.VERTICAL)

        # QR-Code versuchen via qrcode-Bibliothek
        qr_shown = False
        try:
            import qrcode  # type: ignore
            import io
            qr = qrcode.QRCode(box_size=6, border=2)
            qr.add_data(url)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            buf.seek(0)
            wx_img = wx.Image(buf, wx.BITMAP_TYPE_PNG)
            bmp = wx.StaticBitmap(dlg, bitmap=wx_img.ConvertToBitmap())
            bmp.SetName("QR-Code Bild")
            root.Add(bmp, 0, wx.ALL | wx.ALIGN_CENTER, 8)
            qr_shown = True
        except ImportError:
            hint = wx.StaticText(
                dlg,
                label="(qrcode-Bibliothek nicht installiert – URL unten kopieren und\nin einem QR-Generator einfügen)",
            )
            hint.SetForegroundColour(wx.Colour(100, 100, 100))
            root.Add(hint, 0, wx.ALL, 8)
        except Exception:
            pass

        # URL immer als Text anzeigen
        url_label = wx.StaticText(dlg, label="tt://-URL:")
        root.Add(url_label, 0, wx.LEFT | wx.TOP, 8)
        url_ctrl = wx.TextCtrl(dlg, value=url, style=wx.TE_READONLY)
        url_ctrl.SetName("Server-URL")
        root.Add(url_ctrl, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)

        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        copy_btn = wx.Button(dlg, label="&URL kopieren")
        copy_btn.SetName("URL kopieren")
        close_btn = wx.Button(dlg, wx.ID_OK, "&Schließen")
        btn_row.Add(copy_btn, 0, wx.RIGHT, 8)
        btn_row.Add(close_btn, 0)
        root.Add(btn_row, 0, wx.ALL | wx.ALIGN_RIGHT, 8)

        def _copy(_e):
            if wx.TheClipboard.Open():
                wx.TheClipboard.SetData(wx.TextDataObject(url))
                wx.TheClipboard.Close()
                self.frame.set_status("URL kopiert")

        copy_btn.Bind(wx.EVT_BUTTON, _copy)
        dlg.SetSizer(root)
        dlg.CentreOnParent()
        dlg.ShowModal()
        dlg.Destroy()

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
        enabled = event.IsChecked()
        self.frame._auto_reconnect = enabled
        self.frame._menu_auto_reconnect.Check(enabled)
        self.frame.settings_store.settings.auto_reconnect_enabled = enabled
        self.frame.settings_store.save()

    def get_ping_text(self) -> str:
        """Gibt den aktuellen Ping als lesbaren String zurück."""
        stats = self.frame.client.get_client_statistics()
        if stats is None:
            return "Ping: nicht verbunden"
        udp_ms = int(stats.nUdpPingTimeMs)
        tcp_ms = int(stats.nTcpPingTimeMs)
        return f"UDP {udp_ms} Millisekunden, TCP {tcp_ms} Millisekunden"

    def _on_stats_timer(self, _event):
        if self.frame._closing:
            return
        stats = self.frame.client.get_client_statistics()
        if stats is None:
            return
        udp_ms = int(stats.nUdpPingTimeMs)
        tcp_ms = int(stats.nTcpPingTimeMs)
        # Ping-Verlauf (letzten 10 Messwerte)
        self._ping_history.append(udp_ms)
        if len(self._ping_history) > 10:
            self._ping_history.pop(0)
        avg_ms = int(sum(self._ping_history) / len(self._ping_history))
        min_ms = min(self._ping_history)
        max_ms = max(self._ping_history)
        self.stats_label.SetLabel(
            f"UDP Ping: {udp_ms} ms, TCP Ping: {tcp_ms} ms"
            f"   |   Verlauf (letzte {len(self._ping_history)}): Ø {avg_ms} ms, min {min_ms} ms, max {max_ms} ms"
        )

    def _on_import_tt_file(self, _event) -> None:
        from pathlib import Path as _Path
        with wx.FileDialog(
            self,
            "TT-Datei importieren",
            wildcard="TeamTalk Datei (*.tt)|*.tt|Alle Dateien|*.*",
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        ) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            path = _Path(dlg.GetPath())
        try:
            parsed = parse_teamtalk_file(path)
            if parsed is None:
                self.frame.set_status("TT-Datei konnte nicht gelesen werden")
                return
            profile = parsed.profile
            if not profile.name:
                profile.name = path.stem
            self.frame.store.add(profile)
            self.reload_server_list()
            self.fill_form(profile)
            self.frame.set_status(f"Server importiert: {profile.name}")
        except Exception as exc:
            self.frame.set_status(f"Import fehlgeschlagen: {exc}")

    def _on_export_selected_tt(self, _event) -> None:
        real_idx = self._get_real_index()
        if real_idx is None:
            self.frame.set_status("Bitte einen Server auswählen")
            return
        profile = self.frame.store.items()[real_idx]
        default_name = f"{profile.name or profile.host}.tt"
        with wx.FileDialog(
            self,
            "Server als TT-Datei exportieren",
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
            self.frame.set_status(f"Exportiert: {path}")
        except Exception as exc:
            self.frame.set_status(f"Export fehlgeschlagen: {exc}")

    def _set_tab_order(self):
        order = [
            self.server_list, self.server_add, self.server_edit, self.server_remove,
            self.host, self.tcp_port, self.udp_port, self.nickname, self.username,
            self.password, self.client_name, self.encrypted,
            self.connect_btn, self.reconnect_btn, self.server_check_btn,
            self.join_root_btn, self.leave_btn, self.logout_btn, self.auto_reconnect,
        ]
        try:
            for i in range(1, len(order)):
                order[i].MoveAfterInTabOrder(order[i - 1])
        except Exception:
            pass

    # --- Filter ---

    def _refresh_group_choices(self) -> None:
        try:
            groups = getattr(self.frame.settings_store.settings, "server_groups", {}) or {}
            choices = ["(Alle)"] + sorted(groups.keys())
            self.server_group_choice.Set(choices)
            self.server_group_choice.SetSelection(0)
            self._group_choices = choices
        except Exception:
            pass

    def _on_group_filter_changed(self, _event) -> None:
        self._apply_combined_filter()

    def _apply_combined_filter(self) -> None:
        filt = self.server_filter.GetValue().strip().lower()
        all_names = self._all_server_names
        sel = self.server_group_choice.GetSelection()
        group_name = self._group_choices[sel] if sel >= 0 else "(Alle)"
        # Group filter
        if group_name != "(Alle)":
            try:
                groups = getattr(self.frame.settings_store.settings, "server_groups", {}) or {}
                group_ids = set(groups.get(group_name, []))
                servers = self.frame.store.items()
                allowed = {i for i, s in enumerate(servers) if s.name in group_ids or str(i) in group_ids}
            except Exception:
                allowed = set(range(len(all_names)))
        else:
            allowed = set(range(len(all_names)))
        if filt:
            self._filtered_indices = [i for i, n in enumerate(all_names) if filt in n.lower() and i in allowed]
        else:
            self._filtered_indices = [i for i in range(len(all_names)) if i in allowed]
        self.server_list.Set([all_names[i] for i in self._filtered_indices])

    def _on_manage_groups(self, _event) -> None:
        dlg = _ServerGroupsDialog(self, self.frame)
        dlg.ShowModal()
        dlg.Destroy()
        self._refresh_group_choices()

    def _on_filter_changed(self, _event):
        self._apply_combined_filter()

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
        connect_item = menu.Append(wx.ID_ANY, _("Verbinden"))
        edit_item = menu.Append(wx.ID_ANY, _("Bearbeiten"))
        dup_item = menu.Append(wx.ID_ANY, _("Duplizieren"))
        gen_tt_item = menu.Append(wx.ID_ANY, _("TT-Datei generieren"))
        remove_item = menu.Append(wx.ID_ANY, _("Entfernen"))
        menu.AppendSeparator()
        join_code_item = menu.Append(wx.ID_ANY, _("Beitrittscode eingeben"))

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

    def on_open_server_browser(self, _event):
        dlg = ServerBrowserDialog(self, self.frame)
        dlg.ShowModal()
        dlg.Destroy()


# v3.0.0 – Server-Gruppen-Dialog

class _ServerGroupsDialog(wx.Dialog):
    """Einfacher Dialog zum Verwalten von Server-Gruppen."""

    def __init__(self, parent: wx.Window, frame) -> None:
        super().__init__(parent, title="Server-Gruppen verwalten", style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.frame = frame
        self.SetMinSize((600, 450))
        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        # Group list
        top_row = wx.BoxSizer(wx.HORIZONTAL)
        grp_box = wx.StaticBox(panel, label="Gruppen")
        grp_sizer = wx.StaticBoxSizer(grp_box, wx.VERTICAL)
        self._grp_list = wx.ListBox(panel, style=wx.LB_SINGLE)
        self._grp_list.SetName("Gruppen-Liste")
        self._grp_list.Bind(wx.EVT_LISTBOX, self._on_group_selected)
        grp_sizer.Add(self._grp_list, 1, wx.ALL | wx.EXPAND, 4)
        grp_btn_row = wx.BoxSizer(wx.HORIZONTAL)
        add_grp_btn = wx.Button(panel, label="&Neu")
        add_grp_btn.Bind(wx.EVT_BUTTON, self._on_add_group)
        del_grp_btn = wx.Button(panel, label="&Löschen")
        del_grp_btn.Bind(wx.EVT_BUTTON, self._on_del_group)
        grp_btn_row.Add(add_grp_btn, 0, wx.RIGHT, 4)
        grp_btn_row.Add(del_grp_btn, 0)
        grp_sizer.Add(grp_btn_row, 0, wx.ALL, 4)
        top_row.Add(grp_sizer, 1, wx.ALL | wx.EXPAND, 4)

        # Server assignment
        srv_box = wx.StaticBox(panel, label="Server in Gruppe")
        srv_sizer = wx.StaticBoxSizer(srv_box, wx.VERTICAL)
        self._srv_list = wx.ListBox(panel, style=wx.LB_SINGLE)
        self._srv_list.SetName("Server in Gruppe")
        srv_sizer.Add(self._srv_list, 1, wx.ALL | wx.EXPAND, 4)
        srv_btn_row = wx.BoxSizer(wx.HORIZONTAL)
        add_srv_btn = wx.Button(panel, label="Server &hinzufügen")
        add_srv_btn.Bind(wx.EVT_BUTTON, self._on_add_server)
        rem_srv_btn = wx.Button(panel, label="Server &entfernen")
        rem_srv_btn.Bind(wx.EVT_BUTTON, self._on_rem_server)
        srv_btn_row.Add(add_srv_btn, 0, wx.RIGHT, 4)
        srv_btn_row.Add(rem_srv_btn, 0)
        srv_sizer.Add(srv_btn_row, 0, wx.ALL, 4)
        top_row.Add(srv_sizer, 1, wx.ALL | wx.EXPAND, 4)

        sizer.Add(top_row, 1, wx.ALL | wx.EXPAND, 4)

        btn_sizer = wx.StdDialogButtonSizer()
        close_btn = wx.Button(panel, wx.ID_OK, label="Schließen")
        btn_sizer.AddButton(close_btn)
        btn_sizer.Realize()
        sizer.Add(btn_sizer, 0, wx.ALL | wx.ALIGN_RIGHT, 8)
        panel.SetSizer(sizer)

        self._groups: dict = dict(getattr(frame.settings_store.settings, "server_groups", {}) or {})
        self._refresh_groups()
        self.CentreOnParent()

    def _refresh_groups(self) -> None:
        self._grp_list.Set(sorted(self._groups.keys()))
        self._srv_list.Clear()

    def _current_group(self) -> Optional[str]:
        idx = self._grp_list.GetSelection()
        if idx == wx.NOT_FOUND:
            return None
        return self._grp_list.GetString(idx)

    def _on_group_selected(self, _event) -> None:
        grp = self._current_group()
        if grp is None:
            return
        members = self._groups.get(grp, [])
        self._srv_list.Set(list(members))

    def _on_add_group(self, _event) -> None:
        with wx.TextEntryDialog(self, "Name der neuen Gruppe:", "Gruppe erstellen") as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            name = dlg.GetValue().strip()
        if not name or name in self._groups:
            return
        self._groups[name] = []
        self._save()
        self._refresh_groups()

    def _on_del_group(self, _event) -> None:
        grp = self._current_group()
        if grp is None:
            return
        self._groups.pop(grp, None)
        self._save()
        self._refresh_groups()

    def _on_add_server(self, _event) -> None:
        grp = self._current_group()
        if grp is None:
            wx.MessageBox("Erst eine Gruppe auswählen.", "Hinweis")
            return
        servers = [p.name for p in self.frame.store.items()]
        with wx.SingleChoiceDialog(self, "Server auswählen:", "Server hinzufügen", servers) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            srv = dlg.GetStringSelection()
        if srv and srv not in self._groups[grp]:
            self._groups[grp].append(srv)
            self._save()
            self._on_group_selected(None)

    def _on_rem_server(self, _event) -> None:
        grp = self._current_group()
        if grp is None:
            return
        idx = self._srv_list.GetSelection()
        if idx == wx.NOT_FOUND:
            return
        srv = self._srv_list.GetString(idx)
        members = self._groups.get(grp, [])
        if srv in members:
            members.remove(srv)
            self._groups[grp] = members
            self._save()
            self._on_group_selected(None)

    def _save(self) -> None:
        self.frame.settings_store.settings.server_groups = dict(self._groups)
        self.frame.settings_store.save()
