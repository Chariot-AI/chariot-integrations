"""Chariot text-to-speech for Pipecat.

A drop-in Pipecat ``TTSService`` over Chariot's streaming TTS WebSocket API
(``/v1/tts/ws``). Audio arrives as raw 16-bit mono PCM frames while the
server is still generating, so playback starts before synthesis finishes.

This file is self-contained: copy it into any Pipecat project.
"""

import asyncio
import json
import os
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import websockets
from loguru import logger

from pipecat.frames.frames import ErrorFrame, Frame, TTSAudioRawFrame
from pipecat.services.settings import TTSSettings
from pipecat.services.tts_service import TTSService

DEFAULT_WS_URL = "wss://api.chariot.in/v1/tts/ws"
DEFAULT_MODEL = "chariot-multilingual-v1"

# Chariot's close code for an exhausted credit balance.
CLOSE_CODE_NO_CREDITS = 4402


@dataclass
class ChariotTTSSettings(TTSSettings):
    """Settings for ChariotTTSService.

    ``voice`` is the Chariot voice UUID from ``GET /v1/voices``.
    ``model`` is sent as Chariot's ``model_type`` query parameter.
    Language is detected from the input text, so ``language`` is unused.
    """

    pass


class ChariotTTSService(TTSService):
    """Streams speech from Chariot's TTS WebSocket API.

    One WebSocket connection per utterance, on purpose: Pipecat cancels the
    ``run_tts`` generator on interruption, which tears the socket down and
    stops the server generating audio nobody will hear.
    """

    Settings = ChariotTTSSettings
    _settings: Settings

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        voice_id: Optional[str] = None,
        model: Optional[str] = None,
        ws_url: str = DEFAULT_WS_URL,
        sample_rate: Optional[int] = 44100,
        receive_timeout: float = 30.0,
        settings: Optional[Settings] = None,
        **kwargs,
    ):
        """Initialize the Chariot TTS service.

        Args:
            api_key: Chariot API key. Falls back to ``CHARIOT_API_KEY``.
            voice_id: Voice UUID from ``GET /v1/voices``. Falls back to
                ``CHARIOT_VOICE_ID``. ``settings.voice`` takes precedence.
            model: Model name. Falls back to ``CHARIOT_MODEL``, then
                ``chariot-multilingual-v1``. ``settings.model`` takes precedence.
            ws_url: WebSocket endpoint override.
            sample_rate: Output sample rate in Hz. Chariot serves 44100;
                the server also declares the rate per session in ``audio.start``
                and that declaration wins.
            receive_timeout: Maximum seconds to wait for the next WebSocket
                message before reporting a stalled stream.
            settings: Runtime-updatable settings; values here win over the
                direct arguments.
            **kwargs: Additional arguments passed to the parent TTSService.
        """
        default_settings = self.Settings(
            voice=voice_id or os.environ.get("CHARIOT_VOICE_ID") or None,
            model=model or os.environ.get("CHARIOT_MODEL") or DEFAULT_MODEL,
            language=None,
        )
        if settings is not None:
            default_settings.apply_update(settings)
        if not default_settings.voice:
            raise ValueError(
                "Chariot voice required: pass voice_id= or set CHARIOT_VOICE_ID"
            )
        if not default_settings.model:
            raise ValueError("Chariot model must not be empty")
        if receive_timeout <= 0:
            raise ValueError("receive_timeout must be positive")

        super().__init__(
            sample_rate=sample_rate,
            push_stop_frames=True,
            push_start_frame=True,
            settings=default_settings,
            **kwargs,
        )

        self._api_key = api_key or os.environ.get("CHARIOT_API_KEY", "")
        if not self._api_key:
            raise ValueError(
                "Chariot API key required: pass api_key= or set CHARIOT_API_KEY"
            )
        self._ws_url = ws_url
        self._receive_timeout = receive_timeout

    def can_generate_metrics(self) -> bool:
        """Chariot TTS reports TTFB and character-usage metrics."""
        return True

    async def run_tts(self, text: str, context_id: str) -> AsyncGenerator[Frame | None, None]:
        """Generate speech from text over one Chariot WebSocket session.

        Args:
            text: The text to synthesize into speech.
            context_id: Unique identifier for this TTS context.

        Yields:
            Frame: Audio frames containing the synthesized speech.
        """
        # The session is flush-driven: text buffers until input.done, which
        # synthesizes it as one piece. Pipecat has already aggregated the text
        # into a sensible utterance, so one piece is exactly right.
        url = urlsplit(self._ws_url)
        query = dict(parse_qsl(url.query))
        query.update(
            {
                "voice_id": self._settings.voice,
                "model_type": self._settings.model,
                "response_format": "pcm",
            }
        )
        uri = urlunsplit(url._replace(query=urlencode(query)))

        try:
            async with websockets.connect(
                uri,
                additional_headers={"chariotai-api-key": self._api_key},
                max_size=None,
                open_timeout=self._receive_timeout,
                close_timeout=2,
            ) as ws:
                await self.start_tts_usage_metrics(text)
                await ws.send(json.dumps({"type": "input.text", "text": text}))
                await ws.send(json.dumps({"type": "input.done"}))

                sample_rate = self.sample_rate
                received_audio = False
                pending = b""
                while True:
                    message = await asyncio.wait_for(ws.recv(), self._receive_timeout)
                    if isinstance(message, bytes):
                        # WebSocket messages need not end on a 16-bit sample.
                        pending += message
                        complete_bytes = len(pending) - len(pending) % 2
                        if not complete_bytes:
                            continue
                        if not received_audio:
                            await self.stop_ttfb_metrics()
                            received_audio = True
                        yield TTSAudioRawFrame(
                            pending[:complete_bytes], sample_rate, 1, context_id=context_id
                        )
                        pending = pending[complete_bytes:]
                        continue

                    event = json.loads(message)
                    event_type = event.get("type")
                    if event_type == "audio.start":
                        # The server states the true output rate; trust it
                        # over the configured default.
                        sample_rate = event.get("sample_rate") or sample_rate
                    elif event_type == "session.done":
                        if pending:
                            yield ErrorFrame(error="Chariot TTS returned an incomplete PCM sample")
                        elif not received_audio:
                            yield ErrorFrame(error="Chariot TTS completed without audio")
                        break
                    elif event_type == "audio.done" and event.get("error"):
                        yield ErrorFrame(error=f"Chariot TTS error: {event['error']}")
                        break
                    elif event_type == "error":
                        message_text = event.get("message", "unknown error")
                        yield ErrorFrame(error=f"Chariot TTS error: {message_text}")
                        break
        except asyncio.CancelledError:
            logger.debug(f"{self}: TTS generation cancelled")
            raise
        except TimeoutError:
            yield ErrorFrame(error="Chariot TTS timed out waiting for the stream")
        except websockets.exceptions.ConnectionClosed as exc:
            if exc.rcvd is not None and exc.rcvd.code == CLOSE_CODE_NO_CREDITS:
                reason = "credit balance exhausted"
            else:
                reason = f"before session.done: {exc}"
            yield ErrorFrame(error=f"Chariot TTS connection closed: {reason}")
        except Exception as exc:
            yield ErrorFrame(error=f"Chariot TTS connection failed: {exc}")
        finally:
            await self.stop_ttfb_metrics()
