"""Check the demo UI, local WebRTC signaling, and background-task cleanup."""

import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from aiortc import RTCConfiguration, RTCPeerConnection, RTCSessionDescription

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bot
from pipecat.transports.smallwebrtc.request_handler import SmallWebRTCRequestHandler


class BotTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_keys_fail_at_startup(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "Chariot voice required"):
                async with bot.app.router.lifespan_context(bot.app):
                    self.fail("Startup should reject missing configuration")

    async def test_ui_signaling_and_shutdown(self):
        started = asyncio.Event()
        cancelled = asyncio.Event()
        options = []

        async def stand_in_bot(connection, voice=None, model=None):
            options.append((voice, model))
            started.set()
            try:
                await asyncio.Future()
            finally:
                cancelled.set()

        peer = RTCPeerConnection(RTCConfiguration(iceServers=[]))
        peer.addTransceiver("audio", direction="sendrecv")
        peer.createDataChannel("rtvi-ai")
        connected = asyncio.Event()

        @peer.on("connectionstatechange")
        async def on_state():
            if peer.connectionState == "connected":
                connected.set()

        environment = {
            "CHARIOT_API_KEY": "test-key", "CHARIOT_VOICE_ID": "test-voice",
            "OPENAI_API_KEY": "test-openai-key",
        }
        try:
            with patch.dict(os.environ, environment, clear=True), \
                 patch.object(bot, "run_bot", stand_in_bot), \
                 patch.object(bot, "webrtc_handler", SmallWebRTCRequestHandler(ice_servers=[])), \
                 patch.object(bot.app.state, "voice", "configured-voice"), \
                 patch.object(bot.app.state, "model", "configured-model"):
                async with bot.app.router.lifespan_context(bot.app):
                    async with httpx.AsyncClient(
                        transport=httpx.ASGITransport(app=bot.app), base_url="http://test"
                    ) as client:
                        self.assertEqual((await client.get("/")).headers["location"], "/client/")
                        self.assertEqual((await client.get("/client/index.html")).status_code, 200)
                        self.assertEqual((await client.post("/sessions/invalid/api/offer")).status_code, 404)
                        start = (await client.post("/start")).json()
                        await peer.setLocalDescription(await peer.createOffer())
                        answer = await client.post(f"/sessions/{start['sessionId']}/api/offer", json={
                            "sdp": peer.localDescription.sdp, "type": peer.localDescription.type,
                        })
                        self.assertEqual(answer.status_code, 200)
                        data = answer.json()
                        self.assertTrue(data["pc_id"])
                        await peer.setRemoteDescription(RTCSessionDescription(
                            sdp=data["sdp"], type=data["type"]
                        ))
                        await asyncio.wait_for(started.wait(), 5)
                        await asyncio.wait_for(connected.wait(), 5)
                        self.assertEqual(options, [("configured-voice", "configured-model")])
                        self.assertEqual(len(bot.bot_tasks), 1)
                self.assertTrue(cancelled.is_set())
                self.assertFalse(bot.bot_tasks)
                self.assertFalse(bot.active_sessions)
        finally:
            await peer.close()


if __name__ == "__main__":
    unittest.main()
