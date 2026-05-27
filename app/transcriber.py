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
        self.provider = provider
        self.api_key = api_key
        self.api_url = api_url
        self.api_model = api_model
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.cache_dir = cache_dir
        self._local_model = None

        if cache_dir:
            os.environ["WHISPER_CACHE_DIR"] = cache_dir

    async def load_model(self):
        if self.provider != "local":
            logger.info(
                "Using external transcription provider: %s (model=%s)",
                self.provider,
                self.api_model or "default",
            )
            return
        if self._local_model is not None:
            return
        from faster_whisper import WhisperModel

        loop = asyncio.get_event_loop()

        def _load():
            logger.info(
                "Loading Whisper model %s (device=%s, compute=%s, cache=%s)",
                self.model_size,
                self.device,
                self.compute_type,
                self.cache_dir or "default",
            )
            kwargs = {
                "model_size_or_path": self.model_size,
                "device": self.device,
                "compute_type": self.compute_type,
            }
            if self.cache_dir:
                kwargs["download_root"] = self.cache_dir
            self._local_model = WhisperModel(**kwargs)
            logger.info("Whisper model loaded")

        await loop.run_in_executor(None, _load)

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

        if self.provider == "ollama":
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                None,
                providers.transcribe_ollama,
                audio_path,
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
        if self._local_model is None:
            await self.load_model()

        loop = asyncio.get_event_loop()

        def _transcribe():
            kwargs = {"beam_size": 5}
            if language:
                kwargs["language"] = language
            segments, info = self._local_model.transcribe(audio_path, **kwargs)
            text_parts = [seg.text for seg in segments]
            return " ".join(text_parts)

        transcript = await loop.run_in_executor(None, _transcribe)
        return transcript.strip()
