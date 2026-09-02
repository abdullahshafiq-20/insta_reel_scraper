from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class JobStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class JobStage(str, Enum):
    INITIALIZED = "initialized"
    METADATA_EXTRACTED = "metadata_extracted"
    DOWNLOADED = "downloaded"
    AUDIO_CONVERTED = "audio_converted"
    TRANSCRIBED = "transcribed"
    FINISHED = "finished"


# ---------------------------------------------------------------------------
# Nested payload models
# ---------------------------------------------------------------------------

class ReelMetadata(BaseModel):
    shortcode: str = Field(..., description="Unique Instagram shortcode")
    url: str = Field(..., description="Target Reel / Post URL")
    username: Optional[str] = Field(None, description="Creator username")
    caption: Optional[str] = Field(None, description="Full caption text")
    hashtags: List[str] = Field(default_factory=list, description="Extracted hashtags")
    mentions: List[str] = Field(default_factory=list, description="Extracted @mentions")
    like_count_raw: Optional[str] = Field(None, description="Raw likes string, e.g. '12.5K'")
    comment_count_raw: Optional[str] = Field(None, description="Raw comments string")
    share_count_raw: Optional[str] = Field(None, description="Raw shares string")
    video_url: Optional[str] = Field(None, description="Best progressive MP4 CDN URL")
    video_urls_candidates: List[str] = Field(
        default_factory=list,
        description="All candidate video stream URLs ordered by quality",
    )
    source: str = Field("headless_browser_dom", description="Extraction method")


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class JobCreate(BaseModel):
    url: str = Field(
        ...,
        description="Instagram Reel or Post URL",
        examples=["https://www.instagram.com/reel/DE48s0_vG4v/"],
    )
    transcription_provider: Optional[str] = Field(
        default=None,
        description="Override provider per-job: 'local' or 'openai'",
    )
    webhook_url: Optional[str] = Field(
        default=None,
        description="Per-job webhook override (overrides env WEBHOOK_URL)",
    )


from typing import Any, Dict, List, Optional, Union

class JobQueued(BaseModel):
    """Immediate 202 response returned when a job is submitted."""
    success: bool = True
    job_id: str
    status: JobStatus
    stage: JobStage
    created_at: datetime
    created_at: Union[datetime, str]


class JobStatusResponse(BaseModel):
    """Polling response for GET /api/v1/jobs/{job_id}."""
    success: bool = True
    job_id: str
    status: JobStatus
    stage: JobStage
    current_queue: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: Union[datetime, str]
    updated_at: Optional[Union[datetime, str]] = None
    completed_at: Optional[Union[datetime, str]] = None
    # Populated once stage=metadata_extracted (Stage 1 complete)
    metadata: Optional[ReelMetadata] = None
    # Populated in later stages
    transcription: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class ErrorResponse(BaseModel):
    success: bool = False
    error: str
    detail: Optional[str] = None
