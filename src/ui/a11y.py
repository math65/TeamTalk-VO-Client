"""Barrierefreiheits-Helfer: VoiceOver-Rollen für wxPython auf macOS."""
from __future__ import annotations

import sys

import wx


def setup_list_accessible(lb: wx.ListBox) -> None:
    """Setzt die native NSAccessibility-Rolle auf AXList (VoiceOver: 'Liste')."""
    if sys.platform != "darwin":
        return

    def _apply():
        try:
            import objc  # noqa: PLC0415
            from AppKit import NSAccessibilityListRole  # noqa: PLC0415

            handle = lb.GetHandle()
            if not handle:
                return
            nsview = objc.objc_object(c_void_p=handle)

            # NSScrollView → NSClipView → wxNSTableView
            tableview = None
            for sv in nsview.subviews():
                cls = sv.__class__.__name__
                if "ClipView" in cls:
                    for child in sv.subviews():
                        tableview = child
                        break
                    break

            if tableview is None:
                return

            tableview.setAccessibilityRole_(NSAccessibilityListRole)
            tableview.setAccessibilityRoleDescription_("Liste")
        except Exception:
            pass

    wx.CallAfter(_apply)


def patch_list_row_accessibility() -> None:
    """Swizzelt wxNSTableView und NSTableRow, damit VoiceOver Listen korrekt ansagt.

    Ohne diesen Patch liest VoiceOver wx.ListBox als "Tabelle" und jede Zeile als
    "Tabelle N Zeile M" vor.  Mit dem Patch werden sie als "Liste" / Listeneintrag
    mit dem Elementtext vorgelesen.
    """
    if sys.platform != "darwin":
        return

    try:
        import objc  # noqa: PLC0415
        from AppKit import NSAccessibilityListRole  # noqa: PLC0415

        # 1. wxNSTableView global als AXList deklarieren
        try:
            wxNSTableView = objc.lookUpClass("wxNSTableView")

            class wxNSTableView(objc.Category(wxNSTableView)):
                def accessibilityRole(self):
                    return NSAccessibilityListRole

                def accessibilityRoleDescription(self):
                    return "Liste"
        except Exception:
            pass

        # 2. NSTableRow: Elementtext vorlesen, "Zeile N" unterdrücken
        def _cell_text(row):
            try:
                children = row.accessibilityAttributeValue_("AXChildren")
                if children:
                    val = children[0].accessibilityAttributeValue_("AXValue")
                    if val:
                        return str(val)
            except Exception:
                pass
            return ""

        _cls_row = objc.lookUpClass("NSTableRow")
        _orig_attr_value = _cls_row.instanceMethodForSelector_(b"accessibilityAttributeValue:")

        class NSTableRow(objc.Category(_cls_row)):
            def accessibilityLabel(self):
                return _cell_text(self)

            def accessibilityValue(self):
                return _cell_text(self)

            def accessibilityRoleDescription(self):
                return ""

            @objc.typedSelector(b"@@:@")
            def accessibilityAttributeValue_(self, attr):
                if attr in ("AXTitle", "AXLabel", "AXDescription", "AXValue"):
                    txt = _cell_text(self)
                    if txt:
                        return txt
                if attr == "AXRoleDescription":
                    return ""
                return _orig_attr_value(self, attr)

    except Exception:
        pass


