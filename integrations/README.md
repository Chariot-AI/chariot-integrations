# Integrations

Chariot inside the frameworks you already build voice applications with. Each integration ships two things: a drop-in service class you can copy into your project, and a runnable demo proving it in a real pipeline.

| | Status | What ships |
|---|---|---|
| [Pipecat](./pipecat) | Available | `ChariotSTTService` and `ChariotTTSService` plus a browser voice agent you can talk to and interrupt |
| LiveKit Agents | Planned | TTS plugin for LiveKit's agent framework |

Missing your framework? The [tts-websocket quickstart](../quickstarts/tts-websocket) documents the full streaming protocol; most TTS adapters are under two hundred lines on top of it. Open an issue and we will help, or send a PR.
