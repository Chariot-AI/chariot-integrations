# Measure streaming TTS latency

```bash
git clone https://github.com/Chariot-AI/chariot-integrations.git
cd chariot-integrations/tools/latency
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.sample .env    # set your API key, voice id, and model
python latency.py --model chariot-multilingual-v1 --json results.json
```

Python 3.10+. API keys come from [platform.chariot.in](https://platform.chariot.in).
Choose a voice from `GET /v1/voices` whose `models[].model` includes your chosen
model. The public field is `model_type`: JSON for HTTP, a query parameter for
WebSocket. `--model` overrides `CHARIOT_MODEL`; the default is `chariot-multilingual-v1`.
Use `--model chariot-v0` to select the earlier model when supported by your voice.
The API validates model availability, speeds, and input limits; the tool never
substitutes another model. See [Models](https://docs.chariot.in/guides/models).

Both streaming endpoints are included by default: `http` rows measure
`POST /v1/tts/stream`, and `websocket` rows measure `/v1/tts/ws`. The selected
endpoints are printed before the trials.

By default, the tool makes **20 sequential synthesis requests**: 5 fresh and
5 on a shared connection for each transport. Each shared-connection group has
one `first` request and four `reused` requests. Normal API credits apply. There
are no hidden warm-ups, retries, parallel requests, or artificial text delays.
It prints each measured trial and connection timing, followed by min, p50, p90,
p99, and max TTFB. Failed and skipped requests are counted separately. Five samples
are a quick check, not a reliable estimate of rare tail latency. With fewer
than 100 successful samples, nearest-rank p99 is simply the observed maximum.

## Choose what to measure

```bash
# HTTP streaming, established connection after the first request
python latency.py --transport http --connection reused --runs 5

# WebSocket, new connection for every generation
python latency.py --transport websocket --connection fresh --runs 5

# Both transports and modes, custom input, optional audio and raw results
python latency.py --transport both --connection both --runs 5 \
  --model chariot-multilingual-v1 --text "नमस्ते, आपका दिन कैसा चल रहा है?" \
  --save-audio audio --json results.json
```

| Option | Default | Meaning |
|---|---|---|
| `--transport` | `both` | `http`, `websocket`, or `both` |
| `--connection` | `both` | `fresh`, `reused`, or `both` |
| `--runs` | `5` | Requests per transport/mode, including the first reused-mode request |
| `--model` | `CHARIOT_MODEL` or `chariot-multilingual-v1` | Sent explicitly as `model_type` |
| `--voice-id` | `CHARIOT_VOICE_ID` | Voice UUID |
| `--text` | Short English test sentence | Same complete text for every request; surrounding whitespace trimmed |
| `--speed` | `1.0` | Must be supported by the voice/model |
| `--optimize-streaming-latency` | `0` | Public quality/latency setting, 0 through 4 |
| `--timeout` | `60` | Seconds per TCP attempt / HTTP socket operation; WebSocket open or generation deadline |
| `--json` | none | Write configuration, raw connection/trial records, and summaries |
| `--save-audio` | none | Directory for a WAV per successful request |

## Exactly what is timed

All elapsed times use the monotonic `perf_counter` clock and are milliseconds.

| Field | Boundary |
|---|---|
| `dns_ms` | Local hostname resolution, including any OS resolver cache |
| `tcp_connect_ms` | TCP connection attempts after DNS; a rough network round-trip estimate only when one address succeeds |
| `tls_ms` | HTTP TLS handshake, including certificate verification |
| `tls_and_ws_upgrade_ms` | WebSocket TLS handshake plus HTTP upgrade and client handshake processing |
| `setup_ms` | DNS through completed transport setup; certificate-store initialization is excluded |
| `ttfb_ms` | Immediately before submitting text to the first nonempty audio body data / binary WebSocket message received |
| `setup_plus_ttfb_ms` | Sum of measured setup and TTFB for a new connection; TTFB alone on a reused connection |
| `ping_rtt_ms` | WebSocket ping/pong after the connection's final measured generation |

TTFB here means **first audio**, not HTTP headers, a WebSocket `audio.start`
event, an empty frame, or an error. For WebSocket it includes sending the full
`input.text` and the immediately following `input.flush`. It is not measured
from the first token of a simulated LLM response. Both transports receive raw
signed 16-bit little-endian mono PCM. HTTP reads use `read1` to avoid waiting for
a large application buffer to fill. Sample rate comes from the HTTP response
header or WebSocket `audio.start`, and is saved with each trial.

The sum `setup_plus_ttfb_ms` excludes local work between setup and submission;
it is not a timer for the entire script or audio playback. TTFB includes remote
processing, any queuing, and network travel. Neither TCP connect nor ping/pong
isolates pure network transit: both can include endpoint scheduling and protocol
work. Multiple TCP address attempts include failed-attempt delays and are shown
as `address_attempts`. No network estimate is subtracted to claim model latency.
Reused requests reference their original connection's setup/network measurements;
they don't open another connection to obtain a fresh probe.

## Connection lifecycle

- **Fresh:** a new TCP/TLS connection for each HTTP request or WebSocket
  generation. Fresh transport does not mean a cold model, DNS resolver, or
  backend cache.
- **Reused HTTP:** fully consume each response, then send the next request on
  the same HTTP/1.1 keep-alive connection.
- **Reused WebSocket:** send `input.text` and `input.flush`, consume audio through
  `audio.done`, then send the next text on the same session. Send `input.done`
  only when finished. Model and voice stay fixed for that session.

The first generation in reused mode is reported as `first`, separately from
the subsequent `reused` samples. With `--runs 1` there are no reused samples.
If a reused connection or generation fails, the remainder of that sequence is
marked skipped. The tool does not reconnect and count it as warm.

WebSocket ping runs after the last measured generation, so it cannot pre-warm
the first trial. A failed ping is reported independently of synthesis results.
The public WebSocket handshake can complete before application authentication
and upstream session setup finish; first-generation TTFB includes that remaining
work. A reused session measures a different application lifecycle from repeated
HTTP requests, even with identical text and voice.

Run order is HTTP fresh, HTTP reused, WebSocket fresh, WebSocket reused. Server
load can change during a run; these groups aren't simultaneous comparisons.
The tool connects directly to `api.chariot.in` with certificate verification.
Environment proxy settings are not used. HTTP is HTTP/1.1. Record the location
you run from when sharing results; the tool cannot infer your client region.

## Output and failures

The JSON includes the exact text, requested model/voice, settings, endpoints,
platform, UTC start time, raw trials, connection IDs, and sample counts. It
does not store the API key. Percentiles use nearest rank over successful
generations only, without removing outliers. A stream that errors after its
first audio is a failed generation, excluded from successful latency summaries.
HTTP completion means a well-framed response ending normally; raw PCM has no
application-level completion marker to independently detect server truncation.

Optional WAV writes happen after the full response is consumed. They don't
enter TTFB, but can lengthen the gap before the next request. Filenames and JSON
paths are overwritten on reruns. Exit status is nonzero if any generation fails
or is skipped. The tool measures latency, not throughput, RTF, or underruns.

Run the local protocol tests without credentials or API calls:

```bash
python -m unittest discover -s tests -v
```
