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

Runnable code for building with [Chariot](https://chariot.in), the voice AI platform built for India: lifelike, streaming text-to-speech in Indian languages and English, served from India for the latency real-time voice needs.

The repo has two kinds of content, matching the two ways developers use Chariot:

- **[Quickstarts](./quickstarts)**: the smallest working program for each API surface. Start here to see the API itself.
- **[Integrations](./integrations)**: Chariot inside the frameworks you already build voice apps with. Each one ships a drop-in service class plus a runnable demo.

**Console and API keys:** [platform.chariot.in](https://platform.chariot.in) · **Site:** [chariot.in](https://chariot.in)

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
| [tts-websocket](./quickstarts/tts-websocket) | `wss:// ... /v1/tts/ws` | The streaming session: feed text in as you get it, read audio out while it generates. The API every real-time integration builds on |

## Integrations

| | Status | What ships |
|---|---|---|
| [Pipecat](./integrations/pipecat) | Available | `ChariotTTSService`, a drop-in `TTSService`, plus a browser voice agent you can talk to and interrupt |
| LiveKit Agents | Planned | TTS plugin for LiveKit's agent framework |

Building against a framework we have not covered? Open an issue, or wire the WebSocket API directly: the [tts-websocket quickstart](./quickstarts/tts-websocket) documents the full protocol.

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

Python 3.10+ throughout.

---

## Contributing

Issues and PRs welcome. See [CONTRIBUTING.md](./CONTRIBUTING.md).

## License

[MIT](./LICENSE)
