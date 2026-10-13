"""Sequential first-audio measurements against Chariot's public streaming APIs."""

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import http.client
from importlib.metadata import version
import json
import math
import os
from pathlib import Path
import platform
import re
import socket
import ssl
import sys
from time import perf_counter
from urllib.parse import urlencode
import wave

from dotenv import load_dotenv
from websockets.sync.client import connect

HOST = "api.chariot.in"
DEFAULT_TEXT = "Hello from Chariot. This is a streaming speech latency test."


def milliseconds(start):
    return (perf_counter() - start) * 1000


@dataclass
class ConnectionTiming:
    id: str
    dns_ms: float | None = None
    tcp_connect_ms: float | None = None
    setup_ms: float | None = None
    tls_ms: float | None = None
    tls_and_ws_upgrade_ms: float | None = None
    peer_ip: str | None = None
    address_attempts: int = 0
    ping_rtt_ms: float | None = None
    ping_error: str | None = None


def open_tcp(host, port, timeout, timing):
    """Resolve once, then expose the actual TCP connection's setup time."""
    start = perf_counter()
    addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    timing.dns_ms = milliseconds(start)
    start = perf_counter()
    last_error = OSError("No addresses returned by DNS")
    for family, kind, protocol, _, address in addresses:
        timing.address_attempts += 1
        sock = socket.socket(family, kind, protocol)
        try:
            sock.settimeout(timeout)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.connect(address)
            timing.tcp_connect_ms = milliseconds(start)
            timing.peer_ip = sock.getpeername()[0]
            return sock
        except OSError as exc:
            last_error = exc
            sock.close()
    raise last_error


class HTTPStream:
    def __init__(self, key, timeout, host=HOST, port=443, secure=True):
        self.key, self.timeout = key, timeout
        self.host, self.port, self.secure = host, port, secure
        self.connection = None

    def open(self, timing):
        # Certificate-store initialization isn't network setup.
        context = ssl.create_default_context() if self.secure else None
        start = perf_counter()
        sock = open_tcp(self.host, self.port, self.timeout, timing)
        try:
            if context:
                tls_start = perf_counter()
                sock = context.wrap_socket(sock, server_hostname=self.host)
                timing.tls_ms = milliseconds(tls_start)
            self.connection = http.client.HTTPConnection(
                self.host, self.port, timeout=self.timeout
            )
            self.connection.sock = sock
            # Never let HTTPConnection silently replace a closed warm socket.
            self.connection.auto_open = 0
            timing.setup_ms = milliseconds(start)
        except Exception:
            sock.close()
            raise

    def generate(self, payload):
        body = json.dumps(payload).encode()
        audio = bytearray()
        first_audio = None
        start = perf_counter()
        self.connection.request("POST", "/v1/tts/stream", body, {
            "chariotai-api-key": self.key,
            "Content-Type": "application/json",
            "Connection": "keep-alive",
        })
        with self.connection.getresponse() as response:
            if response.status != 200:
                raise RuntimeError(
                    f"HTTP {response.status}: {response.read(2048).decode(errors='replace')}"
                )
            content_type = response.getheader("Content-Type", "")
            if content_type.split(";")[0].strip().lower() != "audio/l16":
                raise RuntimeError(f"Expected raw PCM audio/L16, received {content_type!r}")
            rate = re.search(r"\brate\s*=\s*(\d+)", content_type, re.IGNORECASE)
            if not rate:
                raise RuntimeError("Missing sample rate in Content-Type")
            sample_rate = int(rate[1])
            if sample_rate <= 0:
                raise RuntimeError("Invalid audio sample rate")
            while True:
                # read1 returns available body data, without waiting to fill a
                # large application buffer or counting HTTP headers as audio.
                chunk = response.read1(65536)
                if not chunk:
                    break
                if first_audio is None:
                    first_audio = milliseconds(start)
                audio.extend(chunk)
            if response.length not in (None, 0):
                raise RuntimeError("HTTP body ended before Content-Length")
        if not audio:
            raise RuntimeError("Response completed without audio")
        return first_audio, bytes(audio), sample_rate

    def close(self):
        if self.connection:
            self.connection.close()


