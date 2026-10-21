# AI processing and its limits

## Two separate steps

The default paid path uses OpenAI `gpt-transcribe` for speech and `gpt-6-luna` for task extraction. `WHISPER_MODEL` is a historical environment variable name; it currently selects `gpt-transcribe`. Speech recognition turns audio into text. `app/ai.py::parse_task` turns a typed message or a cleaned voice transcript into one validated task. A good transcript does not by itself guarantee correct task fields.

Text is parsed during Telegram ingestion. Voice recognition and parsing run in the background worker. Task descriptions are data: no model output executes a tool, sends a message on the user's behalf, or performs the requested action. Greetings/questions can return `is_task=false` in the AI path and produce no task. One message creates at most one task.

The Responses request uses strict JSON schema, `store=false`, a 300-token output limit and a 15-second default timeout. The schema requires `is_task`, `title`, `description`, `due_date` and `priority`. The application validates the response again using TaskCreate; incomplete/refused/malformed responses generate safe errors rather than partial tasks. The model must preserve the user's language and must not invent missing dates or priorities. Model access, actual comprehension and provider retention policies remain external dependencies; `store=false` is not a blanket retention guarantee.

## Time and language

The parser receives the current `Asia/Yerevan` timestamp. Unless another timezone is explicitly named, deadlines use Yerevan time. Relative dates are interpreted from that time; date-only deadlines use local midnight. Storage uses UTC and both dashboard inputs and displayed deadlines use Yerevan time, regardless of browser timezone.

`gpt-transcribe` receives multipart `languages[]` hints for `hy` and `en` when `WHISPER_LANGUAGE=auto`; a selected language sends one hint. Its `languages` response is validated and unsupported languages are rejected. The older `whisper-1` and local whisper.cpp contract use `response_format=verbose_json`, an optional singular `language`, and validated legacy language/segment metadata. Legacy low-confidence/no-speech segments are rejected. The new model does not provide that identical confidence contract; real audio checks and empty/inaudible transcript rejection still apply.

Recognized Armenian voice gets Armenian success/metadata labels. The dashboard has no language selector. Exact names, spoken corrections, colloquial times, accents and noisy recordings can still be misunderstood. A task confirmation is not evidence of accurate transcription.

## Bounded audio and failures

Metadata and actual ffprobe/ffmpeg inspection enforce 1–120 seconds and 20 MiB by default. Downloads use only the fixed Telegram host, have bounded retries, reject unsafe paths and stream to private temporary storage. Audio is converted to mono 16 kHz WAV. Temporary files are deleted on success, failure and cancellation; a hard kill leaves only bounded container RAM until replacement. No separate raw transcript is retained.

Speech requests default to 45 seconds and at most `WHISPER_MAX_RETRIES=3` total attempts. Retry delays use exponential backoff with jitter; transient transport errors, 429 and 5xx are retried, permanent provider rejection is not. The whole voice job has a 60-second deadline, including task parsing, which can end the retry budget early. A shared Redis AI gate limits request volume and the audio circuit opens after repeated transient failures. This request-count gate is not a monetary cap.

Jobs persist QUEUED, PROCESSING, RETRYING, COMPLETED, FAILED, DEAD_LETTER or legacy TIMED_OUT/CANCELLED states. Infrastructure recovery/manual retries share a three-retry, 24-hour lifetime. Stale claims are reconciled; permanent bad input fails safely. Final failure has a text alternative. Unique source keys prevent a second task from replaying the same accepted voice job. Telegram delivery is at least once across an ambiguous network/crash boundary.

The hourly/daily per-owner voice quotas both default to 500; the daily window starts at UTC midnight. These count accepted transcription effects, including attempts that may later fail. There are separate active-job and global AI rate bounds. Cost metadata estimates successful speech using duration × configured per-minute price; parser costs, failed/retried provider calls and provider billing adjustments are not reconciled.

## Free local mode

The development overlay replaces the provider URL/key in every Python role, selects the SHA-256-verified multilingual whisper.cpp `base` model, forces `TASK_PARSER_ENABLED=false` and a zero speech estimate. It makes no OpenAI request. The deterministic fallback in `app/services.py` recognizes explicit English/Armenian field labels and preserves unstructured text; it does not provide the same intent/field comprehension as the AI parser. Explicit structured values are validated before task creation.

The local model is about 141 MiB, limited to two CPUs/1 GiB, and the pinned amd64 image uses emulation on Apple Silicon. Long/noisy speech may exceed the same deadlines. Production settings reject the nonofficial provider host.

## Evidence

`make test-local-ai` uses real local inference for a public English sample and `tests/fixtures/voice-fields.wav`. The latter is synthetic macOS Samantha speech: “Title. Call Anna. Description. Discuss the report. Due date. Tomorrow at six P M. Priority. High.” It checks every stored field, Yerevan/UTC conversion, queue/DB/SSE, replay identity and confirmation. Telegram HTTP is mocked. Neither sample establishes Armenian speech accuracy.

`uv run python -m scripts.evaluate_ai` checks 17 deterministic fallback fixtures. Unit tests for the AI parser and paid speech contract mock the provider boundary. They verify contracts and safe failure behavior, not real model comprehension. README's longer Armenian/English examples are manual acceptance scenarios with expected semantics; no broad measured success rate is claimed. Current evidence and remaining release gates are in [VERIFICATION.md](../VERIFICATION.md).
