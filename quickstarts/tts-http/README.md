# TTS over HTTP

One request in, one WAV out. `POST /v1/tts` is the right tool when nobody is waiting on the audio: files, batch jobs, notifications.

## Setup

```bash
pip install -r requirements.txt
cp .env.sample .env    # add your key and voice id
```

Keys live at [platform.chariot.in](https://platform.chariot.in). List voices with:

```bash
curl -s https://api.chariot.in/v1/voices -H "chariotai-api-key: YOUR_API_KEY"
```

## Run

```bash
python tts.py "Hello from Chariot. Namaste!"
python tts.py "Hello from Chariot." --model chariot-multilingual-v1
```

Writes `hello.wav` to the current directory. The equivalent curl:

```bash
curl -X POST https://api.chariot.in/v1/tts \
  -H "chariotai-api-key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"voice_id": "YOUR_VOICE_ID", "text": "Hello from Chariot. Namaste!", "model_type": "chariot-multilingual-v1"}' \
  --output hello.wav
```

`--model` overrides `CHARIOT_MODEL` (default: `chariot-multilingual-v1`). Choose a voice whose
`models[].model` includes the requested model, then send that value as
`model_type`. See [Models](https://docs.chariot.in/guides/models).

## Streaming audio

Use [HTTP streaming](../tts-stream) when the full text is available and audio
should arrive progressively. Use [WebSocket](../tts-websocket) when text arrives
incrementally, such as from an LLM. Compare first-audio latency with the
[latency tool](../../tools/latency).
