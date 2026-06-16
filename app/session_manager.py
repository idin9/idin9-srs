import asyncio
import time
import logging
import threading
from typing import Optional, Callable
from datetime import datetime

from .models import SessionState, SessionInfo
from .rtp_session import RtpSession
from .audio_processor import AudioProcessor
from .transcriber import Transcriber
from .sentiment_analyzer import SentimentAnalyzer
from .indexer import RecordingIndexer

logger = logging.getLogger(__name__)


class SessionManager:
    def __init__(
        self,
        audio_processor: AudioProcessor,
        transcriber: Transcriber,
        sentiment_analyzer: SentimentAnalyzer,
        indexer: RecordingIndexer,
        rtp_host: str,
        rtp_port_range: tuple[int, int],
        loop: asyncio.AbstractEventLoop,
        transcription_enabled: bool = True,
        sentiment_enabled: bool = True,
    ):
        self.audio_processor = audio_processor
        self.transcriber = transcriber
        self.sentiment_analyzer = sentiment_analyzer
        self.indexer = indexer
        self.rtp_host = rtp_host
        self.rtp_min_port, self.rtp_max_port = rtp_port_range
        self.loop = loop
        self._sessions: dict[str, SessionInfo] = {}
        # _rtp_sessions key: (session_id, stream_index) -> RtpSession
        self._rtp_sessions: dict[tuple[str, int], RtpSession] = {}
        self._next_rtp_port = self.rtp_min_port
        self._rtp_port_lock = threading.Lock()
        self._used_rtp_ports: set[int] = set()
        # Track last audio receive time per session (monotonic clock)
        self._last_audio_time: dict[str, float] = {}
        self._stale_check_task: Optional[asyncio.Task] = None

    @property
    def transcription_enabled(self) -> bool:
        from .config import settings as cfg
        return cfg.transcription_enabled

    @property
    def sentiment_enabled(self) -> bool:
        from .config import settings as cfg
        return cfg.sentiment_enabled

    def allocate_rtp_port_sync(self) -> int | None:
        with self._rtp_port_lock:
            start = self._next_rtp_port
            while self._next_rtp_port in self._used_rtp_ports:
                self._next_rtp_port += 2
                if self._next_rtp_port > self.rtp_max_port:
                    self._next_rtp_port = self.rtp_min_port
                if self._next_rtp_port == start:
                    return None
            port = self._next_rtp_port
            self._used_rtp_ports.add(port)
            self._next_rtp_port += 2
            if self._next_rtp_port > self.rtp_max_port:
                self._next_rtp_port = self.rtp_min_port
            return port

    async def create_session(
        self,
        session_id: str,
        streams: list[dict],
        caller: str = "",
        callee: str = "",
        xml_metadata: Optional[dict] = None,
    ) -> SessionInfo:
        """
        Create a recording session with multiple RTP streams.

        streams: list of dicts with keys:
          - remote_ip: str
          - remote_port: int
          - allocated_port: int (the local port to listen on)
          - codecs: dict (optional)
        """
        info = SessionInfo(
            session_id=session_id,
            caller=caller,
            callee=callee,
            state=SessionState.recording,
            start_time=datetime.utcnow().isoformat(),
        )
        self._sessions[session_id] = info

        created_any = False
        for i, stream in enumerate(streams):
            remote_ip = stream.get('remote_ip', '127.0.0.1')
            remote_port = stream.get('remote_port', 0)
            allocated_port = stream.get('allocated_port')
            if not allocated_port:
                allocated_port = self.allocate_rtp_port_sync()
            if not allocated_port:
                logger.error("No available RTP port for stream %d of session %s", i, session_id)
                continue

            # Create per-stream callback with stream index
            def make_callback(sid: str, sidx: int):
                def callback(s: str, payload: bytes, pt: int):
                    self._on_audio(sid, sidx, payload, pt)
                return callback

            rtp_session = RtpSession(
                session_id=f"{session_id}:{i}",
                local_port=allocated_port,
                remote_ip=remote_ip,
                remote_port=remote_port,
                on_audio_callback=make_callback(session_id, i),
                loop=self.loop,
                host=self.rtp_host,
            )
            self._rtp_sessions[(session_id, i)] = rtp_session
            await rtp_session.start()
            created_any = True
            logger.info(
                "Session %s stream %d: RTP %s -> %s:%s (codecs: %s)",
                session_id, i, allocated_port, remote_ip, remote_port,
                stream.get('codecs', {}),
            )

        if not created_any:
            logger.warning("Session %s created with no RTP streams", session_id)
        else:
            logger.info("Session %s created with %d stream(s)", session_id, len(streams))

        return info

    def _on_audio(self, session_id: str, stream_index: int, payload: bytes, payload_type: int):
        self._last_audio_time[session_id] = time.monotonic()
        self.audio_processor.feed_audio(session_id, stream_index, payload, payload_type)

    async def stop_session(self, session_id: str) -> Optional[SessionInfo]:
        info = self._sessions.get(session_id)
        if info is None:
            logger.warning("Session %s not found", session_id)
            return None

        info.state = SessionState.processing

        # Stop all RTP sessions for this call
        to_remove = [k for k in self._rtp_sessions if k[0] == session_id]
        for key in to_remove:
            rtp_session = self._rtp_sessions.pop(key, None)
            if rtp_session:
                rtp_session.stop()
                with self._rtp_port_lock:
                    self._used_rtp_ports.discard(rtp_session.local_port)

        duration = self.audio_processor.get_audio_duration(session_id)
        logger.info("Session %s recorded %s seconds", session_id, duration)

        final_path = None
        try:
            wav_path = self.audio_processor.save_wav(session_id)
            if wav_path:
                if self.transcription_enabled:
                    transcript = await self.transcriber.transcribe(wav_path)
                    info.transcript = transcript
                    logger.info("Session %s transcription complete (%d chars)", session_id, len(transcript))
                else:
                    info.transcript = "[transcription disabled]"

                if self.sentiment_enabled and info.transcript and info.transcript != "[transcription disabled]":
                    result = await self.sentiment_analyzer.analyze(info.transcript)
                    info.sentiment_score = result.get("score", 1.0)
                    info.sentiment_label = result.get("label", "neutral")
                    logger.info("Session %s sentiment: %s (%.1f)", session_id, info.sentiment_label, info.sentiment_score)
                else:
                    info.sentiment_score = 1.0
                    info.sentiment_label = "neutral"

                # Run audio post-processing (Opus conversion and encryption)
                final_path = self.audio_processor.process_final_audio(session_id, wav_path)
        except Exception as e:
            logger.error("Session %s processing error: %s", session_id, e)

        info.state = SessionState.completed
        info.end_time = datetime.utcnow().isoformat()
        logger.info(
            "Session %s completed",
            session_id,
        )

        # Store in indexer
        if final_path:
            self.indexer.add_recording(
                session_id=session_id,
                caller=info.caller,
                callee=info.callee,
                start_time=info.start_time,
                end_time=info.end_time,
                wav_path=final_path,
                duration=duration,
                sentiment_score=info.sentiment_score,
                sentiment_label=info.sentiment_label,
                transcript=info.transcript,
            )

        self._last_audio_time.pop(session_id, None)
        self._sessions.pop(session_id, None)

        return info

    def get_session(self, session_id: str) -> Optional[SessionInfo]:
        return self._sessions.get(session_id)

    def list_sessions(self) -> list[SessionInfo]:
        return list(self._sessions.values())

    def start_stale_session_checker(self):
        """Start background task that auto-stops sessions with no recent RTP activity."""
        if self._stale_check_task is not None:
            return
        self._stale_check_task = asyncio.ensure_future(self._stale_check_loop(), loop=self.loop)

    def stop_stale_session_checker(self):
        if self._stale_check_task is not None:
            self._stale_check_task.cancel()
            self._stale_check_task = None

    async def _stale_check_loop(self):
        from .config import settings as cfg
        while True:
            try:
                await asyncio.sleep(30)
                timeout = cfg.session_timeout_seconds
                if timeout <= 0:
                    continue
                now = time.monotonic()
                stale = []
                for sid, last_time in list(self._last_audio_time.items()):
                    if sid not in self._sessions:
                        continue
                    if self._sessions[sid].state != SessionState.recording:
                        continue
                    if now - last_time > timeout:
                        stale.append(sid)
                for sid in stale:
                    logger.info("Auto-stopping stale session %s (no RTP for >%ss)", sid, timeout)
                    try:
                        await self.stop_session(sid)
                    except Exception as e:
                        logger.error("Failed to auto-stop session %s: %s", sid, e)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Stale session checker error: %s", e)

    def cleanup(self, session_id: str):
        self._sessions.pop(session_id, None)
        self._last_audio_time.pop(session_id, None)
        keys = [k for k in self._rtp_sessions if k[0] == session_id]
        for key in keys:
            rtp_session = self._rtp_sessions.pop(key, None)
            if rtp_session:
                rtp_session.stop()
                with self._rtp_port_lock:
                    self._used_rtp_ports.discard(rtp_session.local_port)
        self.audio_processor.clear(session_id)
