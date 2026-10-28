# File transcription (Beta)

Transcribe one recording with `POST /v1/asr/transcribe`. Upload a file as multipart form data, or provide a public/signed URL. The HTTP request returns one complete JSON result, not a stream.

## Run

Python 3.10+:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.sample .env  # add your Chariot API key
python transcribe.py --file recording.wav --timestamps
python transcribe.py --url 'https://example.com/recording.mp3' --language hi --style native
```

Get a key at [platform.chariot.in](https://platform.chariot.in). No voice ID or LLM key is needed for transcription.

The request sends `model_type=chariot-1-asr-realtime`, `mode=high_accuracy`, and exactly one of `input_audio_file` or `input_audio_url`. `--language none` selects automatic language detection. `--style` selects `codemix` or `native`; `--timestamps` requests word boundaries.

The script prints the complete API response, including `text`, `words`, `request_id`, and `duration`. Word timestamps are seconds from the start of the recording; do not assume word timings are available for every result.

## Choosing the API

This synchronous endpoint is for short recordings. See the [ASR documentation](https://docs.chariot.in/guides/speech-to-text/overview) for current formats and limits. For longer recordings or work that must survive your client disconnecting, use the [batch quickstart](../asr-batch). For live audio, use the [WebSocket quickstart](../asr-websocket).

The client waits up to 300 seconds of network inactivity. A timeout does not prove the server stopped processing; check your transcription history before retrying. This example does not automatically retry a billable submission.

## Test

```bash
python -m unittest discover -s tests -v
```

Tests use a mock HTTP transport. They verify multipart uploads, URL fields, options, and server failures without an API key.
