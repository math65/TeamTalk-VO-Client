"""Barrierefreiheits-Helfer: VoiceOver-Rollen für wxPython auf macOS."""
from __future__ import annotations

import sys

import wx


class ListAccessible(wx.Accessible):
    """Setzt ROLE_SYSTEM_LIST, damit VoiceOver 'Liste' statt 'Tabelle' ansagt."""

    def GetRole(self, childId: int):
        if childId == 0:
            return (wx.ACC_OK, wx.ROLE_SYSTEM_LIST)
        return super().GetRole(childId)

    def GetName(self, childId: int):
        if childId == 0:
            win = self.GetWindow()
            return (wx.ACC_OK, win.GetName() if win else "")
        return super().GetName(childId)


def setup_list_accessible(lb: wx.ListBox) -> None:
    """Weist einer ListBox die korrekte VoiceOver-Rolle 'Liste' zu."""
    if sys.platform == "darwin":
        try:
            lb.SetAccessible(ListAccessible(lb))
        except Exception:
            pass
