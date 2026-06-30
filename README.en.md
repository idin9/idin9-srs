# idin9-srs (English)

> [ภาษาไทย (Thai Version)](README.th.md)

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115%2B-009688)](https://fastapi.tiangolo.com/)
[![License](https://img.shields.io/badge/License-MIT-green)]()
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED)]()

**Version:** 26.06.16  |
**Author:** Kanit Klai-Udom  |
**Contact:** [www.idin9.com](https://www.idin9.com)  
**License:** MIT

---

## English 🇬🇧

**idin9-srs** is a real-time **Session Recording Server (SRS)** that integrates with AudioCodes Mediant SBC via the SIPREC protocol (RFC 7866). It captures dual RTP audio streams (caller/callee), transcribes speech using OpenAI Whisper, and performs emotion sentiment analysis with a configurable anger score from **1 (calm) to 10 (most angry)**. Includes a web-based management UI for auditors and administrators.

### Features

| Feature | Description |
|---------|-------------|
| **SIPREC SRS (RFC 7866)** | Compliant Session Recording Server — receives SIP INVITE with multipart MIME (SDP + XML metadata) |
| **Dual RTP Streams** | Two independent RTP streams (caller left / callee right) → stereo audio |
| **Codec Support** | G.711 μ-law (PCMU), G.711 A-law (PCMA), G.729, Opus |
| **Speech-to-Text** | Powered by faster-whisper (tiny → large-v3 models, 100+ languages) |
| **Sentiment Analysis** | HuggingFace emotion recognition → configurable 1–10 anger score |
| **XML Metadata** | Parses SIPREC XML for caller, callee, participant AORs, session ID |
| **SQLite Index** | All recordings indexed with timestamp, caller, callee, score, transcript — searchable |
| **REST API** | Start/stop recordings, fetch transcript & sentiment, search/query historical records |
| **Retention Policy** | Configurable retention years (default 7); API + cron-based cleanup |
| **Configurable Mapping** | Emotion → score mapping adjustable via `.env` or Admin UI |
| **Web Frontend (Auditor)** | Search by date/time, caller, callee, sentiment; play audio; export recordings |
| **Web Frontend (Admin)** | View/edit system parameters; trigger retention cleanup |

### Architecture (SIPREC SRS — RFC 7866)

```
AudioCodes Mediant SBC (SRC)
      │
      │ SIP INVITE (Multipart MIME: SDP + XML metadata)
      ▼
┌──────────────────────┐     ┌─────────────────────┐
│  sip_stack.py         │────►│  mime_parser.py      │
│  (SIP/UDP :5060)      │     │  • Parse multipart   │
│  • INVITE → 200 OK    │     │  • Extract SDP + XML  │
│  • BYE → 200 OK       │     │  • Extract caller/    │
│  • Dual-stream SDP    │     │    callee metadata   │
└──────────┬───────────┘     └──────────┬──────────┘
           │ streams list                │ metadata
           ▼                             ▼
┌───────────────────────────────────────────────────────┐
│  SessionManager                                        │
│  • Creates 2 RtpSessions (caller RTP / callee RTP)    │
│  • Manages lifecycle                                   │
└──────────┬──────────────┬───────────────┬────────────┘
           │ stream 0      │ stream 1      │
           ▼                ▼               │
┌──────────────────┐ ┌──────────────────┐  │
│  rtp_session 0   │ │  rtp_session 1   │  │
│  (caller voice)  │ │  (callee voice)  │  │
└────────┬─────────┘ └────────┬─────────┘  │
         │ payload            │ payload     │
         ▼                    ▼            │
┌─────────────────────────────────────┐    │
│  AudioProcessor                     │    │
│  • stream 0 → left channel buffer   │    │
│  • stream 1 → right channel buffer  │    │
│  • Combine → Stereo 16-bit WAV      │    │
└──────────────────┬──────────────────┘    │
                   │ WAV file               │
                   ▼                       ▼
┌─────────────────────┐  ┌─────────────────────┐
│  Transcriber         │  │  Indexer             │
│  (Whisper STT)       │  │  (SQLite DB)         │
└──────────┬──────────┘  │  • session_id        │
           │ text        │  • caller/callee      │
           ▼             │  • timestamps         │
┌─────────────────────┐  │  • sentiment score    │
│  Sentiment Analyzer  │  │  • transcript         │
│  (1–10 anger score)  │  │  • wav_path          │
└─────────────────────┘  └─────────────────────┘

┌──────────────────────────────────────────────────────┐
│  FastAPI REST Server (HTTP :8000)                    │
│  ┌──────────────────────────────────────────────┐    │
│  │  /api/v1/record/start · stop/{id} · /record/{id} │  │
│  │  /api/v1/sessions · /api/v1/recordings            │  │
│  │  /api/v1/recordings/{id}/audio  ← play/export    │  │
│  │  /api/v1/admin/settings  ← Admin UI              │  │
│  │  /api/v1/maintenance/cleanup                     │  │
│  └──────────────────────────────────────────────┘    │
│  ┌──────────────────────────────────────────────┐    │
│  │  Web Frontend (/)                             │    │
│  │  ┌─────────────┐  ┌────────────────────┐     │    │
│  │  │  Auditor     │  │  Administrator    │     │    │
│  │  │  • Search    │  │  • View config    │     │    │
│  │  │  • Play      │  │  • Edit params    │     │    │
│  │  │  • Export    │  │  • Run cleanup    │     │    │
│  │  └─────────────┘  └────────────────────┘     │    │
│  └──────────────────────────────────────────────┘    │
│  Swagger UI: /docs                                   │
└──────────────────────────────────────────────────────┘
```

### Quick Start

#### 1. Requirements

| Dependency | Minimum Version | Recommended |
|-----------|----------------|-------------|
| Python | 3.10 | 3.12 |
| ffmpeg | 4.x | 5.x+ (Required for Opus compression) |
| RAM | 4 GB (tiny model) | 16 GB (medium/large) |
| Disk | 10 GB | 50 GB+ |
| OS | Linux (Ubuntu 22.04+, Debian 12+, CentOS 9+) | Ubuntu 24.04 |
| GPU (optional) | NVIDIA+ CUDA 12.x | For faster Whisper inference |
| CUDA Toolkit | 11.8+ (if using GPU) | 12.1 |

#### 2. Installation

```bash
# Install system-level dependencies (ffmpeg)
# On Ubuntu/Debian:
sudo apt update && sudo apt install -y ffmpeg

cd /Projects/idin9-srs

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Upgrade pip
pip install --upgrade pip setuptools wheel

# Install dependencies
pip install -r requirements.txt

# For GPU acceleration (optional):
# pip install torch==2.1.0+cu121 --index-url https://download.pytorch.org/whl/cu121
```

#### 3. Configuration

```bash
cp .env.example .env
# Edit .env with your settings:
nano .env
```

Key configuration parameters:

```ini
# SIPREC receiver
SIP_LISTEN_HOST=0.0.0.0
SIP_LISTEN_PORT=5060

# Whisper model (tiny/base/small/medium/large-v3) — auto-downloaded on first run
WHISPER_MODEL_SIZE=base
WHISPER_CACHE_DIR=                    # optional: set cache path for Whisper model

# Sentiment model (multilingual, supports Thai) — auto-downloaded on first run
SENTIMENT_MODEL=cardiffnlp/twitter-xlm-roberta-base-sentiment
SENTIMENT_MAPPING={"negative":8.0, "neutral":1.0, "positive":1.0}
HF_CACHE_DIR=                         # optional: set cache path for HuggingFace models

# Retention (years). Set 0 to keep all recordings forever.
RETENTION_YEARS=7

# Index database for long-term search
INDEX_DB=index.db
```

#### 4. Run the Server

```bash
# Activate virtual environment
source venv/bin/activate

# Start the server
python run.py

# The server starts:
#   - SIPREC receiver on UDP 0.0.0.0:5060
#   - RTP receiver on UDP ports 10000–10100
#   - REST API on HTTP 0.0.0.0:8000
```

> ⚠️ **Note**: Port 5060 requires root privileges on Linux.
> Use `sudo python run.py` or set `SIP_LISTEN_PORT=15060` in `.env` (non-privileged port).

> 🔑 **API Authentication**: If `API_KEY` is set in `.env`, all API requests must include the header `X-API-Key: your-key`. Health and info endpoints are exempt.

#### 5. Operation Examples

```bash
# Health check (no auth required)
curl http://localhost:8000/api/v1/health

# Start a recording session (with API key if configured)
curl -X POST "http://localhost:8000/api/v1/record/start" \
  ${API_KEY:+-H "X-API-Key: $API_KEY"}
# → {"session_id":"uuid","state":"recording"}

# Stop recording → get transcript + sentiment score
curl -X POST "http://localhost:8000/api/v1/record/stop/{session_id}"
# → {"session_id":"uuid","state":"completed","transcript":"...","sentiment_score":8.5,"sentiment_label":"anger"}

# Get transcript and sentiment for a completed session
curl "http://localhost:8000/api/v1/record/{session_id}"

# Search historical recordings with filters
curl "http://localhost:8000/api/v1/recordings?caller=sip:1000@domain.com&min_sentiment=7&limit=50"

# List active sessions
curl "http://localhost:8000/api/v1/sessions"

# Manual cleanup of old recordings (uses RETENTION_YEARS)
curl -X POST "http://localhost:8000/api/v1/maintenance/cleanup"

# Swagger UI (interactive API docs)
open http://localhost:8000/docs
```

#### 6. Retention & Cleanup

The server indexes recordings in a SQLite database (`recordings/index.db`). All metadata is searchable via the API.

- **Automatic cleanup**: Trigger via `POST /api/v1/maintenance/cleanup`
- **Cron job**: Add to crontab for daily cleanup at 3 AM:

```bash
0 3 * * * /path/to/idin9-srs/scripts/cleanup.sh /path/to/idin9-srs >> /var/log/idin9-srs-cleanup.log 2>&1
```

Set `RETENTION_YEARS=0` in `.env` to keep all recordings indefinitely.

#### 7. AudioCodes SBC Integration

1. Log into AudioCodes SBC Web Interface
2. Configure SIP Recording to point to this server's IP on UDP port 5060
3. Ensure codecs PCMU (G.711 μ-law) or PCMA (G.711 A-law) are enabled
4. The SBC sends SIP INVITE → server responds with 200 OK + RTP port
5. Audio flows automatically

#### 8. API Endpoints Summary

| Method | Path | Description | Query Params |
|--------|------|-------------|-------------|
| POST | `/api/v1/record/start` | Start recording | `caller`, `callee` |
| POST | `/api/v1/record/stop/{id}` | Stop + process transcript/sentiment | — |
| GET | `/api/v1/record/{id}` | Get transcript & sentiment | — |
| GET | `/api/v1/sessions` | List active sessions | — |
| GET | `/api/v1/recordings` | Search indexed recordings | `caller`, `callee`, `start_time_from`, `start_time_to`, `min_sentiment`, `max_sentiment`, `limit`, `offset` |
| GET | `/api/v1/recordings/{id}/audio` | Play/download audio file (Opus/WAV, decrypted on-the-fly) | — |
| GET | `/api/v1/admin/settings` | View all configuration | — |
| PUT | `/api/v1/admin/settings` | Update configuration (save to override file) | — |
| POST | `/api/v1/maintenance/cleanup` | Trigger retention cleanup | — |
| GET | `/api/v1/health` | Health check | — |
| GET | `/` | Web Frontend (Auditor + Admin UI) | — |
| GET | `/docs` | Swagger UI | — |

#### 9. Production Deployment

```bash
# Using systemd (recommended)
sudo cp scripts/idin9-srs.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now idin9-srs
```

#### 10. Web Frontend (Auditor &amp; Administrator)

The server includes a built-in web UI at `http://localhost:8000/`.

**Auditor Panel** — Search, listen, and export recordings:
- Filter by date/time range, caller, callee, sentiment score
- Play audio directly in the browser (HTML5 player)
- Download the original audio file (Opus/WAV, decrypted on-the-fly)
- Table shows: date/time, caller, callee, duration, sentiment badge

**Administrator Panel** — View and edit system parameters:
- View current configuration (SIP ports, RTP range, Whisper model, etc.)
- Edit sentiment mapping (emotion → score JSON) — applies immediately
- Edit retention years — applies immediately
- Edit Whisper model size/device — requires restart
- Trigger retention cleanup manually

**Note:** The Admin UI saves changes to `config.override.json` in the project root. Some parameters (SIP port, RTP ports, Whisper model) require a server restart to take effect.

```
Project Root
├── config.override.json   ← Written by Admin UI; loaded on startup
├── static/                ← Frontend (HTML, CSS, JS)
│   ├── index.html
│   ├── style.css
│   └── app.js
```

#### 11. Resource Management

- **Indexing**: Every completed recording is stored in `recordings/index.db` with session_id, caller, callee, start/end timestamps, sentiment score, and full transcript.
- **Search**: Query by caller, callee, time range, and sentiment score via `GET /api/v1/recordings`.
- **Audio Streaming**: Recordings can be played or downloaded via `GET /api/v1/recordings/{id}/audio`.
- **Retention**: Set `RETENTION_YEARS` in `.env` (default 7 years). Old WAV files can be cleaned via API (`POST /api/v1/maintenance/cleanup`) or cron (`scripts/cleanup.sh`).
- **Backup**: To protect your data:

```bash
tar -czf idin9-srs-backup-$(date +%Y%m%d).tar.gz recordings/ config.override.json
```

#### 12. Sentiment Score Customization &amp; Language Support

**Default model** is `cardiffnlp/twitter-xlm-roberta-base-sentiment` — a **multilingual** model supporting Thai, English, and 40+ languages. It returns 3 labels: `negative`, `neutral`, `positive`.

**For English calls** with richer emotion detail (anger, disgust, fear, joy, sadness, surprise), switch to:

```ini
SENTIMENT_MODEL=j-hartmann/emotion-english-distilroberta-base
SENTIMENT_MAPPING={"anger":10, "disgust":8, "fear":7, "sadness":5, "surprise":4, "joy":1, "neutral":1}
```

The final score is computed as a weighted average where each detected label pulls the score toward its mapped value based on the model's confidence.

Edit `SENTIMENT_MAPPING` in `.env` to adjust the score for each label:

```ini
# For the multilingual model (Thai + English):
SENTIMENT_MAPPING={"negative":8.0, "neutral":1.0, "positive":1.0}

# Or for custom weighting:
SENTIMENT_MAPPING={"negative":10, "neutral":1, "positive":1}
```

---

## 13. AI Providers

You can choose between **local models** (default, downloaded on first run) or **external cloud/local APIs** for transcription and sentiment analysis.

### Provider Selection

Set these in `.env` to choose your AI backend:

```ini
# Options: local (default), openai, ollama, gemini
TRANSCRIPTION_PROVIDER=local
SENTIMENT_PROVIDER=local
```

### Provider Comparison

| Provider | Transcription | Sentiment | API Key Required | Internet Required |
|----------|--------------|-----------|-----------------|------------------|
| `local` | faster-whisper (~1.5 GB) | HuggingFace XLM-R (~500 MB) | No | No (after download) |
| `openai` | Whisper API | GPT-4o-mini chat | Yes (sk-...) | Yes |
| `ollama` | Ollama Whisper model | Ollama chat model (e.g., llama3.2) | No | No |
| `gemini` | Gemini 2.0 Flash | Gemini 2.0 Flash | Yes (AIza...) | Yes |

### Configuration by Provider

#### Local (default)

Models are **downloaded automatically on first run**. Cache directories are configurable:

```ini
# Whisper model cache (default: ~/.cache/whisper/)
WHISPER_CACHE_DIR=/data/models/whisper
WHISPER_MODEL_SIZE=base          # tiny, base, small, medium, large-v3

# HuggingFace model cache (default: ~/.cache/huggingface/)
HF_CACHE_DIR=/data/models/huggingface
SENTIMENT_MODEL=cardiffnlp/twitter-xlm-roberta-base-sentiment
SENTIMENT_MAPPING={"negative":8.0, "neutral":1.0, "positive":1.0}
```

#### OpenAI

```ini
TRANSCRIPTION_PROVIDER=openai
TRANSCRIPTION_API_KEY=sk-...       # Your OpenAI API key
TRANSCRIPTION_API_MODEL=whisper-1  # Default

SENTIMENT_PROVIDER=openai
SENTIMENT_API_KEY=sk-...           # Reuse same key or separate
SENTIMENT_API_MODEL=gpt-4o-mini    # Default
```

Uses OpenAI's Whisper API for transcription and GPT chat completion for sentiment analysis.

#### Ollama (fully offline — local or remote)

```bash
# Install Ollama: https://ollama.com
ollama pull whisper         # For transcription
ollama pull llama3.2        # For sentiment analysis
```

**Local Ollama** (same machine):

```ini
TRANSCRIPTION_PROVIDER=ollama
TRANSCRIPTION_API_URL=http://localhost:11434
TRANSCRIPTION_API_MODEL=whisper

SENTIMENT_PROVIDER=ollama
SENTIMENT_API_URL=http://localhost:11434
SENTIMENT_API_MODEL=llama3.2
```

**Remote Ollama** (different machine on the network):

```ini
TRANSCRIPTION_PROVIDER=ollama
TRANSCRIPTION_API_URL=http://192.168.1.100:11434
TRANSCRIPTION_API_MODEL=whisper

SENTIMENT_PROVIDER=ollama
SENTIMENT_API_URL=http://192.168.1.100:11434
SENTIMENT_API_MODEL=llama3.2
```

> 💡 **Ollama binds to 127.0.0.1 by default.** To accept remote connections, set the environment variable `OLLAMA_HOST=0.0.0.0` before starting Ollama on the remote machine:
> ```bash
> export OLLAMA_HOST=0.0.0.0
> ollama serve
> ```
> Or add it to the Ollama systemd override:
> ```bash
> sudo systemctl edit ollama.service
> # Add: [Service]
> #      Environment=OLLAMA_HOST=0.0.0.0
> sudo systemctl restart ollama
> ```
> Then verify from the idin9-srs machine: `curl http://192.168.1.100:11434/api/tags`

**Full offload example** — no local AI models needed, everything runs on the remote Ollama machine:

```bash
# On the Ollama server (192.168.1.100):
export OLLAMA_HOST=0.0.0.0
ollama pull whisper
ollama pull llama3.2

# On the idin9-srs machine, .env:
TRANSCRIPTION_PROVIDER=ollama
SENTIMENT_PROVIDER=ollama
TRANSCRIPTION_API_URL=http://192.168.1.100:11434
SENTIMENT_API_URL=http://192.168.1.100:11434
TRANSCRIPTION_API_MODEL=whisper
SENTIMENT_API_MODEL=llama3.2

# No GPU needed on the idin9-srs machine!
# No heavy models downloaded locally.
# The idin9-srs machine only needs CPU + network access to the Ollama server.
```

#### Google Gemini

```ini
TRANSCRIPTION_PROVIDER=gemini
TRANSCRIPTION_API_KEY=AIza...     # Google AI Studio API key
TRANSCRIPTION_API_MODEL=models/gemini-2.0-flash-001  # Default

SENTIMENT_PROVIDER=gemini
SENTIMENT_API_KEY=AIza...         # Reuse same key or separate
SENTIMENT_API_MODEL=models/gemini-2.0-flash-001  # Default
```

### Mixed Provider Example

Use different providers for transcription and sentiment:

```ini
# Transcribe with local Whisper (free, fast)
TRANSCRIPTION_PROVIDER=local
WHISPER_MODEL_SIZE=base

# Analyze sentiment with OpenAI (more nuanced understanding)
SENTIMENT_PROVIDER=openai
SENTIMENT_API_KEY=sk-...
```

### Pre-downloading Local Models for Offline / Docker

```bash
export WHISPER_CACHE_DIR=/data/models/whisper
export HF_HOME=/data/models/huggingface
python run.py
# Wait for both models to load, then Ctrl+C
```

Mount the same cache directories in production to avoid re-downloading.

---

## 14. Upgrade Procedure

### General Upgrade Steps

```bash
# 1. Pull latest code
cd /Projects/idin9-srs
git pull origin main

# 2. Activate virtual environment and update dependencies
source venv/bin/activate
pip install --upgrade -r requirements.txt

# 3. Review and merge new configuration parameters
#    Compare your .env with .env.example to add any new settings.
#    NOTE: Your existing .env will NOT be overwritten.
diff .env .env.example  # see what's new

# 4. Restart the service
sudo systemctl restart idin9-srs
# Or if running manually:
# python run.py
```

### Version Migration Notes

#### Upgrading from v1.0 / v1.1 / v1.2

| Change | Action Required |
|--------|----------------|
| **External AI providers added** (v1.2+) | Add to `.env`: `TRANSCRIPTION_PROVIDER`, `SENTIMENT_PROVIDER`, `TRANSCRIPTION_API_KEY`, `TRANSCRIPTION_API_URL`, `TRANSCRIPTION_API_MODEL`, `SENTIMENT_API_KEY`, `SENTIMENT_API_URL`, `SENTIMENT_API_MODEL`. Default is `local` (no change in behavior). |
| **API key authentication** (v1.2+) | Add `API_KEY=` to `.env`. Leave empty to keep auth disabled. |
| **New `providers.py` module** (v1.2+) | File is auto-imported; no manual action needed. |
| **AI model cache directories** (v1.2+) | Add to `.env`: `WHISPER_CACHE_DIR=`, `HF_CACHE_DIR=`. Leave empty for default paths. |

#### Upgrading from v1.0 / v1.1 (siprec → idin9-srs)

| Change | Action Required |
|--------|----------------|
| **Class renames** — `SiprecServer` → `Idin9SrsServer`, `SiprecProtocol` → `Idin9SrsProtocol` (v1.3) | Python code only; no user action needed. |
| **Function rename** — `extract_siprec_metadata` → `extract_recording_metadata` (v1.3) | Only affects custom code importing this function. |
| **File rename** — `scripts/siprec.service` → `scripts/idin9-srs.service` (v1.3) | Remove old service: `sudo systemctl stop siprec && sudo rm /etc/systemd/system/siprec.service`. Install new one: `sudo cp scripts/idin9-srs.service /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now idin9-srs`. |
| **Log file rename** — `/var/log/siprec-cleanup.log` → `/var/log/idin9-srs-cleanup.log` (v1.3) | Update cron job path if you use one. |

#### Upgrading from v1.2 / v1.3 / 26.06.02

| Change | Action Required |
|--------|----------------|
| **Add OPUS Audio Format support** (26.06.03) | Select Ogg/Opus format inside the Administrator settings card to compress audio utilizing system `ffmpeg`. |
| **AES-256 At-Rest Encryption & On-The-Fly Decryption** (26.06.03) | Toggle AES-256 file encryption at rest inside settings. On-the-fly decryption is handled seamlessly in-memory when playing back or downloading. |
| **Fixed live console log formatting** (26.06.02) | Frontend logs are now formatted with correct newline boundaries. |
| **Fixed SIP BYE ending callback** (26.06.02) | Recording sessions are now correctly stopped and finalized automatically upon SIP BYE termination. |
| **Fixed RTP port allocation leak** (26.06.02) | Allocated ports are properly returned to the port pool upon session completion or cleanup. |
| **Admin UI supports AI provider config** (26.06.00) | Frontend auto-updates; no action needed. Go to the Administrator tab to see new fields. |
| **Removed `POST /record/start`** (26.06.00) | Remove any scripts calling this deprecated endpoint. Sessions are created only by SIP INVITE. |
| **UUID validation on session_id** (26.06.00) | API now rejects non-UUID session IDs. Ensure clients use the UUID format returned by the system. |
| **`from fastapi.responses import FileResponse` moved** (26.06.00) | Only affects custom API code importing from the wrong location. |
| **Version format changed** (26.06.01) | Version now uses `year.month.revision` format (e.g., 26.06.01). |
| **Feature toggles for transcript/sentiment** (26.06.01) | Add `TRANSCRIPTION_ENABLED=true` and `SENTIMENT_ENABLED=true` to `.env`. Default is `true` (no change in behavior). Toggle via Admin UI or `.env`. |

### Quick diff of `.env.example` vs your `.env`

After pulling the latest code, run this to see what new configuration parameters are available:

```bash
cd /Projects/idin9-srs
grep -v '^\s*#' .env.example | grep -v '^\s*$' | cut -d= -f1 | while read key; do
  grep -q "^${key}=" .env 2>/dev/null || echo "MISSING: $key"
done
```

Any parameter shown as `MISSING` can be added to your `.env` with its default value from `.env.example`.
