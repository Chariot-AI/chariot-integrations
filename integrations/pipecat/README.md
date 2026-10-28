# Chariot + Pipecat

Use Chariot's streaming speech-to-text and text-to-speech inside a [Pipecat](https://github.com/pipecat-ai/pipecat) pipeline.

Three things live here:

- **`chariot_stt.py`**: `ChariotSTTService`, a drop-in streaming Pipecat `STTService`. Copy this one file into any Pipecat project.
- **`chariot_tts.py`**: `ChariotTTSService`, a drop-in Pipecat `TTSService`. Copy this one file into any Pipecat project.
- **`bot.py`**: a complete browser voice agent using it. Speak, and it answers in a Chariot voice; speaking during a reply interrupts playback and synthesis.

## The demo

```
Browser microphone
        v
SmallWebRTCTransport (WebRTC)
        v
Chariot STT ->  OpenAI LLM  ->  Chariot TTS
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
| `OPENAI_API_KEY` | Used for the LLM only in this demo |

## Run

```bash
python bot.py
```

Open **http://localhost:7860**, click **Connect**, allow microphone access, and talk. `Ctrl+C` stops the server. Flags: `--host`, `--port`, `--voice`, and `--model` override startup settings. Missing keys or voice IDs are reported at startup.

## Streaming speech-to-text

```python
from chariot_stt import ChariotSTTService

stt = ChariotSTTService(
    api_key="...",  # or CHARIOT_API_KEY in the environment
    commit_strategy="manual",
    settings=ChariotSTTService.Settings(
        model="chariot-1-asr-realtime",
        language=None,  # automatic detection; or a language code such as "hi"
        mode="balanced",
        style="codemix",
        include_timestamps=True,
    ),
)
```

Place `stt` between `transport.input()` and the user aggregator, as shown below. Configure the user aggregator with `LLMUserAggregatorParams(vad_analyzer=SileroVADAnalyzer())`, as the demo does. Its VAD frames travel upstream to the STT service. The service uses the pipeline's input sample rate; audio must be mono PCM16 at 8000, 16000, 22050, 24000, 32000, 44100, or 48000 Hz.

- **One connection per call**: wait for `session.started`, then stream audio while receiving transcripts concurrently. Interrupting an assistant reply leaves this listening connection open.
- **Manual commits (default)**: Pipecat's `VADUserStoppedSpeakingFrame` sends `input.commit`. The reply becomes a finalized `TranscriptionFrame`. This needs a Pipecat VAD analyzer or another processor emitting those frames.
- **Server VAD**: use `commit_strategy="vad"`. Chariot decides transcript segment boundaries; Pipecat's VAD and turn strategies still decide when the conversational user turn ends and when to interrupt. Server speech events are exposed as callbacks, not injected as a second set of Pipecat VAD frames.
- **Transcripts**: deltas become accumulated `InterimTranscriptionFrame` text. Committed text replaces those partials in a `TranscriptionFrame`; never append both. The original event, including optional word timestamps, is in `frame.result`. Final closing text is only the uncommitted tail.
- **Options**: `balanced` or `high_accuracy`, `codemix` or `native`, and a supported language code or `None`. A `Language` enum also works. These settings are fixed when the socket connects; runtime changes report an error instead of pretending to apply.
- **Lifecycle**: `EndFrame` sends `input.done` and drains the final transcript; `CancelFrame` closes immediately. Connection and fatal server errors end the pipeline. No automatic reconnect/replay is performed because it could lose or duplicate speech. An idle connection uses JSON keepalives rather than generated silence.
- **Timeouts**: `connect_timeout=15`, `finalize_timeout=65` seconds, and `keepalive_interval=15` seconds are configurable. Finalization is bounded for each manual commit and at end of input. Handle `on_session_expiring` to end or replace a call before the public session limit.
- **Metrics**: Pipecat's STT base records transcription timing and audio usage; TTS metrics are described below.

Server VAD constructor options:

| Option | Default | Range |
|---|---|---|
| `silence_duration_ms` | 500 | 100 to 10000 ms |
| `vad_threshold` | 0.5 | 0.05 to 0.95 |
| `min_speech_duration_ms` | 250 | 0 to 5000 ms |
| `prefix_padding_ms` | 300 | 0 to 2000 ms |

Callbacks registered with `@stt.event_handler(...)`: `on_connected(service)`, `on_disconnected(service)`, `on_connection_error(service, message)`, `on_speech_started(service, event)`, `on_speech_stopped(service, event)`, and `on_session_expiring(service, event)`. Speech events are requested in server VAD mode.

The demo reads `CHARIOT_ASR_LANGUAGE`, `CHARIOT_ASR_MODE`, `CHARIOT_ASR_STYLE`, and `CHARIOT_ASR_COMMIT_STRATEGY`; defaults are shown in `.env.sample`. File and durable batch transcription are separate HTTP workflows: see [asr-http](../../quickstarts/asr-http) and [asr-batch](../../quickstarts/asr-batch).

## Using the services in your own pipeline

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
    stt,                 # ChariotSTTService configured above
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

The tests use a local WebSocket server and real Pipecat pipelines. They need no API keys and do not call production. They cover STT manual/server VAD commits, interim and final text, timestamps, LLM context delivery, bounded finalization, invalid credentials, and TTS streaming and interruption. Demo tests check the UI, WebRTC signaling, and shutdown with a stand-in bot. The suite has been verified on Pipecat 1.7.0 and 1.12.0.
