# Chariot + Pipecat

Use Chariot's streaming text-to-speech inside a [Pipecat](https://github.com/pipecat-ai/pipecat) pipeline.

Two things live here:

- **`chariot_tts.py`**: `ChariotTTSService`, a drop-in Pipecat `TTSService`. Copy this one file into any Pipecat project.
- **`bot.py`**: a complete browser voice agent using it. Speak, and it answers in a Chariot voice; interrupt it mid-sentence and it stops immediately.

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

Python 3.10+ and a microphone (accessed through the browser).

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
| `OPENAI_API_KEY` | Used for speech-to-text and the LLM in this demo |

## Run

```bash
python bot.py
```

Open **http://localhost:7860**, click **Connect**, allow microphone access, and talk. `Ctrl+C` stops the server. Flags: `--host`, `--port`, and `--voice` to override the voice UUID at startup.

## Using the service in your own pipeline

```python
from chariot_tts import ChariotTTSService

tts = ChariotTTSService(
    api_key="...",       # or CHARIOT_API_KEY in the environment
    voice_id="...",      # or CHARIOT_VOICE_ID
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
- **Errors**: failures surface as Pipecat `ErrorFrame`s rather than hanging the pipeline. An exhausted credit balance is reported as exactly that.
- **Other deployments**: point `ws_url=` at any host serving the Chariot TTS WebSocket protocol.

## What to try

- Interrupt mid-sentence: start speaking while it is talking.
- Switch voices live: restart with `--voice <uuid>` and hear the difference.
- Speak Hinglish: ask it something in mixed Hindi and English.
