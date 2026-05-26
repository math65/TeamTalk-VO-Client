"""
Windows per-application audio capture via WASAPI Process Loopback API.

Captures the audio output of a specific Windows process and exposes
int16 PCM frames. ``AppAudioMixer`` mixes one or more captures into a
single MEDIAFILE stream that is fed to the channel via
``client.insert_audio_block_bytes()``.

Requires Windows 10 build 2004 (May 2020 Update) or newer. On other
platforms the module imports cleanly but ``is_available()`` returns
``False`` and instantiating ``AppAudioCapture`` raises ``RuntimeError``.
"""
from __future__ import annotations

import array
import ctypes as _ct
import logging
import queue
import sys
import threading
import uuid
from typing import List, Optional, Tuple

logger = logging.getLogger("tt.app_audio")


# ── Constants ──────────────────────────────────────────────────────────

_S_OK = 0
_AUDCLNT_SHAREMODE_SHARED = 0
_AUDCLNT_STREAMFLAGS_LOOPBACK = 0x00020000
_AUDCLNT_STREAMFLAGS_EVENTCALLBACK = 0x00040000
_AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM = 0x80000000
_AUDCLNT_BUFFERFLAGS_SILENT = 0x2
_WAVE_FORMAT_PCM = 1
_VT_BLOB = 65

_VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK = "VAD\\Process_Loopback"
_ACTIVATION_TYPE_PROCESS_LOOPBACK = 1
_PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE = 0

_IS_WIN = sys.platform == "win32"


# ── GUID helper ────────────────────────────────────────────────────────

class _GUID(_ct.Structure):
    _fields_ = [("data", _ct.c_byte * 16)]


def _guid(s: str) -> "_GUID":
    g = _GUID()
    _ct.memmove(g.data, uuid.UUID(s).bytes_le, 16)
    return g


_IID_IAudioClient = _guid("{1CB9AD4C-DBFA-4c32-B178-C2F568A703B2}")
_IID_IAudioCaptureClient = _guid("{C8ADBD64-E71E-48a0-A4DE-185C395CD317}")


# ── Structures ─────────────────────────────────────────────────────────

class _WAVEFORMATEX(_ct.Structure):
    _fields_ = [
        ("wFormatTag", _ct.c_ushort),
        ("nChannels", _ct.c_ushort),
        ("nSamplesPerSec", _ct.c_ulong),
        ("nAvgBytesPerSec", _ct.c_ulong),
        ("nBlockAlign", _ct.c_ushort),
        ("wBitsPerSample", _ct.c_ushort),
        ("cbSize", _ct.c_ushort),
    ]


class _AUDIOCLIENT_PROCESS_LOOPBACK_PARAMS(_ct.Structure):
    _fields_ = [
        ("TargetProcessId", _ct.c_ulong),
        ("ProcessLoopbackMode", _ct.c_int),
    ]


class _AUDIOCLIENT_ACTIVATION_PARAMS(_ct.Structure):
    _fields_ = [
        ("ActivationType", _ct.c_int),
        ("ProcessLoopbackParams", _AUDIOCLIENT_PROCESS_LOOPBACK_PARAMS),
    ]


class _PROPVARIANT(_ct.Structure):
    _fields_ = [
        ("vt", _ct.c_ushort),
        ("wReserved1", _ct.c_ushort),
        ("wReserved2", _ct.c_ushort),
        ("wReserved3", _ct.c_ushort),
        ("blob_cbSize", _ct.c_ulong),
        ("blob_pBlobData", _ct.c_void_p),
    ]


# ── COM vtable helpers / DLL bindings (Windows-only) ───────────────────
#
# Everything in this block uses ``ctypes.WINFUNCTYPE`` (Windows stdcall
# wrappers) which only exists on Windows. On other platforms the names
# stay undefined and the public ``AppAudioCapture`` raises RuntimeError
# at construction; ``AppAudioMixer`` works as an inert no-op.

_API_AVAILABLE = False
_ActivateAudioInterfaceAsync = None

