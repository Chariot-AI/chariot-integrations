"""Exercise the public adapter through real Pipecat pipelines and local sockets."""

import asyncio
import json
import os
import sys
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from loguru import logger
from websockets.asyncio.server import serve

from pipecat.frames.frames import (
    ErrorFrame, InterruptionFrame, MetricsFrame, TTSAudioRawFrame,
    TTSSpeakFrame, TTSStartedFrame, TTSStoppedFrame, TTSUpdateSettingsFrame,
)
from pipecat.metrics.metrics import TTFBMetricsData, TTSUsageMetricsData
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.workers.runner import WorkerRunner

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from chariot_tts import ChariotTTSService, DEFAULT_MODEL

logger.remove()
logger.add(sys.stderr, level="ERROR")
PCM = b"\x01\x00\xff\x7f" * 100


class Capture(FrameProcessor):
    def __init__(self, direction):
        super().__init__(enable_direct_mode=True)
        self.direction = direction
        self.frames = []
        self.queue = asyncio.Queue()

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if direction == self.direction:
            self.frames.append(frame)
            self.queue.put_nowait(frame)
        await self.push_frame(frame, direction)

    async def until(self, frame_type):
        async with asyncio.timeout(5):
            while True:
                frame = await self.queue.get()
                if isinstance(frame, frame_type):
                    return frame


@asynccontextmanager
async def pipeline(service):
    upstream = Capture(FrameDirection.UPSTREAM)
    downstream = Capture(FrameDirection.DOWNSTREAM)
    worker = PipelineWorker(
        Pipeline([upstream, service, downstream]),
        params=PipelineParams(enable_metrics=True, enable_usage_metrics=True),
        enable_rtvi=False,
        cancel_on_idle_timeout=False,
    )
    started = asyncio.Event()

    @worker.event_handler("on_pipeline_started")
    async def on_started(worker, frame):
        started.set()

    runner = WorkerRunner(handle_sigint=False)
    await runner.add_workers(worker)
    running = asyncio.create_task(runner.run())
    try:
        await asyncio.wait_for(started.wait(), 5)
        yield worker, downstream, upstream
    finally:
        await worker.cancel()
        await asyncio.wait_for(running, 5)


class ChariotTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.requests = []
        self.replies = [
            {"type": "audio.start", "sample_rate": 44100},
            PCM,
            {"type": "audio.done"},
            {"type": "session.done"},
        ]
        self.closed = asyncio.Event()
        self.server = await serve(self.handle, "127.0.0.1", 0)
        port = self.server.sockets[0].getsockname()[1]
        self.url = f"ws://127.0.0.1:{port}/v1/tts/ws?existing=value"
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()

    async def asyncTearDown(self):
        self.env.stop()
        self.server.close()
        await self.server.wait_closed()

    async def handle(self, ws):
        request = {
            "query": parse_qs(urlsplit(ws.request.path).query),
            "key": ws.request.headers.get("chariotai-api-key"),
            "messages": [json.loads(await ws.recv()), json.loads(await ws.recv())],
        }
        self.requests.append(request)
        for reply in self.replies:
            if isinstance(reply, bytes):
                await ws.send(reply)
            elif isinstance(reply, int):
                await ws.close(reply)
                return
            elif reply is None:
                await ws.wait_closed()
                self.closed.set()
                return
            else:
                await ws.send(json.dumps(reply))

    def service(self, **kwargs):
        return ChariotTTSService(
            api_key="test-key", voice_id="test-voice", ws_url=self.url, **kwargs
        )

    async def test_streams_pcm_model_context_and_metrics(self):
        # An odd message boundary must not drop or invent audio samples.
        self.replies[1:2] = [b"", PCM[:3], PCM[3:]]
        async with pipeline(self.service()) as (worker, down, up):
            await worker.queue_frame(TTSSpeakFrame("Hello."))
            stopped = await down.until(TTSStoppedFrame)
            audio = [f for f in down.frames if isinstance(f, TTSAudioRawFrame)]
            self.assertEqual(b"".join(f.audio for f in audio), PCM)
            self.assertTrue(all(f.sample_rate == 44100 and f.num_channels == 1 for f in audio))
            self.assertTrue(all(f.context_id == stopped.context_id for f in audio))
            started = next(f for f in down.frames if isinstance(f, TTSStartedFrame))
            self.assertEqual(started.context_id, stopped.context_id)
            self.assertFalse(any(isinstance(f, ErrorFrame) for f in up.frames))
            metrics = [m for f in down.frames if isinstance(f, MetricsFrame) for m in f.data]
            self.assertTrue(any(isinstance(m, TTFBMetricsData) and m.value > 0 for m in metrics))
            self.assertTrue(any(isinstance(m, TTSUsageMetricsData) for m in metrics))
        self.assertEqual(self.requests[0], {
            "key": "test-key",
            "query": {"voice_id": ["test-voice"], "model_type": [DEFAULT_MODEL],
                      "response_format": ["pcm"], "existing": ["value"]},
            "messages": [{"type": "input.text", "text": "Hello."}, {"type": "input.done"}],
        })

    async def test_settings_override_and_runtime_model_update(self):
        with patch.dict(os.environ, {"CHARIOT_MODEL": "env-model"}):
            self.assertEqual(self.service()._settings.model, "env-model")
            self.assertEqual(self.service(model="argument-model")._settings.model, "argument-model")
            service = self.service(model="argument-model", settings=ChariotTTSService.Settings(
                model="settings-model", voice="settings-voice"
            ))
        self.assertIsNone(service._settings.language)
        async with pipeline(service) as (worker, down, up):
            await worker.queue_frame(TTSSpeakFrame("First."))
            await down.until(TTSStoppedFrame)
            await worker.queue_frame(TTSUpdateSettingsFrame(
                delta=ChariotTTSService.Settings(model="updated-model", voice="updated-voice")
            ))
            await worker.queue_frame(TTSSpeakFrame("Second."))
            await down.until(TTSStoppedFrame)
        self.assertEqual(self.requests[0]["query"]["model_type"], ["settings-model"])
        self.assertEqual(self.requests[0]["query"]["voice_id"], ["settings-voice"])
        self.assertEqual(self.requests[1]["query"]["model_type"], ["updated-model"])
        self.assertEqual(self.requests[1]["query"]["voice_id"], ["updated-voice"])

    async def assert_stream_error(self, message, **kwargs):
        async with pipeline(self.service(**kwargs)) as (worker, down, up):
            await worker.queue_frame(TTSSpeakFrame("Hello."))
            error = await up.until(ErrorFrame)
            self.assertIn(message, error.error)

    async def test_segment_failure_after_partial_audio(self):
        self.replies[2] = {"type": "audio.done", "error": "generation failed"}
        await self.assert_stream_error("generation failed")

    async def test_server_error(self):
        self.replies = [{"type": "error", "message": "invalid voice"}]
        await self.assert_stream_error("invalid voice")

    async def test_credit_exhaustion(self):
        self.replies = [4402]
        await self.assert_stream_error("credit balance exhausted")

    async def test_normal_close_before_completion_is_an_error(self):
        self.replies = self.replies[:2]
        await self.assert_stream_error("before session.done")

    async def test_empty_result(self):
        self.replies = [{"type": "session.done"}]
        await self.assert_stream_error("completed without audio")

    async def test_incomplete_pcm_sample(self):
        self.replies[1] = b"\x01"
        await self.assert_stream_error("incomplete PCM sample")

    async def test_receive_timeout_closes_socket(self):
        self.replies = [None]
        await self.assert_stream_error("timed out", receive_timeout=0.1)
        await asyncio.wait_for(self.closed.wait(), 2)

    async def test_interruption_closes_socket_and_next_utterance_works(self):
        self.replies = [self.replies[0], PCM, None]
        async with pipeline(self.service()) as (worker, down, up):
            await worker.queue_frame(TTSSpeakFrame("Interrupted."))
            first = await down.until(TTSAudioRawFrame)
            await worker.queue_frame(InterruptionFrame())
            await down.until(InterruptionFrame)
            await asyncio.wait_for(self.closed.wait(), 2)
            self.replies = [
                {"type": "audio.start", "sample_rate": 24000}, PCM,
                {"type": "audio.done"}, {"type": "session.done"},
            ]
            await worker.queue_frame(TTSSpeakFrame("Next utterance."))
            second = await down.until(TTSAudioRawFrame)
            await down.until(TTSStoppedFrame)
            self.assertNotEqual(first.context_id, second.context_id)
            self.assertEqual(second.sample_rate, 24000)
            self.assertFalse(any(isinstance(f, ErrorFrame) for f in up.frames))
        self.assertEqual(len(self.requests), 2)


if __name__ == "__main__":
    unittest.main()