def patch_control_accessibility() -> None:
    """Swizzelt wxNSSlider, wxNSTextField, wxNSTextView und NSProgressIndicator,
    damit VoiceOver deutsche Rollenbeschreibungen ansagt.

    Muss einmal beim Programmstart aufgerufen werden (nach wx.App-Erstellung).
    """
    if sys.platform != "darwin":
        return

    try:
        import objc  # noqa: PLC0415
        from AppKit import (  # noqa: PLC0415
            NSAccessibilitySliderRole,
            NSAccessibilityTextFieldRole,
            NSAccessibilityTextAreaRole,
        )

        # --- wxNSSlider → "Regler" ---
        try:
            wxNSSlider = objc.lookUpClass("wxNSSlider")

            class wxNSSlider(objc.Category(wxNSSlider)):
                def accessibilityRole(self):
                    return NSAccessibilitySliderRole

                def accessibilityRoleDescription(self):
                    return "Regler"
        except Exception:
            pass

        # --- wxNSTextField (single-line TextCtrl) → "Textfeld" ---
        try:
            wxNSTextField = objc.lookUpClass("wxNSTextField")

            class wxNSTextField(objc.Category(wxNSTextField)):
                def accessibilityRole(self):
                    return NSAccessibilityTextFieldRole

                def accessibilityRoleDescription(self):
                    return "Textfeld"
        except Exception:
            pass

        # --- wxNSTextView (multiline wx.TextCtrl) → "Textbereich" ---
        try:
            wxNSTextView = objc.lookUpClass("wxNSTextView")

            class wxNSTextView(objc.Category(wxNSTextView)):
                def accessibilityRole(self):
                    return NSAccessibilityTextAreaRole

                def accessibilityRoleDescription(self):
                    return "Textbereich"
        except Exception:
            pass

        # --- wxNSOutlineView (TreeCtrl) → "Baumansicht" ---
        try:
            wxNSOutlineView = objc.lookUpClass("wxNSOutlineView")

            class wxNSOutlineView(objc.Category(wxNSOutlineView)):
                def accessibilityRoleDescription(self):
                    return "Baumansicht"
        except Exception:
            pass

        # --- NSProgressIndicator (wx.Gauge) → "Fortschrittsanzeige" ---
        try:
            NSProgressIndicator = objc.lookUpClass("NSProgressIndicator")

            class NSProgressIndicator(objc.Category(NSProgressIndicator)):
                def accessibilityRoleDescription(self):
                    return "Fortschrittsanzeige"
        except Exception:
            pass

    except Exception:
        pass


def patch_button_accessibility() -> None:
    """Swizzelt wxNSButton, wxNSPopUpButton und wxNSComboBox einmalig,
    damit VoiceOver deutsche Rollennamen ansagt.

    Muss einmal beim Programmstart aufgerufen werden (nach wx.App-Erstellung).
    """
    if sys.platform != "darwin":
        return

    try:
        import objc  # noqa: PLC0415
        from AppKit import (  # noqa: PLC0415
            NSAccessibilityButtonRole,
            NSAccessibilityCheckBoxRole,
            NSAccessibilityComboBoxRole,
            NSAccessibilityPopUpButtonRole,
        )

        # --- wxNSButton: normale Taste oder Schalter (CheckBox) ---
        # bezelStyle == 0  →  CheckBox / Schalter
        # bezelStyle != 0  →  normaler Button / Taste
        wxNSButton = objc.lookUpClass("wxNSButton")

        class wxNSButton(objc.Category(wxNSButton)):
            def accessibilityRole(self):
                try:
                    return (
                        NSAccessibilityCheckBoxRole
                        if self.bezelStyle() == 0
                        else NSAccessibilityButtonRole
                    )
                except Exception:
                    return NSAccessibilityButtonRole

            def accessibilityRoleDescription(self):
                try:
                    return "Schalter" if self.bezelStyle() == 0 else "Taste"
                except Exception:
                    return "Taste"

        # --- wxNSPopUpButton: Auswahlmenü (wx.Choice) ---
        wxNSPopUpButton = objc.lookUpClass("wxNSPopUpButton")

        class wxNSPopUpButton(objc.Category(wxNSPopUpButton)):
            def accessibilityRole(self):
                return NSAccessibilityPopUpButtonRole

            def accessibilityRoleDescription(self):
                return "Auswahlmenü"

        # --- wxNSComboBox: Kombinationsfeld (wx.ComboBox) ---
        wxNSComboBox = objc.lookUpClass("wxNSComboBox")

        class wxNSComboBox(objc.Category(wxNSComboBox)):
            def accessibilityRole(self):
                return NSAccessibilityComboBoxRole

            def accessibilityRoleDescription(self):
                return "Kombinationsfeld"

        # --- NSStepper (wxSpinCtrl): numerischen Wert statt "X% Stepper" ansagen ---
        # VoiceOver berechnet den Prozentwert aus dem internen NSStepper-Bereich (oft 0-100 mit
        # Standardwert 50), nicht aus dem SpinCtrl-Bereich.  Wir ersetzen accessibilityValue durch
        # den echten numerischen Wert aus dem gepaarten NSTextField.
        try:
            NSStepper = objc.lookUpClass("NSStepper")

            class NSStepper(objc.Category(NSStepper)):
                def accessibilityValue(self):
                    try:
                        parent = self.superview()
                        if parent is not None:
                            for sib in parent.subviews():
                                if sib.__class__.__name__ in ("NSTextField", "wxNSTextField"):
                                    txt = sib.stringValue()
                                    if txt:
                                        return txt
                    except Exception:
                        pass
                    return str(int(self.doubleValue()))

                def accessibilityRoleDescription(self):
                    return "Regler"
        except Exception:
            pass

    except Exception:
        pass