if _IS_WIN:
    def _vcall(ptr, index, restype, *argtypes):
        vtbl = _ct.cast(ptr, _ct.POINTER(_ct.c_void_p))[0]
        arr = _ct.cast(vtbl, _ct.POINTER(_ct.c_void_p * (index + 1)))
        return _ct.WINFUNCTYPE(restype, _ct.c_void_p, *argtypes)(arr.contents[index])

    class _AudioClient:
        def __init__(self, ptr):
            self.ptr = ptr

        def Initialize(self, mode, flags, duration, period, fmt_ptr, guid_ptr):
            fn = _vcall(self.ptr, 3, _ct.c_long,
                        _ct.c_int, _ct.c_ulong, _ct.c_longlong, _ct.c_longlong,
                        _ct.c_void_p, _ct.c_void_p)
            return fn(self.ptr, mode, flags, duration, period, fmt_ptr, guid_ptr)

        def Start(self):
            return _vcall(self.ptr, 10, _ct.c_long)(self.ptr)

        def Stop(self):
            return _vcall(self.ptr, 11, _ct.c_long)(self.ptr)

        def SetEventHandle(self, event_handle):
            return _vcall(self.ptr, 13, _ct.c_long, _ct.c_void_p)(self.ptr, event_handle)

        def GetService(self, iid_ptr):
            p = _ct.c_void_p()
            _vcall(self.ptr, 14, _ct.c_long,
                   _ct.c_void_p, _ct.POINTER(_ct.c_void_p))(self.ptr, iid_ptr, _ct.byref(p))
            return p.value

        def Release(self):
            _vcall(self.ptr, 2, _ct.c_ulong)(self.ptr)

    class _CaptureClient:
        def __init__(self, ptr):
            self.ptr = ptr
            self._fn_next = _vcall(ptr, 5, _ct.c_long, _ct.POINTER(_ct.c_uint))
            self._fn_get = _vcall(ptr, 3, _ct.c_long,
                                  _ct.POINTER(_ct.c_void_p), _ct.POINTER(_ct.c_uint),
                                  _ct.POINTER(_ct.c_ulong), _ct.c_void_p, _ct.c_void_p)
            self._fn_rel = _vcall(ptr, 4, _ct.c_long, _ct.c_uint)

        def GetNextPacketSize(self):
            v = _ct.c_uint()
            self._fn_next(self.ptr, _ct.byref(v))
            return v.value

        def GetBuffer(self):
            data = _ct.c_void_p()
            frames = _ct.c_uint()
            flags = _ct.c_ulong()
            hr = self._fn_get(self.ptr, _ct.byref(data), _ct.byref(frames),
                              _ct.byref(flags), None, None)
            return hr, data.value, frames.value, flags.value

        def ReleaseBuffer(self, n):
            return self._fn_rel(self.ptr, n)

    class _AsyncOp:
        def __init__(self, ptr):
            self.ptr = ptr

        def GetActivateResult(self):
            hr_out = _ct.c_long()
            intf = _ct.c_void_p()
            _vcall(self.ptr, 3, _ct.c_long,
                   _ct.POINTER(_ct.c_long), _ct.POINTER(_ct.c_void_p))(
                self.ptr, _ct.byref(hr_out), _ct.byref(intf))
            return hr_out.value, intf.value

        def Release(self):
            _vcall(self.ptr, 2, _ct.c_ulong)(self.ptr)

    _QI_T = _ct.WINFUNCTYPE(_ct.c_long, _ct.c_void_p, _ct.c_void_p, _ct.POINTER(_ct.c_void_p))
    _ADDREF_T = _ct.WINFUNCTYPE(_ct.c_ulong, _ct.c_void_p)
    _RELEASE_T = _ct.WINFUNCTYPE(_ct.c_ulong, _ct.c_void_p)
    _COMPLETED_T = _ct.WINFUNCTYPE(_ct.c_long, _ct.c_void_p, _ct.c_void_p)

    class _HandlerVtbl(_ct.Structure):
        _fields_ = [
            ("QueryInterface", _QI_T),
            ("AddRef", _ADDREF_T),
            ("Release", _RELEASE_T),
            ("ActivateCompleted", _COMPLETED_T),
        ]

    class _CompletionHandler:
        """COM object implementing IActivateAudioInterfaceCompletionHandler."""

        def __init__(self):
            self.event = threading.Event()

            @_QI_T
            def qi(this, riid, ppv):
                ppv[0] = this
                return _S_OK

            @_ADDREF_T
            def addref(this):
                return 1

            @_RELEASE_T
            def release(this):
                return 1

            @_COMPLETED_T
            def completed(this, op):
                self.event.set()
                return _S_OK

            self._refs = (qi, addref, release, completed)
            self._vtbl = _HandlerVtbl(qi, addref, release, completed)
            self._obj = (_ct.c_void_p * 1)(_ct.addressof(self._vtbl))

        @property
        def ptr(self):
            return _ct.addressof(self._obj)

    try:
        _mmdevapi = _ct.WinDLL("mmdevapi")
        _ActivateAudioInterfaceAsync = _mmdevapi.ActivateAudioInterfaceAsync
        _ActivateAudioInterfaceAsync.restype = _ct.c_long
        _ActivateAudioInterfaceAsync.argtypes = [
            _ct.c_wchar_p,
            _ct.c_void_p,
            _ct.c_void_p,
            _ct.c_void_p,
            _ct.POINTER(_ct.c_void_p),
        ]
        _API_AVAILABLE = True
    except (OSError, AttributeError):
        _API_AVAILABLE = False


