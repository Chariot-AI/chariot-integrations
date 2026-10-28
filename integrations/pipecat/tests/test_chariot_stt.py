"""Exercise the ASR adapter in real pipelines against a local WebSocket server."""
import asyncio
import json
import unittest
from urllib.parse import parse_qs, urlsplit

from websockets.asyncio.server import serve
from pipecat.frames.frames import (
    EndFrame, ErrorFrame, InputAudioRawFrame, InterruptionFrame,
    InterimTranscriptionFrame, STTUpdateSettingsFrame, TranscriptionFrame,
    VADUserStartedSpeakingFrame, VADUserStoppedSpeakingFrame, LLMContextFrame,
)
from test_chariot_tts import pipeline, Capture
from pipecat.processors.frame_processor import FrameDirection
from pipecat.pipeline.pipeline import Pipeline
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair
from chariot_stt import ChariotSTTService

PCM = b"\x00\x00" * 1600


class STTTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.messages = []
        self.requests = []
        self.commits = 0
        self.final_tail = "tail"
        self.empty_commit = False
        self.close_early = False
        self.reject = None
        self.stall_commit = False
        self.stall_done = False
        self.closed = asyncio.Event()
        self.server = await serve(self.handle, "127.0.0.1", 0)
        self.url = f"ws://127.0.0.1:{self.server.sockets[0].getsockname()[1]}/v1/asr/ws"

    async def asyncTearDown(self):
        self.server.close()
        await self.server.wait_closed()

    async def handle(self, ws):
        query = parse_qs(urlsplit(ws.request.path).query)
        self.requests.append((query, ws.request.headers.get("chariotai-api-key")))
        try:
            if self.reject:
                await ws.send(json.dumps(self.reject))
                return
            await ws.send(json.dumps({"type":"session.started", "session_id":"test-session",
                                      "sample_rate":16000, "commit_strategy":query["commit_strategy"][0]}))
            async for data in ws:
                self.messages.append(data)
                if isinstance(data, bytes):
                    await ws.send(json.dumps({"type":"transcript.delta", "text":"hel"}))
                    await ws.send(json.dumps({"type":"transcript.delta", "text":"lo"}))
                    if self.close_early:
                        return
                    if query["commit_strategy"] == ["vad"]:
                        await self.commit(ws)
                else:
                    kind = json.loads(data)["type"]
                    if kind == "input.commit" and not self.stall_commit:
                        await self.commit(ws)
                    if kind == "input.done" and not self.stall_done:
                        await ws.send(json.dumps({"type":"transcript.done", "text":self.final_tail,
                                                  "audio_seconds":0.1, "words":[]}))
                        return
        finally:
            self.closed.set()

    async def commit(self, ws):
        self.commits += 1
        await ws.send(json.dumps({"type":"transcript.committed", "text":"" if self.empty_commit else f"turn {self.commits}",
                                  "segment_id":self.commits-1, "words":[{"text":"turn", "start":0., "end":.1}]}))

    def service(self, **kwargs):
        return ChariotSTTService(api_key="test-key", ws_url=self.url, **kwargs)

    def controls(self):
        return [json.loads(m)["type"] for m in self.messages if isinstance(m, str)]

    async def audio(self, worker):
        await worker.queue_frame(InputAudioRawFrame(PCM, 16000, 1))

    async def test_manual_commits_interims_timestamps_and_interruption(self):
        service = self.service(settings=ChariotSTTService.Settings(
            language="hi", mode="high_accuracy", style="native", include_timestamps=True))
        async with pipeline(service) as (worker, down, up):
            await self.audio(worker)
            first = await down.until(InterimTranscriptionFrame)
            second = await down.until(InterimTranscriptionFrame)
            self.assertEqual([first.text, second.text], ["hel", "hello"])
            await worker.queue_frame(VADUserStoppedSpeakingFrame())
            final = await down.until(TranscriptionFrame)
            self.assertEqual(final.text, "turn 1")
            self.assertTrue(final.finalized)
            self.assertEqual(final.result["words"][0]["start"], 0.)
            await worker.queue_frame(InterruptionFrame())
            await down.until(InterruptionFrame)
            await self.audio(worker)
            await down.until(InterimTranscriptionFrame)
            await worker.queue_frame(VADUserStoppedSpeakingFrame())
            self.assertEqual((await down.until(TranscriptionFrame)).text, "turn 2")
            self.assertEqual(len(self.requests), 1)
        self.assertTrue(self.closed.is_set())
        query, key = self.requests[0]
        self.assertEqual(key, "test-key")
        for name, value in {"mode":"high_accuracy", "style":"native", "language":"hi", "include_timestamps":"true"}.items():
            self.assertEqual(query[name], [value])
        self.assertEqual(self.controls().count("input.commit"), 2)

    async def test_server_vad_never_sends_local_commits(self):
        async with pipeline(self.service(commit_strategy="vad")) as (worker, down, up):
            await self.audio(worker)
            final = await down.until(TranscriptionFrame)
            self.assertFalse(final.finalized)
            await worker.queue_frame(VADUserStoppedSpeakingFrame())
            await down.until(VADUserStoppedSpeakingFrame)
            self.assertNotIn("input.commit", self.controls())
        self.assertEqual(self.requests[0][0]["silence_duration_ms"], ["500"])

    async def test_graceful_end_returns_tail_once(self):
        async with pipeline(self.service()) as (worker, down, up):
            await self.audio(worker)
            await down.until(InterimTranscriptionFrame)
            await worker.queue_frame(VADUserStoppedSpeakingFrame())
            await down.until(TranscriptionFrame)
            await worker.queue_frame(EndFrame())
            await down.until(EndFrame)
            self.assertEqual([f.text for f in down.frames if isinstance(f, TranscriptionFrame)], ["turn 1", "tail"])
        self.assertEqual(self.controls().count("input.done"), 1)

    async def test_empty_final_tail_does_not_repeat_commits(self):
        self.final_tail = ""
        async with pipeline(self.service()) as (worker, down, up):
            await self.audio(worker)
            await down.until(InterimTranscriptionFrame)
            await worker.queue_frame(VADUserStoppedSpeakingFrame())
            await down.until(TranscriptionFrame)
            await worker.queue_frame(EndFrame())
            await down.until(EndFrame)
            self.assertEqual([f.text for f in down.frames if isinstance(f, TranscriptionFrame)], ["turn 1"])

    async def test_keepalive_is_json_not_billable_silence(self):
        async with pipeline(self.service(keepalive_interval=.02)) as (worker, down, up):
            await asyncio.sleep(.07)
            self.assertIn("keepalive", self.controls())
            self.assertFalse(any(isinstance(m, bytes) for m in self.messages))

    async def test_premature_close_is_error(self):
        self.close_early = True
        async with pipeline(self.service()) as (worker, down, up):
            await self.audio(worker)
            error = await up.until(ErrorFrame)
            self.assertIn("before transcript.done", error.error)
            self.assertTrue(error.fatal)

    async def test_stalled_commit_is_bounded(self):
        self.stall_commit = True
        async with pipeline(self.service(finalize_timeout=.1)) as (worker, down, up):
            await self.audio(worker)
            await down.until(InterimTranscriptionFrame)
            await worker.queue_frame(VADUserStoppedSpeakingFrame())
            self.assertIn("timed out", (await up.until(ErrorFrame)).error)

    async def test_runtime_settings_are_rejected_without_false_update(self):
        service = self.service()
        async with pipeline(service) as (worker, down, up):
            await worker.queue_frame(STTUpdateSettingsFrame(delta=ChariotSTTService.Settings(language="hi")))
            self.assertIn("fixed", (await up.until(ErrorFrame)).error)
            self.assertIsNone(service._settings.language)

    async def test_mismatched_audio_is_rejected(self):
        async with pipeline(self.service()) as (worker, down, up):
            await worker.queue_frame(InputAudioRawFrame(PCM, 48000, 1))
            self.assertIn("configured sample rate", (await up.until(ErrorFrame)).error)

    async def test_manual_transcript_reaches_llm_context(self):
        context = LLMContext()
        user, assistant = LLMContextAggregatorPair(context)
        capture = Capture(FrameDirection.DOWNSTREAM)
        async with pipeline(Pipeline([self.service(), capture, user])) as (worker, down, up):
            await worker.queue_frame(VADUserStartedSpeakingFrame())
            await down.until(VADUserStartedSpeakingFrame)
            await self.audio(worker)
            await capture.until(InterimTranscriptionFrame)
            await worker.queue_frame(VADUserStoppedSpeakingFrame())
            await down.until(LLMContextFrame)
            self.assertEqual(context.messages[-1]["content"], "turn 1")

    async def test_empty_commit_then_next_utterance(self):
        self.empty_commit = True
        async with pipeline(self.service()) as (worker, down, up):
            await self.audio(worker)
            await down.until(InterimTranscriptionFrame)
            await worker.queue_frame(VADUserStoppedSpeakingFrame())
            async with asyncio.timeout(2):
                while not self.commits:
                    await asyncio.sleep(.01)
            self.empty_commit = False
            await self.audio(worker)
            await down.until(InterimTranscriptionFrame)
            await worker.queue_frame(VADUserStoppedSpeakingFrame())
            self.assertEqual((await down.until(TranscriptionFrame)).text, "turn 2")

    async def test_final_timeout_closes_socket(self):
        self.stall_done = True
        async with pipeline(self.service(finalize_timeout=.1)) as (worker, down, up):
            await worker.queue_frame(EndFrame())
            self.assertIn("final transcript", (await up.until(ErrorFrame)).error)
        self.assertTrue(self.closed.is_set())

    async def test_rejected_handshake_is_reported(self):
        for code in [1008, 4402, 4429]:
            with self.subTest(code=code):
                self.reject = {"type": "error", "code": code, "message": "Session rejected"}
                async with pipeline(self.service()) as (worker, down, up):
                    error = await up.until(ErrorFrame)
                    self.assertIn("Session rejected", error.error)
                    self.assertTrue(error.fatal)

    def test_invalid_settings(self):
        for kwargs in [dict(silence_duration_ms=99), dict(silence_duration_ms=10001),
                       dict(vad_threshold=float('nan')), dict(commit_strategy="unknown"),
                       dict(sample_rate=12345), dict(keepalive_interval=60),
                       dict(settings=ChariotSTTService.Settings(language="de")),
                       dict(settings=ChariotSTTService.Settings(mode="unknown"))]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.service(**kwargs)


if __name__ == '__main__':
    unittest.main()
