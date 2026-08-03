import asyncio
import os
import logging
from typing import Optional

from . import providers

logger = logging.getLogger(__name__)


class Transcriber:
    def __init__(
        self,
        provider: str = "local",
        api_key: str = "",
        api_url: str = "",
        api_model: str = "",
        model_size: str = "base",
        device: str = "auto",
        compute_type: str = "auto",
        cache_dir: Optional[str] = None,
    ):
        self._provider = provider
        self._api_key = api_key
        self._api_url = api_url
        self._api_model = api_model
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.cache_dir = cache_dir
        self._local_model = None
        self._hf_pipeline = None
        self._model_type = None  # "whisper" or "hf"

        if cache_dir:
            os.environ["WHISPER_CACHE_DIR"] = cache_dir

    @property
    def provider(self) -> str:
        from .config import settings as cfg
        return cfg.transcription_provider

    @property
    def api_key(self) -> str:
        from .config import settings as cfg
        return cfg.transcription_api_key

    @property
    def api_url(self) -> str:
        from .config import settings as cfg
        return cfg.transcription_api_url

    @property
    def api_model(self) -> str:
        from .config import settings as cfg
        return cfg.transcription_api_model

    async def load_model(self):
        if self.provider != "local":
            logger.info(
                "Using external transcription provider: %s (model=%s)",
                self.provider,
                self.api_model or "default",
            )
            return
        if self._local_model is not None or self._hf_pipeline is not None:
            return

        try:
            loop = asyncio.get_event_loop()

            def _load():
                logger.info(
                    "Loading local ASR model %s (device=%s, compute=%s, cache=%s)",
                    self.model_size,
                    self.device,
                    self.compute_type,
                    self.cache_dir or "default",
                )
                whisper_sizes = {"tiny", "base", "small", "medium", "large-v1", "large-v2", "large-v3", "tiny.en", "base.en", "small.en", "medium.en"}
                is_whisper_size = self.model_size.lower() in whisper_sizes or "ct2" in self.model_size.lower()
                is_qwen = "qwen" in self.model_size.lower()

                if not is_whisper_size and (is_qwen or "/" in self.model_size):
                    try:
                        from transformers import pipeline
                        device_arg = 0 if self.device == "cuda" else (-1 if self.device == "cpu" else "auto")
                        try:
                            self._hf_pipeline = pipeline(
                                "automatic-speech-recognition",
                                model=self.model_size,
                                trust_remote_code=True,
                                device_map=device_arg if device_arg != "auto" else "auto"
                            )
                        except Exception:
                            self._hf_pipeline = pipeline(
                                "automatic-speech-recognition",
                                model=self.model_size,
                                trust_remote_code=True
                            )
                        self._model_type = "hf"
                        logger.info("HuggingFace ASR pipeline (%s) loaded successfully", self.model_size)
                        return
                    except Exception as e:
                        logger.warning("HuggingFace ASR pipeline load failed for %s: %s", self.model_size, e)

                # Try faster-whisper
                try:
                    from faster_whisper import WhisperModel
                    kwargs = {
                        "model_size_or_path": self.model_size,
                        "device": self.device,
                        "compute_type": self.compute_type,
                    }
                    if self.cache_dir:
                        kwargs["download_root"] = self.cache_dir
                    self._local_model = WhisperModel(**kwargs)
                    self._model_type = "whisper"
                    logger.info("Whisper CTranslate2 model (%s) loaded successfully", self.model_size)
                except Exception as e:
                    logger.error("Failed to load local ASR model %s: %s", self.model_size, e)

            await loop.run_in_executor(None, _load)
        except Exception as e:
            logger.error("Error loading transcriber model: %s", e)

    async def transcribe(self, audio_path: str, language: Optional[str] = None) -> str:
        if self.provider == "openai":
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                None,
                providers.transcribe_openai,
                audio_path,
                self.api_key,
                self.api_url,
                self.api_model,
            )

        if self.provider == "gemini":
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                None,
                providers.transcribe_gemini,
                audio_path,
                self.api_key,
                self.api_url,
                self.api_model,
            )

        # Local provider
        if self._local_model is None and self._hf_pipeline is None:
            await self.load_model()

        loop = asyncio.get_event_loop()

        def _transcribe():
            if self._model_type == "hf":
                res = self._hf_pipeline(audio_path)
                if isinstance(res, dict):
                    return res.get("text", "")
                elif isinstance(res, list) and res and isinstance(res[0], dict):
                    return " ".join([r.get("text", "") for r in res])
                return str(res)

            kwargs = {"beam_size": 1}
            if language:
                kwargs["language"] = language
            segments, info = self._local_model.transcribe(audio_path, **kwargs)
            text_parts = [seg.text for seg in segments]
            return " ".join(text_parts)

        transcript = await loop.run_in_executor(None, _transcribe)
        return transcript.strip()

    async def transcribe_segments(self, audio_path: str, language: Optional[str] = None) -> list:
        if self.provider != "local":
            text = await self.transcribe(audio_path, language)
            return [(0.0, 0.0, text)] if text else []

        if self._local_model is None and self._hf_pipeline is None:
            await self.load_model()

        loop = asyncio.get_event_loop()

        def _segments():
            if self._model_type == "hf":
                try:
                    res = self._hf_pipeline(audio_path, return_timestamps=True)
                    chunks = res.get("chunks", []) if isinstance(res, dict) else []
                    if chunks:
                        out = []
                        for c in chunks:
                            ts = c.get("timestamp", (0.0, 0.0))
                            s = ts[0] if ts[0] is not None else 0.0
                            e = ts[1] if ts[1] is not None else 0.0
                            out.append((s, e, c.get("text", "").strip()))
                        return out
                except Exception:
                    pass
                text = self._hf_pipeline(audio_path)
                text_str = text.get("text", "") if isinstance(text, dict) else str(text)
                return [(0.0, 0.0, text_str.strip())] if text_str.strip() else []

            kwargs = {"beam_size": 1}
            if language:
                kwargs["language"] = language
            segs, _ = self._local_model.transcribe(audio_path, **kwargs)
            return [(seg.start, seg.end, seg.text.strip()) for seg in segs if seg.text.strip()]

        return await loop.run_in_executor(None, _segments)
