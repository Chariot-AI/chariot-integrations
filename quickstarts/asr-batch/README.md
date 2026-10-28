# Batch transcription (Beta)

Submit durable transcription jobs with `POST /v1/asr/batches`, then poll for their results. A batch can contain one long recording or multiple recordings. Closing the client does not cancel accepted jobs.

## Run

Python 3.10+:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.sample .env  # add your Chariot API key
python batch.py --file recording.wav --timestamps
python batch.py --url 'https://example.com/one.mp3' --url 'https://example.com/two.wav'
```

Only **one file** is uploaded per multipart request. It is referenced by `file_index: 0` in the JSON `manifest` form field; the file field is `files`. Multiple recordings use repeated `--url` arguments and a JSON request. Public/signed URLs must remain accessible until the service fetches the audio. See [ASR documentation](https://docs.chariot.in/guides/speech-to-text/overview) for current per-file limits and batch size.

The script prints the batch ID and each `custom_id` to transcription-ID mapping immediately. Progress goes to stderr; the complete batch and full transcription results are printed as JSON to stdout once processing finishes. Redirect stdout to a file if desired.

```bash
python batch.py --file recording.wav --idempotency-key recording-001 > result.json
python batch.py --batch-id YOUR_BATCH_ID > result.json
```

`--batch-id` resumes polling without resubmission. If a submission's response is lost, repeat the **identical request** with its printed idempotency key to recover the same batch. A new key creates a new batch. Do not reuse a key for different input or options.

## Request and result

Every input has its own `custom_id`, `model_type`, language, style, and timestamp setting. This example uses `chariot-1-asr-realtime` and `high_accuracy`; `--language`, `--style`, and `--timestamps` apply to every input in this invocation. A JSON URL request looks like:

```json
{
  "inputs": [
    {
      "custom_id": "file-1",
      "audio_url": "https://example.com/recording.wav",
      "model_type": "chariot-1-asr-realtime",
      "language": "none",
      "mode": "high_accuracy",
      "style": "codemix",
      "include_timestamps": true
    }
  ]
}
```

Polling uses `GET /v1/asr/batches/{id}` until `completed`, `partially_completed`, `failed`, or `cancelled`. It then pages through `/v1/asr/history?batch_id=...` and fetches each `/v1/asr/transcriptions/{id}`. History previews are not complete transcripts; details include `result.text`, `result.words`, status, and error information.

One file can fail while others complete. The script prints all results and exits nonzero unless the whole batch completed successfully. A stage percentage, when present in a transcription, describes that stage only, not the overall job.

`--poll-interval` defaults to 5 seconds. `--timeout` defaults to 4 hours of polling; reaching it or pressing Ctrl+C does **not** cancel the batch. Resume with its ID, or explicitly cancel using `POST /v1/asr/batches/{id}/cancel`. Completion webhooks are also available in the API; this quickstart uses polling and does not run a webhook receiver.

For a short file with an immediate response, see [synchronous ASR](../asr-http). For a voice agent, see [Pipecat](../../integrations/pipecat).

## Test

```bash
python -m unittest discover -s tests -v
```

Tests use a mock HTTP transport to check uploads, URL batches, pagination, full-result fetching, partial failures, and resuming without another submission.
