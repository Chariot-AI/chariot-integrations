# Quickstarts

The smallest working program for each Chariot API surface. Each folder is self-sufficient; start with its README.

| | API | Use it for |
|---|---|---|
| [tts-http](./tts-http) | `POST /v1/tts` | Offline synthesis: files, batch jobs, notifications |
| [tts-websocket](./tts-websocket) | `wss:// ... /v1/tts/ws` | Live synthesis: assistants, agents, anything conversational |

Both authenticate with the `chariotai-api-key` header and take a `voice_id` from `GET https://api.chariot.in/v1/voices`. Keys live at [platform.chariot.in](https://platform.chariot.in).

Rule of thumb: if a human is waiting while the speech is made, use the WebSocket.
