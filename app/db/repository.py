"""
app/db/repository.py
--------------------
Lightweight, thread-safe asynchronous SQLite repository for job persistence.
Uses Python's built-in sqlite3 with asyncio.to_thread, requiring no external ORM.
"""
import asyncio
import json
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.config import settings

logger = logging.getLogger("insta.db")


def _get_db_path() -> str:
    db_url = settings.DATABASE_URL
    if ":///" in db_url:
        return db_url.split(":///", 1)[1]
    if "://" in db_url:
        return db_url.split("://", 1)[1]
    return db_url or "jobs.db"


class JobRepository:
    def __init__(self) -> None:
        self.db_path = _get_db_path()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    url TEXT NOT NULL,
                    status TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    current_queue TEXT,
                    metadata_json TEXT,
                    video_path TEXT,
                    audio_path TEXT,
                    transcription_json TEXT,
                    error_message TEXT,
                    transcription_provider TEXT,
                    webhook_url TEXT,
                    webhook_status TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT,
                    completed_at TEXT
                )
                """
            )
            conn.commit()
        logger.info("Initialized SQLite jobs database at: %s", self.db_path)

    def _row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        data = dict(row)
        if data.get("metadata_json"):
            try:
                data["metadata"] = json.loads(data["metadata_json"])
            except Exception:
                data["metadata"] = None
        else:
            data["metadata"] = None

        if data.get("transcription_json"):
            try:
                data["transcription"] = json.loads(data["transcription_json"])
            except Exception:
                data["transcription"] = None
        else:
            data["transcription"] = None

        return data

    async def create_job(
        self,
        job_id: str,
        url: str,
        transcription_provider: Optional[str] = None,
        webhook_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()

        def _sync_create():
            with self._get_connection() as conn:
                conn.execute(
                    """
                    INSERT INTO jobs (
                        id, url, status, stage, current_queue,
                        transcription_provider, webhook_url, webhook_status,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        job_id,
                        url,
                        "queued",
                        "initialized",
                        "scrape_queue",
                        transcription_provider or settings.TRANSCRIPTION_PROVIDER,
                        webhook_url or settings.WEBHOOK_URL or None,
                        "pending",
                        now,
                        now,
                    ),
                )
                conn.commit()

        await asyncio.to_thread(_sync_create)
        return await self.get_job(job_id)

    async def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        def _sync_get():
            with self._get_connection() as conn:
                cur = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
                row = cur.fetchone()
                return self._row_to_dict(row) if row else None

        return await asyncio.to_thread(_sync_get)

    async def update_job(
        self,
        job_id: str,
        status: Optional[str] = None,
        stage: Optional[str] = None,
        current_queue: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
        completed: bool = False,
        webhook_status: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        now = datetime.now(timezone.utc).isoformat()

        def _sync_update():
            fields = ["updated_at = ?"]
            params = [now]

            if status is not None:
                fields.append("status = ?")
                params.append(status)
            if stage is not None:
                fields.append("stage = ?")
                params.append(stage)
            if current_queue is not None:
                fields.append("current_queue = ?")
                params.append(current_queue)
            if metadata is not None:
                fields.append("metadata_json = ?")
                params.append(json.dumps(metadata))
            if error is not None:
                fields.append("error_message = ?")
                params.append(error)
            if completed:
                fields.append("completed_at = ?")
                params.append(now)
            if webhook_status is not None:
                fields.append("webhook_status = ?")
                params.append(webhook_status)

            params.append(job_id)
            query = f"UPDATE jobs SET {', '.join(fields)} WHERE id = ?"

            with self._get_connection() as conn:
                conn.execute(query, tuple(params))
                conn.commit()

        await asyncio.to_thread(_sync_update)
        return await self.get_job(job_id)


job_repo = JobRepository()