# ── Public API ─────────────────────────────────────────────────────────

def is_available() -> bool:
    """True iff WASAPI Process Loopback is usable (Windows 10 2004+)."""
    return _API_AVAILABLE


def pycaw_available() -> bool:
    """True iff the optional ``pycaw`` package is importable."""
    try:
        import pycaw.pycaw  # noqa: F401
        return True
    except Exception:
        return False


def list_audio_processes() -> List[Tuple[int, str]]:
    """Return ``[(pid, name), …]`` for processes currently producing audio.

    Empty list if ``pycaw`` is missing or enumeration fails. Sorted by name.
    """
    try:
        from pycaw.pycaw import AudioUtilities
    except Exception:
        return []
    try:
        sessions = AudioUtilities.GetAllSessions()
    except Exception as e:
        logger.warning("Failed to enumerate audio sessions: %s", e)
        return []
    result: List[Tuple[int, str]] = []
    seen = set()
    for s in sessions:
        proc = getattr(s, "Process", None)
        if not proc or proc.pid in seen:
            continue
        try:
            name = proc.name()
        except Exception:
            continue
        seen.add(proc.pid)
        result.append((proc.pid, name))
    return sorted(result, key=lambda x: x[1].lower())


class AppAudioCapture:
    """Capture audio from one Windows process via WASAPI Process Loopback.

    Frames are int16 PCM at the requested sample rate/channels, exposed
    through ``self.queue`` (``queue.Queue[bytes]``, maxsize=30, oldest
    dropped on overflow). ``self.error`` is populated if the pump thread
    crashes; check it from the consumer.
    """

    def __init__(self, pid: int, target_sample_rate: int = 48000,
                 target_channels: int = 1, frame_size: int = 960):
        if not _API_AVAILABLE:
            raise RuntimeError("WASAPI Process Loopback API not available")
        self._pid = pid
        self._target_sr = target_sample_rate
        self._target_ch = target_channels
        self._frame_size = frame_size
        self._frame_bytes = frame_size * target_channels * 2
        self._client: Optional[_AudioClient] = None
        self._capture: Optional[_CaptureClient] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._capture_event = None
        self._activate_event: Optional[threading.Event] = None
        self._activate_error: Optional[str] = None
        self.queue: "queue.Queue[bytes]" = queue.Queue(maxsize=30)
        self._volume = 1.0
        self.error: Optional[str] = None

    def set_volume(self, linear: float) -> None:
        """Set capture volume (0.0 = muted, 1.0 = unity, 2.0 = +6 dB)."""
        self._volume = max(0.0, min(2.0, linear))

    def start(self) -> None:
        """Activate the loopback and start the capture thread.

        Raises ``RuntimeError`` if activation fails (process gone, UAC
        elevation mismatch, unsupported Windows version, …).
        """
        if self._running:
            return
        self.error = None
        self._running = True
        self._activate_error = None
        self._activate_event = threading.Event()
        self._thread = threading.Thread(
            target=self._activate_and_capture,
            daemon=True,
            name=f"app-audio-capture-{self._pid}",
        )
        self._thread.start()
        self._activate_event.wait(timeout=10.0)
        if self._activate_error:
            self._running = False
            self._thread = None
            raise RuntimeError(self._activate_error)

    def stop(self) -> None:
        self._running = False
        if self._capture_event:
            try:
                _ct.windll.kernel32.SetEvent(self._capture_event)
            except Exception:
                pass
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
        if self._client:
            try:
                self._client.Stop()
            except Exception:
                pass
            try:
                self._client.Release()
            except Exception:
                pass
            self._client = None
            self._capture = None
        if self._capture_event:
            try:
                _ct.windll.kernel32.CloseHandle(self._capture_event)
            except Exception:
                pass
            self._capture_event = None
        while not self.queue.empty():
            try:
                self.queue.get_nowait()
            except queue.Empty:
                break

    # ── Private ────────────────────────────────────────────────────────

    def _activate_and_capture(self) -> None:
        _ct.windll.ole32.CoInitializeEx(None, 0)  # COINIT_MULTITHREADED
        try:
            self._activate()
            assert self._activate_event is not None
            self._activate_event.set()
            self._capture_loop()
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            logger.error("App audio activation failed for PID %d:\n%s", self._pid, tb)
            self._activate_error = f"{e}\n{tb}"
            if self._activate_event is not None:
                self._activate_event.set()
        finally:
            try:
                _ct.windll.ole32.CoUninitialize()
            except Exception:
                pass

    def _activate(self) -> None:
        params = _AUDIOCLIENT_ACTIVATION_PARAMS()
        params.ActivationType = _ACTIVATION_TYPE_PROCESS_LOOPBACK
        params.ProcessLoopbackParams.TargetProcessId = self._pid
        params.ProcessLoopbackParams.ProcessLoopbackMode = (
            _PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE
        )

        pv = _PROPVARIANT()
        pv.vt = _VT_BLOB
        pv.blob_cbSize = _ct.sizeof(params)
        pv.blob_pBlobData = _ct.addressof(params)

        handler = _CompletionHandler()
        operation = _ct.c_void_p()

        hr = _ActivateAudioInterfaceAsync(
            _VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK,
            _ct.addressof(_IID_IAudioClient),
            _ct.addressof(pv),
            handler.ptr,
            _ct.byref(operation),
        )
        if hr != _S_OK:
            raise OSError(f"ActivateAudioInterfaceAsync failed: 0x{hr & 0xFFFFFFFF:08X}")
        if not handler.event.wait(timeout=5.0):
            raise TimeoutError("Audio interface activation timed out")
        if not operation.value:
            raise OSError("ActivateAudioInterfaceAsync returned NULL operation")

        op = _AsyncOp(operation.value)
        try:
            act_hr, intf_ptr = op.GetActivateResult()
            if act_hr != _S_OK or not intf_ptr:
                raise OSError(
                    f"Process audio activation failed: 0x{act_hr & 0xFFFFFFFF:08X}"
                )
        finally:
            op.Release()

        audio_client_ptr = _ct.c_void_p()
        qi_fn = _vcall(intf_ptr, 0, _ct.c_long,
                       _ct.c_void_p, _ct.POINTER(_ct.c_void_p))
        hr = qi_fn(intf_ptr, _ct.addressof(_IID_IAudioClient),
                   _ct.byref(audio_client_ptr))
        _vcall(intf_ptr, 2, _ct.c_ulong)(intf_ptr)
        if hr != _S_OK or not audio_client_ptr.value:
            raise OSError(
                f"QueryInterface for IAudioClient failed: 0x{hr & 0xFFFFFFFF:08X}"
            )

        self._client = _AudioClient(audio_client_ptr.value)

        fmt = _WAVEFORMATEX()
        fmt.wFormatTag = _WAVE_FORMAT_PCM
        fmt.nChannels = self._target_ch
        fmt.nSamplesPerSec = self._target_sr
        fmt.wBitsPerSample = 16
        fmt.nBlockAlign = self._target_ch * 2
        fmt.nAvgBytesPerSec = self._target_sr * self._target_ch * 2
        fmt.cbSize = 0

        _kernel32 = _ct.windll.kernel32
        self._capture_event = _kernel32.CreateEventW(None, False, False, None)
        if not self._capture_event:
            self._client.Release()
            self._client = None
            raise OSError("CreateEvent failed")

        stream_flags = (_AUDCLNT_STREAMFLAGS_LOOPBACK |
                        _AUDCLNT_STREAMFLAGS_EVENTCALLBACK |
                        _AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM)
        hr = self._client.Initialize(
            _AUDCLNT_SHAREMODE_SHARED,
            stream_flags,
            0, 0,
            _ct.addressof(fmt),
            None,
        )
        if hr != _S_OK:
            _kernel32.CloseHandle(self._capture_event)
            self._capture_event = None
            self._client.Release()
            self._client = None
            raise OSError(f"IAudioClient::Initialize failed: 0x{hr & 0xFFFFFFFF:08X}")

        hr = self._client.SetEventHandle(self._capture_event)
        if hr != _S_OK:
            _kernel32.CloseHandle(self._capture_event)
            self._capture_event = None
            self._client.Release()
            self._client = None
            raise OSError(f"SetEventHandle failed: 0x{hr & 0xFFFFFFFF:08X}")

        cap_ptr = self._client.GetService(_ct.addressof(_IID_IAudioCaptureClient))
        if not cap_ptr:
            _kernel32.CloseHandle(self._capture_event)
            self._capture_event = None
            self._client.Release()
            self._client = None
            raise OSError("Failed to get IAudioCaptureClient")
        self._capture = _CaptureClient(cap_ptr)

        hr = self._client.Start()
        if hr != _S_OK:
            _kernel32.CloseHandle(self._capture_event)
            self._capture_event = None
            self._client.Release()
            self._client = None
            raise OSError(f"IAudioClient::Start failed: 0x{hr & 0xFFFFFFFF:08X}")

        logger.info("App audio capture started: PID=%d, %dHz %dch int16",
                    self._pid, self._target_sr, self._target_ch)

    def _capture_loop(self) -> None:
        _kernel32 = _ct.windll.kernel32
        accumulator = bytearray()
        try:
            while self._running:
                _kernel32.WaitForSingleObject(self._capture_event, 20)
                if not self._running:
                    break
                try:
                    pkt = self._capture.GetNextPacketSize()
                except Exception:
                    break
                if pkt == 0:
                    continue
                while pkt > 0 and self._running:
                    hr, data_ptr, n_frames, flags = self._capture.GetBuffer()
                    if hr != _S_OK:
                        break
                    if n_frames > 0:
                        if flags & _AUDCLNT_BUFFERFLAGS_SILENT:
                            accumulator.extend(
                                b"\x00" * (n_frames * self._target_ch * 2))
                        elif data_ptr:
                            accumulator.extend(self._convert(data_ptr, n_frames))
                    self._capture.ReleaseBuffer(n_frames)
                    try:
                        pkt = self._capture.GetNextPacketSize()
                    except Exception:
                        pkt = 0
                while len(accumulator) >= self._frame_bytes:
                    frame = bytes(accumulator[:self._frame_bytes])
                    del accumulator[:self._frame_bytes]
                    if self.queue.full():
                        try:
                            self.queue.get_nowait()
                        except queue.Empty:
                            pass
                    try:
                        self.queue.put_nowait(frame)
                    except queue.Full:
                        pass
        except Exception as e:
            logger.error("App audio capture loop error (PID %d): %s", self._pid, e)
            self.error = str(e)

    def _convert(self, data_ptr: int, n_frames: int) -> bytes:
        raw_size = n_frames * self._target_ch * 2
        raw = bytes((_ct.c_byte * raw_size).from_address(data_ptr))
        vol = self._volume
        if vol == 1.0:
            return raw
        src = array.array("h")
        src.frombytes(raw)
        for i in range(len(src)):
            v = int(src[i] * vol)
            if v > 32767:
                v = 32767
            elif v < -32768:
                v = -32768
            src[i] = v
        return src.tobytes()


