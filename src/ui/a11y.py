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
    """Swizzelt NSTableRow einmalig, damit VoiceOver den Listeneintragstext vorliest.

    wxNSTableView-Zeilen enthalten den Text in einer NSTableViewCellProxy-Kindansicht.
    VoiceOver liest ohne diesen Patch nur die Rolle ('Zeile'), nicht den Inhalt.
    """
    if sys.platform != "darwin":
        return

    try:
        import objc  # noqa: PLC0415

        cls_row = objc.lookUpClass("NSTableRow")

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

        @objc.typedSelector(b"@@:")
        def _row_label(self):
            return _cell_text(self)

        _orig_attr_value = cls_row.instanceMethodForSelector_(
            b"accessibilityAttributeValue:"
        )

        @objc.typedSelector(b"@@:@")
        def _row_attr_value(self, attr):
            if attr in ("AXTitle", "AXLabel", "AXDescription"):
                txt = _cell_text(self)
                if txt:
                    return txt
            return _orig_attr_value(self, attr)

        objc.classAddMethod(cls_row, b"accessibilityLabel", _row_label)
        objc.classAddMethod(cls_row, b"accessibilityAttributeValue:", _row_attr_value)

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
        cls_btn = objc.lookUpClass("wxNSButton")

        # bezelStyle == 0  →  CheckBox / Schalter
        # bezelStyle != 0  →  normaler Button / Taste

        @objc.typedSelector(b"@@:")
        def _btn_role(self):
            try:
                return (
                    NSAccessibilityCheckBoxRole
                    if self.bezelStyle() == 0
                    else NSAccessibilityButtonRole
                )
            except Exception:
                return NSAccessibilityButtonRole

        @objc.typedSelector(b"@@:")
        def _btn_role_desc(self):
            try:
                return "Schalter" if self.bezelStyle() == 0 else "Taste"
            except Exception:
                return "Taste"

        objc.classAddMethod(cls_btn, b"accessibilityRole", _btn_role)
        objc.classAddMethod(cls_btn, b"accessibilityRoleDescription", _btn_role_desc)

        # --- wxNSPopUpButton: Auswahlmenü (wx.Choice) ---
        cls_popup = objc.lookUpClass("wxNSPopUpButton")

        @objc.typedSelector(b"@@:")
        def _popup_role(self):
            return NSAccessibilityPopUpButtonRole

        @objc.typedSelector(b"@@:")
        def _popup_role_desc(self):
            return "Auswahlmenü"

        objc.classAddMethod(cls_popup, b"accessibilityRole", _popup_role)
        objc.classAddMethod(cls_popup, b"accessibilityRoleDescription", _popup_role_desc)

        # --- wxNSComboBox: Kombinationsfeld (wx.ComboBox) ---
        cls_combo = objc.lookUpClass("wxNSComboBox")

        @objc.typedSelector(b"@@:")
        def _combo_role(self):
            return NSAccessibilityComboBoxRole

        @objc.typedSelector(b"@@:")
        def _combo_role_desc(self):
            return "Kombinationsfeld"

        objc.classAddMethod(cls_combo, b"accessibilityRole", _combo_role)
        objc.classAddMethod(cls_combo, b"accessibilityRoleDescription", _combo_role_desc)

    except Exception:
        pass
