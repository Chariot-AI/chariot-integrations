"""Streaming Chariot speech-to-text for Pipecat. Copy this file into your project."""

import asyncio
import copy
import json
import math
import os
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import websockets
from pipecat.frames.frames import (
    CancelFrame, EndFrame, Frame, InputAudioRawFrame, InterimTranscriptionFrame,
    StartFrame, TranscriptionFrame, VADUserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.settings import STTSettings
from pipecat.services.stt_service import STTService
from pipecat.transcriptions.language import Language
from pipecat.utils.time import time_now_iso8601
try:
    from pipecat.utils.types import NOT_GIVEN, NotGiven
except ImportError:  # Pipecat 1.7 keeps the sentinel in settings.
    from pipecat.services.settings import NOT_GIVEN, _NotGiven as NotGiven

DEFAULT_MODEL = "chariot-1-asr-realtime"
DEFAULT_WS_URL = "wss://api.chariot.in/v1/asr/ws"
SAMPLE_RATES = {8000, 16000, 22050, 24000, 32000, 44100, 48000}
LANGUAGES = {"none", "en", "hi", "bn", "gu", "kn", "ml", "mr", "or", "pa", "sa", "ta", "te"}


@dataclass
class ChariotSTTSettings(STTSettings):
    """Connection settings; create a new service to change them during a call.

    model maps to model_type. language=None selects automatic detection.
    """

    mode: str | NotGiven = field(default_factory=lambda: NOT_GIVEN)
    style: str | NotGiven = field(default_factory=lambda: NOT_GIVEN)
    include_timestamps: bool | NotGiven = field(default_factory=lambda: NOT_GIVEN)


def language_code(language) -> str:
    value = language.value if isinstance(language, Language) else language
    value = "none" if value is None else str(value).split("-")[0].lower()
    if value not in LANGUAGES:
        raise ValueError("Unsupported Chariot transcription language")
    return value


def validate_settings(settings):
    if settings.model != DEFAULT_MODEL:
        raise ValueError(f"model must be {DEFAULT_MODEL}")
    language_code(settings.language)
    if settings.mode not in ("balanced", "high_accuracy"):
        raise ValueError("mode must be balanced or high_accuracy")
    if settings.style not in ("codemix", "native"):
        raise ValueError("style must be codemix or native")
    if not isinstance(settings.include_timestamps, bool):
        raise ValueError("include_timestamps must be a boolean")
    if settings.extra:
        raise ValueError("Unknown Chariot STT settings")


class ChariotSTTService(STTService):
    """One ASR WebSocket per pipeline, with interim and finalized segments.

    manual commits on Pipecat VAD stop. vad lets Chariot finalize segments;
    Pipecat's own VAD and turn strategies still control conversation turns.
    Network failures surface as fatal ErrorFrames; audio is never silently
    replayed into a new session. A new pipeline opens a fresh session.
    """

    Settings = ChariotSTTSettings

    def __init__(
        self, *, api_key: str | None = None, ws_url: str = DEFAULT_WS_URL,
        sample_rate: int | None = None, settings: Settings | None = None,
        commit_strategy: str = "manual", silence_duration_ms: int = 500,
        vad_threshold: float = 0.5, min_speech_duration_ms: int = 250,
        prefix_padding_ms: int = 300, connect_timeout: float = 15,
        finalize_timeout: float = 65, keepalive_interval: float = 15, **kwargs,
    ):
        resolved = self.Settings(model=DEFAULT_MODEL, language=None, mode="balanced",
                                 style="codemix", include_timestamps=False)
        if settings is not None:
            resolved.apply_update(settings)
        validate_settings(resolved)
        if sample_rate is not None and sample_rate not in SAMPLE_RATES:
            raise ValueError("Unsupported PCM sample rate")
        if commit_strategy not in ("manual", "vad"):
            raise ValueError("commit_strategy must be manual or vad")
        for name, value, low, high in [
            ("silence_duration_ms", silence_duration_ms, 100, 10000),
            ("min_speech_duration_ms", min_speech_duration_ms, 0, 5000),
            ("prefix_padding_ms", prefix_padding_ms, 0, 2000),
        ]:
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f"{name} must be an integer from {low} to {high}")
        if not math.isfinite(vad_threshold) or not 0.05 <= vad_threshold <= 0.95:
            raise ValueError("vad_threshold must be from 0.05 to 0.95")
        for name, value in [("connect_timeout", connect_timeout), ("finalize_timeout", finalize_timeout),
                            ("keepalive_interval", keepalive_interval)]:
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be positive and finite")
        if keepalive_interval >= 60:
            raise ValueError("keepalive_interval must be below the 60-second idle timeout")
        self._api_key = api_key or os.getenv("CHARIOT_API_KEY", "")
        if not self._api_key:
            raise ValueError("Chariot API key required: pass api_key= or set CHARIOT_API_KEY")
        super().__init__(sample_rate=sample_rate, settings=resolved, **kwargs)
        self._url = ws_url
        self._commit_strategy = commit_strategy
        self._vad = dict(silence_duration_ms=silence_duration_ms, vad_threshold=vad_threshold,
                         min_speech_duration_ms=min_speech_duration_ms, prefix_padding_ms=prefix_padding_ms)
        self._connect_timeout = connect_timeout
        self._finalize_timeout = finalize_timeout
        self._heartbeat_interval = keepalive_interval
        self._ws = None
        self._receive_task = None
        self._heartbeat_task = None
        self._send_lock = asyncio.Lock()
        self._done = asyncio.Event()
        self._failed = False
        self._ending = False
        self._partial = ""
        self._uncommitted_bytes = 0
        self._pending_commits = 0
        self._commit_deadline = None
        self._register_event_handler("on_speech_started")
        self._register_event_handler("on_speech_stopped")
        self._register_event_handler("on_session_expiring")

    def language_to_service_language(self, language):
        code = language_code(language)
        return None if code == "none" else code

    def can_generate_metrics(self) -> bool:
        return True

    async def _update_settings(self, delta):
        # The public socket has no session.update; do not appear to apply one.
        candidate = copy.deepcopy(self._settings)
        candidate.apply_update(delta)
        try:
            validate_settings(candidate)
        except ValueError as error:
            await self.push_error(str(error))
            return {}
        if self._ws is not None:
            await self.push_error("Chariot STT settings are fixed for this call; create a new service to change them")
            return {}
        return await super()._update_settings(delta)

    async def start(self, frame: StartFrame):
        await super().start(frame)
        try:
            if self.sample_rate not in SAMPLE_RATES:
                raise ValueError("Unsupported pipeline PCM sample rate")
            parts = urlsplit(self._url)
            query = dict(parse_qsl(parts.query))
            query.update(model_type=self._settings.model, language=language_code(self._settings.language),
                         mode=self._settings.mode, style=self._settings.style,
                         audio_format=f"pcm_{self.sample_rate}", commit_strategy=self._commit_strategy,
                         include_timestamps=str(self._settings.include_timestamps).lower(),
                         vad_events=str(self._commit_strategy == "vad").lower(), **self._vad)
            url = urlunsplit(parts._replace(query=urlencode(query)))
            async with asyncio.timeout(self._connect_timeout):
                self._ws = await websockets.connect(url, additional_headers={"chariotai-api-key": self._api_key},
                                                     max_size=4 * 1024 * 1024, close_timeout=2)
                event = json.loads(await self._ws.recv())
                if event.get("type") != "session.started":
                    raise ValueError(event.get("message", "ASR session did not start"))
                if event.get("sample_rate") != self.sample_rate or event.get("commit_strategy") != self._commit_strategy:
                    raise ValueError("ASR session settings do not match the requested audio and commit strategy")
            self._receive_task = self.create_task(self._receive())
            self._heartbeat_task = self.create_task(self._heartbeat())
            await self._call_event_handler("on_connected")
        except Exception as error:
            # Transport exceptions can include a URL; keep credentials out of logs.
            message = str(error) if isinstance(error, ValueError) else type(error).__name__
            await self._fail(f"Chariot STT connection failed: {message}")

    async def process_audio_frame(self, frame: InputAudioRawFrame, direction: FrameDirection):
        if frame.sample_rate != self.sample_rate or frame.num_channels != 1 or len(frame.audio) % 2:
            await self._fail("Chariot STT needs complete mono PCM16 samples at the configured sample rate")
            return
        if not self._failed and not self._ending:
            await super().process_audio_frame(frame, direction)

    async def run_stt(self, audio: bytes) -> AsyncGenerator[Frame | None, None]:
        try:
            async with self._send_lock:
                if self._ws is not None and not self._ending and not self._failed:
                    await self._ws.send(audio)
                    self._uncommitted_bytes += len(audio)
        except Exception:
            await self._fail("Chariot STT audio connection lost")
        yield None

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, VADUserStoppedSpeakingFrame) and self._commit_strategy == "manual":
            try:
                async with self._send_lock:
                    if self._ws is not None and not self._failed and not self._ending and self._uncommitted_bytes:
                        await self._ws.send(json.dumps({"type": "input.commit"}))
                        self._uncommitted_bytes = 0
                        self._pending_commits += 1
                        if self._commit_deadline is None:
                            self._commit_deadline = asyncio.get_running_loop().time() + self._finalize_timeout
            except Exception:
                await self._fail("Chariot STT could not finalize the utterance")

    async def _receive(self):
        try:
            async for message in self._ws:
                event = json.loads(message)
                kind = event.get("type")
                if kind == "transcript.delta":
                    self._partial += event["text"]
                    if self._partial:
                        await self.push_frame(InterimTranscriptionFrame(
                            self._partial, self._user_id, time_now_iso8601(), result=event))
                elif kind in ("transcript.committed", "transcript.done"):
                    if kind == "transcript.committed" and self._pending_commits:
                        self._pending_commits -= 1
                        self._commit_deadline = (asyncio.get_running_loop().time() + self._finalize_timeout
                                                 if self._pending_commits else None)
                    self._partial = ""
                    code = language_code(self._settings.language)
                    language = None if code == "none" else Language(code)
                    # A commit's text replaces its partials; closing text is only the tail.
                    if event["text"]:
                        await self.push_frame(TranscriptionFrame(
                            event["text"], self._user_id, time_now_iso8601(), language,
                            result=event, finalized=self._commit_strategy == "manual"))
                    await self.emit_stt_usage_metrics()
                    if kind == "transcript.done":
                        if not self._ending:
                            await self._fail("Chariot STT finished before input ended")
                        self._done.set()
                        return
                elif kind == "error":
                    if "code" in event:
                        await self._fail(f"Chariot STT ({event['code']}): {event.get('message', 'Session failed')}")
                        return
                    await self.push_error(event.get("message", "Chariot STT message error"))
                elif kind in ("input_audio_buffer.speech_started", "input_audio_buffer.speech_stopped"):
                    name = "on_speech_started" if kind.endswith("speech_started") else "on_speech_stopped"
                    await self._call_event_handler(name, event)
                elif kind == "session.expiring":
                    await self._call_event_handler("on_session_expiring", event)
            if not self._done.is_set():
                await self._fail("Chariot STT connection closed before transcript.done")
        except asyncio.CancelledError:
            raise
        except Exception:
            if not self._failed:
                await self._fail("Chariot STT receive failed before transcript.done")

    async def _heartbeat(self):
        try:
            while True:
                await asyncio.sleep(min(self._heartbeat_interval, self._finalize_timeout / 2))
                if self._commit_deadline is not None and asyncio.get_running_loop().time() >= self._commit_deadline:
                    await self._fail("Chariot STT utterance finalization timed out")
                    return
                async with self._send_lock:
                    if not self._ending and not self._failed:
                        await self._ws.send(json.dumps({"type": "keepalive"}))
        except asyncio.CancelledError:
            raise
        except Exception:
            await self._fail("Chariot STT keepalive failed")

    async def _fail(self, message):
        if self._failed:
            return
        self._failed = True
        self._done.set()
        if self._ws is not None:
            await self._ws.close()
        await self._call_event_handler("on_connection_error", message)
        await self.push_error(message, fatal=True)

    async def _disconnect(self):
        self._ending = True
        for task in (self._heartbeat_task, self._receive_task):
            if task is not None and task is not asyncio.current_task():
                await self.cancel_task(task)
        self._heartbeat_task = self._receive_task = None
        if self._ws is not None:
            await self._ws.close()
            self._ws = None
            await self._call_event_handler("on_disconnected")

    async def stop(self, frame: EndFrame):
        try:
            async with self._send_lock:
                self._ending = True
                if self._ws is not None and not self._failed:
                    await self._ws.send(json.dumps({"type": "input.done"}))
            if self._ws is not None and not self._failed:
                await asyncio.wait_for(self._done.wait(), self._finalize_timeout)
        except Exception:
            await self._fail("Chariot STT could not finish the final transcript")
        finally:
            await self._disconnect()
            await super().stop(frame)

    async def cancel(self, frame: CancelFrame):
        await self._disconnect()
        await super().cancel(frame)

    async def cleanup(self):
        await self._disconnect()
        await super().cleanup()
