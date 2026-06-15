# idin9-srs (ภาษาไทย)

> [English Version](README.en.md)

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115%2B-009688)](https://fastapi.tiangolo.com/)
[![License](https://img.shields.io/badge/License-MIT-green)]()
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED)]()

**เวอร์ชัน:** 26.06.03  |
**ผู้พัฒนา:** Kanit Klai-Udom  |
**ติดต่อ:** [www.idin9.com](https://www.idin9.com)  
**ลิขสิทธิ์:** MIT

---

## สารบัญ

- [ภาพรวมระบบ](#ภาพรวมระบบ)
- [สถาปัตยกรรม](#สถาปัตยกรรม)
- [ความต้องการของระบบ](#ความต้องการของระบบ)
- [การติดตั้ง](#การติดตั้ง)
- [การตั้งค่า AudioCodes SBC](#การตั้งค่า-audiocodes-sbc)
- [การเรียกใช้งาน](#การเรียกใช้งาน)
- [API Reference](#api-reference)
- [โครงสร้างโปรเจกต์](#โครงสร้างโปรเจกต์)
- [การปรับแต่ง](#การปรับแต่ง)
- [การอัปเกรด](#ขั้นตอนการอัปเกรด)
- [การแก้ไขปัญหา](#การแก้ไขปัญหา)
- [การ Deploy แบบ Production](#การ-deploy-แบบ-production)

---

## ภาพรวมระบบ

แอปพลิเคชันนี้ทำหน้าที่เป็น **SIPREC Recording Server** ที่รับสายจาก AudioCodes SBC เพื่อ:

1. **บันทึกเสียงสนทนา** — รับ RTP audio stream ผ่าน SIPREC protocol
2. **ถอดเสียงเป็นข้อความ** — ใช้ Whisper model ของ OpenAI (faster-whisper) แปลงเสียงเป็นข้อความภาษาไทย/อังกฤษ
3. **วิเคราะห์อารมณ์** — ใช้โมเดล Emotion Recognition จาก HuggingFace ให้คะแนนความรู้สึก โดยเฉพาะระดับความโกรธ
4. **ให้คะแนนความโกรธ 1–10**:
   - `1` = สงบ เป็นกลาง มีความสุข
   - `5` = เศร้า กลัว
   - `8–10` = โกรธ รุนแรง

---

## สถาปัตยกรรม

```
AudioCodes SBC
      │
      │ SIP INVITE (SIPREC)
      ▼
┌─────────────────┐     ┌─────────────────┐
│  SIP Stack      │────►│  Session        │
│  (UDP :5060)    │     │  Manager        │
└─────────────────┘     └─────┬───────────┘
                              │
                    ┌─────────▼─────────┐
                    │  RTP Session      │
                    │  (UDP :10000-     │
                    │   10100)          │
                    └─────────┬─────────┘
                              │ audio payload
                    ┌─────────▼─────────┐
                    │  Audio Processor  │
                    │  (decode PCMU/    │
                    │   PCMA/Opus)      │
                    └─────────┬─────────┘
                              │ WAV file
                    ┌─────────▼─────────┐
                    │  Transcriber      │
                    │  (Whisper STT)    │
                    └─────────┬─────────┘
                              │ text
                    ┌─────────▼─────────┐
                    │ Sentiment         │
                    │ Analyzer          │
                    │ (1-10 score)      │
                    └───────────────────┘

┌─────────────────────────────────────┐
│  FastAPI REST API (:8000)           │
│  POST /record/start                 │
│  POST /record/stop/{id}             │
│  GET  /record/{id}                  │
│  GET  /sessions                     │
└─────────────────────────────────────┘
```

---

## ความต้องการของระบบ

### Hardware
- CPU: 4 cores ขึ้นไป (แนะนำ 8 cores สำหรับ Whisper real-time)
- RAM: 8 GB ขึ้นไป (แนะนำ 16 GB)
- Storage: 50 GB ขึ้นไปสำหรับเก็บไฟล์เสียง
- Network: การเข้าถึงพอร์ต UDP 5060 และช่วงพอร์ต 10000-10100

### Software
- **OS**: Linux (Ubuntu 22.04+, Debian 12+), macOS, หรือ Windows WSL2
- **Python**: 3.10 ขึ้นไป
- **ffmpeg**: แนะนำ version 5.x ขึ้นไป (จำเป็นสำหรับการบีบอัดเสียงแบบ Opus)
- **CUDA** (optional): สำหรับเร่งความเร็ว Whisper ด้วย GPU

---

## การติดตั้ง

### 1. ติดตั้ง ffmpeg (System-level dependency)

```bash
# สำหรับ Ubuntu / Debian:
sudo apt update && sudo apt install -y ffmpeg
```

### 2. โคลนโปรเจกต์

```bash
cd /Projects/idin9-srs
```

### 3. สร้าง Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate   # Linux/macOS
# venv\Scripts\activate    # Windows
```

### 4. ติดตั้ง Dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

หากมี GPU NVIDIA และต้องการใช้ CUDA:

```bash
pip install torch==2.1.0+cu121 --index-url https://download.pytorch.org/whl/cu121
pip install -r requirements.txt
```

### 5. ตั้งค่า Configuration

```bash
cp .env.example .env
```

แก้ไขไฟล์ `.env` ตามสภาพแวดล้อมของคุณ:

```ini
# SIPREC Server
SIP_LISTEN_HOST=0.0.0.0
SIP_LISTEN_PORT=5060

# RTP
RTP_LISTEN_HOST=0.0.0.0
RTP_MIN_PORT=10000
RTP_MAX_PORT=10100

# API
API_HOST=0.0.0.0
API_PORT=8000

# Whisper Model
# model size: tiny, base, small, medium, large-v3
# เลือก model ตามทรัพยากร:
#   tiny   = เร็วที่สุด, แม่นยำน้อยที่สุด (~1GB RAM)
#   base   = สมดุล (~1.5GB RAM) ✅ แนะนำ
#   small  = แม่นยำขึ้น (~2.5GB RAM)
#   medium = แม่นยำมาก (~5GB RAM)
#   large  = แม่นยำที่สุด (~10GB RAM)
WHISPER_MODEL_SIZE=base
WHISPER_DEVICE=auto       # auto = ใช้ GPU ถ้ามี, cpu ถ้าไม่มี
WHISPER_COMPUTE_TYPE=auto # auto = float16 สำหรับ GPU, int8 สำหรับ CPU

# Sentiment Model
SENTIMENT_MODEL=j-hartmann/emotion-english-distilroberta-base

# Output directory สำหรับไฟล์เสียง .wav
OUTPUT_DIR=recordings
```

---

## การตั้งค่า AudioCodes SBC

### ขั้นตอนการตั้งค่า SIPREC บน AudioCodes SBC

1. **เข้าสู่ระบบ Web Interface** ของ AudioCodes SBC

2. **ไปที่ Configuration > VoIP > SIP Definitions > Proxy Sets**
   - เพิ่ม Proxy Set ใหม่
   - ใส่ IP Address ของเซิร์ฟเวอร์นี้ (ที่รัน idin9-srs)
   - พอร์ต: 5060 (UDP)

3. **ไปที่ Configuration > VoIP > SIP Definitions > IP Groups**
   - สร้าง IP Group ใหม่สำหรับ Recording Server
   - ประเภท: Server
   - Proxy Set: เลือกที่สร้างในขั้นตอน 2

4. **ไปที่ Configuration > VoIP > Coders**
   - ตรวจสอบว่าเปิดใช้ PCMU (G.711 μ-law), PCMA (G.711 A-law) อย่างน้อยหนึ่งตัว

5. **ไปที่ Configuration > VoIP > SIP Recording**
   - เปิดใช้งาน SIP Recording
   - ตั้งค่า Recording Server IP: IP ของเซิร์ฟเวอร์นี้
   - ตั้งค่า Recording Port: 5060
   - เลือก Recording Trigger: ตามความต้องการ (Always / On Demand)

6. **บันทึกและ Apply** การตั้งค่า

### ตรวจสอบการเชื่อมต่อ

AudioCodes SBC จะส่ง SIP INVITE ไปยังเซิร์ฟเวอร์เมื่อมีการสนทนาที่ต้องการบันทึก
คุณควรเห็น log ประมาณนี้:

```
INFO app.sip_stack: SIPREC server listening on udp 0.0.0.0:5060
INFO app.sip_stack: Received INVITE from ('192.168.1.100', 5060)
INFO app.sip_stack: Sent 200 OK for call abc123 on RTP port 10000
```

---

## การเรียกใช้งาน

### เริ่มต้นเซิร์ฟเวอร์

```bash
cd /Projects/idin9-srs
source venv/bin/activate
python run.py
```

เซิร์ฟเวอร์จะเริ่มทำงาน:
- **SIPREC Server**: UDP port 5060 (รับ SIP INVITE จาก SBC)
- **RTP Receiver**: UDP ports 10000-10100 (รับเสียง)
- **REST API**: HTTP port 8000

### เริ่มบันทึกด้วย API

```bash
# เริ่มบันทึก (สำหรับกรณี On-Demand)
curl -X POST "http://localhost:8000/api/v1/record/start"

# Response:
# {"session_id":"abc-123-def","state":"recording"}
```

### หยุดบันทึกและดึงผลลัพธ์

```bash
# หยุดบันทึก session abc-123-def
curl -X POST "http://localhost:8000/api/v1/record/stop/abc-123-def"

# Response:
# {
#   "session_id": "abc-123-def",
#   "state": "completed",
#   "transcript": "I'm very frustrated with this service...",
#   "sentiment_score": 8.5,
#   "sentiment_label": "anger"
# }
```

### ดึงข้อมูล Session

```bash
# ดู transcript และ sentiment score
curl "http://localhost:8000/api/v1/record/abc-123-def"

# ดูรายการ session ทั้งหมด
curl "http://localhost:8000/api/v1/sessions"
```

### ตรวจสอบสุขภาพระบบ

```bash
curl "http://localhost:8000/api/v1/health"
# {"status": "ok"}
```

### Swagger UI

เปิดเบราว์เซอร์ไปที่: [http://localhost:8000/docs](http://localhost:8000/docs)

---

## API Reference

### `POST /api/v1/record/start`

เริ่มบันทึกใหม่

**Parameters (query):**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| caller | string | ไม่ | หมายเลขผู้โทร |
| callee | string | ไม่ | หมายเลขผู้รับสาย |

**Response `200`:**

```json
{
  "session_id": "uuid-string",
  "state": "recording"
}
```

---

### `POST /api/v1/record/stop/{session_id}`

หยุดบันทึกและประมวลผล (ถอดเสียง + วิเคราะห์อารมณ์)

**Path Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| session_id | string | ID ของ session ที่ต้องการหยุด |

**Response `200`:**

```json
{
  "session_id": "uuid-string",
  "state": "completed",
  "transcript": "ข้อความที่ถอดเสียงได้",
  "sentiment_score": 7.2,
  "sentiment_label": "anger"
}
```

---

### `GET /api/v1/record/{session_id}`

ดึงผลลัพธ์ transcript และ sentiment score ของ session

**Path Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| session_id | string | ID ของ session |

**Response `200`:**

```json
{
  "session_id": "uuid-string",
  "transcript": "ข้อความที่ถอดเสียงได้",
  "sentiment_score": 7.2,
  "sentiment_label": "anger"
}
```

**Response `404`:**

```json
{
  "detail": "Session abc not found"
}
```

---

### `GET /api/v1/sessions`

แสดงรายการ session ทั้งหมด

**Response `200`:**

```json
[
  {
    "session_id": "abc-123",
    "caller": "<sip:1000@domain.com>",
    "callee": "<sip:2000@domain.com>",
    "state": "completed",
    "sentiment_score": 8.5,
    "sentiment_label": "anger",
    "transcript": "I'm very frustrated..."
  }
]
```

---

### `GET /api/v1/health`

ตรวจสอบสถานะเซิร์ฟเวอร์

**Response `200`:**

```json
{
  "status": "ok"
}
```

---

## โครงสร้างโปรเจกต์

```
idin9-srs/
├── .env                    # ไฟล์ตั้งค่า (ไม่รวมใน git)
├── .env.example            # ตัวอย่างไฟล์ตั้งค่า
├── .gitignore
├── requirements.txt        # รายการแพ็กเกจที่ต้องติดตั้ง
├── run.py                  # จุดเริ่มต้นแอปพลิเคชัน
├── README.md               # เอกสารดัชนีนำทาง
├── README.en.md            # เอกสารภาษาอังกฤษ
├── README.th.md            # เอกสารภาษาไทย
├── recordings/             # โฟลเดอร์เก็บไฟล์เสียง .wav
└── app/
    ├── __init__.py
    ├── main.py             # FastAPI app, lifecycle management
    ├── config.py           # โหลดค่าจาก .env
    ├── models.py           # Pydantic models สำหรับ API
    ├── api.py              # REST API routes
    ├── sip_stack.py        # SIP/UDP server สำหรับรับ SIPREC
    ├── rtp_session.py      # จัดการ RTP stream
    ├── audio_processor.py  # ถอดรหัส audio codec และแปลงเป็น WAV
    ├── transcriber.py      # Whisper speech-to-text
    ├── sentiment_analyzer.py # วิเคราะห์อารมณ์ (1-10)
    └── session_manager.py  # จัดการ lifecycle ของ session
```

---

## การปรับแต่ง

### เปลี่ยนโมเดล Whisper

แก้ไขใน `.env`:

```ini
WHISPER_MODEL_SIZE=medium  # tiny, base, small, medium, large-v3
```

ขนาดโมเดล vs ความแม่นยำ vs ทรัพยากร:

| Model | RAM | ความเร็ว | ความแม่นยำ |
|-------|-----|---------|-----------|
| tiny | ~1GB | เร็วมาก | พอใช้ |
| base | ~1.5GB | เร็ว | ดี |
| small | ~2.5GB | ปานกลาง | ดีมาก |
| medium | ~5GB | ช้า | ดีเยี่ยม |
| large-v3 | ~10GB | ช้ามาก | ดีที่สุด |

### เปลี่ยนโมเดล Sentiment Analysis

ค่าเริ่มต้นเป็นโมเดล multilingual (`cardiffnlp/twitter-xlm-roberta-base-sentiment`) ที่รองรับภาษาไทย:

```ini
SENTIMENT_MODEL=cardiffnlp/twitter-xlm-roberta-base-sentiment
SENTIMENT_MAPPING={"negative":8.0, "neutral":1.0, "positive":1.0}
```

สำหรับภาษาอังกฤษที่ต้องการอารมณ์ที่ละเอียดขึ้น (7 อย่าง):

```ini
SENTIMENT_MODEL=j-hartmann/emotion-english-distilroberta-base
SENTIMENT_MAPPING={"anger":10, "disgust":8, "fear":7, "sadness":5, "surprise":4, "joy":1, "neutral":1}
```

โมเดลอื่นๆ ที่แนะนำ:
- `bhadresh-savani/distilbert-base-uncased-emotion`
- `SamLowe/roberta-base-go_emotions`

### เลือก AI Provider

ระบบรองรับ **4 providers** สำหรับทั้งการถอดเสียง (transcription) และวิเคราะห์อารมณ์ (sentiment):

```ini
# local (ค่าเริ่มต้น, ดาวน์โหลดโมเดลครั้งแรก), openai, ollama, gemini
TRANSCRIPTION_PROVIDER=local
SENTIMENT_PROVIDER=local
```

| Provider | Transcription | Sentiment | ต้องใช้ API Key | ต้องใช้อินเทอร์เน็ต |
|----------|--------------|-----------|----------------|-------------------|
| `local` | faster-whisper (~1.5 GB) | HuggingFace XLM-R (~500 MB) | ไม่ | ไม่ (หลังดาวน์โหลด) |
| `openai` | Whisper API | GPT-4o-mini | ใช่ (sk-...) | ใช่ |
| `ollama` | Ollama Whisper | Ollama chat (llama3.2) | ไม่ | ไม่ |
| `gemini` | Gemini 2.0 Flash | Gemini 2.0 Flash | ใช่ (AIza...) | ใช่ |

**ตัวอย่างการใช้งานแบบผสม:**

```ini
# ถอดเสียงด้วย local (ฟรี, เร็ว)
TRANSCRIPTION_PROVIDER=local
WHISPER_MODEL_SIZE=base

# วิเคราะห์อารมณ์ด้วย OpenAI (เข้าใจบริบทดีกว่า)
SENTIMENT_PROVIDER=openai
SENTIMENT_API_KEY=sk-...
```

### จัดการ Cache โมเดล AI (กรณีใช้ local provider)

โมเดลทั้งหมดจะ **ดาวน์โหลดอัตโนมัติในครั้งแรกที่รัน** และเก็บไว้ใน cache directory:

```ini
# ตำแหน่งเก็บโมเดล Whisper (ค่าเริ่มต้น: ~/.cache/whisper/)
WHISPER_CACHE_DIR=/data/models/whisper

# ตำแหน่งเก็บโมเดล HuggingFace (ค่าเริ่มต้น: ~/.cache/huggingface/)
HF_CACHE_DIR=/data/models/huggingface
```

| โมเดล | ขนาดดาวน์โหลด |
|-------|--------------|
| Whisper `base` | ~1.5 GB |
| Sentiment (XLM-RoBERTa) | ~500 MB |

### การใช้ GPU

ติดตั้ง PyTorch with CUDA ก่อนติดตั้ง dependencies:

```bash
pip install torch==2.1.0+cu121 --index-url https://download.pytorch.org/whl/cu121
pip install -r requirements.txt
```

ตั้งค่าใน `.env`:

```ini
WHISPER_DEVICE=cuda
WHISPER_COMPUTE_TYPE=float16
```

---

## ขั้นตอนการอัปเกรด

### ขั้นตอนทั่วไป

```bash
# 1. ดึงโค้ดล่าสุด
cd /Projects/idin9-srs
git pull origin main

# 2. อัปเดต dependencies
source venv/bin/activate
pip install --upgrade -r requirements.txt

# 3. ตรวจสอบการตั้งค่าใหม่ใน .env.example เทียบกับ .env ของคุณ
diff .env .env.example

# 4. รีสตาร์ท service
sudo systemctl restart idin9-srs
# หรือถ้ารันด้วย python โดยตรง:
# python run.py
```

### หมายเหตุการอัปเกรดข้ามเวอร์ชัน

#### อัปเกรดจาก v1.0 / v1.1 / v1.2

| การเปลี่ยนแปลง | การดำเนินการ |
|----------------|-------------|
| **เพิ่ม External AI providers** (v1.2+) | เพิ่มใน `.env`: `TRANSCRIPTION_PROVIDER`, `SENTIMENT_PROVIDER`, `TRANSCRIPTION_API_KEY`, `TRANSCRIPTION_API_URL`, `TRANSCRIPTION_API_MODEL`, `SENTIMENT_API_KEY`, `SENTIMENT_API_URL`, `SENTIMENT_API_MODEL` |
| **API key authentication** (v1.2+) | เพิ่ม `API_KEY=` ใน `.env` |
| **AI model cache directories** (v1.2+) | เพิ่มใน `.env`: `WHISPER_CACHE_DIR=`, `HF_CACHE_DIR=` |

#### อัปเกรดจาก v1.2 / v1.3 / 26.06.02

| การเปลี่ยนแปลง | การดำเนินการ |
|----------------|-------------|
| **รองรับฟอร์แมตเสียงแบบ OPUS** (26.06.03) | เลือกบันทึกเสียงแบบ Ogg/Opus ในการตั้งค่าของผู้ดูแลระบบเพื่อประหยัดพื้นที่จัดเก็บเสียงโดยใช้ ffmpeg |
| **การเข้ารหัสไฟล์เสียง AES-256 (At-rest Encryption)** (26.06.03) | เปิดใช้ระบบเข้ารหัสไฟล์เสียงบันทึกด้วยคีย์ลับ และทำการถอดรหัสในหน่วยความจำทันทีแบบ on-the-fly เมื่อมีการกดฟังหรือดาวน์โหลดผ่านเว็บเบราว์เซอร์ |
| **แก้ไขการแสดงผล live console logs** (26.06.02) | แสดงผลบรรทัดข้อความ log บนหน้าเว็บอย่างถูกต้อง |
| **แก้ไข callback การจบสายด้วย SIP BYE** (26.06.02) | รองรับการหยุดบันทึกและรันขั้นตอนการถอดความและวิเคราะห์อารมณ์ทันทีเมื่อคู่สายวางสาย (SIP BYE) |
| **แก้ไขปัญหาพอร์ต RTP รั่วไหล** (26.06.02) | คืนค่า local port ให้กับ port pool เสมอเมื่อจบสายหรือมีการทำลาย session |
| **ยกเลิก `POST /record/start`** (26.06.00) | ลบสคริปต์ที่เรียก endpoint นี้ |
| **ตรวจสอบ UUID session_id** (26.06.00) | API จะปฏิเสธ session_id ที่ไม่ใช่ UUID |
| **เพิ่ม toggle ปิด/เปิด transcript และ sentiment** (26.06.01) | เพิ่ม `TRANSCRIPTION_ENABLED=true` และ `SENTIMENT_ENABLED=true` ใน `.env` |

---

## การแก้ไขปัญหา

### เซิร์ฟเวอร์ไม่สามารถ bind พอร์ต 5060

**สาเหตุ**: ต้องใช้ root/sudo เพื่อเปิด

**วิธีแก้**:

```bash
# ใช้ sudo รัน
sudo python run.py

# หรือเปลี่ยนไปใช้พอร์ตสูงใน .env
SIP_LISTEN_PORT=15060
```

### ไม่ได้รับ INVITE จาก SBC

1. ตรวจสอบ Firewall: เปิด UDP port 5060
2. ตรวจสอบ Network: SBC ต้องสามารถเข้าถึงเซิร์ฟเวอร์นี้ได้
3. ตรวจสอบ SBC log ว่ามีการส่ง SIPREC หรือไม่

### Whisper ทำงานช้า

1. ใช้โมเดลที่เล็กลง: `WHISPER_MODEL_SIZE=tiny`
2. ใช้ GPU: ติดตั้ง CUDA และตั้งค่า `WHISPER_DEVICE=cuda`
3. ลดขนาดตัวอย่างเสียงหรือเพิ่มพลัง CPU

### ไม่มีไฟล์เสียงใน `recordings/`

1. ตรวจสอบว่าได้รับ RTP packets จริง (ดู log)
2. ตรวจสอบว่า AudioCodes SBC ส่ง codec ที่รองรับ (PCMU=0, PCMA=8)
3. ตรวจสอบ log error ของ `audio_processor.py`

### API คืนค่า session not found

Session จะถูกสร้างเมื่อได้รับ SIP INVITE จาก SBC เท่านั้น
การเรียก `POST /record/start` ผ่าน API จะสร้าง session ID แต่ยังไม่มีข้อมูลจริง
จนกว่า SIPREC จะเริ่มส่งเสียงมา

---

## การ Deploy แบบ Production

สำหรับใช้งานจริง แนะนำ:

1. **ใช้ Process Manager**:

```bash
# ติดตั้ง supervisor
sudo apt install supervisor

# สร้างไฟล์ /etc/supervisor/conf.d/idin9-srs.conf
[program:idin9-srs]
command=/home/user/idin9-srs/venv/bin/python run.py
directory=/home/user/idin9-srs
user=root
autostart=true
autorestart=true
```

2. **ใช้ Nginx Reverse Proxy** สำหรับ API:

```nginx
server {
    listen 443 ssl;
    server_name idin9-srs.domain.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

3. **เพิ่มระบบ Authentication** ให้ API endpoints

4. **ตั้งค่า Systemd Service**:

```bash
sudo cp scripts/idin9-srs.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now idin9-srs
```

```bash
sudo systemctl enable idin9-srs
sudo systemctl start idin9-srs
```

---

## License

MIT License
