# idin9-srs — AGENTS.md

## What this is

SIPREC recording server (RFC 7866) integrating with AudioCodes Mediant SBC. Captures dual RTP streams, transcribes with Whisper, analyzes sentiment, serves recordings via REST API + web dashboard.

## Run

```bash
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Systemd unit: `scripts/idin9-srs.service` (uses `run.py` which does not exist at root — fix before deploying with systemd).

## Config

- **`.env`** (gitignored) — primary, loaded by `pydantic-settings`. Copy `.env.example` to start.
- **`config.override.json`** (gitignored) — runtime overrides merged at startup and writable via `PUT /api/v1/admin/settings`. Values override `.env`.
- SIP/RTP ports require restart; AI model changes require restart.
- Session auto-stop after 300s of no RTP activity (`session_timeout_seconds`, 0=off). Stale checker runs every 30s.

## API

All routes under `/api/v1/`. Auth via `X-API-Key` header (disabled when `API_KEY` is empty). Health and info endpoints are unauthenticated.

Key endpoints:
- `POST /record/stop/{session_id}` — stop session, trigger transcription + sentiment
- `GET /record/{session_id}` — get transcript/sentiment (live or indexed)
- `GET /recordings/{session_id}/audio` — download/stream, decrypts on the fly
- `GET /recordings` — search with filters (caller, callee, sentiment range, time range)
- `PUT /admin/settings` — persist to `config.override.json`
- `POST /maintenance/cleanup` — delete recordings older than retention

## Architecture

```
SIP UDP :5060  →  Idin9SrsServer (sip_stack.py)  →  SessionManager
                     ↓
RTP UDP :10000+  →  RtpSession (rtp_session.py)  →  AudioProcessor
                                                      ↓
                                               Transcriber → SentimentAnalyzer → RecordingIndexer (SQLite)
```

- Audio output: WAV (stereo: caller L, callee R) or Opus (via ffmpeg, requires `ffmpeg` on PATH). Optional AES-256 Fernet encryption.
- Codecs supported: PCMU, PCMA, G.729 (silence if `g729` package missing), Opus.
- Index DB: `{output_dir}/index.db` (SQLite, auto-created).

## AI providers

| Feature | `local` | `openai` | `ollama` | `gemini` |
|---|---|---|---|---|
| Transcription | faster-whisper | Whisper API | Whisper via Ollama | Gemini API |
| Sentiment | HuggingFace transformer | GPT-4o-mini (default) | llama3.2 (default) | Gemini Flash |

- Local Whisper downloads model on first run (size: `WHISPER_MODEL_SIZE`).
- Local sentiment downloads HuggingFace model to `HF_HOME`/`TRANSFORMERS_CACHE`.

## Key notes

- No tests, no CI, no lint/typecheck config exist.
- No `run.py` at root (systemd service references one that doesn't exist).
- G.729 support requires `pip install g729` (uncommon package, silence fallback otherwise).
- Sentiment score range: 1.0 (calm) – 10.0 (angry).
- Audio playback uses `/api/v1/recordings/{id}/audio` which decrypts on the fly.
- Retention cleanup has dual paths: `POST /api/v1/maintenance/cleanup` (Python) or `scripts/cleanup.sh` (bash cron).
