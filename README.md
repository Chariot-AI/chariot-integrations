<p align="center">
  <img src="assets/chariot-logo.png" alt="Chariot" width="400">
</p>

<p align="center">
  <a href="https://x.com/Chariot_IN">
    <img src="https://img.shields.io/badge/Follow-%40Chariot__IN-000000?logo=x&logoColor=white" alt="X">
  </a>
  <a href="https://www.linkedin.com/company/chariot-in/">
    <img src="https://img.shields.io/badge/LinkedIn-Chariot-0A66C2?logo=linkedin&logoColor=white" alt="LinkedIn">
  </a>
  <a href="https://www.instagram.com/chariot_in/">
    <img src="https://img.shields.io/badge/Instagram-chariot__in-E4405F?logo=instagram&logoColor=white" alt="Instagram">
  </a>
  <a href="https://facebook.com/chariot.in">
    <img src="https://img.shields.io/badge/Facebook-chariot.in-1877F2?logo=facebook&logoColor=white" alt="Facebook">
  </a>
</p>

# Chariot Integrations

Runnable code for building with [Chariot](https://chariot.in), the voice AI platform built for India: streaming speech-to-text and lifelike text-to-speech in Indian languages and English, served from India for the latency real-time voice needs.

The repo includes:

- **[Quickstarts](./quickstarts)**: the smallest working program for each API surface. Start here to see the API itself.
- **[Integrations](./integrations)**: Chariot inside the frameworks you already build voice apps with. Each one ships a drop-in service class plus a runnable demo.
- **[Latency tool](./tools/latency)**: measure HTTP streaming and WebSocket first-audio latency, with model selection and separate fresh/reused connection results.

**API docs:** [docs.chariot.in](https://docs.chariot.in/api-reference/introduction) · **Console and API keys:** [platform.chariot.in](https://platform.chariot.in) · **Site:** [chariot.in](https://chariot.in)

---

## Thirty seconds to audio

```bash
curl -X POST https://api.chariot.in/v1/tts \
  -H "chariotai-api-key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"voice_id": "YOUR_VOICE_ID", "text": "Hello from Chariot. Namaste!"}' \
  --output hello.wav
```

`YOUR_API_KEY` comes from [platform.chariot.in](https://platform.chariot.in); `YOUR_VOICE_ID` is any voice from `GET https://api.chariot.in/v1/voices`.

---

## Quickstarts

| | API | What you learn |
|---|---|---|
| [tts-http](./quickstarts/tts-http) | `POST /v1/tts` | One request in, one WAV out. The right tool for files, batch jobs, notifications |
| [tts-stream](./quickstarts/tts-stream) | `POST /v1/tts/stream` | Send full text and receive audio progressively over HTTP |
| [tts-websocket](./quickstarts/tts-websocket) | `wss:// ... /v1/tts/ws` | The streaming session: feed text in as you get it, read audio out while it generates. The API every real-time integration builds on |
| [asr-websocket](./quickstarts/asr-websocket) | `wss:// ... /v1/asr/ws` | Live transcription with manual commits or server VAD |
| [asr-http](./quickstarts/asr-http) | `POST /v1/asr/transcribe` | Short file or URL to a complete transcript (Beta) |
| [asr-batch](./quickstarts/asr-batch) | `POST /v1/asr/batches` | Durable single-file or multi-URL jobs with polling (Beta) |

## Integrations

| | Status | What ships |
|---|---|---|
| [Pipecat](./integrations/pipecat) | Available | `ChariotSTTService` and `ChariotTTSService` plus a browser voice agent you can talk to and interrupt |
| LiveKit Agents | Planned | TTS plugin for LiveKit's agent framework |

Building against a framework we have not covered? Open an issue, or wire the WebSocket API directly: the [tts-websocket quickstart](./quickstarts/tts-websocket) documents the full protocol.

## Measure API latency

The [latency tool](./tools/latency) reports connection setup, TCP connect timing,
WebSocket ping RTT, and time to first audio for both streaming transports.
Each trial is sequential. Fresh connections and requests reusing a connection
have separate summaries, with raw JSON available for inspection.

```bash
cd tools/latency
pip install -r requirements.txt
cp .env.sample .env
python latency.py --model chariot-multilingual-v1 --json results.json
```

Select a voice whose `models[].model` includes your chosen model. All TTS
quickstarts also support `--model`; they send the public `model_type` field.
See the [model guide](https://docs.chariot.in/guides/models).

---

## Running the examples

Every example folder is self-sufficient: its own README, its own `requirements.txt`, its own `.env.sample` listing every variable it reads.

```bash
git clone https://github.com/Chariot-AI/chariot-integrations.git
cd chariot-integrations/quickstarts/tts-http
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.sample .env   # add your key and voice id
python tts.py "Hello from Chariot."
```

Quickstarts and the latency tool require Python 3.10+. The Pipecat integration requires Python 3.11+.

---

## Contributing

Issues and PRs welcome. See [CONTRIBUTING.md](./CONTRIBUTING.md).

## License

[MIT](./LICENSE)
