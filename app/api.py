import os
import json
import logging
import uuid
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, Request, Query, FileResponse, Header, Depends
from typing import Optional, List, Dict, Any
from pathlib import Path

from .models import (
    SessionInfo,
    SessionState,
    StartRecordResponse,
    StopRecordResponse,
    SentimentTranscriptResponse,
    RecordingInfo,
    ErrorResponse,
)
from .config import settings

logger = logging.getLogger(__name__)


async def verify_api_key(x_api_key: str = Header("", alias="X-API-Key")):
    if not settings.api_key:
        return True
    if x_api_key != settings.api_key:
        raise HTTPException(status_code=403, detail="Invalid or missing API key")
    return True


def create_router():
    router = APIRouter(prefix="/api/v1", tags=["idin9-srs"])

    # ===================== RECORD =====================

    @router.post(
        "/record/start",
        response_model=StartRecordResponse,
        responses={500: {"model": ErrorResponse}},
        summary="Start a SIPREC recording session",
    )
    async def start_recording(
        request: Request,
        _auth: bool = Depends(verify_api_key),
        caller: Optional[str] = None,
        callee: Optional[str] = None,
    ):
        session_id = str(uuid.uuid4())
        return StartRecordResponse(session_id=session_id, state=SessionState.recording)

    @router.post(
        "/record/stop/{session_id}",
        response_model=StopRecordResponse,
        responses={404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
        summary="Stop a recording and process results",
    )
    async def stop_recording(session_id: str, request: Request, _auth: bool = Depends(verify_api_key)):
        sm = request.app.state.session_manager
        info = await sm.stop_session(session_id)
        if info is None:
            raise HTTPException(404, detail=f"Session {session_id} not found")
        return StopRecordResponse(
            session_id=info.session_id,
            state=info.state,
            transcript=info.transcript or "",
            sentiment_score=info.sentiment_score or 1.0,
            sentiment_label=info.sentiment_label or "neutral",
        )

    # ===================== RECORD (GET) =====================

    @router.get(
        "/record/{session_id}",
        response_model=SentimentTranscriptResponse,
        responses={404: {"model": ErrorResponse}},
        summary="Get sentiment and transcript for a session",
    )
    async def get_sentiment_transcript(session_id: str, request: Request, _auth: bool = Depends(verify_api_key)):
        sm = request.app.state.session_manager
        info = sm.get_session(session_id)
        if info is not None:
            return SentimentTranscriptResponse(
                session_id=info.session_id,
                transcript=info.transcript or "",
                sentiment_score=info.sentiment_score or 1.0,
                sentiment_label=info.sentiment_label or "neutral",
            )
        # Fall back to indexer for completed sessions
        indexer = request.app.state.indexer
        record = indexer.get_recording(session_id)
        if record is None:
            raise HTTPException(404, detail=f"Session {session_id} not found")
        return SentimentTranscriptResponse(
            session_id=record.get("session_id", session_id),
            transcript=record.get("transcript", ""),
            sentiment_score=record.get("sentiment_score", 1.0),
            sentiment_label=record.get("sentiment_label", "neutral"),
        )

    # ===================== AUDIO FILE =====================

    @router.get(
        "/recordings/{session_id}/audio",
        summary="Download or play the recording audio file",
        responses={404: {"description": "Audio file not found"}},
    )
    async def get_audio_file(session_id: str, request: Request, _auth: bool = Depends(verify_api_key)):
        """Stream the WAV audio file for playback or download."""
        # First check the indexer for the wav_path
        indexer = request.app.state.indexer
        record = indexer.get_recording(session_id)
        if record and record.get("wav_path") and os.path.exists(record["wav_path"]):
            return FileResponse(
                record["wav_path"],
                media_type="audio/wav",
                filename=f"{session_id}.wav",
                headers={"Accept-Ranges": "bytes"},
            )

        # Fall back to the default path pattern
        from .config import settings
        wav_path = os.path.join(settings.output_dir, f"{session_id}.wav")
        if os.path.exists(wav_path):
            return FileResponse(
                wav_path,
                media_type="audio/wav",
                filename=f"{session_id}.wav",
                headers={"Accept-Ranges": "bytes"},
            )

        raise HTTPException(404, detail=f"Audio file for session {session_id} not found")

    # ===================== SESSIONS =====================

    @router.get(
        "/sessions",
        response_model=list[SessionInfo],
        summary="List all active recording sessions (in memory)",
    )
    async def list_sessions(request: Request, _auth: bool = Depends(verify_api_key)):
        sm = request.app.state.session_manager
        return sm.list_sessions()

    # ===================== RECORDINGS SEARCH =====================

    @router.get(
        "/recordings",
        response_model=List[RecordingInfo],
        summary="Query indexed recordings with filtering and pagination",
    )
    async def list_recordings(
        request: Request,
        _auth: bool = Depends(verify_api_key),
        limit: int = Query(100, ge=1, le=1000, description="Maximum number of records to return"),
        offset: int = Query(0, ge=0, description="Number of records to skip"),
        start_time_from: Optional[str] = Query(None, description="Filter recordings ending after this time (ISO format)"),
        start_time_to: Optional[str] = Query(None, description="Filter recordings ending before this time (ISO format)"),
        caller: Optional[str] = Query(None, description="Filter by caller ID"),
        callee: Optional[str] = Query(None, description="Filter by callee ID"),
        min_sentiment: Optional[float] = Query(None, ge=1.0, le=10.0, description="Minimum sentiment score (1-10)"),
        max_sentiment: Optional[float] = Query(None, ge=1.0, le=10.0, description="Maximum sentiment score (1-10)"),
    ):
        """Query recordings from the long-term index with optional filters."""
        indexer = request.app.state.indexer
        recordings = indexer.list_recordings(
            limit=limit,
            offset=offset,
            start_time_from=start_time_from,
            start_time_to=start_time_to,
            caller=caller,
            callee=callee,
            min_sentiment=min_sentiment,
            max_sentiment=max_sentiment,
        )
        return recordings

    # ===================== ADMIN SETTINGS =====================

    @router.get(
        "/admin/settings",
        summary="Get current system configuration",
    )
    async def get_settings(request: Request, _auth: bool = Depends(verify_api_key)):
        """Return all current settings from the config."""
        from .config import settings as cfg

        mapping_raw = cfg.sentiment_mapping if hasattr(cfg, 'sentiment_mapping') else '{}'
        return {
            "sip_listen_host": cfg.sip_listen_host,
            "sip_listen_port": cfg.sip_listen_port,
            "rtp_min_port": cfg.rtp_min_port,
            "rtp_max_port": cfg.rtp_max_port,
            "api_host": cfg.api_host,
            "api_port": cfg.api_port,
            "output_dir": cfg.output_dir,
            "whisper_model_size": cfg.whisper_model_size,
            "whisper_device": cfg.whisper_device,
            "whisper_compute_type": cfg.whisper_compute_type,
            "sentiment_model": cfg.sentiment_model,
            "sentiment_mapping": mapping_raw,
            "retention_years": cfg.retention_years,
            "index_db": cfg.index_db,
        }

    @router.put(
        "/admin/settings",
        summary="Update system configuration",
    )
    async def update_settings(payload: Dict[str, Any], request: Request, _auth: bool = Depends(verify_api_key)):
        """
        Save configuration overrides to config.override.json.
        Note: Some settings (SIP port, RTP ports, Whisper model) require a server restart.
        """
        allowed_fields = {
            "sentiment_mapping",
            "whisper_model_size",
            "whisper_device",
            "whisper_compute_type",
            "retention_years",
            "output_dir",
        }

        project_root = Path(__file__).parent.parent
        override_path = project_root / "config.override.json"

        # Load existing overrides if any
        overrides = {}
        if override_path.exists():
            try:
                overrides = json.loads(override_path.read_text())
            except (json.JSONDecodeError, OSError):
                overrides = {}

        # Apply allowed fields
        updated = False
        for key in allowed_fields:
            if key in payload and payload[key] is not None:
                overrides[key] = payload[key]
                updated = True

        if not updated:
            raise HTTPException(400, detail="No valid configuration fields provided")

        # Write to override file
        try:
            with open(override_path, "w") as f:
                json.dump(overrides, f, indent=2)
        except OSError as e:
            raise HTTPException(500, detail=f"Failed to write config override: {e}")

        logger.info("Config overrides saved: %s", overrides)

        return {
            "status": "saved",
            "overrides": overrides,
            "message": "Configuration saved. Some changes may require a server restart.",
        }

    # ===================== MAINTENANCE =====================

    @router.post(
        "/maintenance/cleanup",
        summary="Trigger cleanup of old recordings based on retention policy",
    )
    async def trigger_cleanup(request: Request, _auth: bool = Depends(verify_api_key)):
        """Manually trigger cleanup of recordings older than retention policy."""
        indexer = request.app.state.indexer
        from .config import settings as cfg

        deleted_count = indexer.cleanup_old_recordings(cfg.retention_years)
        return {
            "deleted_recordings": deleted_count,
            "retention_years": cfg.retention_years,
            "message": f"Cleaned up {deleted_count} recordings older than {cfg.retention_years} years",
        }

    # ===================== HEALTH =====================

    @router.get(
        "/health",
        summary="Health check (no API key required)",
    )
    async def health():
        return {"status": "ok"}

    # Public docs/info endpoint — no auth
    @router.get(
        "/info",
        summary="Public service info (no API key required)",
    )
    async def public_info():
        return {
            "service": "idin9-srs",
            "version": "1.3.0",
            "auth_required": bool(settings.api_key),
        }

    return router
