import json
from pydantic_settings import BaseSettings
from typing import Dict


class Settings(BaseSettings):
    sip_listen_host: str = "0.0.0.0"
    sip_listen_port: int = 5060
    rtp_listen_host: str = "0.0.0.0"
    rtp_min_port: int = 7000
    rtp_max_port: int = 7399
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    # API key authentication. If set, all API requests must include X-API-Key header.
    # Leave empty to disable authentication (no API key required).
    api_key: str = ""
    output_dir: str = "recordings"
    audio_format: str = "opus"  # "wav" or "opus"
    encryption_enabled: bool = True
    encryption_password: str = ""

    # ── Transcription Provider ─────────────────────────
    #   local     - faster-whisper (default, runs locally)
    #   openai    - OpenAI Whisper API
    #   ollama    - Ollama local API (requires whisper model in Ollama)
    #   gemini    - Google Gemini API
    transcription_provider: str = "local"
    transcription_api_key: str = ""
    # Base URL for provider API. Defaults:
    #   openai: https://api.openai.com/v1
    #   ollama: http://localhost:11434
    #   gemini: https://generativelanguage.googleapis.com/v1
    transcription_api_url: str = ""
    # Model name passed to the provider:
    #   openai: whisper-1 (default)
    #   ollama: whisper (default)
    #   gemini: models/gemini-2.0-flash-001 (default)
    transcription_api_model: str = ""

    # ── Sentiment Provider ──────────────────────────────
    #   local     - HuggingFace transformer (default, runs locally)
    #   openai    - OpenAI chat completion
    #   ollama    - Ollama local API
    #   gemini    - Google Gemini API
    sentiment_provider: str = "local"
    sentiment_api_key: str = ""
    # Base URL for provider API. Defaults:
    #   openai: https://api.openai.com/v1
    #   ollama: http://localhost:11434
    #   gemini: https://generativelanguage.googleapis.com/v1
    sentiment_api_url: str = ""
    # Model name passed to the provider:
    #   openai: gpt-4o-mini (default)
    #   ollama: llama3.2 (default)
    #   gemini: models/gemini-2.0-flash-001 (default)
    sentiment_api_model: str = ""

    # ── Whisper (Local) ─────────────────────────────────
    whisper_model_size: str = "base"
    whisper_device: str = "auto"
    whisper_compute_type: str = "auto"
    whisper_cache_dir: str = ""
    whisper_language: str = ""

    # ── Sentiment (Local) ───────────────────────────────
    #   English emotion: j-hartmann/emotion-english-distilroberta-base
    #   Multilingual (Thai support): cardiffnlp/twitter-xlm-roberta-base-sentiment
    sentiment_model: str = "cardiffnlp/twitter-xlm-roberta-base-sentiment"
    sentiment_mapping: str = '{"negative":8.0, "neutral":1.0, "positive":1.0}'
    hf_cache_dir: str = ""

    # ── Feature Toggles ──────────────────────────────────
    transcription_enabled: bool = True
    sentiment_enabled: bool = True

    # ── Authentication ──────────────────────────────────
    auth_mode: str = "local" # "api_key", "local", "both"
    jwt_secret: str = ""  # MUST set via .env; empty = hard failure on login
    jwt_algorithm: str = "HS256"
    jwt_expiry_hours: int = 24

    # ── Regional & Display ───────────────────────────────
    timezone: str = "UTC"
    locale: str = "en_US"
    font_family: str = "system"
    datetime_format: str = "system"

    # ── Retention ───────────────────────────────────────
    retention_years: int = 7
    index_db: str = "index.db"

    # ── Session Timeout ─────────────────────────────────
    session_timeout_seconds: int = 300

    def get_sentiment_mapping(self) -> Dict[str, float]:
        try:
            return json.loads(self.sentiment_mapping)
        except json.JSONDecodeError:
            return {"anger":10, "disgust":8, "fear":7, "sadness":5, "surprise":4, "joy":1, "neutral":1}

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
