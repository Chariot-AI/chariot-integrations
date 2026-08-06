"""Stream text into Chariot TTS and audio out, over one WebSocket.

Two modes:

    one shot (default): send the full text, then input.done. The server
    synthesizes everything as one continuous generation.

    --stream: drip-feed the text in small fragments the way an LLM emits
    tokens, flushing after each so audio is generated progressively. This is
    the pattern a voice agent uses.

Usage:
    python streaming.py "Hello. How are you today?"
    python streaming.py "Hello. How are you today?" --stream
"""

import asyncio
import json
import os
import sys
import wave

import websockets
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.environ["CHARIOT_API_KEY"]
VOICE_ID = os.environ["CHARIOT_VOICE_ID"]
OUT_PATH = "out.wav"
FRAGMENT_CHARS = 12  # roughly what an LLM hands you per few tokens


def fragment(text: str, size: int) -> list[str]:
    """Cut text into ~size-char pieces at word boundaries, like a token stream."""
    words = text.split(" ")
    pieces: list[str] = []
    buf = ""
    for word in words:
        candidate = f"{buf} {word}".strip()
        if len(candidate) >= size:
            pieces.append(candidate + " ")
            buf = ""
        else:
            buf = candidate
    if buf:
        pieces.append(buf)
    return pieces


async def run(text: str, stream_mode: bool) -> None:
    # Generation is flush-driven: the server buffers text until input.flush
    # or input.done, then synthesizes the buffer as one piece. When you flush
    # is the whole segmentation story, and it is under your control.
    uri = (
        "wss://api.chariot.in/v1/tts/ws"
        f"?voice_id={VOICE_ID}&response_format=pcm"
    )

    audio = bytearray()
    sample_rate = 44100  # the server's audio.start declaration overrides this

    async with websockets.connect(
        uri, additional_headers={"chariotai-api-key": API_KEY}, max_size=None
    ) as ws:

        async def send_text() -> None:
            if stream_mode:
                for piece in fragment(text, FRAGMENT_CHARS):
                    print(f"-> input.text  {piece!r}")
                    await ws.send(json.dumps({"type": "input.text", "text": piece}))
                    await asyncio.sleep(0.05)  # mimic token pacing
                    await ws.send(json.dumps({"type": "input.flush"}))
            else:
                print(f"-> input.text  {text!r}")
                await ws.send(json.dumps({"type": "input.text", "text": text}))
            print("-> input.done")
            await ws.send(json.dumps({"type": "input.done"}))

        sender = asyncio.create_task(send_text())
        try:
            async for message in ws:
                if isinstance(message, bytes):
                    audio.extend(message)
                    continue
                event = json.loads(message)
                print(f"<- {event}")
                if event["type"] == "audio.start":
                    sample_rate = event.get("sample_rate") or sample_rate
                elif event["type"] == "session.done":
                    break
                elif event["type"] == "error":
                    print(f"server error: {event.get('message')}", file=sys.stderr)
                    break
        finally:
            await sender

    if not audio:
        print("no audio received", file=sys.stderr)
        return
    with wave.open(OUT_PATH, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit PCM
        wf.setframerate(sample_rate)
        wf.writeframes(bytes(audio))
    seconds = len(audio) / 2 / sample_rate
    print(f"wrote {OUT_PATH}: {seconds:.1f}s at {sample_rate} Hz")


if __name__ == "__main__":
    args = sys.argv[1:]
    stream_mode = "--stream" in args
    args = [a for a in args if a != "--stream"]
    default_text = "Hello from Chariot. This is the streaming API, speaking as it thinks."
    asyncio.run(run(args[0] if args else default_text, stream_mode))
