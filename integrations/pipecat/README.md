# Chariot + Pipecat

Use Chariot's streaming text-to-speech inside a [Pipecat](https://github.com/pipecat-ai/pipecat) pipeline.

Two things live here:

- **`chariot_tts.py`**: `ChariotTTSService`, a drop-in Pipecat `TTSService`. Copy this one file into any Pipecat project.
- **`bot.py`**: a complete browser voice agent using it. Speak, and it answers in a Chariot voice; speaking during a reply interrupts playback and synthesis.

## The demo

```
Browser microphone
        v
SmallWebRTCTransport (WebRTC)
        v
OpenAI STT  ->  OpenAI LLM  ->  Chariot TTS
                                     v
                        SmallWebRTCTransport (WebRTC)
                                     v
                          Browser speaker output
```

Silero VAD watches for you speaking while the agent is talking. When that happens, Pipecat cancels the in-flight synthesis; `ChariotTTSService` opens one WebSocket per utterance, so cancelling the generator tears down the socket and the server stops generating audio nobody will hear. No custom interruption code.

## Setup

Python 3.11+ and a microphone (accessed through the browser).

```bash
git clone https://github.com/Chariot-AI/chariot-integrations.git
cd chariot-integrations/integrations/pipecat
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.sample .env    # add your keys
```

| Variable | Description |
|---|---|
| `CHARIOT_API_KEY` | Your Chariot API key, from [platform.chariot.in](https://platform.chariot.in) |
| `CHARIOT_VOICE_ID` | The voice that answers, from `GET https://api.chariot.in/v1/voices` |
| `CHARIOT_MODEL` | Defaults to `chariot-multilingual-v1`; choose a voice whose `models[].model` includes this model |
| `OPENAI_API_KEY` | Used for speech-to-text and the LLM in this demo |

## Run

```bash
python bot.py
```

Open **http://localhost:7860**, click **Connect**, allow microphone access, and talk. `Ctrl+C` stops the server. Flags: `--host`, `--port`, `--voice`, and `--model` override startup settings. Missing keys or voice IDs are reported at startup.

## Using the service in your own pipeline

```python
from chariot_tts import ChariotTTSService

tts = ChariotTTSService(
    api_key="...",       # or CHARIOT_API_KEY in the environment
    voice_id="...",      # or CHARIOT_VOICE_ID
    model="chariot-multilingual-v1",  # or CHARIOT_MODEL; this is the default
    sample_rate=44100,
)

pipeline = Pipeline([
    transport.input(),
    stt,                 # any Pipecat STT service
    user_aggregator,
    llm,                 # any Pipecat LLM service
    tts,                 # Chariot speaks the replies
    transport.output(),
    assistant_aggregator,
])
```

Behaviour worth knowing:

- **Streaming**: audio frames are yielded while the server is still generating. Output is 16-bit mono PCM at 44.1 kHz, and every frame carries the rate the server declares, so a change on the server side cannot mis-rate your audio.
- **Interruptions**: one WebSocket per utterance; generator cancellation closes it. Nothing to configure.
- **Settings**: `settings=ChariotTTSService.Settings(voice=..., model=...)` takes precedence over constructor arguments and environment variables. Pipecat settings updates apply to the next utterance. Chariot detects language from the text.
- **Errors**: server errors (including `audio.done.error`), premature closes, empty results, and receive timeouts surface as Pipecat `ErrorFrame`s. An exhausted credit balance is reported as exactly that. `receive_timeout=30.0` bounds connection setup and each wait for a WebSocket message.
- **Metrics**: the demo enables Pipecat TTFB and character-usage metrics. TTFB measures synthesis start through the first complete PCM sample, including WebSocket connection setup. It is not a separate measurement of network latency; use the [latency tool](../../tools/latency) for transport measurements.
- **Other deployments**: point `ws_url=` at any host serving the Chariot TTS WebSocket protocol.

## What to try

- Interrupt mid-sentence: start speaking while it is talking.
- Switch voices live: restart with `--voice <uuid>` and hear the difference.
- Speak Hinglish: ask it something in mixed Hindi and English.

## Check the integration

```bash
python -m unittest discover -s tests -v
```

The tests use a local WebSocket server and real Pipecat pipelines. They need no API keys and do not call production. They cover PCM streaming, model selection, server failures, stalled streams, and interruption followed by a new utterance. Demo tests check the UI, WebRTC signaling, and shutdown with a stand-in bot. The suite has been verified on Pipecat 1.7.0 and 1.12.0.
