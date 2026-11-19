# Chariot + LiveKit Agents

Use Chariot's streaming speech-to-text and text-to-speech inside a [LiveKit Agents](https://github.com/livekit/agents) voice agent.

The STT and TTS come from the [`livekit-plugins-chariot`](https://pypi.org/project/livekit-plugins-chariot/) package:

- **`chariot.STT()`**: streaming speech-to-text for English and Indian languages, including code-mixed speech. The final transcript arrives as soon as LiveKit ends the user's turn.
- **`chariot.TTS()`**: streaming text-to-speech that starts speaking while the LLM is still writing, on one connection kept open across replies; an interruption cancels just the current reply.

This folder holds **`agent.py`**, a complete voice agent built with them. Speak, and it answers in a Chariot voice; speaking during a reply interrupts it.

## Install the package

In your own LiveKit Agents project:

```bash
uv add livekit-plugins-chariot
```

or `pip install livekit-plugins-chariot`. Every option is documented in the [LiveKit Agents guide](https://docs.chariot.in/guides/integrations/livekit). The plugin is also proposed for inclusion in LiveKit Agents in [livekit/agents#8560](https://github.com/livekit/agents/pull/8560).

## The demo

```
Microphone
    v
Chariot STT  ->  OpenAI LLM  ->  Chariot TTS
                                     v
                                  Speakers
```

Silero VAD decides when you have finished speaking, and Chariot finalizes the transcript right then. When you speak while the agent is talking, LiveKit interrupts the reply and the Chariot plugin cancels it on the server. No custom interruption code.

## Setup

Python 3.10+ and a microphone.

```bash
git clone https://github.com/Chariot-AI/chariot-integrations.git
cd chariot-integrations/integrations/livekit
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.sample .env    # add your keys
```

On Linux, console mode also needs PortAudio: `sudo apt install libportaudio2`. macOS and Windows include it.

| Variable | Description |
|---|---|
| `CHARIOT_API_KEY` | Your Chariot API key, from [platform.chariot.in](https://platform.chariot.in) |
| `CHARIOT_VOICE_ID` | Optional. The voice that answers, from `GET https://api.chariot.in/v1/voices`; unset uses the default voice |
| `CHARIOT_MODEL` | Optional. `chariot-multilingual-v1` (the default) or `chariot-v0` |
| `CHARIOT_ASR_LANGUAGE` | Optional. A language code such as `hi`, or `none` to detect it |
| `CHARIOT_ASR_MODE` | `balanced` (default) or `high_accuracy` |
| `CHARIOT_ASR_STYLE` | `codemix` (default) or `native` |
| `CHARIOT_ASR_COMMIT_STRATEGY` | `manual` (default, LiveKit's turn detection ends each utterance) or `vad` (Chariot's) |
| `OPENAI_API_KEY` | Used for the LLM only in this demo |
| `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` | Only for `dev` mode: the LiveKit server the agent joins |

## Run

```bash
python agent.py console
```

Console mode talks through your terminal's microphone and speakers, with no LiveKit server. `Ctrl+C` stops it. Each turn logs its latency: end-of-turn delay, STT, LLM and TTS. Missing keys are reported at startup.

To run the agent in LiveKit rooms instead, set the `LIVEKIT_*` variables and run `python agent.py dev`, then connect a frontend as described in the [LiveKit Agents quickstart](https://docs.livekit.io/agents/start/voice-ai/).

## Using the plugin in your own agent

```python
from livekit.agents import AgentSession
from livekit.plugins import chariot, openai, silero

session = AgentSession(
    vad=silero.VAD.load(),
    stt=chariot.STT(language="hi"),  # omit the language to detect it
    llm=openai.LLM(),                # any LiveKit LLM plugin
    tts=chariot.TTS(),               # the default voice, or voice="..."
)
```

Both read `CHARIOT_API_KEY` from the environment, or take `api_key=`. Recorded audio goes through `stt.recognize()`; for file and batch transcription outside an agent, see [asr-http](../../quickstarts/asr-http) and [asr-batch](../../quickstarts/asr-batch).

## What to try

- Interrupt mid-sentence: start speaking while it is talking.
- Switch voices: set `CHARIOT_VOICE_ID` and restart to hear the difference.
- Speak Hinglish: ask it something in mixed Hindi and English.

## Check the demo

```bash
python -m unittest discover -s tests -v
```

The tests check that the STT and TTS settings come from `.env` and that the agent refuses to start without keys. They need no API keys and do not call production. The plugin itself is tested in [livekit/agents#8560](https://github.com/livekit/agents/pull/8560).
