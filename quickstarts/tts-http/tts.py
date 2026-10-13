"""One HTTP request to Chariot TTS, one WAV file out.

Usage:
    python tts.py "Hello from Chariot. Namaste!"
"""

import argparse
import os

import requests
from dotenv import load_dotenv

load_dotenv()

OUT_PATH = "hello.wav"


def main(text: str, model: str) -> None:
    response = requests.post(
        "https://api.chariot.in/v1/tts",
        headers={"chariotai-api-key": os.environ["CHARIOT_API_KEY"]},
        json={"voice_id": os.environ["CHARIOT_VOICE_ID"], "text": text, "model_type": model},
        timeout=60,
    )
    response.raise_for_status()
    with open(OUT_PATH, "wb") as f:
        f.write(response.content)
    print(f"wrote {OUT_PATH} ({len(response.content)} bytes)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("text", nargs="?", default="Hello from Chariot. Namaste!")
    parser.add_argument("--model", default=os.getenv("CHARIOT_MODEL", "chariot-multilingual-v1"))
    args = parser.parse_args()
    main(args.text, args.model)
