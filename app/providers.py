import base64
import json
import logging
import mimetypes
import os
import uuid
from urllib.parse import urljoin
from urllib.request import Request, urlopen
from urllib.error import URLError

logger = logging.getLogger(__name__)

# ── Default API base URLs ──────────────────────────────
OPENAI_API_BASE = "https://api.openai.com/v1"
OLLAMA_API_BASE = "http://localhost:11434"
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1"


def _build_headers(api_key: str = "") -> dict:
    headers = {"User-Agent": "idin9-srs/1.1"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _json_request(url: str, data: dict, headers: dict) -> dict:
    body = json.dumps(data).encode("utf-8")
    req = Request(url, data=body, headers={**headers, "Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except URLError as e:
        logger.error("API request failed: %s %s", url, e)
        raise
    except json.JSONDecodeError as e:
        logger.error("API response parse failed: %s", e)
        raise


def _build_multipart_form(fields: dict, file_field: str, file_path: str, file_field_name: str = "file") -> tuple:
    boundary = uuid.uuid4().hex
    lines = []
    for key, value in fields.items():
        lines.append(f"--{boundary}".encode())
        lines.append(f'Content-Disposition: form-data; name="{key}"'.encode())
        lines.append(b"")
        lines.append(str(value).encode("utf-8"))
    lines.append(f"--{boundary}".encode())
    filename = os.path.basename(file_path)
    content_type, _ = mimetypes.guess_type(file_path)
    if content_type is None:
        content_type = "application/octet-stream"
    lines.append(
        f'Content-Disposition: form-data; name="{file_field_name}"; filename="{filename}"'.encode()
    )
    lines.append(f"Content-Type: {content_type}".encode())
    lines.append(b"")
    with open(file_path, "rb") as f:
        lines.append(f.read())
    lines.append(f"--{boundary}--".encode())
    lines.append(b"")
    body = b"\r\n".join(lines)
    content_type_header = f"multipart/form-data; boundary={boundary}"
    return body, content_type_header


# ── Transcription ───────────────────────────────────────

def transcribe_openai(audio_path: str, api_key: str, api_url: str, model: str) -> str:
    base = api_url.strip() or OPENAI_API_BASE
    url = urljoin(base.rstrip("/") + "/", "audio/transcriptions")
    body, ct = _build_multipart_form(
        fields={"model": model or "whisper-1", "response_format": "json"},
        file_field="file",
        file_path=audio_path,
    )
    headers = _build_headers(api_key)
    headers["Content-Type"] = ct
    req = Request(url, data=body, headers=headers, method="POST")
    try:
        with urlopen(req, timeout=300) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        return result.get("text", "")
    except URLError as e:
        logger.error("OpenAI transcription failed: %s", e)
        raise


def transcribe_ollama(audio_path: str, api_url: str, model: str) -> str:
    base = api_url.strip() or OLLAMA_API_BASE
    url = urljoin(base.rstrip("/") + "/", "api/generate")
    with open(audio_path, "rb") as f:
        audio_b64 = base64.b64encode(f.read()).decode("utf-8")
    payload = {
        "model": model or "whisper",
        "prompt": "",
        "audio": audio_b64,
    }
    headers = _build_headers()
    result = _json_request(url, payload, headers)
    return result.get("response", "").strip()


def transcribe_gemini(audio_path: str, api_key: str, api_url: str, model: str) -> str:
    base = api_url.strip() or GEMINI_API_BASE
    model_name = model or "models/gemini-2.0-flash-001"
    url = f"{base.rstrip('/')}/{model_name}:generateContent"
    with open(audio_path, "rb") as f:
        audio_b64 = base64.b64encode(f.read()).decode("utf-8")
    payload = {
        "contents": [{
            "parts": [
                {"inline_data": {"mime_type": "audio/wav", "data": audio_b64}},
                {"text": "Transcribe the speech in this audio exactly as spoken. Return only the transcribed text."},
            ]
        }]
    }
    headers = _build_headers(api_key)
    result = _json_request(url, payload, headers)
    try:
        parts = result["candidates"][0]["content"]["parts"]
        return " ".join(p["text"] for p in parts if "text" in p).strip()
    except (KeyError, IndexError):
        logger.error("Unexpected Gemini response: %s", result)
        return ""


# ── Sentiment Analysis ──────────────────────────────────

SENTIMENT_SYSTEM_PROMPT = (
    "You are a sentiment analyst. Analyze the emotional tone of the following "
    "transcribed conversation. Respond with a JSON object containing two fields:\n"
    '  "sentiment": a single word describing the overall emotion '
    "(e.g., anger, joy, sadness, fear, neutral, surprise, disgust)\n"
    '  "score": a number between 1 and 10, where 1 = very calm/positive, '
    "5 = neutral, and 10 = extremely angry/negative\n"
    "Return ONLY valid JSON, no other text."
)


def _parse_sentiment_response(text: str) -> dict:
    text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("{") and line.endswith("}"):
                try:
                    data = json.loads(line)
                    break
                except json.JSONDecodeError:
                    continue
        else:
            logger.warning("Could not parse sentiment response: %s", text[:200])
            return {"score": 5.0, "sentiment": "neutral"}

    score = float(data.get("score", 5.0))
    score = max(1.0, min(10.0, score))
    sentiment = str(data.get("sentiment", "neutral")).lower()
    return {"score": score, "sentiment": sentiment}


def sentiment_openai(text: str, api_key: str, api_url: str, model: str) -> dict:
    base = api_url.strip() or OPENAI_API_BASE
    url = urljoin(base.rstrip("/") + "/", "chat/completions")
    payload = {
        "model": model or "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": SENTIMENT_SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
        "temperature": 0.1,
        "max_tokens": 200,
    }
    headers = _build_headers(api_key)
    result = _json_request(url, payload, headers)
    try:
        content = result["choices"][0]["message"]["content"]
    except (KeyError, IndexError):
        logger.error("Unexpected OpenAI chat response: %s", result)
        return {"score": 5.0, "sentiment": "neutral"}
    return _parse_sentiment_response(content)


def sentiment_ollama(text: str, api_url: str, model: str) -> dict:
    base = api_url.strip() or OLLAMA_API_BASE
    url = urljoin(base.rstrip("/") + "/", "api/chat")
    payload = {
        "model": model or "llama3.2",
        "messages": [
            {"role": "system", "content": SENTIMENT_SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
        "stream": False,
        "options": {"temperature": 0.1},
    }
    headers = _build_headers()
    result = _json_request(url, payload, headers)
    content = result.get("message", {}).get("content", "")
    return _parse_sentiment_response(content)


def sentiment_gemini(text: str, api_key: str, api_url: str, model: str) -> dict:
    base = api_url.strip() or GEMINI_API_BASE
    model_name = model or "models/gemini-2.0-flash-001"
    url = f"{base.rstrip('/')}/{model_name}:generateContent"
    payload = {
        "contents": [{
            "parts": [{"text": f"{SENTIMENT_SYSTEM_PROMPT}\n\n{text}"}]
        }],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 200,
        },
    }
    headers = _build_headers(api_key)
    result = _json_request(url, payload, headers)
    try:
        parts = result["candidates"][0]["content"]["parts"]
        content = " ".join(p["text"] for p in parts if "text" in p)
    except (KeyError, IndexError):
        logger.error("Unexpected Gemini response: %s", result)
        return {"score": 5.0, "sentiment": "neutral"}
    return _parse_sentiment_response(content)
