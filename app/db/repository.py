"""
app/db/repository.py
--------------------
Asynchronous PostgreSQL repository for job persistence using asyncpg.
"""
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import asyncpg

from app.config import settings

logger = logging.getLogger("insta.db.repository")


def _get_postgres_dsn() -> str:
    db_url = settings.DATABASE_URL
    # Normalize postgresql+asyncpg:// or postgresql:// to postgres:// for asyncpg
    if db_url.startswith("postgresql+asyncpg://"):
        db_url = "postgresql://" + db_url[len("postgresql+asyncpg://"):]
    elif db_url.startswith("sqlite"):
        # Fallback if someone didn't update DATABASE_URL
        db_url = f"postgresql://{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD}@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}"
    return db_url


class JobRepository:
    def __init__(self) -> None:
        self.dsn = _get_postgres_dsn()
        self._pool: Optional[asyncpg.Pool] = None

    async def get_pool(self) -> asyncpg.Pool:
        if self._pool is None:
            logger.info("Connecting to PostgreSQL at: %s", self.dsn.split("@")[-1] if "@" in self.dsn else self.dsn)
            self._pool = await asyncpg.create_pool(
                dsn=self.dsn,
                min_size=1,
                max_size=10,
                command_timeout=60.0,
            )
        return self._pool

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    def _record_to_dict(self, record: Optional[asyncpg.Record]) -> Optional[Dict[str, Any]]:
        if not record:
            return None
        data = dict(record)

        # Parse JSONB fields if returned as string
        meta = data.get("metadata_json")
        if isinstance(meta, str):
            try:
                data["metadata"] = json.loads(meta)
            except Exception:
                data["metadata"] = None
        else:
            data["metadata"] = meta

        trans = data.get("transcription_json")
        if isinstance(trans, str):
            try:
                data["transcription"] = json.loads(trans)
            except Exception:
                data["transcription"] = None
        else:
            data["transcription"] = trans

        # Convert timestamps to ISO string if datetime
        for ts_field in ("created_at", "updated_at", "completed_at"):
            val = data.get(ts_field)
            if isinstance(val, datetime):
                data[ts_field] = val.isoformat()

        return data

    async def create_job(
        self,
        job_id: str,
        url: str,
        transcription_provider: Optional[str] = None,
        webhook_url: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        pool = await self.get_pool()
        now = datetime.now(timezone.utc)

        query = """
            INSERT INTO jobs (
                id, url, status, stage, current_queue,
                transcription_provider, webhook_url, webhook_status,
                created_at, updated_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            RETURNING *;
        """
        async with pool.acquire() as conn:
            record = await conn.fetchrow(
                query,
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
            )
            return self._record_to_dict(record)

    async def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        pool = await self.get_pool()
        query = "SELECT * FROM jobs WHERE id = $1;"
        async with pool.acquire() as conn:
            record = await conn.fetchrow(query, job_id)
            return self._record_to_dict(record)

    async def update_job(
        self,
        job_id: str,
        status: Optional[str] = None,
        stage: Optional[str] = None,
        current_queue: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        video_path: Optional[str] = None,
        audio_path: Optional[str] = None,
        transcription: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
        completed: bool = False,
        webhook_status: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        pool = await self.get_pool()
        now = datetime.now(timezone.utc)

        set_clauses = ["updated_at = $1"]
        params: list = [now]
        param_idx = 2

        if status is not None:
            set_clauses.append(f"status = ${param_idx}")
            params.append(status)
            param_idx += 1

        if stage is not None:
            set_clauses.append(f"stage = ${param_idx}")
            params.append(stage)
            param_idx += 1

        if current_queue is not None:
            set_clauses.append(f"current_queue = ${param_idx}")
            params.append(current_queue)
            param_idx += 1

        if metadata is not None:
            set_clauses.append(f"metadata_json = ${param_idx}")
            params.append(json.dumps(metadata))
            param_idx += 1

        if video_path is not None:
            set_clauses.append(f"video_path = ${param_idx}")
            params.append(video_path)
            param_idx += 1

        if audio_path is not None:
            set_clauses.append(f"audio_path = ${param_idx}")
            params.append(audio_path)
            param_idx += 1

        if transcription is not None:
            set_clauses.append(f"transcription_json = ${param_idx}")
            params.append(json.dumps(transcription))
            param_idx += 1

        if error is not None:
            set_clauses.append(f"error_message = ${param_idx}")
            params.append(error)
            param_idx += 1

        if completed:
            set_clauses.append(f"completed_at = ${param_idx}")
            params.append(now)
            param_idx += 1

        if webhook_status is not None:
            set_clauses.append(f"webhook_status = ${param_idx}")
            params.append(webhook_status)
            param_idx += 1

        set_str = ", ".join(set_clauses)
        query = f"UPDATE jobs SET {set_str} WHERE id = ${param_idx} RETURNING *;"
        params.append(job_id)

        async with pool.acquire() as conn:
            record = await conn.fetchrow(query, *params)
            return self._record_to_dict(record)


job_repo = JobRepository()

