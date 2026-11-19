"""Check that the demo builds Chariot STT and TTS from .env and refuses to start without keys."""

import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
import agent


class AgentTests(unittest.IsolatedAsyncioTestCase):
    async def test_stt_settings_come_from_the_environment(self):
        environment = {
            "CHARIOT_API_KEY": "test-key",
            "CHARIOT_ASR_LANGUAGE": "hi-IN",
            "CHARIOT_ASR_MODE": "high_accuracy",
            "CHARIOT_ASR_STYLE": "native",
            "CHARIOT_ASR_COMMIT_STRATEGY": "vad",
        }
        with patch.dict(os.environ, environment, clear=True):
            stt = agent.create_stt()
        options = stt._opts
        self.assertEqual(
            (options.language, options.mode, options.style, options.server_vad),
            ("hi", "high_accuracy", "native", {}),
        )
        # with Chariot's VAD splitting utterances, LiveKit does not flush the stream
        self.assertFalse(stt.capabilities.manual_flush)
        await stt.aclose()

    async def test_stt_defaults_detect_the_language_and_follow_livekit_turns(self):
        environment = {"CHARIOT_API_KEY": "test-key", "CHARIOT_ASR_LANGUAGE": "none"}
        with patch.dict(os.environ, environment, clear=True):
            stt = agent.create_stt()
        options = stt._opts
        self.assertEqual(
            (options.language, options.mode, options.style, options.server_vad),
            (None, "balanced", "codemix", None),
        )
        self.assertTrue(stt.capabilities.manual_flush)
        await stt.aclose()

    async def test_tts_uses_the_configured_voice_and_model(self):
        environment = {
            "CHARIOT_API_KEY": "test-key",
            "CHARIOT_VOICE_ID": "test-voice",
            "CHARIOT_MODEL": "chariot-v0",
        }
        with patch.dict(os.environ, environment, clear=True):
            tts = agent.create_tts()
        self.assertEqual((tts._opts.voice, tts.model), ("test-voice", "chariot-v0"))
        await tts.aclose()

        with patch.dict(os.environ, {"CHARIOT_API_KEY": "test-key"}, clear=True):
            tts = agent.create_tts()
        self.assertEqual(tts.model, "chariot-multilingual-v1")
        await tts.aclose()

    def test_missing_keys_stop_the_agent_before_it_starts(self):
        # set but empty, so a local .env cannot fill them in
        environment = {**os.environ, "CHARIOT_API_KEY": "", "OPENAI_API_KEY": ""}
        result = subprocess.run(
            [sys.executable, "agent.py", "console"],
            cwd=AGENT_DIR,
            env=environment,
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("Missing CHARIOT_API_KEY, OPENAI_API_KEY", result.stderr)


if __name__ == "__main__":
    unittest.main()
