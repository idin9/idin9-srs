import asyncio
import logging
from typing import Optional, Dict
from . import providers

logger = logging.getLogger(__name__)


class SentimentAnalyzer:
    def __init__(
        self,
        provider: str = "local",
        api_key: str = "",
        api_url: str = "",
        api_model: str = "",
        model_name: str = "cardiffnlp/twitter-xlm-roberta-base-sentiment",
        sentiment_mapping: Optional[Dict[str, float]] = None,
    ):
        self._provider = provider
        self._api_key = api_key
        self._api_url = api_url
        self._api_model = api_model
        self.model_name = model_name
        self._sentiment_mapping = sentiment_mapping
        self._pipeline = None

    @property
    def provider(self) -> str:
        from .config import settings as cfg
        return cfg.sentiment_provider

    @property
    def api_key(self) -> str:
        from .config import settings as cfg
        return cfg.sentiment_api_key

    @property
    def api_url(self) -> str:
        from .config import settings as cfg
        return cfg.sentiment_api_url

    @property
    def api_model(self) -> str:
        from .config import settings as cfg
        return cfg.sentiment_api_model

    @property
    def sentiment_mapping(self) -> Dict[str, float]:
        from .config import settings as cfg
        return cfg.get_sentiment_mapping()

    async def load_model(self):
        if self.provider != "local":
            logger.info(
                "Using external sentiment provider: %s (model=%s)",
                self.provider,
                self.api_model or "default",
            )
            return
        if self._pipeline is not None:
            return
        from transformers import pipeline

        loop = asyncio.get_event_loop()

        def _load():
            logger.info("Loading local sentiment model %s", self.model_name)
            self._pipeline = pipeline(
                "text-classification",
                model=self.model_name,
                top_k=None,
            )
            logger.info("Sentiment model loaded")

        await loop.run_in_executor(None, _load)

    async def analyze(self, text: str) -> dict:
        if not text.strip():
            return {"score": 1.0, "label": "neutral", "emotions": {}}

        if self.provider == "openai":
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                providers.sentiment_openai,
                text,
                self.api_key,
                self.api_url,
                self.api_model,
            )
            label = result.get("sentiment", "neutral")
            score = result.get("score", 5.0)
            return {"score": round(score, 1), "label": label, "emotions": {label: score}}

        if self.provider == "ollama":
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                providers.sentiment_ollama,
                text,
                self.api_url,
                self.api_model,
            )
            label = result.get("sentiment", "neutral")
            score = result.get("score", 5.0)
            return {"score": round(score, 1), "label": label, "emotions": {label: score}}

        if self.provider == "gemini":
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                providers.sentiment_gemini,
                text,
                self.api_key,
                self.api_url,
                self.api_model,
            )
            label = result.get("sentiment", "neutral")
            score = result.get("score", 5.0)
            return {"score": round(score, 1), "label": label, "emotions": {label: score}}

        # Local provider
        if self._pipeline is None:
            await self.load_model()

        loop = asyncio.get_event_loop()

        def _analyze():
            result = self._pipeline(text)
            if isinstance(result, list) and isinstance(result[0], list):
                return result[0]
            return result

        predictions = await loop.run_in_executor(None, _analyze)

        if isinstance(predictions, list) and len(predictions) > 0:
            scores = {}
            for pred in predictions:
                if isinstance(pred, dict):
                    label = pred.get("label", "").lower()
                    score = pred.get("score", 0.0)
                    if label:
                        scores[label] = score

            baseline = self.sentiment_mapping.get("neutral", 1.0)
            weighted_score = baseline
            for label, base_score in self.sentiment_mapping.items():
                weight = scores.get(label, 0.0)
                weighted_score += (base_score - weighted_score) * weight * 0.5

            weighted_score = max(1.0, min(10.0, weighted_score))
            dominant_label = max(scores, key=scores.get) if scores else "neutral"

            return {
                "score": round(weighted_score, 1),
                "label": dominant_label,
                "emotions": scores,
            }

        return {"score": 1.0, "label": "neutral", "emotions": {}}
