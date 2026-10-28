"""Check request payloads using an in-memory HTTP transport."""
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs
import httpx
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from transcribe import transcribe


class TranscriptionTests(unittest.TestCase):
    def test_multipart_and_options(self):
        def handle(request):
            self.assertEqual(request.url.path, "/v1/asr/transcribe")
            self.assertIn("multipart/form-data", request.headers["content-type"])
            self.assertIn(b'name="input_audio_file"; filename="sample.wav"', request.content)
            self.assertIn(b"example-audio", request.content)
            self.assertIn(b'name="include_timestamps"\r\n\r\ntrue', request.content)
            self.assertIn(b'name="style"\r\n\r\nnative', request.content)
            return httpx.Response(200, json={"text": "hello", "words": None})
        with tempfile.TemporaryDirectory() as folder, httpx.Client(transport=httpx.MockTransport(handle)) as client:
            path = Path(folder) / "sample.wav"
            path.write_bytes(b"example-audio")
            self.assertEqual(transcribe(client, file=path, style="native", timestamps=True), {"text": "hello", "words": None})

    def test_url_form(self):
        def handle(request):
            fields = parse_qs(request.content.decode())
            self.assertEqual(fields["input_audio_url"], ["https://example.com/a.wav"])
            self.assertEqual(fields["language"], ["hi"])
            self.assertEqual(fields["mode"], ["high_accuracy"])
            self.assertNotIn("input_audio_file", fields)
            return httpx.Response(200, json={"text": "hello"})
        with httpx.Client(transport=httpx.MockTransport(handle)) as client:
            transcribe(client, url="https://example.com/a.wav", language="hi")

    def test_failure(self):
        with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(413, json={"detail": "File too large"}))) as client:
            with self.assertRaisesRegex(RuntimeError, "HTTP 413"):
                transcribe(client, url="https://example.com/a.wav")

    def test_exactly_one_source(self):
        with self.assertRaises(ValueError):
            transcribe(None)
        with self.assertRaises(ValueError):
            transcribe(None, file="a.wav", url="https://example.com/a.wav")
