"""Local protocol tests: no Chariot credentials or paid API calls."""

from contextlib import contextmanager, redirect_stdout
import http.server
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from websockets.sync.server import serve

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from latency import ConnectionTiming, HTTPStream, WebSocketStream, run_group, summarize
import latency


KEY = "local-test-placeholder"
SETTINGS = {
    "voice_id": "test-voice", "model_type": "chariot-multilingual-v1",
    "speed": 1.0, "optimize_streaming_latency": 0,
}
PAYLOAD = {**SETTINGS, "text": "Hello from a local test."}


class HTTPHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.calls.append((self.client_address, self.path, dict(self.headers), body))
        behavior = self.server.behavior
        if behavior == "error":
            self.send_response(422)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(200)
        content_type = "application/json" if behavior == "not-audio" else "audio/L16; rate=44100; channels=1"
        self.send_header("Content-Type", content_type)
        if behavior == "truncated":
            self.send_header("Content-Length", "100")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(b"\0\0")
            self.wfile.flush()
            self.close_connection = True
            return
        self.send_header("Transfer-Encoding", "chunked")
        if behavior == "close":
            self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.flush()
        if behavior == "not-audio":
            return
        # Headers arrive well before audio; then a tiny chunk arrives well
        # before the rest. Neither boundary should be mistaken for TTFB.
        time.sleep(0.06)
        if behavior != "empty":
            self.wfile.write(b"2\r\n\0\0\r\n")
            self.wfile.flush()
            time.sleep(0.08)
            self.wfile.write(b"2\r\n\1\0\r\n")
        self.wfile.write(b"0\r\n\r\n")
        self.wfile.flush()
        if behavior == "close":
            self.close_connection = True


@contextmanager
def http_server(behavior="normal"):
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), HTTPHandler)
    server.behavior, server.calls = behavior, []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@contextmanager
