# Chariot + Pipecat

Use Chariot's streaming speech-to-text and text-to-speech inside a [Pipecat](https://github.com/pipecat-ai/pipecat) pipeline.

The services come from the [`pipecat-chariot`](https://pypi.org/project/pipecat-chariot/) package:

- **`ChariotSTTService`**: streaming speech-to-text for English and Indian languages, including code-mixed speech.
- **`ChariotTTSService`**: streaming text-to-speech on one connection per call; an interruption cancels just the current reply.

This folder holds **`bot.py`**, a complete browser voice agent built with them. Speak, and it answers in a Chariot voice; speaking during a reply interrupts it.

## Install the package

In your own Pipecat project:

```bash
uv add pipecat-chariot
```

or `pip install pipecat-chariot`. Configuration, behaviour and every option are documented in the [package README](https://github.com/Chariot-AI/pipecat-chariot#readme).

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

Silero VAD decides when you have finished speaking, and Chariot finalizes the transcript right then. When you speak while the agent is talking, Pipecat interrupts the reply and the Chariot service cancels it on the server. No custom interruption code.

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
| `CHARIOT_VOICE_ID` | Optional. The voice that answers, from `GET https://api.chariot.in/v1/voices`; unset uses a Chariot stock voice |
| `CHARIOT_MODEL` | Optional. `chariot-multilingual-v1` (the default) or `chariot-v0` |
| `CHARIOT_ASR_LANGUAGE` | Optional. A language code such as `hi`, or `none` to detect it |
| `CHARIOT_ASR_MODE` | `balanced` (default) or `high_accuracy` |
| `CHARIOT_ASR_STYLE` | `codemix` (default) or `native` |
| `CHARIOT_ASR_COMMIT_STRATEGY` | `manual` (default, Pipecat's VAD ends each utterance) or `vad` (Chariot's) |
| `OPENAI_API_KEY` | Used for the LLM only in this demo |

## Run

```bash
python bot.py
```

Open **http://localhost:7860**, click **Connect**, allow microphone access, and talk. `Ctrl+C` stops the server. Flags: `--host`, `--port`, `--voice`, and `--model` override startup settings. Missing keys are reported at startup.

## Using the services in your own pipeline

```python
from pipecat_chariot import ChariotSTTService, ChariotTTSService

stt = ChariotSTTService(
    api_key="...",
    settings=ChariotSTTService.Settings(language="hi"),  # omit to detect the language
)

tts = ChariotTTSService(
    api_key="...",
    voice_id="...",  # optional; a Chariot stock voice by default
)

pipeline = Pipeline([
    transport.input(),
    stt,
    user_aggregator,     # with LLMUserAggregatorParams(vad_analyzer=SileroVADAnalyzer())
    llm,                 # any Pipecat LLM service
    tts,
    transport.output(),
    assistant_aggregator,
])
```

File and batch transcription are separate HTTP workflows: see [asr-http](../../quickstarts/asr-http) and [asr-batch](../../quickstarts/asr-batch).

## What to try

- Interrupt mid-sentence: start speaking while it is talking.
- Switch voices live: restart with `--voice <uuid>` and hear the difference.
- Speak Hinglish: ask it something in mixed Hindi and English.

## Check the demo

```bash
python -m unittest discover -s tests -v
```

The tests check the demo UI, WebRTC signaling, startup validation and shutdown with a stand-in bot. They need no API keys and do not call production. The Chariot services themselves are tested in the [`pipecat-chariot`](https://github.com/Chariot-AI/pipecat-chariot) repository.
