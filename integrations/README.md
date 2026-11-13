# Integrations

Chariot inside the frameworks you already build voice applications with. Each integration pairs the Chariot services for that framework, installed as a package, with a runnable demo proving them in a real pipeline.

| | Status | What ships |
|---|---|---|
| [Pipecat](./pipecat) | Available | `ChariotSTTService` and `ChariotTTSService` from [`pipecat-chariot`](https://pypi.org/project/pipecat-chariot/), plus a browser voice agent you can talk to and interrupt |
| LiveKit Agents | Planned | STT and TTS plugin for LiveKit's agent framework |

Missing your framework? The [tts-websocket quickstart](../quickstarts/tts-websocket) documents the full streaming protocol; most TTS adapters are under two hundred lines on top of it. Open an issue and we will help, or send a PR.
