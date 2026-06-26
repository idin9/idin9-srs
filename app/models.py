from pydantic import BaseModel
from typing import Optional
from enum import Enum
from datetime import datetime


class SessionState(str, Enum):
    idle = "idle"
    recording = "recording"
    processing = "processing"
    completed = "completed"


class SessionInfo(BaseModel):
    session_id: str
    caller: Optional[str] = None
    callee: Optional[str] = None
    state: SessionState = SessionState.idle
    sentiment_score: Optional[float] = None
    sentiment_label: Optional[str] = None
    transcript: Optional[str] = None
    start_time: Optional[str] = None  # ISO format datetime string
    end_time: Optional[str] = None    # ISO format datetime string
    bad_word_percentage: float = 0.0
    xml_metadata: Optional[str] = None  # Raw SIPREC XML metadata from INVITE


class StartRecordResponse(BaseModel):
    session_id: str
    state: SessionState


class StopRecordResponse(BaseModel):
    session_id: str
    state: SessionState
    transcript: str
    sentiment_score: float
    sentiment_label: str


class SentimentTranscriptResponse(BaseModel):
    session_id: str
    transcript: str
    sentiment_score: float
    sentiment_label: str
    bad_word_percentage: float = 0.0


class RecordingInfo(BaseModel):
    session_id: str
    caller: Optional[str] = None
    callee: Optional[str] = None
    start_time: str  # ISO format datetime string
    end_time: str    # ISO format datetime string
    wav_path: str
    duration: float  # in seconds
    sentiment_score: float  # 1-10
    sentiment_label: str
    transcript: str
    bad_word_percentage: float = 0.0


class ErrorResponse(BaseModel):
    detail: str


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    role: str
    username: str


class UserCreateRequest(BaseModel):
    username: str
    password: str
    role: str  # "admin" or "auditor"


class UserRoleUpdateRequest(BaseModel):
    role: str

