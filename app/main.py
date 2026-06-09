import asyncio
import json
import logging
import os
from collections import deque
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse
from contextlib import asynccontextmanager

from .config import settings
from .audio_processor import AudioProcessor
from .transcriber import Transcriber
from .sentiment_analyzer import SentimentAnalyzer
from .session_manager import SessionManager
from .sip_stack import Idin9SrsServer
from .api import create_router
from .indexer import RecordingIndexer

# Create an in-memory log buffer for the web console
log_buffer = deque(maxlen=500)

class WebConsoleLogHandler(logging.Handler):
    def emit(self, record):
        try:
            msg = self.format(record)
            log_buffer.append(msg)
        except Exception:
            self.handleError(record)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        WebConsoleLogHandler()
    ]
)
logger = logging.getLogger(__name__)

idin9_srs_server: Idin9SrsServer | None = None


def load_config_overrides():
    """Load config.override.json and merge overrides into settings."""
    override_path = Path(__file__).parent.parent / "config.override.json"
    if not override_path.exists():
        return

    try:
        overrides = json.loads(override_path.read_text())
        logger.info("Loading config overrides: %s", overrides)
        for key, value in overrides.items():
            if hasattr(settings, key) and value is not None:
                setattr(settings, key, value)
                logger.info("  Override %s = %s", key, value)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to load config.override.json: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global idin9_srs_server

    # Load runtime config overrides
    load_config_overrides()

    # Set cache directories for AI models
    whisper_cache = settings.whisper_cache_dir.strip() or None
    hf_cache = settings.hf_cache_dir.strip() or None
    if hf_cache:
        os.environ["HF_HOME"] = hf_cache
        os.environ["TRANSFORMERS_CACHE"] = hf_cache
        logger.info("HuggingFace cache dir: %s", hf_cache)

    loop = asyncio.get_event_loop()

    audio_processor = AudioProcessor(output_dir=settings.output_dir)

    transcriber = Transcriber(
        provider=settings.transcription_provider,
        api_key=settings.transcription_api_key,
        api_url=settings.transcription_api_url,
        api_model=settings.transcription_api_model,
        model_size=settings.whisper_model_size,
        device=settings.whisper_device,
        compute_type=settings.whisper_compute_type,
        cache_dir=whisper_cache,
    )
    await transcriber.load_model()

    sentiment_analyzer = SentimentAnalyzer(
        provider=settings.sentiment_provider,
        api_key=settings.sentiment_api_key,
        api_url=settings.sentiment_api_url,
        api_model=settings.sentiment_api_model,
        model_name=settings.sentiment_model,
        sentiment_mapping=settings.get_sentiment_mapping(),
    )
    await sentiment_analyzer.load_model()

    # Initialize indexer for long-term storage and search
    indexer_path = os.path.join(settings.output_dir, settings.index_db)
    indexer = RecordingIndexer(indexer_path)

    rtp_port_range = (settings.rtp_min_port, settings.rtp_max_port)
    sm = SessionManager(
        audio_processor=audio_processor,
        transcriber=transcriber,
        sentiment_analyzer=sentiment_analyzer,
        indexer=indexer,
        rtp_host=settings.rtp_listen_host,
        rtp_port_range=rtp_port_range,
        loop=loop,
        transcription_enabled=settings.transcription_enabled,
        sentiment_enabled=settings.sentiment_enabled,
    )
    app.state.session_manager = sm
    app.state.indexer = indexer

    idin9_srs_server = Idin9SrsServer(
        host=settings.sip_listen_host,
        port=settings.sip_listen_port,
        rtp_port_allocator=sm.allocate_rtp_port_sync,
        on_new_session_callback=sm.create_session,
        loop=loop,
    )
    await idin9_srs_server.start()

    logger.info(
        "SIPREC server on udp %s:%s, API on %s:%s",
        settings.sip_listen_host,
        settings.sip_listen_port,
        settings.api_host,
        settings.api_port,
    )

    yield

    if idin9_srs_server:
        idin9_srs_server.stop()
    logger.info("Server stopped")


def create_app() -> FastAPI:
    app = FastAPI(
        title="idin9-srs",
        description="SIPREC recording server with sentiment analysis and transcription",
        version="26.06.01",
        lifespan=lifespan,
    )

    # API routes
    router = create_router()
    app.include_router(router)

    # Serve static frontend files
    static_dir = Path(__file__).parent.parent / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # Serve index.html at root
    @app.get("/", include_in_schema=False)
    async def root():
        index_path = static_dir / "index.html"
        if index_path.exists():
            return HTMLResponse(index_path.read_text())
        return {
            "service": "idin9-srs",
            "version": "26.06.01",
            "docs": "/docs",
        }

    return app


app = create_app()
