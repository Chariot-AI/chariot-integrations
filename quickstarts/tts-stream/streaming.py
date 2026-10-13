"""Send full text over HTTP, receive PCM chunks, and save a playable WAV."""

import argparse
import os
import re
import wave

from dotenv import load_dotenv
import requests


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("text", nargs="?", default="Hello from Chariot. Namaste!")
    parser.add_argument("--model", default=os.getenv("CHARIOT_MODEL", "chariot-multilingual-v1"))
    args = parser.parse_args()
    audio = bytearray()
    with requests.post(
        "https://api.chariot.in/v1/tts/stream",
        headers={"chariotai-api-key": os.environ["CHARIOT_API_KEY"]},
        json={
            "voice_id": os.environ["CHARIOT_VOICE_ID"],
            "text": args.text,
            "model_type": args.model,
        },
        stream=True,
        timeout=60,
    ) as response:
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "")
        if content_type.split(";")[0].strip().lower() != "audio/l16":
            raise RuntimeError(f"Expected audio/L16, received {content_type!r}")
        rate = re.search(r"\brate\s*=\s*(\d+)", content_type, re.IGNORECASE)
        if not rate:
            raise RuntimeError("Missing audio sample rate")
        # None avoids waiting to accumulate a fixed-size application buffer.
        for chunk in response.iter_content(chunk_size=None):
            if chunk:
                print(f"Received {len(chunk)} audio bytes", flush=True)
                audio.extend(chunk)
    if not audio or len(audio) % 2:
        raise RuntimeError("Missing or incomplete 16-bit PCM audio")
    with wave.open("out.wav", "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(int(rate[1]))
        output.writeframes(audio)
    print(f"Wrote out.wav using {args.model}")


if __name__ == "__main__":
    main()
