from __future__ import annotations

import ctypes
import time
import threading
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

from .tt import load_teamtalk_module


@dataclass
class ConnectResult:
    ok: bool
    message: str


class TeamTalkClient:
    def __init__(self) -> None:
        self.tt = load_teamtalk_module()
        self.client = self.tt.TeamTalk()
        self._event_thread: Optional[threading.Thread] = None
        self._event_stop = threading.Event()
        self._last_connect: Optional[Tuple[str, int, int, str, str, str, str, bool]] = None
        self._connected = False

    def _timestamp_ms(self) -> int:
        return int(round(time.time() * 1000))

    def _wait_for_event(self, event, timeout_ms: int) -> Tuple[bool, "TTMessage"]:
        end = self._timestamp_ms() + timeout_ms
        msg = self.client.getMessage(timeout_ms)
        while msg.nClientEvent != event:
            if self._timestamp_ms() >= end:
                return False, self.tt.TTMessage()
            msg = self.client.getMessage(timeout_ms)
        return True, msg

    def _wait_for_events(self, events, timeout_ms: int) -> Tuple[bool, "TTMessage"]:
        end = self._timestamp_ms() + timeout_ms
        msg = self.client.getMessage(timeout_ms)
        while msg.nClientEvent not in events:
            if self._timestamp_ms() >= end:
                return False, self.tt.TTMessage()
            msg = self.client.getMessage(timeout_ms)
        return True, msg

    def _wait_for_cmd_success(self, cmdid: int, timeout_ms: int) -> Tuple[bool, "TTMessage"]:
        result = True
        while result:
            result, msg = self._wait_for_event(self.tt.ClientEvent.CLIENTEVENT_CMD_SUCCESS, timeout_ms)
            if result and msg.nSource == cmdid:
                return result, msg
        return False, self.tt.TTMessage()

    def _wait_for_cmd_result(self, cmdid: int, timeout_ms: int) -> Tuple[bool, "TTMessage"]:
        end = self._timestamp_ms() + timeout_ms
        while self._timestamp_ms() < end:
            msg = self.client.getMessage(timeout_ms)
            if msg.nClientEvent == self.tt.ClientEvent.CLIENTEVENT_CMD_SUCCESS and msg.nSource == cmdid:
                return True, msg
            if msg.nClientEvent == self.tt.ClientEvent.CLIENTEVENT_CMD_ERROR and msg.nSource == cmdid:
                return False, msg
        return False, self.tt.TTMessage()

    def _drain_message_queue(self, max_messages: int = 200) -> None:
        """Drop stale SDK events before starting a new connect sequence."""
        for _ in range(max_messages):
            msg = self.client.getMessage(0)
            if msg.nClientEvent == self.tt.ClientEvent.CLIENTEVENT_NONE:
                break

    def connect_and_login(
        self,
        host: str,
        tcp_port: int,
        udp_port: int,
        nickname: str,
        username: str,
        password: str,
        client_name: str,
        encrypted: bool = False,
        timeout_ms: int = 8000,
    ) -> ConnectResult:
        self._last_connect = (host, tcp_port, udp_port, nickname, username, password, client_name, encrypted)
        # Ensure prior sessions do not block reconnect/server-switch.
        try:
            self.client.disconnect()
        except Exception:
            pass
        self._connected = False
        self._drain_message_queue()

        if encrypted:
            try:
                ctx = self.tt.EncryptionContext()
                # Allow encrypted connections even when server uses self-signed certs.
                ctx.bVerifyPeer = False
                ctx.bVerifyClientOnce = False
                ctx.nVerifyDepth = 0
                self.client.setEncryptionContext(ctx)
            except Exception:
                pass
        else:
            try:
                # Reset any previous TLS context when using plain connections.
                self.client.setEncryptionContext(self.tt.EncryptionContext())
            except Exception:
                pass

        if not self.client.connect(self.tt.ttstr(host), tcp_port, udp_port, 0, 0, encrypted):
            return ConnectResult(False, "Verbindung konnte nicht gestartet werden")

        ok, msg = self._wait_for_events(
            (
                self.tt.ClientEvent.CLIENTEVENT_CON_SUCCESS,
                self.tt.ClientEvent.CLIENTEVENT_CON_FAILED,
                self.tt.ClientEvent.CLIENTEVENT_CON_CRYPT_ERROR,
            ),
            timeout_ms,
        )
        if not ok:
            return ConnectResult(False, "Verbindung fehlgeschlagen")
        if msg.nClientEvent == self.tt.ClientEvent.CLIENTEVENT_CON_FAILED:
            return ConnectResult(False, "Verbindung fehlgeschlagen")
        if msg.nClientEvent == self.tt.ClientEvent.CLIENTEVENT_CON_CRYPT_ERROR:
            return ConnectResult(False, "Verschluesselungsfehler")

        cmdid = self.client.doLogin(
            self.tt.ttstr(nickname),
            self.tt.ttstr(username),
            self.tt.ttstr(password),
            self.tt.ttstr(client_name),
        )

        ok, _ = self._wait_for_event(self.tt.ClientEvent.CLIENTEVENT_CMD_MYSELF_LOGGEDIN, timeout_ms)
        if not ok:
            return ConnectResult(False, "Login fehlgeschlagen")

        ok, msg = self._wait_for_cmd_result(cmdid, timeout_ms)
        if not ok:
            if msg.nClientEvent == self.tt.ClientEvent.CLIENTEVENT_CMD_ERROR:
                err = self.tt.ttstr(msg.clienterrormsg.szErrorMsg)
                return ConnectResult(False, f"Login fehlgeschlagen: {err}")
            return ConnectResult(False, "Server antwortet nicht auf Login")

        self._connected = True
        return ConnectResult(True, f"Eingeloggt in Kanal: {self.tt.ttstr(msg.channel.szName)}")

    def join_root_channel(self, timeout_ms: int = 2000) -> ConnectResult:
        cmdid = self.client.doJoinChannelByID(self.client.getRootChannelID(), self.tt.ttstr(""))
        ok, _ = self._wait_for_cmd_success(cmdid, timeout_ms)
        if not ok:
            return ConnectResult(False, "Kanalbeitritt fehlgeschlagen")
        return ConnectResult(True, "Kanalbeitritt erfolgreich")

    def join_channel_by_id(self, channel_id: int, password: str = "", timeout_ms: int = 2000) -> ConnectResult:
        cmdid = self.client.doJoinChannelByID(channel_id, self.tt.ttstr(password))
        ok, msg = self._wait_for_cmd_result(cmdid, timeout_ms)
        if not ok:
            if msg.nClientEvent == self.tt.ClientEvent.CLIENTEVENT_CMD_ERROR:
                err = self.tt.ttstr(msg.clienterrormsg.szErrorMsg)
                return ConnectResult(False, f"Kanalbeitritt fehlgeschlagen: {err}")
            if msg.nClientEvent == self.tt.ClientEvent.CLIENTEVENT_NONE:
                return ConnectResult(False, "Kanalbeitritt fehlgeschlagen: Timeout")
            return ConnectResult(False, "Kanalbeitritt fehlgeschlagen")
        return ConnectResult(True, "Kanalbeitritt erfolgreich")

    def join_channel_by_path(self, path: str, password: str = "", timeout_ms: int = 4000) -> ConnectResult:
        normalized = path.strip()
        normalized = normalized.strip()
        if not normalized.startswith("/"):
            normalized = "/" + normalized
        alt_normalized = normalized
        if alt_normalized.endswith("/") and len(alt_normalized) > 1:
            alt_normalized = alt_normalized[:-1]

        segments = [seg for seg in alt_normalized.split("/") if seg]
        if not segments:
            return ConnectResult(False, "Ungueltiger Kanalpfad")

        current_path = ""
        parent_id = self.get_root_channel_id()
        for idx, segment in enumerate(segments):
            current_path += "/" + segment
            candidates = [current_path, current_path + "/"]
            chan_id = 0
            for candidate in candidates:
                chan_id = self.get_channel_id_from_path(candidate)
                if chan_id:
                    break
            is_last = idx == len(segments) - 1
            if chan_id and chan_id > 0:
                if is_last:
                    return self.join_channel_by_id(chan_id, password=password, timeout_ms=timeout_ms)
                if self.get_my_channel_id() != chan_id:
                    res = self.join_channel_by_id(chan_id, password="", timeout_ms=timeout_ms)
                    if not res.ok:
                        return res
                parent_id = chan_id
                continue

            ch = self.tt.Channel()
            ch.nParentID = parent_id
            ch.szName = self.tt.ttstr(segment)
            if is_last and password:
                ch.szPassword = self.tt.ttstr(password)
                ch.bPassword = True

            cmdid = self.client.doJoinChannel(ch)
            ok, msg = self._wait_for_cmd_result(cmdid, timeout_ms)
            if not ok:
                if msg.nClientEvent == self.tt.ClientEvent.CLIENTEVENT_CMD_ERROR:
                    err = self.tt.ttstr(msg.clienterrormsg.szErrorMsg)
                    return ConnectResult(False, f"Kanalbeitritt fehlgeschlagen: {err}")
                if msg.nClientEvent == self.tt.ClientEvent.CLIENTEVENT_NONE:
                    return ConnectResult(False, "Kanalbeitritt fehlgeschlagen: Timeout")
                return ConnectResult(False, "Kanalbeitritt fehlgeschlagen")

            if is_last:
                return ConnectResult(True, "Kanalbeitritt erfolgreich")

            parent_id = self.get_my_channel_id()

        return ConnectResult(False, "Kanalbeitritt fehlgeschlagen")

    def leave_channel(self, timeout_ms: int = 2000) -> ConnectResult:
        cmdid = self.client.doLeaveChannel()
        ok, _ = self._wait_for_cmd_success(cmdid, timeout_ms)
        if not ok:
            return ConnectResult(False, "Kanal verlassen fehlgeschlagen")
        return ConnectResult(True, "Kanal verlassen")

    def logout(self, timeout_ms: int = 2000) -> ConnectResult:
        cmdid = self.client.doLogout()
        ok, _ = self._wait_for_cmd_success(cmdid, timeout_ms)
        if not ok:
            return ConnectResult(False, "Logout fehlgeschlagen")
        self._connected = False
        return ConnectResult(True, "Logout erfolgreich")

    def get_server_channels(self):
        return self.client.getServerChannels()

    def get_server_users(self):
        return self.client.getServerUsers()

    def get_channel_users(self, channel_id: int):
        return self.client.getChannelUsers(channel_id)

    def get_channel(self, channel_id: int):
        return self.client.getChannel(channel_id)

    def get_channel_path(self, channel_id: int):
        return self.client.getChannelPath(channel_id)

    def get_root_channel_id(self) -> int:
        return self.client.getRootChannelID()

    def get_channel_id_from_path(self, path: str) -> int:
        return self.client.getChannelIDFromPath(self.tt.ttstr(path))

    def get_my_channel_id(self) -> int:
        return self.client.getMyChannelID()

    def restart_sound_system(self) -> bool:
        fn = getattr(self.tt, "_RestartSoundSystem", None)
        if fn:
            return fn()
        return False

    def get_sound_devices(self):
        return self.client.getSoundDevices()

    def get_default_sound_devices(self):
        return self.client.getDefaultSoundDevices()

    def init_sound_input_device(self, device_id: int) -> bool:
        return self.client.initSoundInputDevice(device_id)

    def init_sound_input_shared_device(self, sample_rate: int, channels: int, frame_size: int) -> bool:
        fn = getattr(self.tt, "_InitSoundInputSharedDevice", None)
        if not fn:
            return False
        return fn(sample_rate, channels, frame_size)

    def init_sound_output_device(self, device_id: int) -> bool:
        return self.client.initSoundOutputDevice(device_id)

    def init_sound_duplex_devices(self, input_device_id: int, output_device_id: int) -> bool:
        fn = getattr(self.tt, "_InitSoundDuplexDevices", None)
        if not fn:
            return False
        return fn(self.client._tt, input_device_id, output_device_id)

    def close_sound_input_device(self) -> bool:
        fn = getattr(self.tt, "_CloseSoundInputDevice", None)
        if not fn:
            return False
        return fn(self.client._tt)

    def close_sound_output_device(self) -> bool:
        fn = getattr(self.tt, "_CloseSoundOutputDevice", None)
        if not fn:
            return False
        return fn(self.client._tt)

    def close_sound_duplex_devices(self) -> bool:
        fn = getattr(self.tt, "_CloseSoundDuplexDevices", None)
        if not fn:
            return False
        return fn(self.client._tt)

    def enable_voice_transmission(self, enable: bool) -> bool:
        return self.client.enableVoiceTransmission(enable)

    def enable_voice_activation(self, enable: bool) -> bool:
        return self.tt._EnableVoiceActivation(self.client._tt, enable)

    def set_voice_activation_level(self, level: int) -> bool:
        return self.tt._SetVoiceActivationLevel(self.client._tt, level)

    def set_sound_input_gain(self, level: int) -> bool:
        return self.tt._SetSoundInputGainLevel(self.client._tt, level)

    def set_sound_output_volume(self, level: int) -> bool:
        return self.tt._SetSoundOutputVolume(self.client._tt, level)

    def send_channel_message(self, channel_id: int, message: str) -> bool:
        msgs = self.tt.buildTextMessage(message, self.tt.TextMsgType.MSGTYPE_CHANNEL, nChannelID=channel_id)
        ok = True
        for msg in msgs:
            ok = ok and (self.client.doTextMessage(msg) >= 0)
        return ok

    def send_user_message(self, user_id: int, message: str) -> bool:
        msgs = self.tt.buildTextMessage(message, self.tt.TextMsgType.MSGTYPE_USER, nToUserID=user_id)
        ok = True
        for msg in msgs:
            ok = ok and (self.client.doTextMessage(msg) >= 0)
        return ok

    # ------------------------------------------------------------------
    # Error & Statistics
    # ------------------------------------------------------------------

    def get_error_message(self, error_no: int) -> str:
        return self.client.getErrorMessage(error_no)

    def get_client_statistics(self) -> Any:
        stats = self.tt.ClientStatistics()
        if self.tt._GetClientStatistics(self.client._tt, ctypes.byref(stats)):
            return stats
        return None

    # ------------------------------------------------------------------
    # Audio Preprocessing & Effects
    # ------------------------------------------------------------------

    def set_sound_device_effects(self, agc: bool = False, denoise: bool = False, echo_cancel: bool = False) -> bool:
        try:
            effects = self.tt.SoundDeviceEffects()
        except Exception:
            return False
        effects.bEnableAGC = agc
        effects.bEnableDenoise = denoise
        effects.bEnableEchoCancellation = echo_cancel
        return self.tt._SetSoundDeviceEffects(self.client._tt, ctypes.byref(effects))

    def get_sound_device_effects(self) -> Any:
        try:
            effects = self.tt.SoundDeviceEffects()
        except Exception:
            return None
        if self.tt._GetSoundDeviceEffects(self.client._tt, ctypes.byref(effects)):
            return effects
        return None

    def set_sound_input_preprocess_webrtc(
        self,
        echo_cancel: bool = True,
        denoise: bool = True,
        agc: bool = True,
        gain_level: int = 0,
    ) -> bool:
        ap = self.tt.AudioPreprocessor()
        ap.nPreprocessor = self.tt.AudioPreprocessorType.WEBRTC_AUDIOPREPROCESSOR
        ap.u.webrtc.bEnable = True
        ap.u.webrtc.preamplifier.bEnable = False
        ap.u.webrtc.echocanceller.bEnable = echo_cancel
        ap.u.webrtc.noisesuppression.bEnable = denoise
        ap.u.webrtc.gaincontroller2.bEnable = agc
        if gain_level:
            ap.u.webrtc.gaincontroller2.fixeddigital.fGainDB = float(gain_level)
        return self.tt._SetSoundInputPreprocessEx(self.client._tt, ctypes.byref(ap))

    def set_sound_input_preprocess_speexdsp(
        self,
        agc: bool = True,
        denoise: bool = True,
        echo_cancel: bool = False,
        agc_gain: int = 8000,
        denoise_suppress: int = -30,
    ) -> bool:
        ap = self.tt.AudioPreprocessor()
        ap.nPreprocessor = self.tt.AudioPreprocessorType.SPEEXDSP_AUDIOPREPROCESSOR
        ap.u.speexdsp.bEnableAGC = agc
        ap.u.speexdsp.nGainLevel = agc_gain
        ap.u.speexdsp.nMaxIncDBSec = 12
        ap.u.speexdsp.nMaxDecDBSec = -40
        ap.u.speexdsp.nMaxGainDB = 30
        ap.u.speexdsp.bEnableDenoise = denoise
        ap.u.speexdsp.nMaxNoiseSuppressDB = denoise_suppress
        ap.u.speexdsp.bEnableEchoCancellation = echo_cancel
        ap.u.speexdsp.nEchoSuppress = -40
        ap.u.speexdsp.nEchoSuppressActive = -15
        return self.tt._SetSoundInputPreprocessEx(self.client._tt, ctypes.byref(ap))

    def set_sound_input_preprocess_none(self) -> bool:
        ap = self.tt.AudioPreprocessor()
        ap.nPreprocessor = self.tt.AudioPreprocessorType.NO_AUDIOPREPROCESSOR
        return self.tt._SetSoundInputPreprocessEx(self.client._tt, ctypes.byref(ap))

    # ------------------------------------------------------------------
    # VU Meter, Voice Activation, Output
    # ------------------------------------------------------------------

    def get_sound_input_level(self) -> int:
        return self.tt._GetSoundInputLevel(self.client._tt)

    def set_voice_activation_stop_delay(self, delay_ms: int) -> bool:
        return self.tt._SetVoiceActivationStopDelay(self.client._tt, delay_ms)

    def get_voice_activation_stop_delay(self) -> int:
        return self.tt._GetVoiceActivationStopDelay(self.client._tt)

    def set_sound_output_mute(self, mute: bool) -> bool:
        return self.tt._SetSoundOutputMute(self.client._tt, mute)

    # ------------------------------------------------------------------
    # Sound Loopback
    # ------------------------------------------------------------------

    def start_sound_loopback_test(self, indev_id: int, outdev_id: int, sample_rate: int = 48000, channels: int = 1) -> int:
        ap = self.tt.AudioPreprocessor()
        ap.nPreprocessor = self.tt.AudioPreprocessorType.NO_AUDIOPREPROCESSOR
        effects = self.tt.SoundDeviceEffects()
        handle = self.tt._StartSoundLoopbackTestEx(indev_id, outdev_id, sample_rate, channels, False, ctypes.byref(ap), ctypes.byref(effects))
        return handle

    def close_sound_loopback_test(self, handle) -> bool:
        return self.tt._CloseSoundLoopbackTest(handle)

    # ------------------------------------------------------------------
    # Per-User Audio
    # ------------------------------------------------------------------

    def set_user_volume(self, user_id: int, stream_type: int, volume: int) -> bool:
        return self.tt._SetUserVolume(self.client._tt, user_id, stream_type, volume)

    def set_user_mute(self, user_id: int, stream_type: int, mute: bool) -> bool:
        return self.tt._SetUserMute(self.client._tt, user_id, stream_type, mute, 0)

    # ------------------------------------------------------------------
    # Subscriptions
    # ------------------------------------------------------------------

    def do_subscribe(self, user_id: int, subscriptions: int) -> int:
        return self.client.doSubscribe(user_id, subscriptions)

    def do_unsubscribe(self, user_id: int, subscriptions: int) -> int:
        return self.client.doUnsubscribe(user_id, subscriptions)

    # ------------------------------------------------------------------
    # Channel Operator
    # ------------------------------------------------------------------

    def do_channel_op(self, channel_id: int, user_id: int, make_op: bool) -> int:
        return self.client.doChannelOp(user_id, channel_id, make_op)

    def is_channel_operator(self, channel_id: int, user_id: int) -> bool:
        return self.tt._IsChannelOperator(self.client._tt, channel_id, user_id)

    # ------------------------------------------------------------------
    # Kick
    # ------------------------------------------------------------------

    def do_kick_user(self, user_id: int, channel_id: int) -> int:
        return self.client.doKickUser(user_id, channel_id)

    # ------------------------------------------------------------------
    # Recording (Muxed)
    # ------------------------------------------------------------------

    def start_recording_muxed(self, filename: str, audio_format: int) -> bool:
        codec = self.tt.AudioCodec()
        return self.tt._StartRecordingMuxedAudioFile(
            self.client._tt, ctypes.byref(codec), self.tt.ttstr(filename), audio_format
        )

    def stop_recording_muxed(self) -> bool:
        return self.tt._StopRecordingMuxedAudioFile(self.client._tt)

    # ------------------------------------------------------------------
    # Media File Streaming
    # ------------------------------------------------------------------

    def get_media_file_info(self, filepath: str) -> Any:
        info = self.tt.MediaFileInfo()
        if self.tt._GetMediaFileInfo(self.tt.ttstr(filepath), ctypes.byref(info)):
            return info
        return None

    def start_streaming_media_to_channel(self, filepath: str, offset_ms: int = 0, preamp_gain: float = 1.0) -> bool:
        playback = self.tt.MediaFilePlayback()
        playback.uOffsetMSec = offset_ms
        playback.bPaused = False
        playback.audioPreprocessor = self._build_stream_preprocessor(preamp_gain)
        codec = self.tt.VideoCodec()
        return self.tt._StartStreamingMediaFileToChannelEx(
            self.client._tt, self.tt.ttstr(filepath), ctypes.byref(playback), ctypes.byref(codec)
        )

    def update_streaming_media(self, paused: bool = False, offset_ms: Optional[int] = 0, preamp_gain: float = 1.0) -> bool:
        playback = self.tt.MediaFilePlayback()
        if offset_ms is None:
            playback.uOffsetMSec = self.tt.TT_MEDIAPLAYBACK_OFFSET_IGNORE
        else:
            playback.uOffsetMSec = offset_ms
        playback.bPaused = paused
        playback.audioPreprocessor = self._build_stream_preprocessor(preamp_gain)
        codec = self.tt.VideoCodec()
        return self.tt._UpdateStreamingMediaFileToChannel(
            self.client._tt, ctypes.byref(playback), ctypes.byref(codec)
        )

    def _build_stream_preprocessor(self, preamp_gain: float):
        ap = self.tt.AudioPreprocessor()
        ap.nPreprocessor = self.tt.AudioPreprocessorType.WEBRTC_AUDIOPREPROCESSOR
        ap.webrtc.preamplifier_bEnable = True
        ap.webrtc.preamplifier_fFixedGainFactor = float(preamp_gain)
        ap.webrtc.echocanceller_bEnable = False
        ap.webrtc.noisesuppression_bEnable = False
        ap.webrtc.gaincontroller2_bEnable = False
        return ap

    # ------------------------------------------------------------------
    # Desktop / Screen Share
    # ------------------------------------------------------------------

    def send_desktop_frame(self, width: int, height: int, bytes_per_line: int, frame: bytes) -> int:
        self._ensure_desktop_api()
        buf = ctypes.create_string_buffer(frame)
        wnd = self.tt.DesktopWindow()
        wnd.nWidth = int(width)
        wnd.nHeight = int(height)
        wnd.bmpFormat = self.tt.BitmapFormat.BMP_RGB32
        wnd.nBytesPerLine = int(bytes_per_line)
        wnd.nSessionID = 0
        wnd.nProtocol = self.tt.DesktopProtocol.DESKTOPPROTOCOL_ZLIB_1
        wnd.frameBuffer = ctypes.cast(buf, ctypes.c_void_p)
        wnd.nFrameBufferSize = int(len(frame))
        return int(self.tt._SendDesktopWindow(self.client._tt, ctypes.byref(wnd), self.tt.BitmapFormat.BMP_RGB32))

    def close_desktop_window(self) -> bool:
        self._ensure_desktop_api()
        return bool(self.tt._CloseDesktopWindow(self.client._tt))

    def _ensure_desktop_api(self) -> None:
        if hasattr(self.tt, "_SendDesktopWindow"):
            return
        self.tt._SendDesktopWindow = self.tt.function_factory(
            self.tt.dll.TT_SendDesktopWindow,
            [self.tt.INT32, [self.tt._TTInstance, ctypes.POINTER(self.tt.DesktopWindow), self.tt.INT32]],
        )
        self.tt._CloseDesktopWindow = self.tt.function_factory(
            self.tt.dll.TT_CloseDesktopWindow,
            [self.tt.BOOL, [self.tt._TTInstance]],
        )

    # ------------------------------------------------------------------
    # Audio injection (app audio)
    # ------------------------------------------------------------------

    def insert_audio_block_bytes(self, pcm: bytes, sample_rate: int, channels: int) -> bool:
        if not pcm:
            return False
        block = self.tt.AudioBlock()
        block.nStreamID = 0
        block.nSampleRate = int(sample_rate)
        block.nChannels = int(channels)
        block.nSamples = int(len(pcm) // (2 * max(1, channels)))
        block.uSampleIndex = 0
        block.uStreamTypes = int(self.tt.StreamType.STREAMTYPE_MEDIAFILE_AUDIO)
        buf = ctypes.create_string_buffer(pcm)
        block.lpRawAudio = ctypes.cast(buf, ctypes.c_void_p)
        return bool(self.tt._InsertAudioBlock(self.client._tt, ctypes.byref(block)))

    def stop_streaming_media(self) -> bool:
        return self.tt._StopStreamingMediaFileToChannel(self.client._tt)

    # ------------------------------------------------------------------
    # File Transfer
    # ------------------------------------------------------------------

    def get_channel_files(self, channel_id: int) -> List:
        return list(self.client.getChannelFiles(channel_id))

    def send_file(self, channel_id: int, local_path: str) -> int:
        return self.client.doSendFile(channel_id, self.tt.ttstr(local_path))

    def recv_file(self, channel_id: int, file_id: int, local_path: str) -> int:
        return self.client.doRecvFile(channel_id, file_id, self.tt.ttstr(local_path))

    def delete_file(self, channel_id: int, file_id: int) -> int:
        return self.client.doDeleteFile(channel_id, file_id)

    def get_file_transfer_info(self, transfer_id: int) -> Any:
        ft = self.tt.FileTransfer()
        if self.tt._GetFileTransferInfo(self.client._tt, transfer_id, ctypes.byref(ft)):
            return ft
        return None

    def cancel_file_transfer(self, transfer_id: int) -> bool:
        return self.tt._CancelFileTransfer(self.client._tt, transfer_id)

    # ------------------------------------------------------------------
    # Admin
    # ------------------------------------------------------------------

    def do_list_user_accounts(self, offset: int = 0, count: int = 100) -> int:
        return self.client.doListUserAccounts(offset, count)

    def do_new_user_account(self, username: str, password: str, user_type: int, user_rights: int = 0, note: str = "") -> int:
        account = self.tt.UserAccount()
        account.szUsername = self.tt.ttstr(username)
        account.szPassword = self.tt.ttstr(password)
        account.uUserType = user_type
        account.uUserRights = user_rights
        account.szNote = self.tt.ttstr(note)
        return self.client.doNewUserAccount(account)

    def do_delete_user_account(self, username: str) -> int:
        return self.client.doDeleteUserAccount(self.tt.ttstr(username))

    def do_ban_user(self, channel_id: int, user_id: int) -> int:
        return self.client.doBanUser(user_id, channel_id)

    def do_unban_user(self, ip_addr: str, ban_type: int = 0) -> int:
        return self.client.doUnBanUser(self.tt.ttstr(ip_addr), ban_type)

    def do_list_bans(self, channel_id: int = 0, offset: int = 0, count: int = 100) -> int:
        return self.client.doListBans(channel_id, offset, count)

    def do_update_server(self, server_name: str = "", motd: str = "", max_users: int = 0) -> int:
        props = self.client.getServerProperties()
        if server_name:
            props.szServerName = self.tt.ttstr(server_name)
        if motd:
            props.szMOTDRaw = self.tt.ttstr(motd)
        if max_users > 0:
            props.nMaxUsers = max_users
        return self.client.doUpdateServer(props)

    def do_save_config(self) -> int:
        return self.client.doSaveConfig()

    def get_server_properties(self) -> Any:
        return self.client.getServerProperties()

    def get_my_user_type(self) -> int:
        return self.tt._GetMyUserType(self.client._tt)

    def get_my_user_id(self) -> int:
        return self.client.getMyUserID()

    def get_user(self, user_id: int) -> Any:
        return self.client.getUser(user_id)

    def start_event_loop(self, handler: Callable[["TTMessage"], None], poll_ms: int = 200) -> None:
        if self._event_thread and self._event_thread.is_alive():
            return

        self._event_stop.clear()

        def loop():
            while not self._event_stop.is_set():
                msg = self.client.getMessage(poll_ms)
                if msg.nClientEvent == self.tt.ClientEvent.CLIENTEVENT_NONE:
                    continue
                handler(msg)

        self._event_thread = threading.Thread(target=loop, daemon=True)
        self._event_thread.start()

    def stop_event_loop(self) -> None:
        self._event_stop.set()

    def stop_event_loop_and_wait(self, timeout: float = 2.0) -> None:
        """Stop the event loop and wait for the thread to finish."""
        self._event_stop.set()
        if self._event_thread and self._event_thread.is_alive():
            self._event_thread.join(timeout)
        self._event_thread = None

    def reconnect(self, timeout_ms: int = 8000) -> ConnectResult:
        if not self._last_connect:
            return ConnectResult(False, "Keine gespeicherten Verbindungsdaten")
        return self.connect_and_login(*self._last_connect, timeout_ms=timeout_ms)

    def close(self) -> None:
        self._connected = False
        self.stop_event_loop()
        self.client.closeTeamTalk()
