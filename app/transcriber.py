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
        self._qwen_model = None
        self._qwen_processor = None
        self._model_type = None  # "whisper", "qwen", or "hf"

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
        if self._local_model is not None or self._hf_pipeline is not None or self._qwen_model is not None:
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

                # Handle Qwen3-ASR models specifically
                if is_qwen:
                    try:
                        import torch
                        from transformers import AutoProcessor
                        logger.info("Loading Qwen3-ASR model and processor: %s", self.model_size)
                        self._qwen_processor = AutoProcessor.from_pretrained(self.model_size, trust_remote_code=True)
                        
                        try:
                            from transformers import AutoModelForSpeechSeq2Seq
                            self._qwen_model = AutoModelForSpeechSeq2Seq.from_pretrained(
                                self.model_size,
                                trust_remote_code=True,
                                dtype=torch.float32,
                                low_cpu_mem_usage=True,
                            )
                        except Exception as ex1:
                            logger.info("AutoModelForSpeechSeq2Seq fallback (%s), attempting direct Qwen3ASR import...", ex1)
                            try:
                                from transformers.models.qwen3_asr.modeling_qwen3_asr import Qwen3ASRForConditionalGeneration
                                self._qwen_model = Qwen3ASRForConditionalGeneration.from_pretrained(
                                    self.model_size,
                                    trust_remote_code=True,
                                    dtype=torch.float32,
                                    low_cpu_mem_usage=True,
                                )
                            except Exception as ex2:
                                logger.info("Direct Qwen3ASR import fallback (%s), attempting AutoModel...", ex2)
                                from transformers import AutoModel
                                self._qwen_model = AutoModel.from_pretrained(
                                    self.model_size,
                                    trust_remote_code=True,
                                    dtype=torch.float32,
                                    low_cpu_mem_usage=True,
                                )

                        self._model_type = "qwen"
                        logger.info("Qwen3-ASR model (%s) loaded successfully", self.model_size)
                        return
                    except Exception as e:
                        logger.warning("Qwen3-ASR model load failed for %s: %s", self.model_size, e)

                # Handle generic HuggingFace pipeline models
                if not is_whisper_size and "/" in self.model_size:
                    try:
                        from transformers import pipeline
                        device_arg = 0 if self.device == "cuda" else (-1 if self.device == "cpu" else "auto")
                        try:
                            self._hf_pipeline = pipeline(
                                "automatic-speech-recognition",
                                model=self.model_size,
                                trust_remote_code=True,
                                device_map=device_arg if device_arg != "auto" else "auto",
                            )
                        except Exception:
                            self._hf_pipeline = pipeline(
                                "automatic-speech-recognition",
                                model=self.model_size,
                                trust_remote_code=True,
                            )
                        self._model_type = "hf"
                        logger.info("HuggingFace ASR pipeline (%s) loaded successfully", self.model_size)
                        return
                    except Exception as e:
                        logger.warning("HuggingFace ASR pipeline load failed for %s: %s", self.model_size, e)

                # Fallback to faster-whisper
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
        if self._local_model is None and self._hf_pipeline is None and self._qwen_model is None:
            await self.load_model()

        if self._local_model is None and self._hf_pipeline is None and self._qwen_model is None:
            logger.error("No local ASR model available for transcription")
            return "[transcription unavailable]"

        loop = asyncio.get_event_loop()

        def _transcribe():
            if self._model_type == "qwen" and self._qwen_model is not None:
                import wave
                import numpy as np
                import torch
                with wave.open(audio_path, 'rb') as wf:
                    frames = wf.readframes(wf.getnframes())
                    rate = wf.getframerate()
                    nchannels = wf.getnchannels()

                samples = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
                if nchannels == 2:
                    samples = samples.reshape(-1, 2).mean(axis=1)

                inputs = self._qwen_processor(
                    text='<|audio_start|><|audio_pad|><|audio_end|>',
                    audio=samples,
                    sampling_rate=rate,
                    return_tensors='pt',
                )
                inputs = {k: v.to(self._qwen_model.device) for k, v in inputs.items() if hasattr(v, 'to')}
                with torch.no_grad():
                    generated_ids = self._qwen_model.generate(**inputs, max_new_tokens=256)
                text = self._qwen_processor.batch_decode(generated_ids, skip_special_tokens=True)[0]
                return text.strip()

            if self._model_type == "hf" and self._hf_pipeline is not None:
                res = self._hf_pipeline(audio_path)
                if isinstance(res, dict):
                    return res.get("text", "").strip()
                elif isinstance(res, list) and res and isinstance(res[0], dict):
                    return " ".join([r.get("text", "") for r in res]).strip()
                return str(res).strip()

            if self._local_model is not None:
                kwargs = {"beam_size": 1}
                if language:
                    kwargs["language"] = language
                segments, info = self._local_model.transcribe(audio_path, **kwargs)
                text_parts = [seg.text for seg in segments]
                return " ".join(text_parts).strip()

            return "[transcription unavailable]"

        transcript = await loop.run_in_executor(None, _transcribe)
        return transcript.strip()

    async def transcribe_segments(self, audio_path: str, language: Optional[str] = None) -> list:
        if self.provider != "local":
            text = await self.transcribe(audio_path, language)
            return [(0.0, 0.0, text)] if text else []

        if self._local_model is None and self._hf_pipeline is None and self._qwen_model is None:
            await self.load_model()

        if self._local_model is None and self._hf_pipeline is None and self._qwen_model is None:
            return []

        loop = asyncio.get_event_loop()

        def _segments():
            if self._model_type == "qwen" or self._model_type == "hf":
                text = self._transcribe()
                return [(0.0, 0.0, text)] if text else []

            if self._local_model is not None:
                kwargs = {"beam_size": 1}
                if language:
                    kwargs["language"] = language
                segs, _ = self._local_model.transcribe(audio_path, **kwargs)
                return [(seg.start, seg.end, seg.text.strip()) for seg in segs if seg.text.strip()]

            return []

        return await loop.run_in_executor(None, _segments)
