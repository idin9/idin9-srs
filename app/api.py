import os
import json
import logging
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, Request, Query, Header, Depends
from fastapi.responses import FileResponse
from typing import Optional, List, Dict, Any
from pathlib import Path
import jwt

from .models import (
    SessionInfo,
    SessionState,
    StartRecordResponse,
    StopRecordResponse,
    SentimentTranscriptResponse,
    RecordingInfo,
    ErrorResponse,
    LoginRequest,
    TokenResponse,
    UserCreateRequest,
    UserRoleUpdateRequest,
)
from .config import settings
from .auth import authenticate_local_user
from . import user_manager

logger = logging.getLogger(__name__)

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(hours=settings.jwt_expiry_hours)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return encoded_jwt

async def verify_auth(
    x_api_key: str = Header("", alias="X-API-Key"),
    authorization: str = Header("", alias="Authorization")
):
    if settings.auth_mode == "api_key" or settings.auth_mode == "both":
        if settings.api_key and x_api_key == settings.api_key:
            return {"username": "api_user", "role": "admin"}
            
    if settings.auth_mode == "local" or settings.auth_mode == "both":
        if authorization.startswith("Bearer "):
            token = authorization.split(" ")[1]
            try:
                payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
                username: str = payload.get("sub")
                role: str = payload.get("role")
                if username is None or role is None:
                    raise HTTPException(status_code=403, detail="Invalid token")
                return {"username": username, "role": role}
            except jwt.ExpiredSignatureError:
                raise HTTPException(status_code=403, detail="Token has expired")
            except jwt.InvalidTokenError:
                raise HTTPException(status_code=403, detail="Invalid token")
                
    raise HTTPException(status_code=403, detail="Invalid authentication credentials")

async def verify_admin(user: dict = Depends(verify_auth)):
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Administrator access required")
    return user