class AppAudioMixer:
    """Aggregate N ``AppAudioCapture`` streams and feed them as one
    MEDIAFILE stream via ``client.insert_audio_block_bytes()``.

    The mixer owns a daemon pump thread that, every ``frame_size`` samples,
    pulls one frame from each active capture, sums them with int16
    saturation, and inserts the result. With zero active captures the
    pump exits and the mixer is idle (no thread, no insertions).
    """

    def __init__(self, client, sample_rate: int = 48000,
                 channels: int = 1, frame_size: int = 960):
        self._client = client
        self._sr = sample_rate
        self._ch = channels
        self._frame_size = frame_size
        self._frame_bytes = frame_size * channels * 2
        self._captures: dict[int, AppAudioCapture] = {}
        self._lock = threading.Lock()
        self._volume = 1.0
        self._pump: Optional[threading.Thread] = None
        self._stop = threading.Event()

    @property
    def active_pids(self) -> set:
        with self._lock:
            return set(self._captures.keys())

    @property
    def is_active(self) -> bool:
        with self._lock:
            return bool(self._captures)

    def set_volume(self, linear: float) -> None:
        v = max(0.0, min(2.0, linear))
        with self._lock:
            self._volume = v
            for cap in self._captures.values():
                cap.set_volume(v)

    def set_captures(self, pids: List[int]) -> Tuple[List[int], List[Tuple[int, str]]]:
        """Reconcile active captures with ``pids``.

        Returns ``(started_or_kept_pids, errors)`` where ``errors`` is a
        list of ``(pid, message)`` for captures that failed to start.
        """
        wanted = set(pids)
        with self._lock:
            current = set(self._captures.keys())
            for pid in current - wanted:
                try:
                    self._captures[pid].stop()
                except Exception:
                    pass
                del self._captures[pid]
            errors: List[Tuple[int, str]] = []
            for pid in wanted - current:
                try:
                    cap = AppAudioCapture(
                        pid,
                        target_sample_rate=self._sr,
                        target_channels=self._ch,
                        frame_size=self._frame_size,
                    )
                    cap.set_volume(self._volume)
                    cap.start()
                    self._captures[pid] = cap
                except Exception as e:
                    logger.warning("Failed to start capture for PID %d: %s", pid, e)
                    errors.append((pid, str(e)))
            ok_pids = sorted(self._captures.keys())
            has_captures = bool(self._captures)

        if has_captures:
            self._ensure_pump()
        else:
            self._stop_pump()
        return ok_pids, errors

    def stop_all(self) -> None:
        with self._lock:
            for cap in self._captures.values():
                try:
                    cap.stop()
                except Exception:
                    pass
            self._captures.clear()
        self._stop_pump()

    # ── Private ────────────────────────────────────────────────────────

    def _ensure_pump(self) -> None:
        if self._pump and self._pump.is_alive():
            return
        self._stop.clear()
        self._pump = threading.Thread(
            target=self._pump_loop,
            daemon=True,
            name="app-audio-mixer-pump",
        )
        self._pump.start()

    def _stop_pump(self) -> None:
        self._stop.set()
        pump = self._pump
        if pump:
            pump.join(timeout=1.5)
        self._pump = None

    def _pump_loop(self) -> None:
        zero = bytes(self._frame_bytes)
        try:
            while not self._stop.is_set():
                with self._lock:
                    caps = list(self._captures.values())
                if not caps:
                    return
                # Pull one frame from each active capture (non-blocking).
                frames: List[bytes] = []
                got_anything = False
                for cap in caps:
                    try:
                        f = cap.queue.get(timeout=0.005)
                        frames.append(f)
                        got_anything = True
                    except queue.Empty:
                        continue
                if not got_anything:
                    continue
                if len(frames) == 1:
                    mixed = frames[0]
                else:
                    mixed = self._mix_frames(frames, zero)
                try:
                    self._client.insert_audio_block_bytes(mixed, self._sr, self._ch)
                except Exception as e:
                    logger.warning("insert_audio_block_bytes failed: %s", e)
        except Exception as e:
            logger.exception("Mixer pump crashed: %s", e)

    def _mix_frames(self, frames: List[bytes], zero: bytes) -> bytes:
        # Pad/trim each frame to expected size, then sum with saturation.
        acc = array.array("h", [0] * (self._frame_bytes // 2))
        for raw in frames:
            if len(raw) != self._frame_bytes:
                if len(raw) < self._frame_bytes:
                    raw = raw + zero[: self._frame_bytes - len(raw)]
                else:
                    raw = raw[: self._frame_bytes]
            src = array.array("h")
            src.frombytes(raw)
            for i in range(len(acc)):
                v = acc[i] + src[i]
                if v > 32767:
                    v = 32767
                elif v < -32768:
                    v = -32768
                acc[i] = v
        return acc.tobytes()
