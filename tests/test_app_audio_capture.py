"""Smoke tests for src/app_audio_capture.py — cross-platform.

The real Windows-only capture cannot be exercised on CI macOS/Linux,
so these tests verify the module imports cleanly, public symbols
exist, the graceful-degradation paths work, and the mixer lifecycle
is sane against a fake client.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import app_audio_capture as m  # noqa: E402


def test_module_exposes_public_api():
    assert callable(m.is_available)
    assert callable(m.pycaw_available)
    assert callable(m.list_audio_processes)
    assert hasattr(m, "AppAudioCapture")
    assert hasattr(m, "AppAudioMixer")


def test_is_available_false_on_non_windows():
    if sys.platform == "win32":
        pytest.skip("Windows-only behaviour")
    assert m.is_available() is False


def test_capture_raises_on_non_windows():
    if sys.platform == "win32":
        pytest.skip("Real activation tested manually on Windows")
    with pytest.raises(RuntimeError):
        m.AppAudioCapture(pid=1234).start()


def test_list_returns_list_even_without_pycaw():
    # Without pycaw installed (or on non-Windows) we must still return
    # an empty list rather than raising.
    result = m.list_audio_processes()
    assert isinstance(result, list)


def test_mixer_lifecycle_with_fake_client():
    class FakeClient:
        def __init__(self):
            self.calls = []

        def insert_audio_block_bytes(self, pcm, sr, ch):
            self.calls.append((len(pcm), sr, ch))
            return True

    mixer = m.AppAudioMixer(FakeClient())
    assert mixer.active_pids == set()
    assert mixer.is_active is False
    mixer.set_volume(0.5)
    mixer.set_volume(3.0)  # Clamped to 2.0 internally
    mixer.stop_all()
    assert mixer.active_pids == set()


def test_mixer_set_captures_returns_errors_on_non_windows():
    if sys.platform == "win32":
        pytest.skip("Real activation tested manually on Windows")

    class FakeClient:
        def insert_audio_block_bytes(self, pcm, sr, ch):
            return True

    mixer = m.AppAudioMixer(FakeClient())
    ok_pids, errors = mixer.set_captures([4231, 1144])
    assert ok_pids == []
    assert len(errors) == 2
    assert all(isinstance(pid, int) and isinstance(msg, str)
               for pid, msg in errors)