class WebSocketStream:
    def __init__(self, key, timeout, settings, host=HOST, port=443, secure=True):
        self.key, self.timeout, self.settings = key, timeout, settings
        self.host, self.port, self.secure = host, port, secure
        self.connection = None

    def open(self, timing):
        query = urlencode({**self.settings, "response_format": "pcm"})
        scheme = "wss" if self.secure else "ws"
        uri = f"{scheme}://{self.host}:{self.port}/v1/tts/ws?{query}"
        context = ssl.create_default_context() if self.secure else None
        start = perf_counter()
        sock = open_tcp(self.host, self.port, self.timeout, timing)
        try:
            upgrade_start = perf_counter()
            self.connection = connect(
                uri, sock=sock, ssl=context,
                additional_headers={"chariotai-api-key": self.key},
                compression=None, open_timeout=self.timeout, close_timeout=2,
                max_size=8 * 1024 * 1024,
            )
            timing.tls_and_ws_upgrade_ms = milliseconds(upgrade_start)
            timing.setup_ms = milliseconds(start)
        except Exception:
            sock.close()
            raise

    def generate(self, payload):
        message = json.dumps({"type": "input.text", "text": payload["text"]})
        flush = json.dumps({"type": "input.flush"})
        audio = bytearray()
        first_audio = None
        sample_rate = None
        start = perf_counter()
        self.connection.send(message)
        self.connection.send(flush)
        deadline = perf_counter() + self.timeout
        while True:
            message = self.connection.recv(timeout=max(0, deadline - perf_counter()))
            if isinstance(message, bytes):
                if message:
                    if first_audio is None:
                        first_audio = milliseconds(start)
                    audio.extend(message)
                continue
            event = json.loads(message)
            if event.get("type") == "error" or event.get("error"):
                raise RuntimeError(f"WebSocket error: {event}")
            if event.get("type") == "audio.start":
                sample_rate = event.get("sample_rate")
            elif event.get("type") == "audio.done":
                if not audio:
                    raise RuntimeError("Generation completed without audio")
                if not isinstance(sample_rate, int) or sample_rate <= 0:
                    raise RuntimeError("Missing sample rate in audio.start")
                return first_audio, bytes(audio), sample_rate
            elif event.get("type") == "session.done":
                raise RuntimeError("Session ended before audio.done")

    def probe_ping(self, timing):
        # Probe after all generations so it cannot pre-warm the first trial.
        start = perf_counter()
        try:
            if not self.connection.ping().wait(self.timeout):
                raise TimeoutError("No WebSocket pong received")
            timing.ping_rtt_ms = milliseconds(start)
        except Exception as exc:
            timing.ping_error = str(exc).replace(self.key, "[redacted]")

    def close(self):
        if self.connection:
            try:
                self.connection.send(json.dumps({"type": "input.done"}))
            except Exception:
                pass
            self.connection.close()


def percentile(values, percent):
    """Nearest-rank percentile; no interpolation or discarded outliers."""
    values = sorted(values)
    return values[max(0, math.ceil(len(values) * percent / 100) - 1)]


def summarize(trials):
    groups = {}
    for trial in trials:
        key = f"{trial['transport']}/{trial['mode']}/{trial['phase']}"
        groups.setdefault(key, []).append(trial)
    result = {}
    for key, group in groups.items():
        values = [t["ttfb_ms"] for t in group if t["status"] == "ok"]
        result[key] = {
            "successful": len(values),
            "failed": sum(t["status"] == "error" for t in group),
            "skipped": sum(t["status"] == "skipped" for t in group),
            "ttfb_ms": ({
                "min": min(values), "p50": percentile(values, 50),
                "p90": percentile(values, 90), "p99": percentile(values, 99),
                "max": max(values),
            } if values else None),
        }
    return result


def run_group(transport, mode, args, factory=None):
    settings = {
        "voice_id": args.voice_id, "model_type": args.model,
        "speed": args.speed,
        "optimize_streaming_latency": args.optimize_streaming_latency,
    }
    payload = {**settings, "text": args.text}
    connections, trials = [], []
    client = None
    stopped = False
    for number in range(1, args.runs + 1):
        is_new = mode == "fresh" or number == 1
        phase = "fresh" if mode == "fresh" else ("first" if is_new else "reused")
        trial = {
            "transport": transport, "mode": mode, "phase": phase,
            "trial": number, "connection_id": None, "status": "ok",
        }
        if stopped:
            trial.update(status="skipped", error="Reuse sequence stopped after failure; no reconnect")
            trials.append(trial)
            print(f"{transport} {mode} trial {number}: SKIPPED (reuse sequence stopped)", flush=True)
            continue
        try:
            if is_new:
                timing = ConnectionTiming(f"{transport}-{mode}-{number}")
                connections.append(timing)
                client = factory() if factory else (
                    HTTPStream(args.api_key, args.timeout) if transport == "http"
                    else WebSocketStream(args.api_key, args.timeout, settings)
                )
                trial["connection_id"] = timing.id
                client.open(timing)
            trial["connection_id"] = timing.id
            ttfb, audio, sample_rate = client.generate(payload)
            if len(audio) % 2:
                raise RuntimeError("Incomplete 16-bit PCM sample")
            trial.update(
                ttfb_ms=ttfb, setup_ms=timing.setup_ms if is_new else 0,
                setup_plus_ttfb_ms=ttfb + (timing.setup_ms if is_new else 0),
                audio_bytes=len(audio), sample_rate=sample_rate,
            )
            # File I/O happens after timing and full response consumption.
            if args.save_audio:
                path = args.save_audio / f"{transport}-{mode}-{number}.wav"
                with wave.open(str(path), "wb") as output:
                    output.setnchannels(1)
                    output.setsampwidth(2)
                    output.setframerate(sample_rate)
                    output.writeframes(audio)
                trial["audio_file"] = str(path)
        except Exception as exc:
            trial.update(status="error", error=str(exc).replace(args.api_key, "[redacted]"))
            stopped = mode == "reused"
        finally:
            if client and (mode == "fresh" or number == args.runs or stopped):
                if transport == "websocket" and trial["status"] == "ok":
                    client.probe_ping(timing)
                client.close()
                client = None
        trials.append(trial)
        if trial["status"] == "ok":
            print(f"{transport:9} {mode:6} {number:3} {phase:6} "
                  f"setup={trial['setup_ms']:7.1f} ms  "
                  f"TTFB={trial['ttfb_ms']:7.1f} ms  "
                  f"setup+TTFB={trial['setup_plus_ttfb_ms']:7.1f} ms", flush=True)
        else:
            print(f"{transport} {mode} trial {number}: ERROR {trial['error']}", flush=True)
    return trials, [asdict(timing) for timing in connections]


