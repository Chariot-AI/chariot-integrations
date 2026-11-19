"""A LiveKit voice agent that listens and speaks with Chariot.

Pipeline: microphone -> Chariot STT -> OpenAI LLM -> Chariot TTS -> speakers,
with Silero VAD deciding when you have finished speaking. The Chariot STT and
TTS come from the livekit-plugins-chariot package.

Run `python agent.py console` to talk to it in your terminal, with no LiveKit
server. `python agent.py dev` connects it to a LiveKit server instead.
"""

import logging
import os
import sys

from dotenv import load_dotenv
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    JobContext,
    MetricsCollectedEvent,
    cli,
    metrics,
)
from livekit.plugins import chariot, openai, silero

load_dotenv()

logger = logging.getLogger("chariot-agent")

INSTRUCTIONS = (
    "You are a friendly voice assistant. Reply in the language the user speaks, "
    "including mixed Hindi and English. Keep replies short. Your output is spoken "
    "aloud, so do not use emojis, markdown, or lists."
)

REQUIRED_KEYS = ("CHARIOT_API_KEY", "OPENAI_API_KEY")

# Commands that start the agent, and so need the keys
RUN_COMMANDS = ("console", "dev", "start", "connect")


def missing_keys() -> list[str]:
    """The required environment variables that are not set."""
    return [key for key in REQUIRED_KEYS if not os.getenv(key)]


def create_stt() -> chariot.STT:
    """Chariot speech-to-text, configured from the environment (see .env.sample)."""
    language = os.getenv("CHARIOT_ASR_LANGUAGE")
    return chariot.STT(
        language=None if not language or language == "none" else language,
        mode=os.getenv("CHARIOT_ASR_MODE") or "balanced",
        style=os.getenv("CHARIOT_ASR_STYLE") or "codemix",
        # manual: LiveKit's turn detection ends each utterance; vad: Chariot's does
        server_vad={} if os.getenv("CHARIOT_ASR_COMMIT_STRATEGY") == "vad" else None,
    )


def create_tts() -> chariot.TTS:
    """Chariot text-to-speech, configured from the environment (see .env.sample)."""
    options = {}
    if voice := os.getenv("CHARIOT_VOICE_ID"):
        options["voice"] = voice
    if model := os.getenv("CHARIOT_MODEL"):
        options["model"] = model
    return chariot.TTS(**options)


class Assistant(Agent):
    def __init__(self) -> None:
        super().__init__(instructions=INSTRUCTIONS)

    async def on_enter(self) -> None:
        self.session.generate_reply(instructions="Greet the user briefly and invite them to talk.")


server = AgentServer()


@server.rtc_session()
async def entrypoint(ctx: JobContext) -> None:
    session = AgentSession(
        vad=silero.VAD.load(),
        stt=create_stt(),
        llm=openai.LLM(),
        tts=create_tts(),
    )

    @session.on("metrics_collected")
    def _on_metrics_collected(ev: MetricsCollectedEvent) -> None:
        # one line per turn and per reply: end-of-turn delay, STT, LLM and TTS latency
        metrics.log_metrics(ev.metrics)

    await session.start(agent=Assistant(), room=ctx.room)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in RUN_COMMANDS and (missing := missing_keys()):
        sys.exit(f"Missing {', '.join(missing)}: copy .env.sample to .env and add your keys.")
    cli.run_app(server)
