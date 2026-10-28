"""Stream a mono PCM16 WAV to Chariot and receive transcripts concurrently."""

import argparse
import asyncio
import json
import math
import os
import sys
import wave
from urllib.parse import urlencode

import websockets
from dotenv import load_dotenv

WS_URL = "wss://api.chariot.in/v1/asr/ws"
MODEL = "chariot-1-asr-realtime"
SAMPLE_RATES = {8000, 16000, 22050, 24000, 32000, 44100, 48000}


async def transcribe(path, api_key, *, language="none", mode="balanced", style="codemix",
                     timestamps=False, commit_strategy="manual", silence_duration_ms=500,
                     commit_every=0, finalize_timeout=65, ws_url=WS_URL):
    if not math.isfinite(commit_every) or commit_every < 0:
        raise ValueError("commit_every must be non-negative and finite")
    if commit_strategy == "vad" and commit_every:
        raise ValueError("Use server VAD or manual periodic commits, not both")
    if not math.isfinite(finalize_timeout) or finalize_timeout <= 0:
        raise ValueError("finalize_timeout must be positive and finite")
    with wave.open(str(path), "rb") as audio:
        rate = audio.getframerate()
        if audio.getnchannels() != 1 or audio.getsampwidth() != 2 or rate not in SAMPLE_RATES or audio.getcomptype() != "NONE":
            raise ValueError("Input must be a mono, signed PCM16 WAV at a supported sample rate (for example 16000 Hz)")
        if audio.getnframes() == 0:
            raise ValueError("Input WAV contains no audio")
        params = dict(model_type=MODEL, audio_format=f"pcm_{rate}", language=language,
                      mode=mode, style=style, include_timestamps=str(timestamps).lower(),
                      commit_strategy=commit_strategy, silence_duration_ms=silence_duration_ms,
                      vad_events=str(commit_strategy == "vad").lower())
        async with websockets.connect(f"{ws_url}?{urlencode(params)}",
                                      additional_headers={"chariotai-api-key": api_key},
                                      open_timeout=15, close_timeout=2, max_size=4 * 1024 * 1024) as ws:
            ready = json.loads(await asyncio.wait_for(ws.recv(), 15))
            if ready.get("type") != "session.started":
                raise RuntimeError(ready.get("message", "Session did not start"))
            if ready.get("sample_rate") != rate:
                raise RuntimeError("Server sample rate differs from the WAV")
            print(f"Session: {ready['session_id']}", file=sys.stderr)
            segments = []
            input_ended = False

            async def receive():
                partial = ""
                async for message in ws:
                    event = json.loads(message)
                    kind = event.get("type")
                    if kind == "error":
                        raise RuntimeError(f"ASR error: {event.get('message', 'unknown error')}")
                    if kind == "transcript.delta":
                        partial += event["text"]
                        print(f"Partial: {partial}", file=sys.stderr)
                    elif kind in ("transcript.committed", "transcript.done"):
                        # The done text is only the uncommitted tail, not a full transcript.
                        if kind == "transcript.done" and not input_ended:
                            raise RuntimeError("Session ended before the file was fully sent")
                        partial = ""
                        segments.append(event)
                        print(f"Final: {event['text']}", file=sys.stderr)
                        if kind == "transcript.done":
                            return segments
                    elif kind == "session.expiring":
                        print("Session is approaching its limit; use batch ASR for long recordings.", file=sys.stderr)
                raise RuntimeError("Socket closed without transcript.done")

            async def send():
                nonlocal input_ended
                sent, since_commit = 0, 0
                started = asyncio.get_running_loop().time()
                while chunk := audio.readframes(rate // 10):
                    await ws.send(chunk)  # Raw PCM only; do not send the WAV header.
                    samples = len(chunk) // 2
                    sent += samples
                    since_commit += samples
                    if commit_every and since_commit >= rate * commit_every:
                        await ws.send(json.dumps({"type": "input.commit"}))
                        since_commit = 0
                    # Pace at audio speed, as a microphone would, while receiving in parallel.
                    await asyncio.sleep(max(0, started + sent / rate - asyncio.get_running_loop().time()))
                input_ended = True
                await ws.send(json.dumps({"type": "input.done"}))

            receiver = asyncio.create_task(receive())
            sender = asyncio.create_task(send())
            try:
                done, _ = await asyncio.wait({sender, receiver}, return_when=asyncio.FIRST_COMPLETED)
                if receiver in done:
                    return receiver.result()  # Includes early server failures.
                await sender
                return await asyncio.wait_for(receiver, finalize_timeout)
            finally:
                for task in (sender, receiver):
                    task.cancel()
                await asyncio.gather(sender, receiver, return_exceptions=True)


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", help="Mono PCM16 WAV")
    parser.add_argument("--language", default="none")
    parser.add_argument("--mode", choices=["balanced", "high_accuracy"], default="balanced")
    parser.add_argument("--style", choices=["codemix", "native"], default="codemix")
    parser.add_argument("--timestamps", action="store_true")
    parser.add_argument("--commit-strategy", choices=["manual", "vad"], default="manual")
    parser.add_argument("--silence-duration-ms", type=int, default=500)
    parser.add_argument("--commit-every", type=float, default=0, help="Manual commit interval in audio seconds; 0 = finalize at EOF")
    args = parser.parse_args()
    key = os.getenv("CHARIOT_API_KEY")
    if not key:
        parser.error("Set CHARIOT_API_KEY in .env or your environment")
    try:
        events = asyncio.run(transcribe(args.file, key, language=args.language, mode=args.mode,
                                       style=args.style, timestamps=args.timestamps,
                                       commit_strategy=args.commit_strategy, silence_duration_ms=args.silence_duration_ms,
                                       commit_every=args.commit_every))
        print(json.dumps({"text": " ".join(e["text"] for e in events if e["text"]), "segments": events},
                         indent=2, ensure_ascii=False))
    except (ValueError, RuntimeError, wave.Error) as error:
        parser.exit(1, f"{error}\n")
    except (OSError, asyncio.TimeoutError, websockets.WebSocketException) as error:
        parser.exit(1, f"Streaming failed ({type(error).__name__}); no automatic audio replay.\n")
    except KeyboardInterrupt:
        parser.exit(130, "Stopped; the socket has been closed.\n")


if __name__ == "__main__":
    main()