def ws_server(behavior="normal"):
    calls, connections = [], []

    def handler(ws):
        connections.append(ws.request)
        text = None
        try:
            for message in ws:
                event = json.loads(message)
                if event["type"] == "input.text":
                    text = event["text"]
                elif event["type"] == "input.flush":
                    calls.append((ws.request.path, text))
                    ws.send(json.dumps({"type": "audio.start", "sample_rate": 44100}))
                    if behavior == "error":
                        ws.send(json.dumps({"type": "error", "message": "unsupported model"}))
                        continue
                    time.sleep(0.06)
                    if behavior != "empty":
                        ws.send(b"")
                        ws.send(b"\0\0")
                    time.sleep(0.08)
                    ws.send(json.dumps({"type": "audio.done", "error": "failed" if behavior == "late-error" else None}))
                elif event["type"] == "input.done":
                    ws.send(json.dumps({"type": "session.done"}))
                    break
        except Exception:
            # Some tests intentionally close on a server error.
            pass

    server = serve(handler, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.socket.getsockname()[1], calls, connections
    finally:
        server.shutdown()
        thread.join(timeout=2)


def args(runs=3):
    return SimpleNamespace(
        api_key=KEY, voice_id=SETTINGS["voice_id"], model=SETTINGS["model_type"],
        text=PAYLOAD["text"], speed=1.0, optimize_streaming_latency=0,
        timeout=2, runs=runs, save_audio=None,
    )


class LatencyTests(unittest.TestCase):
    def test_http_first_audio_excludes_headers_and_does_not_wait_for_full_body(self):
        with http_server() as server:
            client = HTTPStream(KEY, 2, "127.0.0.1", server.server_port, False)
            timing = ConnectionTiming("http-test")
            client.open(timing)
            try:
                started = time.perf_counter()
                ttfb, audio, rate = client.generate(PAYLOAD)
                duration = (time.perf_counter() - started) * 1000
                self.assertGreaterEqual(ttfb, 50)
                self.assertGreater(duration - ttfb, 50)
                self.assertEqual((audio, rate), (b"\0\0\1\0", 44100))
                self.assertEqual(server.calls[0][3]["model_type"], SETTINGS["model_type"])
                self.assertEqual(server.calls[0][1], "/v1/tts/stream")
                self.assertEqual(server.calls[0][2]["chariotai-api-key"], KEY)
                self.assertEqual(timing.peer_ip, "127.0.0.1")
            finally:
                client.close()

    def test_http_fresh_and_reused_use_expected_socket_counts(self):
        for mode, expected in [("fresh", 3), ("reused", 1)]:
            with self.subTest(mode=mode), http_server() as server, redirect_stdout(io.StringIO()):
                factory = lambda: HTTPStream(KEY, 2, "127.0.0.1", server.server_port, False)
                trials, connections = run_group("http", mode, args(), factory)
                self.assertTrue(all(t["status"] == "ok" for t in trials))
                self.assertEqual(len(connections), expected)
                self.assertEqual(len({call[0] for call in server.calls}), expected)
                if mode == "reused":
                    self.assertEqual([t["phase"] for t in trials], ["first", "reused", "reused"])
                    self.assertEqual(trials[1]["setup_ms"], 0)

    def test_http_closed_reused_socket_is_not_silently_replaced(self):
        with http_server("close") as server, redirect_stdout(io.StringIO()):
            factory = lambda: HTTPStream(KEY, 2, "127.0.0.1", server.server_port, False)
            trials, connections = run_group("http", "reused", args(4), factory)
            self.assertEqual([t["status"] for t in trials], ["ok", "error", "skipped", "skipped"])
            self.assertEqual(len(connections), 1)
            self.assertEqual(len(server.calls), 1)

    def test_http_rejects_failed_empty_non_audio_and_truncated_responses(self):
        for behavior in ["error", "empty", "not-audio", "truncated"]:
            with self.subTest(behavior=behavior), http_server(behavior) as server:
                client = HTTPStream(KEY, 2, "127.0.0.1", server.server_port, False)
                client.open(ConnectionTiming("http-error"))
                try:
                    with self.assertRaises(RuntimeError):
                        client.generate(PAYLOAD)
                finally:
                    client.close()

    def test_websocket_counts_binary_audio_not_control_or_empty_messages(self):
        with ws_server() as (port, calls, connections):
            client = WebSocketStream(KEY, 2, SETTINGS, "127.0.0.1", port, False)
            timing = ConnectionTiming("ws-test")
            client.open(timing)
            try:
                started = time.perf_counter()
                ttfb, audio, rate = client.generate(PAYLOAD)
                duration = (time.perf_counter() - started) * 1000
                self.assertGreaterEqual(ttfb, 50)
                self.assertGreater(duration - ttfb, 50)
                self.assertEqual((audio, rate), (b"\0\0", 44100))
                query = parse_qs(urlsplit(calls[0][0]).query)
                self.assertEqual(query["model_type"], [SETTINGS["model_type"]])
                self.assertEqual(query["response_format"], ["pcm"])
                self.assertEqual(connections[0].headers["chariotai-api-key"], KEY)
                self.assertIsNone(timing.ping_rtt_ms)
                client.probe_ping(timing)
                self.assertIsNotNone(timing.ping_rtt_ms)
            finally:
                client.close()

    def test_websocket_fresh_and_reused_sessions(self):
        for mode, expected in [("fresh", 3), ("reused", 1)]:
            with self.subTest(mode=mode), ws_server() as (port, calls, sessions), redirect_stdout(io.StringIO()):
                factory = lambda: WebSocketStream(KEY, 2, SETTINGS, "127.0.0.1", port, False)
                trials, connections = run_group("websocket", mode, args(), factory)
                self.assertTrue(all(t["status"] == "ok" for t in trials))
                self.assertEqual(len(sessions), expected)
                self.assertEqual(len(connections), expected)
                self.assertEqual(len(calls), 3)

    def test_websocket_rejects_error_empty_and_failure_after_first_audio(self):
        for behavior in ["error", "empty", "late-error"]:
            with self.subTest(behavior=behavior), ws_server(behavior) as (port, _, _):
                client = WebSocketStream(KEY, 2, SETTINGS, "127.0.0.1", port, False)
                client.open(ConnectionTiming("ws-error"))
                try:
                    with self.assertRaises(RuntimeError):
                        client.generate(PAYLOAD)
                finally:
                    client.close()

    def test_summary_separates_first_request_and_reports_failure_denominators(self):
        base = {"transport": "http", "mode": "reused", "phase": "reused"}
        trials = [
            {**base, "phase": "first", "status": "ok", "ttfb_ms": 900},
            *[{**base, "status": "ok", "ttfb_ms": n} for n in range(1, 11)],
            {**base, "status": "error"}, {**base, "status": "skipped"},
        ]
        summary = summarize(trials)
        self.assertEqual(summary["http/reused/first"]["successful"], 1)
        warm = summary["http/reused/reused"]
        self.assertEqual((warm["successful"], warm["failed"], warm["skipped"]), (10, 1, 1))
        self.assertEqual(warm["ttfb_ms"], {"min": 1, "p50": 5, "p90": 9, "p99": 10, "max": 10})
        hundred = [{**base, "status": "ok", "ttfb_ms": n} for n in range(100, 0, -1)]
        self.assertEqual(summarize(hundred)["http/reused/reused"]["ttfb_ms"]["p99"], 99)

    def test_default_model_is_multilingual_v1(self):
        with patch.dict("os.environ", {"CHARIOT_API_KEY": KEY, "CHARIOT_VOICE_ID": "test-voice"}, clear=True), \
             patch.object(sys, "argv", ["latency.py"]):
            self.assertEqual(latency.parse_args().model, "chariot-multilingual-v1")

    def test_cli_report_audio_and_exit_status(self):
        with http_server() as server, ws_server() as (port, _, _), tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            cli_args = [
                "latency.py", "--runs", "2", "--model", SETTINGS["model_type"],
                "--save-audio", str(output / "audio"), "--json", str(output / "results.json"),
            ]
            http_factory = lambda key, timeout: HTTPStream(key, timeout, "127.0.0.1", server.server_port, False)
            ws_factory = lambda key, timeout, settings: WebSocketStream(key, timeout, settings, "127.0.0.1", port, False)
            with patch.dict("os.environ", {"CHARIOT_API_KEY": KEY, "CHARIOT_VOICE_ID": "test-voice"}), \
                 patch.object(sys, "argv", cli_args), \
                 patch.object(latency, "HTTPStream", side_effect=http_factory), \
                 patch.object(latency, "WebSocketStream", side_effect=ws_factory), \
                 redirect_stdout(io.StringIO()):
                self.assertEqual(latency.main(), 0)
            raw = (output / "results.json").read_text()
            self.assertNotIn(KEY, raw)
            report = json.loads(raw)
            self.assertEqual(len(report["trials"]), 8)
            self.assertEqual(len(report["connections"]), 6)
            self.assertEqual(report["config"]["model_type"], SETTINGS["model_type"])
            self.assertEqual(len(list((output / "audio").glob("*.wav"))), 8)

    def test_cli_nonzero_for_api_errors(self):
        with http_server("error") as server, redirect_stdout(io.StringIO()):
            factory = lambda key, timeout: HTTPStream(key, timeout, "127.0.0.1", server.server_port, False)
            with patch.dict("os.environ", {"CHARIOT_API_KEY": KEY, "CHARIOT_VOICE_ID": "test-voice"}), \
                 patch.object(sys, "argv", ["latency.py", "--transport", "http", "--connection", "reused", "--runs", "2"]), \
                 patch.object(latency, "HTTPStream", side_effect=factory):
                self.assertEqual(latency.main(), 1)


if __name__ == "__main__":
    unittest.main()
