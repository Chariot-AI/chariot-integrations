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
```

Writes `hello.wav` to the current directory. The equivalent curl:

```bash
curl -X POST https://api.chariot.in/v1/tts \
  -H "chariotai-api-key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"voice_id": "YOUR_VOICE_ID", "text": "Hello from Chariot. Namaste!"}' \
  --output hello.wav
```

## When to use the WebSocket instead

If a person is listening while the speech is made (an assistant, an agent, a reader), use the [tts-websocket quickstart](../tts-websocket): audio starts streaming back before generation finishes.