class FocusRestoreHelper:
    """v4.4.0 – Hilfsobjekt um den Fokus nach Dialogen zuverlässig wiederherzustellen.

    Verwendung::

        helper = FocusRestoreHelper()
        helper.save(my_list_box)
        dlg = wx.TextEntryDialog(frame, ...)
        dlg.ShowModal()
        dlg.Destroy()
        helper.restore()

    Speichert das fokussierte Widget und stellt es nach einem Dialog wieder her.
    Funktioniert auch wenn das Widget zwischenzeitlich neu befüllt wurde
    (z. B. ListBox nach Refresh) – dann wird nur der Selektions-Index behalten.
    """

    def __init__(self) -> None:
        self._widget: "wx.Window | None" = None
        self._lb_selection: int = wx.NOT_FOUND

    def save(self, widget: "wx.Window | None" = None) -> None:
        """Speichert das angegebene Widget (oder das aktuell fokussierte)."""
        try:
            import wx as _wx
            self._widget = widget
            if isinstance(widget, _wx.ListBox):
                self._lb_selection = widget.GetSelection()
            else:
                self._lb_selection = _wx.NOT_FOUND
        except Exception:
            self._widget = None
            self._lb_selection = wx.NOT_FOUND

    def restore(self) -> None:
        """Stellt den Fokus und ggf. die Selektion wieder her."""
        try:
            import wx as _wx
            w = self._widget
            if w is None or not w:
                return
            if isinstance(w, _wx.ListBox):
                count = w.GetCount()
                sel = self._lb_selection
                if sel != _wx.NOT_FOUND and 0 <= sel < count:
                    w.SetSelection(sel)
                elif count > 0:
                    w.SetSelection(0)
            try:
                w.SetFocus()
            except Exception:
                pass
        except Exception:
            pass


def bind_listbox_keyboard_nav(lb: "wx.ListBox") -> None:
    """v4.4.0 – Bindet Home/End/PgUp/PgDn-Navigation an eine wx.ListBox.

    wxPython implementiert diese Tasten auf macOS nicht zuverlässig.
    Diese Funktion patcht sie für die angegebene Instanz.
    """
    import wx

    def _on_key(event: wx.KeyEvent) -> None:
        key = event.GetKeyCode()
        count = lb.GetCount()
        if count == 0:
            event.Skip()
            return
        sel = lb.GetSelection()
        if sel == wx.NOT_FOUND:
            sel = 0

        if key == wx.WXK_HOME:
            lb.SetSelection(0)
        elif key == wx.WXK_END:
            lb.SetSelection(count - 1)
        elif key in (wx.WXK_PAGEUP, wx.WXK_PRIOR):
            lb.SetSelection(max(0, sel - 10))
        elif key in (wx.WXK_PAGEDOWN, wx.WXK_NEXT):
            lb.SetSelection(min(count - 1, sel + 10))
        else:
            event.Skip()
            return
        # Pseudo-Auswahl-Event feuern
        evt = wx.CommandEvent(wx.EVT_LISTBOX.typeId, lb.GetId())
        evt.SetInt(lb.GetSelection())
        wx.PostEvent(lb, evt)

    lb.Bind(wx.EVT_KEY_DOWN, _on_key)


