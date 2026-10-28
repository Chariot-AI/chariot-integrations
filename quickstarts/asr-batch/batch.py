"""Submit a durable ASR batch and poll it, or resume polling by batch ID."""

import argparse
import json
import math
import os
import sys
import time
from pathlib import Path
from uuid import UUID, uuid4

import httpx
from dotenv import load_dotenv

API_URL = "https://api.chariot.in/v1/asr"
MODEL = "chariot-1-asr-realtime"
TERMINAL = {"completed", "partially_completed", "failed", "cancelled"}


def checked(response):
    if not response.is_success:
        raise RuntimeError(f"API rejected request (HTTP {response.status_code}): {response.text}")
    return response.json()


def submit(client, *, file=None, urls=None, language="none", style="codemix", timestamps=False, idempotency_key):
    if bool(file) == bool(urls):
        raise ValueError("Provide one file or one or more URLs")
    options = {"model_type": MODEL, "language": language, "mode": "high_accuracy",
               "style": style, "include_timestamps": timestamps}
    headers = {"Idempotency-Key": idempotency_key}
    if file:
        path = Path(file)
        manifest = {"inputs": [{"custom_id": "file-1", "file_index": 0, **options}]}
        with path.open("rb") as audio:
            response = client.post(f"{API_URL}/batches", headers=headers,
                                   data={"manifest": json.dumps(manifest)},
                                   files={"files": (path.name, audio, "application/octet-stream")})
    else:
        manifest = {"inputs": [{"custom_id": f"file-{i}", "audio_url": url, **options}
                               for i, url in enumerate(urls, 1)]}
        response = client.post(f"{API_URL}/batches", headers=headers, json=manifest)
    return checked(response)


def poll(client, batch_id, *, interval=5, timeout=14400):
    batch_id = str(UUID(str(batch_id)))
    if not all(math.isfinite(v) and v > 0 for v in (interval, timeout)):
        raise ValueError("Polling interval and timeout must be positive and finite")
    deadline = time.monotonic() + timeout
    previous = None
    while True:
        batch = checked(client.get(f"{API_URL}/batches/{batch_id}"))
        state = (batch["status"], batch["counts"])
        if state != previous:
            print(f"{batch_id}: {state[0]} {state[1]}", file=sys.stderr, flush=True)
            previous = state
        if batch["status"] in TERMINAL:
            break
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"Polling stopped; job continues. Resume with --batch-id {batch_id}")
        time.sleep(min(interval, remaining))

    # History is paginated and contains previews. Fetch details for full results.
    items, cursor = [], None
    while True:
        params = {"batch_id": batch_id, "limit": 100}
        if cursor:
            params["cursor"] = cursor
        page = checked(client.get(f"{API_URL}/history", params=params))
        for item in page["items"]:
            identifier = str(UUID(item["id"]))
            items.append(checked(client.get(f"{API_URL}/transcriptions/{identifier}")))
        cursor = page.get("next_cursor")
        if not cursor:
            return {"batch": batch, "transcriptions": items}


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--file", type=Path, help="Upload one local recording")
    source.add_argument("--url", action="append", help="Public/signed audio URL; repeat for multiple recordings")
    source.add_argument("--batch-id", type=UUID, help="Resume polling without submitting again")
    parser.add_argument("--idempotency-key", help="Reuse this key with exactly the same submission after an uncertain response")
    parser.add_argument("--language", default="none")
    parser.add_argument("--style", choices=["codemix", "native"], default="codemix")
    parser.add_argument("--timestamps", action="store_true")
    parser.add_argument("--poll-interval", type=float, default=5)
    parser.add_argument("--timeout", type=float, default=14400, help="Polling time limit in seconds; does not cancel the job")
    args = parser.parse_args()
    key = os.getenv("CHARIOT_API_KEY")
    if not key:
        parser.error("Set CHARIOT_API_KEY in .env or your environment")
    if not all(math.isfinite(v) and v > 0 for v in (args.poll_interval, args.timeout)):
        parser.error("Polling interval and timeout must be positive and finite")
    try:
        with httpx.Client(headers={"chariotai-api-key": key}, timeout=httpx.Timeout(300, connect=15)) as client:
            batch_id = args.batch_id
            if not batch_id:
                request_key = args.idempotency_key or str(uuid4())
                print(f"Idempotency key: {request_key}", file=sys.stderr, flush=True)
                accepted = submit(client, file=args.file, urls=args.url, language=args.language,
                                  style=args.style, timestamps=args.timestamps, idempotency_key=request_key)
                batch_id = accepted["id"]
                print(f"Batch ID: {batch_id}\nResume: python batch.py --batch-id {batch_id}", file=sys.stderr, flush=True)
                for item in accepted["items"]:
                    print(f"{item['custom_id']}: {item['id']}", file=sys.stderr)
            result = poll(client, batch_id, interval=args.poll_interval, timeout=args.timeout)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        if result["batch"]["status"] != "completed":
            parser.exit(1, "Some recordings did not complete; inspect each transcription's status and error.\n")
    except KeyboardInterrupt:
        parser.exit(130, "Stopped polling; accepted jobs continue. Resume using the printed batch ID.\n")
    except httpx.RequestError as error:
        parser.exit(1, f"Connection failed ({type(error).__name__}). Resume by batch ID, or retry the identical submission with the printed idempotency key.\n")
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
