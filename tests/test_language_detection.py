"""Tests für die automatische Sprach-Erkennung beim ersten Start."""
import locale
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest

from i18n import detect_system_language, ensure_language


_POSIX_ENV_VARS = ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE")


def _clear_env(monkeypatch):
    for var in _POSIX_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


# ---------------------------------------------------------------------------
# detect_system_language
# ---------------------------------------------------------------------------

def test_detect_locale_fr_returns_fr(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setattr(locale, "getlocale", lambda *a, **kw: ("fr_FR", "UTF-8"))
    assert detect_system_language() == "fr"


def test_detect_locale_de_returns_de(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setattr(locale, "getlocale", lambda *a, **kw: ("de_DE", "UTF-8"))
    assert detect_system_language() == "de"


def test_detect_locale_es_ar_returns_es(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setattr(locale, "getlocale", lambda *a, **kw: ("es_AR", "UTF-8"))
    assert detect_system_language() == "es"


def test_unsupported_locale_falls_back_to_en(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setattr(locale, "getlocale", lambda *a, **kw: ("it_IT", "UTF-8"))
    assert detect_system_language() == "en"


def test_locale_none_uses_lang_env(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setattr(locale, "getlocale", lambda *a, **kw: (None, None))
    monkeypatch.setenv("LANG", "es_ES.UTF-8")
    assert detect_system_language() == "es"


def test_language_env_picks_first_supported(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setattr(locale, "getlocale", lambda *a, **kw: (None, None))
    monkeypatch.setenv("LANGUAGE", "it:fr:en")
    assert detect_system_language() == "fr"


def test_lc_all_takes_precedence_over_lang(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setattr(locale, "getlocale", lambda *a, **kw: (None, None))
    monkeypatch.setenv("LC_ALL", "de_DE.UTF-8")
    monkeypatch.setenv("LANG", "fr_FR.UTF-8")
    assert detect_system_language() == "de"


def test_no_locale_no_env_returns_en_default(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setattr(locale, "getlocale", lambda *a, **kw: (None, None))
    assert detect_system_language() == "en"


def test_locale_raises_falls_back_to_en(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setattr(locale, "getlocale", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("locale broken")))
    assert detect_system_language() == "en"


def test_custom_default_respected_when_nothing_detectable(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setattr(locale, "getlocale", lambda *a, **kw: (None, None))
    assert detect_system_language(default="de") == "de"


def test_posix_c_locale_ignored(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setattr(locale, "getlocale", lambda *a, **kw: (None, None))
    monkeypatch.setenv("LANG", "C")
    monkeypatch.setenv("LC_ALL", "POSIX")
    assert detect_system_language() == "en"


# ---------------------------------------------------------------------------
# ensure_language
# ---------------------------------------------------------------------------

class _FakeSettings:
    def __init__(self, app_language: str = ""):
        self.app_language = app_language


class _FakeStore:
    def __init__(self, app_language: str = ""):
        self.settings = _FakeSettings(app_language)
        self.save_calls = 0

    def save(self) -> None:
        self.save_calls += 1


def test_ensure_language_detects_and_persists_when_empty(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setattr(locale, "getlocale", lambda *a, **kw: ("fr_FR", "UTF-8"))
    store = _FakeStore(app_language="")
    result = ensure_language(store)
    assert result == "fr"
    assert store.settings.app_language == "fr"
    assert store.save_calls == 1


def test_ensure_language_skips_when_already_set(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setattr(locale, "getlocale", lambda *a, **kw: ("fr_FR", "UTF-8"))
    store = _FakeStore(app_language="de")
    result = ensure_language(store)
    assert result == "de"
    assert store.settings.app_language == "de"
    assert store.save_calls == 0


def test_ensure_language_detects_en_when_unsupported_system_lang(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setattr(locale, "getlocale", lambda *a, **kw: ("ja_JP", "UTF-8"))
    store = _FakeStore(app_language="")
    result = ensure_language(store)
    assert result == "en"
    assert store.settings.app_language == "en"
    assert store.save_calls == 1