def post_voiceover_announcement(text: str) -> None:
    """Kündigt text über VoiceOver an (macOS, NSAccessibilityAnnouncementRequested)."""
    if sys.platform != "darwin":
        return
    try:
        import objc  # noqa: F401
        import AppKit
        user_info = {
            AppKit.NSAccessibilityAnnouncementKey: text,
            AppKit.NSAccessibilityPriorityKey: AppKit.NSAccessibilityPriorityHigh,
        }
        AppKit.NSAccessibilityPostNotificationWithUserInfo(
            AppKit.NSApp().mainWindow(),
            AppKit.NSAccessibilityAnnouncementRequestedNotification,
            user_info,
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# v5.4.0 – Barrierefreiheit Stufe 3
# ---------------------------------------------------------------------------

class LiveRegionAnnouncer:
    """Verwaltet VoiceOver-Durchsagen mit Priorität und Entduplizierung.

    Kündigt nur Änderungen an (verhindert Spam bei schnellen Updates).
    Puffert Durchsagen und lässt nur eine gleichzeitig durch.
    """

    def __init__(self) -> None:
        self._last_text: str = ""
        self._timer: "wx.Timer | None" = None

    def announce(self, text: str, force: bool = False) -> None:
        """Kündigt ``text`` an, wenn er sich vom letzten Wert unterscheidet.

        Args:
            text:  Der anzusagende Text.
            force: Wenn True, wird auch bei gleichem Text angesagt.
        """
        if not text or (text == self._last_text and not force):
            return
        self._last_text = text
        post_voiceover_announcement(text)

    def announce_delayed(self, text: str, delay_ms: int = 300) -> None:
        """Kündigt text nach ``delay_ms`` an (debounced für schnelle Updates)."""
        if self._timer is not None:
            try:
                self._timer.Stop()
            except Exception:
                pass
        try:
            import wx as _wx

            def _fire():
                self.announce(text)

            self._timer = _wx.CallLater(delay_ms, _fire)
        except Exception:
            self.announce(text)

    def reset(self) -> None:
        """Setzt den gespeicherten Zustand zurück (nach Panel-Wechsel)."""
        self._last_text = ""


def setup_tab_order(controls: list) -> None:
    """Setzt die Tab-Reihenfolge explizit für eine Liste von wx-Controls.

    wxPython/macOS ignoriert teilweise die Reihenfolge der SetNextHandler-Kette.
    Diese Funktion nutzt MoveAfterInTabOrder().

    Args:
        controls: Geordnete Liste von wx.Window-Instanzen.
    """
    for i in range(1, len(controls)):
        try:
            controls[i].MoveAfterInTabOrder(controls[i - 1])
        except Exception:
            pass


def set_accessible_name(ctrl: "wx.Window", name: str) -> None:
    """Setzt den zugänglichen Namen eines Controls (AXLabel).

    Auf macOS wird SetName() als AXLabel exponiert.
    """
    try:
        ctrl.SetName(name)
    except Exception:
        pass


def set_accessible_help(ctrl: "wx.Window", help_text: str) -> None:
    """Setzt den Hilfetext eines Controls (AXHelp / Tooltip).

    Wird von VoiceOver als Hilfsbeschreibung vorgelesen.
    """
    try:
        ctrl.SetHelpText(help_text)
        ctrl.SetToolTip(help_text)
    except Exception:
        pass


def audit_accessibility(panel: "wx.Panel") -> list:
    """Prüft eine Panel-Hierarchie auf häufige Barrierefreiheitsprobleme.

    Gibt eine Liste von Warnungen als Strings zurück.
    Geprüft wird:
    - Controls ohne Namen (leerer AXLabel)
    - Buttons ohne Beschriftung
    - TextCtrl ohne Help-Text

    v5.4.0 – Entwickler-Werkzeug für Barrierefreiheits-Reviews.
    """
    warnings: list = []
    try:
        for child in panel.GetChildren():
            name = child.GetName() if hasattr(child, "GetName") else ""
            label = child.GetLabel() if hasattr(child, "GetLabel") else ""
            cls = child.__class__.__name__

            if cls == "Button" and not label.strip():
                warnings.append(f"Button ohne Beschriftung: id={child.GetId()}")

            if cls in ("TextCtrl", "SearchCtrl") and not name.strip():
                warnings.append(f"TextCtrl ohne Name: id={child.GetId()}")

            if cls == "ListBox" and not name.strip():
                warnings.append(f"ListBox ohne Name: id={child.GetId()}")
    except Exception:
        pass
    return warnings
