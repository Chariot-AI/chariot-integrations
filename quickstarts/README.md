# Quickstarts

The smallest working program for each Chariot API surface. Each folder is self-sufficient; start with its README.

| | API | Use it for |
|---|---|---|
| [tts-http](./tts-http) | `POST /v1/tts` | Offline synthesis: files, batch jobs, notifications |
| [tts-stream](./tts-stream) | `POST /v1/tts/stream` | Full text available up front, audio returned progressively |
| [tts-websocket](./tts-websocket) | `wss:// ... /v1/tts/ws` | Live synthesis: assistants, agents, anything conversational |
| [asr-websocket](./asr-websocket) | `wss:// ... /v1/asr/ws` | Live transcription with manual commits or server VAD |
| [asr-http](./asr-http) | `POST /v1/asr/transcribe` | Short file or URL to a complete transcript (Beta) |
| [asr-batch](./asr-batch) | `POST /v1/asr/batches` | Durable single-file or multi-URL jobs with polling (Beta) |

All authenticate with the `chariotai-api-key` header. TTS examples also take a `voice_id` from `GET https://api.chariot.in/v1/voices`. Keys live at [platform.chariot.in](https://platform.chariot.in).

TTS examples accept `--model` or `CHARIOT_MODEL`. The public API field is `model_type`.
Choose a compatible voice using its `models[].model` entries.

Use HTTP streaming for complete input text, and WebSocket for incremental text.
For connection setup and TTFB measurements, use the [latency tool](../tools/latency).
