# TTS over streaming HTTP

```bash
pip install -r requirements.txt
cp .env.sample .env    # add your API key, voice id, and model
python streaming.py "Hello from Chariot. Namaste!" --model chariot-multilingual-v1
```

`POST /v1/tts/stream` accepts the full text and streams audio back as it is
generated. This example prints each received chunk and saves `out.wav` after
the stream finishes. It does not play audio in real time.

The response is raw signed 16-bit little-endian mono PCM, not a WAV file. Its
`Content-Type` declares the sample rate (`audio/L16; rate=44100; channels=1`).
The example adds a WAV header when saving it. An equivalent raw-audio request:

```bash
curl --no-buffer https://api.chariot.in/v1/tts/stream \
  -H "chariotai-api-key: $CHARIOT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"voice_id":"YOUR_VOICE_ID","text":"Hello from Chariot.","model_type":"chariot-multilingual-v1"}' \
  --output out.pcm
```

`--model` overrides `CHARIOT_MODEL`, which defaults to `chariot-multilingual-v1`. Select a
voice from `GET /v1/voices` whose `models[].model` includes the model you pass
as `model_type`. See the [model guide](https://docs.chariot.in/guides/models).
An unsupported combination is an error, not a fallback to a different model.

Use [WebSocket](../tts-websocket) when text arrives incrementally. Use
[completed HTTP synthesis](../tts-http) when you want a complete WAV response.
To measure connection setup and first-audio latency, run the
[latency tool](../../tools/latency).
