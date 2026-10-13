# Quickstarts

The smallest working program for each Chariot API surface. Each folder is self-sufficient; start with its README.

| | API | Use it for |
|---|---|---|
| [tts-http](./tts-http) | `POST /v1/tts` | Offline synthesis: files, batch jobs, notifications |
| [tts-stream](./tts-stream) | `POST /v1/tts/stream` | Full text available up front, audio returned progressively |
| [tts-websocket](./tts-websocket) | `wss:// ... /v1/tts/ws` | Live synthesis: assistants, agents, anything conversational |

All authenticate with the `chariotai-api-key` header and take a `voice_id` from `GET https://api.chariot.in/v1/voices`. Keys live at [platform.chariot.in](https://platform.chariot.in).

All accept `--model` or `CHARIOT_MODEL`. The public API field is `model_type`.
Choose a compatible voice using its `models[].model` entries.

Use HTTP streaming for complete input text, and WebSocket for incremental text.
For connection setup and TTFB measurements, use the [latency tool](../tools/latency).