def create_router():
    router = APIRouter(prefix="/api/v1", tags=["idin9-srs"])

    # ===================== RECORD =====================

    @router.post(
        "/record/stop/{session_id}",
        response_model=StopRecordResponse,
        responses={404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
        summary="Stop a recording and process results",
    )
    async def stop_recording(session_id: str, request: Request, user: dict = Depends(verify_auth)):
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
    async def get_sentiment_transcript(session_id: str, request: Request, user: dict = Depends(verify_auth)):
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
    async def get_audio_file(session_id: str, request: Request, user: dict = Depends(verify_auth)):
        """Stream the audio file for playback or download. Decrypts on-the-fly if encrypted."""
        indexer = request.app.state.indexer
        record = indexer.get_recording(session_id)
        
        file_path = None
        if record and record.get("wav_path") and os.path.exists(record["wav_path"]):
            file_path = record["wav_path"]
            
        # Fallback to scanning disk if not in database
        if not file_path:
            from .config import settings
            output_abs = os.path.abspath(settings.output_dir)
            for ext in [".wav", ".opus", ".wav.enc", ".opus.enc"]:
                candidate = os.path.normpath(os.path.join(output_abs, f"{session_id}{ext}"))
                if candidate.startswith(output_abs) and os.path.exists(candidate):
                    file_path = candidate
                    break
                    
        if not file_path:
            raise HTTPException(404, detail=f"Audio file for session {session_id} not found")
            
        resolved = os.path.abspath(file_path)
        
        # Determine format/mimetype and whether it is encrypted
        is_encrypted = resolved.endswith(".enc")
        is_opus = ".opus" in resolved
        
        media_type = "audio/ogg" if is_opus else "audio/wav"
        ext = ".opus" if is_opus else ".wav"
        filename = f"{session_id}{ext}"
        
        if is_encrypted:
            from .config import settings
            from .audio_processor import decrypt_file
            import io
            from fastapi.responses import StreamingResponse
            
            password = settings.encryption_password or "idin9-srs-default-pass"
            try:
                decrypted_bytes = decrypt_file(resolved, password)
                return StreamingResponse(
                    io.BytesIO(decrypted_bytes),
                    media_type=media_type,
                    headers={
                        "Content-Disposition": f'inline; filename="{filename}"',
                        "Accept-Ranges": "bytes",
                        "Content-Length": str(len(decrypted_bytes))
                    }
                )
            except Exception as e:
                raise HTTPException(500, detail=f"Failed to decrypt audio: {e}")
        else:
            return FileResponse(
                resolved,
                media_type=media_type,
                filename=filename,
                headers={"Accept-Ranges": "bytes"},
            )

    # ===================== SESSIONS & LOGS =====================

    @router.get(
        "/sessions",
        response_model=list[SessionInfo],
        summary="List all active recording sessions (in memory)",
    )
    async def list_sessions(request: Request, user: dict = Depends(verify_admin)):
        sm = request.app.state.session_manager
        return sm.list_sessions()

    @router.get(
        "/logs",
        summary="Get recent live logs",
    )
    async def get_logs(request: Request, user: dict = Depends(verify_admin)):
        from .main import log_buffer
        return {"logs": list(log_buffer)}

    # ===================== RECORDINGS SEARCH =====================

    @router.get(
        "/recordings",
        summary="Query indexed recordings with filtering and pagination",
    )
    async def list_recordings(
        request: Request,
        user: dict = Depends(verify_auth),
        limit: int = Query(50, ge=1, le=1000, description="Maximum number of records to return"),
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
        total_count = indexer.get_total_count(
            start_time_from=start_time_from,
            start_time_to=start_time_to,
            caller=caller,
            callee=callee,
            min_sentiment=min_sentiment,
            max_sentiment=max_sentiment,
        )
        return {
            "recordings": recordings,
            "total_count": total_count,
            "limit": limit,
            "offset": offset
        }

    # ===================== ADMIN SETTINGS =====================

    @router.get(
        "/admin/settings",
        summary="Get current system configuration",
    )
    async def get_settings(request: Request, user: dict = Depends(verify_admin)):
        """Return all current settings from the config."""
        from .config import settings as cfg

        mapping_raw = cfg.sentiment_mapping if hasattr(cfg, 'sentiment_mapping') else '{}'

        def _mask(val: str) -> str:
            return "********" if val else ""

        return {
            "sip_listen_host": cfg.sip_listen_host,
            "sip_listen_port": cfg.sip_listen_port,
            "rtp_min_port": cfg.rtp_min_port,
            "rtp_max_port": cfg.rtp_max_port,
            "api_host": cfg.api_host,
            "api_port": cfg.api_port,
            "api_key": _mask(cfg.api_key),
            "auth_mode": cfg.auth_mode,
            "timezone": cfg.timezone,
            "locale": cfg.locale,
            "font_family": cfg.font_family,
            "output_dir": cfg.output_dir,
            "transcription_provider": cfg.transcription_provider,
            "transcription_api_key": _mask(cfg.transcription_api_key),
            "transcription_api_url": cfg.transcription_api_url,
            "transcription_api_model": cfg.transcription_api_model,
            "sentiment_provider": cfg.sentiment_provider,
            "sentiment_api_key": _mask(cfg.sentiment_api_key),
            "sentiment_api_url": cfg.sentiment_api_url,
            "sentiment_api_model": cfg.sentiment_api_model,
            "whisper_model_size": cfg.whisper_model_size,
            "whisper_device": cfg.whisper_device,
            "whisper_compute_type": cfg.whisper_compute_type,
            "whisper_cache_dir": cfg.whisper_cache_dir,
            "sentiment_model": cfg.sentiment_model,
            "sentiment_mapping": mapping_raw,
            "hf_cache_dir": cfg.hf_cache_dir,
            "transcription_enabled": cfg.transcription_enabled,
            "sentiment_enabled": cfg.sentiment_enabled,
            "retention_years": cfg.retention_years,
            "index_db": cfg.index_db,
            "audio_format": cfg.audio_format,
            "encryption_enabled": cfg.encryption_enabled,
            "encryption_password": _mask(cfg.encryption_password),
            "session_timeout_seconds": cfg.session_timeout_seconds,
        }

    @router.put(
        "/admin/settings",
        summary="Update system configuration",
    )
    async def update_settings(payload: Dict[str, Any], request: Request, user: dict = Depends(verify_admin)):
        """
        Save configuration overrides to config.override.json.
        Note: Some settings (SIP port, RTP ports, Whisper model) require a server restart.
        """
        allowed_fields = {
            "sip_listen_host",
            "sip_listen_port",
            "rtp_min_port",
            "rtp_max_port",
            "api_key",
            "auth_mode",
            "timezone",
            "locale",
            "font_family",
            "transcription_provider",
            "transcription_api_key",
            "transcription_api_url",
            "transcription_api_model",
            "sentiment_provider",
            "sentiment_api_key",
            "sentiment_api_url",
            "sentiment_api_model",
            "whisper_model_size",
            "whisper_device",
            "whisper_compute_type",
            "whisper_cache_dir",
            "whisper_language",
            "sentiment_model",
            "transcription_enabled",
            "sentiment_enabled",
            "sentiment_mapping",
            "hf_cache_dir",
            "retention_years",
            "index_db",
            "output_dir",
            "audio_format",
            "encryption_enabled",
            "encryption_password",
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
        from .config import settings as cfg
        updated = False
        for key in allowed_fields:
            if key in payload and payload[key] is not None:
                val = payload[key]
                if key in ("retention_years", "session_timeout_seconds", "sip_listen_port", "api_port", "rtp_min_port", "rtp_max_port") and val is not None:
                    val = int(val)
                elif key in ("transcription_enabled", "sentiment_enabled", "encryption_enabled") and val is not None:
                    val = bool(val)
                overrides[key] = val
                setattr(cfg, key, val)
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
    async def trigger_cleanup(request: Request, user: dict = Depends(verify_admin)):
        """Manually trigger cleanup of recordings older than retention policy."""
        indexer = request.app.state.indexer
        from .config import settings as cfg

        deleted_count = indexer.cleanup_old_recordings(cfg.retention_years)
        return {
            "deleted_recordings": deleted_count,
            "retention_years": cfg.retention_years,
            "message": f"Cleaned up {deleted_count} recordings older than {cfg.retention_years} years",
        }

    # ===================== AUTH & USERS =====================

    @router.post(
        "/auth/login",
        response_model=TokenResponse,
        summary="Login with local Linux user",
    )
    async def login(login_req: LoginRequest):
        if settings.auth_mode == "api_key":
            raise HTTPException(400, detail="Local authentication is disabled")
            
        user_info = authenticate_local_user(login_req.username, login_req.password)
        if not user_info:
            raise HTTPException(status_code=401, detail="Incorrect username or password")
            
        access_token = create_access_token(data={"sub": user_info["username"], "role": user_info["role"]})
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "role": user_info["role"],
            "username": user_info["username"]
        }

    @router.get(
        "/auth/me",
        summary="Get current user info",
    )
    async def get_me(user: dict = Depends(verify_auth)):
        return user

    @router.get(
        "/admin/users",
        summary="List all local users for this application",
    )
    async def get_users(user: dict = Depends(verify_admin)):
        return user_manager.list_users()

    @router.post(
        "/admin/users",
        summary="Create a new local user",
    )
    async def create_user(req: UserCreateRequest, user: dict = Depends(verify_admin)):
        if req.role not in ["admin", "auditor"]:
            raise HTTPException(400, detail="Invalid role")
        success, msg = user_manager.create_user(req.username, req.password, req.role)
        if not success:
            raise HTTPException(400, detail=msg)
        return {"status": "success", "message": msg}

    @router.delete(
        "/admin/users/{username}",
        summary="Delete a local user",
    )
    async def delete_user(username: str, user: dict = Depends(verify_admin)):
        success, msg = user_manager.delete_user(username)
        if not success:
            raise HTTPException(400, detail=msg)
        return {"status": "success", "message": msg}

    @router.put(
        "/admin/users/{username}/role",
        summary="Update a local user's role",
    )
    async def update_user_role(username: str, req: UserRoleUpdateRequest, user: dict = Depends(verify_admin)):
        if req.role not in ["admin", "auditor"]:
            raise HTTPException(400, detail="Invalid role")
        success, msg = user_manager.change_user_role(username, req.role)
        if not success:
            raise HTTPException(400, detail=msg)
        return {"status": "success", "message": msg}

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
            "version": "26.06.05",
            "auth_mode": settings.auth_mode,
            "auth_required": bool(settings.api_key) if settings.auth_mode == "api_key" else True,
        }

    return router