def parse_args():
    load_dotenv(Path(__file__).with_name(".env"))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transport", choices=["http", "websocket", "both"], default="both")
    parser.add_argument("--connection", choices=["fresh", "reused", "both"], default="both")
    parser.add_argument("--runs", type=int, default=10, help="Trials per transport and connection mode")
    parser.add_argument("--model", default=os.getenv("CHARIOT_MODEL", "chariot-multilingual-v1"))
    parser.add_argument("--voice-id", default=os.getenv("CHARIOT_VOICE_ID"))
    parser.add_argument("--text", default=DEFAULT_TEXT)
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument("--optimize-streaming-latency", type=int, choices=range(5), default=0)
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--json", type=Path, dest="json_path", help="Write raw trials and summaries")
    parser.add_argument("--save-audio", type=Path, metavar="DIRECTORY")
    args = parser.parse_args()
    args.api_key = os.getenv("CHARIOT_API_KEY", "")
    if not args.api_key.strip() or not args.voice_id or not args.voice_id.strip():
        parser.error("Set CHARIOT_API_KEY and CHARIOT_VOICE_ID in .env or the environment")
    if args.runs < 1 or not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("--runs and --timeout must be positive")
    if not 0.5 <= args.speed <= 2 or not args.text.strip() or not args.model.strip():
        parser.error("Provide nonempty text/model and a speed between 0.5 and 2.0")
    # HTTP trims surrounding whitespace; send the same text on both transports.
    args.text = args.text.strip()
    if args.save_audio:
        args.save_audio.mkdir(parents=True, exist_ok=True)
    return args


def main():
    args = parse_args()
    transports = ["http", "websocket"] if args.transport == "both" else [args.transport]
    modes = ["fresh", "reused"] if args.connection == "both" else [args.connection]
    report = {
        "schema_version": 1,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "python": platform.python_version(), "platform": platform.platform(),
        "websockets_version": version("websockets"),
        "config": {
            "http_endpoint": f"https://{HOST}/v1/tts/stream",
            "websocket_endpoint": f"wss://{HOST}/v1/tts/ws",
            "model_type": args.model, "voice_id": args.voice_id, "text": args.text,
            "speed": args.speed, "optimize_streaming_latency": args.optimize_streaming_latency,
            "audio_format": "pcm_s16le_mono", "transports": transports,
            "connection_modes": modes, "runs_per_mode": args.runs,
            "timeout_seconds": args.timeout, "warmup_requests": 0,
            "proxy": "direct connections; environment proxies are not used",
        },
        "trials": [], "connections": [],
    }
    print(f"Model: {args.model} | voice: {args.voice_id} | speed: {args.speed} | "
          f"optimize_streaming_latency: {args.optimize_streaming_latency}")
    print(f"Text: {args.text!r}")
    print(f"{len(transports) * len(modes) * args.runs} sequential synthesis requests; "
          "normal API credits apply. No hidden warm-ups or retries.")
    for transport in transports:
        for mode in modes:
            trials, connections = run_group(transport, mode, args)
            report["trials"].extend(trials)
            report["connections"].extend(connections)
    report["summary"] = summarize(report["trials"])
    print("\nConnection timings (ms; TCP connect approximates RTT only for one successful address attempt):")
    for connection in report["connections"]:
        fields = ("dns_ms", "tcp_connect_ms", "tls_ms", "tls_and_ws_upgrade_ms", "ping_rtt_ms")
        values = " ".join(f"{key}={connection[key]:.1f}" for key in fields if connection[key] is not None)
        print(f"{connection['id']}: {values} attempts={connection['address_attempts']}")
        if connection["ping_error"]:
            print(f"  ping unavailable: {connection['ping_error']}")
    print("\nTTFB summary (ms; successful generations only, nearest-rank percentiles):")
    for group, summary in report["summary"].items():
        stats = summary["ttfb_ms"]
        values = " ".join(f"{key}={value:.1f}" for key, value in stats.items()) if stats else "no successful samples"
        print(f"{group}: n={summary['successful']} failed={summary['failed']} "
              f"skipped={summary['skipped']} {values}")
    if args.json_path:
        args.json_path.write_text(json.dumps(report, indent=2) + "\n")
        print(f"Raw results: {args.json_path}")
    return int(any(t["status"] != "ok" for t in report["trials"]))


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
