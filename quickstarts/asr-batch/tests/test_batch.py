"""Check submission and resumable result retrieval without an API key."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4
import httpx
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from batch import submit, poll


class BatchTests(unittest.TestCase):
    def test_single_multipart_upload(self):
        def handle(request):
            self.assertEqual(request.headers["Idempotency-Key"], "example-request")
            self.assertEqual(request.content.count(b'name="files"; filename='), 1)
            self.assertIn(b'"file_index": 0', request.content)
            self.assertIn(b'name="manifest"', request.content)
            self.assertIn(b"example-audio", request.content)
            return httpx.Response(202, json={"id": "example-batch"})
        with tempfile.TemporaryDirectory() as folder, httpx.Client(transport=httpx.MockTransport(handle)) as client:
            path = Path(folder) / "sample.wav"
            path.write_bytes(b"example-audio")
            self.assertEqual(submit(client, file=path, idempotency_key="example-request")["id"], "example-batch")

    def test_multiple_urls(self):
        def handle(request):
            self.assertEqual(request.headers["content-type"], "application/json")
            inputs = json.loads(request.content)["inputs"]
            self.assertEqual([i["custom_id"] for i in inputs], ["file-1", "file-2"])
            self.assertEqual(inputs[1]["audio_url"], "https://example.com/b.wav")
            self.assertTrue(all(i["include_timestamps"] for i in inputs))
            return httpx.Response(202, json={"id": "example-batch"})
        with httpx.Client(transport=httpx.MockTransport(handle)) as client:
            submit(client, urls=["https://example.com/a.wav", "https://example.com/b.wav"], timestamps=True, idempotency_key="example-request")

    def test_resume_pagination_and_full_results(self):
        bid, first, second = map(str, [uuid4(), uuid4(), uuid4()])
        requests = []
        def handle(request):
            requests.append(request)
            self.assertEqual(request.method, "GET")
            if request.url.path.endswith(f"/batches/{bid}"):
                return httpx.Response(200, json={"id": bid, "status": "partially_completed", "counts": {"completed": 1, "failed": 1}})
            if request.url.path.endswith("/history"):
                self.assertEqual(request.url.params["batch_id"], bid)
                later = "cursor" in request.url.params
                return httpx.Response(200, json={"items": [{"id": second if later else first, "transcript_preview": "short"}], "next_cursor": None if later else "example-cursor"})
            failed = request.url.path.endswith(second)
            return httpx.Response(200, json={"id": second if failed else first, "status": "failed" if failed else "completed", "result": None if failed else {"text": "complete transcript", "words": []}, "error": {"code": "invalid_audio"} if failed else None})
        with httpx.Client(transport=httpx.MockTransport(handle)) as client:
            result = poll(client, bid)
        self.assertEqual(len(requests), 5)
        self.assertEqual(result["transcriptions"][0]["result"]["text"], "complete transcript")
        self.assertEqual(result["transcriptions"][1]["error"]["code"], "invalid_audio")

    def test_timeout_does_not_cancel_or_resubmit(self):
        calls = []
        def handle(request):
            calls.append(request.method)
            return httpx.Response(200, json={"status": "processing", "counts": {"processing": 1}})
        with httpx.Client(transport=httpx.MockTransport(handle)) as client:
            with self.assertRaisesRegex(TimeoutError, "Resume with --batch-id"):
                poll(client, str(uuid4()), interval=.005, timeout=.01)
        self.assertTrue(calls)
        self.assertEqual(set(calls), {"GET"})

    def test_cancelled_batch_is_terminal(self):
        def handle(request):
            if request.url.path.endswith("/history"):
                return httpx.Response(200, json={"items": [], "next_cursor": None})
            return httpx.Response(200, json={"status": "cancelled", "counts": {"cancelled": 1}})
        with httpx.Client(transport=httpx.MockTransport(handle)) as client:
            self.assertEqual(poll(client, str(uuid4()))["batch"]["status"], "cancelled")
