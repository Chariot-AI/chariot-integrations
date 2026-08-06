"""One HTTP request to Chariot TTS, one WAV file out.

Usage:
    python tts.py "Hello from Chariot. Namaste!"
"""

import os
import sys

import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.environ["CHARIOT_API_KEY"]
VOICE_ID = os.environ["CHARIOT_VOICE_ID"]
OUT_PATH = "hello.wav"


def main(text: str) -> None:
    response = requests.post(
        "https://api.chariot.in/v1/tts",
        headers={"chariotai-api-key": API_KEY},
        json={"voice_id": VOICE_ID, "text": text},
        timeout=60,
    )
    response.raise_for_status()
    with open(OUT_PATH, "wb") as f:
        f.write(response.content)
    print(f"wrote {OUT_PATH} ({len(response.content)} bytes)")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "Hello from Chariot. Namaste!")
