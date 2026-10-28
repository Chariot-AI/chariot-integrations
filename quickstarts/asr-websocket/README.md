# Streaming speech-to-text

Send audio to `wss://api.chariot.in/v1/asr/ws` and receive partial and finalized text while the connection stays open. This example streams a WAV at audio speed, like a microphone, and receives messages concurrently.

## Run

Python 3.10+:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.sample .env  # add your Chariot API key
python streaming.py recording.wav --timestamps
python streaming.py recording.wav --commit-every 5
python streaming.py recording.wav --commit-strategy vad --silence-duration-ms 500
python streaming.py recording.wav --language hi --style native --mode high_accuracy
```

Input must be a mono, signed 16-bit PCM WAV. Supported sample rates are 8000, 16000, 22050, 24000, 32000, 44100, and 48000 Hz. Convert another format first, for example:

```bash
ffmpeg -i recording.mp3 -ac 1 -ar 16000 -c:a pcm_s16le recording.wav
```

For other file formats or long recordings, use the [file](../asr-http) or [batch](../asr-batch) examples instead. For a browser microphone demo, see [Pipecat](../../integrations/pipecat).

## Protocol

1. Authenticate with the `chariotai-api-key` header and wait for `session.started`.
2. Send raw PCM bytes as binary messages. The WAV header is not sent.
3. Receive `transcript.delta` messages and append their text within the current segment.
4. With manual commits, `input.commit` finalizes the current segment and keeps the socket open. `--commit-every` demonstrates periodic commits; a voice agent normally commits at a speech boundary.
5. With `commit_strategy=vad`, the server detects speech boundaries and emits `transcript.committed`. `silence_duration_ms` defaults to 500 and accepts 100 through 10000 ms. Do not combine server VAD with periodic manual commits.
6. Send `input.done` at the end. Wait for `transcript.done` before closing. Its text is only the remaining uncommitted tail, so keep earlier committed segments too.

Committed text replaces the partial text for that segment. The script prints partials and finals to stderr, then outputs JSON with assembled `text` and the original committed/done `segments`. It does not add partials to the final transcript or duplicate the closing tail. With `--timestamps`, segment events carry word timings where available, in seconds from session start.

The public model is `chariot-1-asr-realtime`. Streaming supports `balanced` and `high_accuracy`; `--language none` selects automatic language detection and `--style` selects `codemix` or `native`. See the [WebSocket guide](https://docs.chariot.in/guides/speech-to-text/websocket) for all options, session limits, and events.

An idle live client can send `{"type":"keepalive"}` periodically. This file example sends audio continuously until EOF and needs no idle heartbeat. It bounds connection setup and finalization waits, closes on cancellation, and does not replay audio automatically after connection failure.

## Test

```bash
python -m unittest discover -s tests -v
```

Tests use a local WebSocket server to verify raw PCM, simultaneous receiving, manual commits, final-tail handling, and premature connection closure.
