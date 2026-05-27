import asyncio
import logging
import threading
from typing import Optional, Callable
from concurrent.futures import ThreadPoolExecutor
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
        self._thread_pool = ThreadPoolExecutor(max_workers=2)

    def allocate_rtp_port_sync(self) -> int | None:
        with self._rtp_port_lock:
            port = self._next_rtp_port
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

        duration = self.audio_processor.get_audio_duration(session_id)
        logger.info("Session %s recorded %s seconds", session_id, duration)

        wav_path = self.audio_processor.save_wav(session_id)
        if wav_path:
            transcript = await self.transcriber.transcribe(wav_path)
            info.transcript = transcript

            result = await self.sentiment_analyzer.analyze(transcript)
            info.sentiment_score = result.get("score", 1.0)
            info.sentiment_label = result.get("label", "neutral")

        info.state = SessionState.completed
        info.end_time = datetime.utcnow().isoformat()
        logger.info(
            "Session %s completed: score=%s label=%s",
            session_id,
            info.sentiment_score,
            info.sentiment_label,
        )

        # Store in indexer
        if wav_path and info.transcript is not None and info.sentiment_score is not None and info.sentiment_label is not None:
            self.indexer.add_recording(
                session_id=session_id,
                caller=info.caller,
                callee=info.callee,
                start_time=info.start_time,
                end_time=info.end_time,
                wav_path=wav_path,
                duration=duration,
                sentiment_score=info.sentiment_score,
                sentiment_label=info.sentiment_label,
                transcript=info.transcript,
            )

        return info

    def get_session(self, session_id: str) -> Optional[SessionInfo]:
        return self._sessions.get(session_id)

    def list_sessions(self) -> list[SessionInfo]:
        return list(self._sessions.values())

    def cleanup(self, session_id: str):
        self._sessions.pop(session_id, None)
        keys = [k for k in self._rtp_sessions if k[0] == session_id]
        for key in keys:
            self._rtp_sessions.pop(key, None)
        self.audio_processor.clear(session_id)
