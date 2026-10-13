# TTS over WebSocket

The streaming session every real-time integration builds on: feed text in as you get it, read audio out while the server is still generating. You can keep sending text while audio for earlier text is still playing, which is exactly the shape of an LLM-driven voice agent.

## The protocol

Connect to:

```
wss://api.chariot.in/v1/tts/ws?voice_id=<uuid>&response_format=pcm&model_type=chariot-multilingual-v1
```

with the `chariotai-api-key` header, then exchange JSON control messages and binary audio frames.

**You send:**

| Message | Meaning |
|---|---|
| `{"type": "input.text", "text": "..."}` | Append text to the session, as much or as little as you have |
| `{"type": "input.flush"}` | Synthesize everything buffered so far, right now |
| `{"type": "input.done"}` | No more text is coming; finish and close |

**You receive:**

| Message | Meaning |
|---|---|
| binary frame | Raw audio: 16-bit mono PCM |
| `{"type": "audio.start", "sample_rate": 44100}` | A generation segment is starting; carries the true sample rate |
| `{"type": "audio.done"}` | That segment finished |
| `{"type": "session.done"}` | Everything is done; the server is closing |
| `{"type": "error", "message": "..."}` | Something went wrong |

Generation is flush-driven: the server buffers `input.text` until you send `input.flush` or `input.done`, then synthesizes everything buffered as one piece. Segmentation is entirely under your control: flush at phrase boundaries for the lowest latency, or send everything and finish with `input.done` for a single continuous generation.

## Setup

```bash
pip install -r requirements.txt
cp .env.sample .env    # add your key and voice id
```

## Run

Full text at once, one continuous generation at `input.done`:

```bash
python streaming.py "Hello. How are you today? I hope your day is going well."
python streaming.py "Hello from Chariot." --model chariot-multilingual-v1
```

Agent mode: the text is drip-fed in small fragments the way an LLM emits tokens, with a flush after each, so you can watch audio arrive progressively:

```bash
python streaming.py "Hello. How are you today? I hope your day is going well." --stream
```

Both write `out.wav` and print every control event as it arrives, so you can watch the session happen.

`--model` overrides `CHARIOT_MODEL` (default: `chariot-multilingual-v1`). Select a voice whose
`models[].model` includes the chosen model. The connection sends it as
`model_type`; it stays fixed for the session. Open another connection to change
models. See [Models](https://docs.chariot.in/guides/models).

Use the [latency tool](../../tools/latency) to measure first audio on fresh and
reused connections. The quickstart's `--stream` mode includes a deliberate
50 ms text-pacing delay, so it is an integration demonstration rather than a
latency measurement.
