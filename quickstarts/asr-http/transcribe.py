"""Transcribe one file or public URL with Chariot's synchronous ASR API."""

import argparse
import json
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

API_URL = "https://api.chariot.in/v1/asr/transcribe"
MODEL = "chariot-1-asr-realtime"


def transcribe(client, *, file=None, url=None, language="none", style="codemix", timestamps=False):
    if bool(file) == bool(url):
        raise ValueError("Provide exactly one file or URL")
    data = {"model_type": MODEL, "language": language, "mode": "high_accuracy",
            "style": style, "include_timestamps": str(timestamps).lower()}
    if file:
        path = Path(file)
        # httpx streams the multipart file instead of reading it all into memory.
        with path.open("rb") as audio:
            response = client.post(API_URL, data=data,
                                   files={"input_audio_file": (path.name, audio, "application/octet-stream")})
    else:
        response = client.post(API_URL, data={**data, "input_audio_url": url})
    if not response.is_success:
        raise RuntimeError(f"Transcription rejected (HTTP {response.status_code}): {response.text}")
    return response.json()


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--file", type=Path)
    source.add_argument("--url", help="Public or signed HTTP(S) audio URL")
    parser.add_argument("--language", default="none", help="Requested language code; none = auto-detect")
    parser.add_argument("--style", choices=["codemix", "native"], default="codemix")
    parser.add_argument("--timestamps", action="store_true")
    args = parser.parse_args()
    key = os.getenv("CHARIOT_API_KEY")
    if not key:
        parser.error("Set CHARIOT_API_KEY in .env or your environment")
    try:
        with httpx.Client(headers={"chariotai-api-key": key}, timeout=httpx.Timeout(300, connect=15)) as client:
            result = transcribe(client, file=args.file, url=args.url, language=args.language,
                                style=args.style, timestamps=args.timestamps)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except httpx.TimeoutException:
        parser.exit(1, "Request timed out; it may still finish on the server. Check history before retrying.\n")
    except httpx.RequestError as error:
        parser.exit(1, f"Connection failed ({type(error).__name__}); check history before retrying.\n")
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
