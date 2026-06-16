import sqlite3
import os
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from .models import SessionInfo


class RecordingIndexer:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        # Ensure directory exists
        os.makedirs(os.path.dirname(self.db_path) if os.path.dirname(self.db_path) else '.', exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS recordings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT UNIQUE,
                    caller TEXT,
                    callee TEXT,
                    start_time TEXT,
                    end_time TEXT,
                    wav_path TEXT,
                    duration REAL,
                    sentiment_score REAL,
                    sentiment_label TEXT,
                    transcript TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            # Create indexes for common queries
            conn.execute('CREATE INDEX IF NOT EXISTS idx_session_id ON recordings(session_id)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_end_time ON recordings(end_time)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_caller ON recordings(caller)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_callee ON recordings(callee)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_sentiment_score ON recordings(sentiment_score)')
            conn.commit()

    def add_recording(self,
                      session_id: str,
                      caller: Optional[str],
                      callee: Optional[str],
                      start_time: str,  # ISO format
                      end_time: str,    # ISO format
                      wav_path: str,
                      duration: float,
                      sentiment_score: float,
                      sentiment_label: str,
                      transcript: str) -> None:
        """Add or update a recording record."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                INSERT OR REPLACE INTO recordings
                (session_id, caller, callee, start_time, end_time, wav_path, duration, sentiment_score, sentiment_label, transcript)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                session_id,
                caller,
                callee,
                start_time,
                end_time,
                wav_path,
                duration,
                sentiment_score,
                sentiment_label,
                transcript
            ))
            conn.commit()

    def get_recording(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get a single recording by session_id."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute('''
                SELECT * FROM recordings WHERE session_id = ?
            ''', (session_id,))
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None

    def list_recordings(self,
                        limit: int = 100,
                        offset: int = 0,
                        start_time_from: Optional[str] = None,
                        start_time_to: Optional[str] = None,
                        caller: Optional[str] = None,
                        callee: Optional[str] = None,
                        min_sentiment: Optional[float] = None,
                        max_sentiment: Optional[float] = None) -> List[Dict[str, Any]]:
        """List recordings with optional filters."""
        query = 'SELECT * FROM recordings WHERE 1=1'
        params = []

        if start_time_from:
            query += ' AND end_time >= ?'
            params.append(start_time_from)
        if start_time_to:
            query += ' AND end_time <= ?'
            params.append(start_time_to)
        if caller:
            query += ' AND caller = ?'
            params.append(caller)
        if callee:
            query += ' AND callee = ?'
            params.append(callee)
        if min_sentiment is not None:
            query += ' AND sentiment_score >= ?'
            params.append(min_sentiment)
        if max_sentiment is not None:
            query += ' AND sentiment_score <= ?'
            params.append(max_sentiment)

        query += ' ORDER BY end_time DESC LIMIT ? OFFSET ?'
        params.extend([limit, offset])

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(query, params)
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def get_total_count(self,
                        start_time_from: Optional[str] = None,
                        start_time_to: Optional[str] = None,
                        caller: Optional[str] = None,
                        callee: Optional[str] = None,
                        min_sentiment: Optional[float] = None,
                        max_sentiment: Optional[float] = None) -> int:
        """Get total count of recordings matching filters."""
        query = 'SELECT COUNT(*) FROM recordings WHERE 1=1'
        params = []

        if start_time_from:
            query += ' AND end_time >= ?'
            params.append(start_time_from)
        if start_time_to:
            query += ' AND end_time <= ?'
            params.append(start_time_to)
        if caller:
            query += ' AND caller = ?'
            params.append(caller)
        if callee:
            query += ' AND callee = ?'
            params.append(callee)
        if min_sentiment is not None:
            query += ' AND sentiment_score >= ?'
            params.append(min_sentiment)
        if max_sentiment is not None:
            query += ' AND sentiment_score <= ?'
            params.append(max_sentiment)

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(query, params)
            return cursor.fetchone()[0]

    def cleanup_old_recordings(self, retention_years: int) -> int:
        """
        Delete recordings older than retention_years.
        Returns number of deleted records.
        """
        cutoff_date = (datetime.now() - timedelta(days=365 * retention_years)).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            # First get the wav paths to delete files
            cursor = conn.execute('''
                SELECT wav_path FROM recordings WHERE end_time < ?
            ''', (cutoff_date,))
            wav_paths = [row[0] for row in cursor.fetchall() if row[0]]

            # Delete database records
            cursor = conn.execute('''
                DELETE FROM recordings WHERE end_time < ?
            ''', (cutoff_date,))
            deleted_count = cursor.rowcount
            conn.commit()

        # Delete actual wav files
        for wav_path in wav_paths:
            try:
                if os.path.exists(wav_path):
                    os.remove(wav_path)
            except OSError as e:
                # Log error but continue
                pass

        return deleted_count
