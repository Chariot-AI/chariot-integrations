"""Exercise full-duplex PCM streaming against a local server."""
import asyncio
import json
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from websockets.asyncio.server import serve
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from streaming import transcribe


class StreamingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "sample.wav"
        self.pcm = b"\x01\x00" * 3200
        with wave.open(str(self.path), "wb") as audio:
            audio.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
            audio.writeframes(self.pcm)
        self.received = bytearray()
        self.controls = []
        self.early = False
        self.stall = False
        self.server = await serve(self.handle, "127.0.0.1", 0)
        self.url = f"ws://127.0.0.1:{self.server.sockets[0].getsockname()[1]}/v1/asr/ws"

    async def asyncTearDown(self):
        self.server.close()
        await self.server.wait_closed()
        self.temp.cleanup()

    async def handle(self, ws):
        self.assertEqual(ws.request.headers["chariotai-api-key"], "test-key")
        query = parse_qs(urlsplit(ws.request.path).query)
        self.assertEqual(query["audio_format"], ["pcm_16000"])
        await ws.send(json.dumps({"type": "session.started", "session_id": "example-session", "sample_rate": 16000}))
        async for message in ws:
            if isinstance(message, bytes):
                self.received.extend(message)
                await ws.send(json.dumps({"type": "transcript.delta", "text": "partial"}))
                if self.early:
                    return
            else:
                kind = json.loads(message)["type"]
                self.controls.append(kind)
                if kind == "input.commit":
                    await ws.send(json.dumps({"type": "transcript.committed", "text": "hello", "words": None}))
                if kind == "input.done" and not self.stall:
                    await ws.send(json.dumps({"type": "transcript.done", "text": "tail", "words": []}))
                    return

    async def test_pcm_commits_and_tail_without_partial_duplication(self):
        events = await transcribe(self.path, "test-key", commit_every=.1, ws_url=self.url)
        self.assertEqual(self.received, self.pcm)
        self.assertEqual(self.controls, ["input.commit", "input.commit", "input.done"])
        self.assertEqual([e["text"] for e in events], ["hello", "hello", "tail"])

    async def test_premature_close(self):
        self.early = True
        with self.assertRaisesRegex(RuntimeError, "without transcript.done"):
            await transcribe(self.path, "test-key", ws_url=self.url)
        self.assertLess(len(self.received), len(self.pcm))

    async def test_timeout_closes_receiver(self):
        self.stall = True
        with self.assertRaises(asyncio.TimeoutError):
            await transcribe(self.path, "test-key", ws_url=self.url, finalize_timeout=.02)

    async def test_conflicting_commit_options(self):
        with self.assertRaises(ValueError):
            await transcribe(self.path, "test-key", ws_url=self.url, commit_strategy="vad", commit_every=1)
