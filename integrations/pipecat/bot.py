"""A browser voice agent that speaks with a Chariot voice.

Pipeline: browser microphone -> OpenAI STT -> OpenAI LLM -> Chariot TTS ->
browser speakers, all over WebRTC with Silero VAD driving interruptions.

Run `python bot.py`, open http://localhost:7860, click Connect, and talk.
"""

import argparse
import asyncio
import os
import uuid
from contextlib import asynccontextmanager

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response
from fastapi.responses import RedirectResponse
from loguru import logger
from pipecat_ai_small_webrtc_prebuilt.frontend import SmallWebRTCPrebuiltUI

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import LLMRunFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.services.openai.stt import OpenAISTTService
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.smallwebrtc.connection import IceServer, SmallWebRTCConnection
from pipecat.transports.smallwebrtc.request_handler import (
    IceCandidate,
    SmallWebRTCPatchRequest,
    SmallWebRTCRequest,
    SmallWebRTCRequestHandler,
)
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport
from pipecat.workers.runner import WorkerRunner

from chariot_tts import ChariotTTSService

load_dotenv(override=True)

ICE_SERVERS = [IceServer(urls="stun:stun.l.google.com:19302")]

webrtc_handler = SmallWebRTCRequestHandler(ice_servers=ICE_SERVERS)
active_sessions: dict = {}
bot_tasks: set[asyncio.Task] = set()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fail at startup instead of leaving a connected browser with a silent bot.
    ChariotTTSService(voice_id=app.state.voice, model=app.state.model)
    if not os.getenv("OPENAI_API_KEY"):
        raise ValueError("Set OPENAI_API_KEY for the demo's STT and LLM")
    try:
        yield
    finally:
        await webrtc_handler.close()
        tasks = list(bot_tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        active_sessions.clear()


app = FastAPI(lifespan=lifespan)
app.state.voice = None
app.state.model = None
app.mount("/client", SmallWebRTCPrebuiltUI)


async def run_bot(
    webrtc_connection: SmallWebRTCConnection,
    voice: str | None = None,
    model: str | None = None,
):
    transport = SmallWebRTCTransport(
        webrtc_connection=webrtc_connection,
        params=TransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
        ),
    )

    stt = OpenAISTTService(api_key=os.getenv("OPENAI_API_KEY"))

    llm = OpenAILLMService(
        api_key=os.getenv("OPENAI_API_KEY"),
        settings=OpenAILLMService.Settings(
            system_instruction=(
                "You are a friendly and helpful voice assistant. "
                "Keep your responses concise. You are speaking aloud, so avoid "
                "bullet points, markdown, or special characters."
            ),
        ),
    )

    # The Chariot voice that answers. 44.1 kHz PCM streams back while the
    # server is still generating, so speech starts before the sentence ends.
    tts = ChariotTTSService(
        api_key=os.getenv("CHARIOT_API_KEY"),
        voice_id=voice or os.getenv("CHARIOT_VOICE_ID"),
        model=model,
        sample_rate=44100,
    )

    context = LLMContext()
    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(vad_analyzer=SileroVADAnalyzer()),
    )

    pipeline = Pipeline(
        [
            transport.input(),       # Browser microphone input
            stt,                     # Speech to text (OpenAI)
            user_aggregator,         # Accumulate the user's turn
            llm,                     # Text to response (OpenAI)
            tts,                     # Text to speech (Chariot)
            transport.output(),      # Browser speaker output
            assistant_aggregator,    # Accumulate the assistant's turn
        ]
    )

    worker = PipelineWorker(
        pipeline,
        params=PipelineParams(enable_metrics=True, enable_usage_metrics=True),
    )

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        logger.info("Client connected")
        context.add_message(
            {
                "role": "user",
                "content": "Greet the user warmly and let them know they can start talking.",
            }
        )
        await worker.queue_frames([LLMRunFrame()])

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info("Client disconnected")
        await worker.cancel()

    runner = WorkerRunner(handle_sigint=False)
    await runner.add_workers(worker)
    await runner.run()


@app.get("/", include_in_schema=False)
async def root_redirect():
    return RedirectResponse(url="/client/")


@app.post("/start")
async def start(request: Request):
    """Return a session ID and ICE config to the prebuilt UI."""
    session_id = str(uuid.uuid4())
    active_sessions[session_id] = {}
    return {
        "sessionId": session_id,
        "iceConfig": {"iceServers": [{"urls": "stun:stun.l.google.com:19302"}]},
    }


@app.api_route(
    "/sessions/{session_id}/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
)
async def session_proxy(session_id: str, path: str, request: Request):
    if session_id not in active_sessions:
        return Response(content="Invalid session", status_code=404)

    if path.endswith("api/offer"):
        data = await request.json()
        if request.method == "POST":
            webrtc_request = SmallWebRTCRequest(
                sdp=data["sdp"],
                type=data["type"],
                pc_id=data.get("pc_id"),
                restart_pc=data.get("restart_pc"),
            )

            async def run_bot_task(connection):
                task = asyncio.create_task(
                    run_bot(connection, voice=app.state.voice, model=app.state.model)
                )
                bot_tasks.add(task)

                def on_done(task):
                    bot_tasks.discard(task)
                    active_sessions.pop(session_id, None)
                    if not task.cancelled() and task.exception() is not None:
                        logger.error(f"Voice session failed: {task.exception()}")

                task.add_done_callback(on_done)

            return await webrtc_handler.handle_web_request(webrtc_request, run_bot_task)
        elif request.method == "PATCH":
            patch_request = SmallWebRTCPatchRequest(
                pc_id=data["pc_id"],
                candidates=[IceCandidate(**c) for c in data.get("candidates", [])],
            )
            await webrtc_handler.handle_patch_request(patch_request)
            return Response(status_code=200)

    return Response(status_code=200)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pipecat voice agent with Chariot TTS")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=7860)
    parser.add_argument("--voice", help="Voice UUID (defaults to CHARIOT_VOICE_ID)")
    parser.add_argument("--model", help="Model name (defaults to CHARIOT_MODEL or multilingual v1)")
    args = parser.parse_args()
    app.state.voice = args.voice
    app.state.model = args.model
    logger.info(f"Open http://{args.host}:{args.port} in your browser")
    uvicorn.run(app, host=args.host, port=args.port)
