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


def patch_button_accessibility() -> None:
    """Swizzelt wxNSButton einmalig, damit VoiceOver 'Taste' / 'Kontrollkästchen' ansagt.

    Muss einmal beim Programmstart aufgerufen werden (nach wx.App-Erstellung).
    """
    if sys.platform != "darwin":
        return

    try:
        import objc  # noqa: PLC0415
        from AppKit import (  # noqa: PLC0415
            NSAccessibilityButtonRole,
            NSAccessibilityCheckBoxRole,
        )

        cls = objc.lookUpClass("wxNSButton")

        # bezelStyle == 0  →  CheckBox / Schalter
        # bezelStyle != 0  →  normaler Button / Taste

        @objc.typedSelector(b"@@:")
        def _new_role(self):
            try:
                return (
                    NSAccessibilityCheckBoxRole
                    if self.bezelStyle() == 0
                    else NSAccessibilityButtonRole
                )
            except Exception:
                return NSAccessibilityButtonRole

        @objc.typedSelector(b"@@:")
        def _new_role_desc(self):
            try:
                return (
                    "Kontrollkästchen"
                    if self.bezelStyle() == 0
                    else "Taste"
                )
            except Exception:
                return "Taste"

        objc.classAddMethod(cls, b"accessibilityRole", _new_role)
        objc.classAddMethod(cls, b"accessibilityRoleDescription", _new_role_desc)
    except Exception:
        pass
