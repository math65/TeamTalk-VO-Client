"""Tests für die Qt-Mnemonik-/Ellipsis-Normalisierung in i18n._()."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from i18n import _, _reattach_decorations, _strip_qt_decorations, set_language


def setup_function(_func):
    set_language("de")


# ---------------------------------------------------------------------------
# _strip_qt_decorations
# ---------------------------------------------------------------------------

def test_strip_no_decorations():
    assert _strip_qt_decorations("Hilfe") == ("Hilfe", None, False)


def test_strip_simple_mnemonic():
    assert _strip_qt_decorations("&Hilfe") == ("Hilfe", "h", False)


def test_strip_mnemonic_inside_word():
    assert _strip_qt_decorations("Logs &exportieren") == ("Logs exportieren", "e", False)


def test_strip_trailing_ellipsis():
    assert _strip_qt_decorations("Verbinden...") == ("Verbinden", None, True)


def test_strip_mnemonic_and_ellipsis():
    assert _strip_qt_decorations("&Verbinden...") == ("Verbinden", "v", True)


def test_strip_escaped_ampersand_preserved():
    assert _strip_qt_decorations("Updates && Versionen") == ("Updates & Versionen", None, False)


def test_strip_ampersand_followed_by_space_is_literal():
    assert _strip_qt_decorations("Updates & Versionen") == ("Updates & Versionen", None, False)


def test_strip_only_first_mnemonic_consumed():
    stripped, mnem, _ell = _strip_qt_decorations("&Foo &Bar")
    assert stripped == "Foo &Bar"
    assert mnem == "f"


# ---------------------------------------------------------------------------
# _reattach_decorations
# ---------------------------------------------------------------------------

def test_reattach_mnemonic_matches_letter():
    assert _reattach_decorations("Aide", "a", False) == "&Aide"


def test_reattach_mnemonic_case_insensitive_match():
    assert _reattach_decorations("Connecter", "c", False) == "&Connecter"


def test_reattach_mnemonic_finds_inner_letter():
    assert _reattach_decorations("Exporter les journaux", "e", False) == "&Exporter les journaux"


def test_reattach_mnemonic_fallback_to_start():
    assert _reattach_decorations("Aide", "z", False) == "&Aide"


def test_reattach_ellipsis_only():
    assert _reattach_decorations("Aide", None, True) == "Aide..."


def test_reattach_both():
    assert _reattach_decorations("Aide", "a", True) == "&Aide..."


# ---------------------------------------------------------------------------
# End-to-end via _()
# ---------------------------------------------------------------------------

def test_direct_dict_lookup_still_works():
    set_language("fr")
    assert _("Verbinden") == "Connecter"


def test_qt_string_with_ellipsis_is_translated():
    set_language("fr")
    assert _("Verbinden...") == "Se connecter..."


def test_qt_string_with_mnemonic_and_ellipsis():
    set_language("fr")
    result = _("&Verbinden...")
    assert result.endswith("...")
    assert "&" in result


def test_explicit_dict_entry_with_mnemonic_takes_precedence():
    set_language("fr")
    assert _("Notiz &bearbeiten...") == "Modifier la &note..."


def test_untranslated_string_returned_as_is():
    set_language("fr")
    nonsense = "Zufallszeichenkette ohne Übersetzung xyz123"
    assert _(nonsense) == nonsense


def test_untranslated_qt_string_returned_as_is():
    set_language("fr")
    nonsense = "&Zufallszeichenkette xyz..."
    assert _(nonsense) == nonsense


def test_de_passthrough():
    set_language("de")
    assert _("&Verbinden...") == "&Verbinden..."
    assert _("Verbinden") == "Verbinden"


def test_en_qt_mnemonic_resolved():
    set_language("en")
    assert _("Verbinden...") == "Connect..."
    result = _("&Verbinden")
    assert "&" in result
