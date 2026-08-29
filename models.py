from typing import List, Optional
from pydantic import BaseModel, Field, HttpUrl


class ScrapeRequest(BaseModel):
    url: str = Field(
        ...,
        description="The full Instagram Reel or Post URL (e.g., https://www.instagram.com/reel/C3...) ",
        examples=["https://www.instagram.com/reel/DE48s0_vG4v/"],
    )
    timeout_ms: Optional[int] = Field(
        default=None,
        description="Optional override navigation timeout in milliseconds (default: 30000)",
        ge=5000,
        le=120000,
    )


class ReelMetadata(BaseModel):
    shortcode: str = Field(..., description="Unique Instagram shortcode ID")
    url: str = Field(..., description="Target Reel URL")
    username: Optional[str] = Field(None, description="Username of the Reel creator")
    caption: Optional[str] = Field(None, description="Full caption/description text")
    hashtags: List[str] = Field(default_factory=list, description="List of hashtags extracted from caption")
    mentions: List[str] = Field(default_factory=list, description="List of @mentions extracted from caption")
    like_count_raw: Optional[str] = Field(None, description="Raw like count (e.g. '12.4K', '1,200')")
    comment_count_raw: Optional[str] = Field(None, description="Raw comment count (e.g. '345')")
    share_count_raw: Optional[str] = Field(None, description="Raw share count if available")
    video_url: Optional[str] = Field(None, description="Direct playable progressive MP4 video CDN link")
    video_urls_candidates: List[str] = Field(
        default_factory=list,
        description="All extracted video URLs ordered by quality/priority",
    )
    source: str = Field("headless_browser_dom", description="Extraction method")


class ScrapeResponse(BaseModel):
    success: bool = Field(True, description="Whether the extraction succeeded")
    data: ReelMetadata = Field(..., description="Extracted Instagram Reel metadata")


class ErrorResponse(BaseModel):
    success: bool = Field(False, description="Whether the extraction succeeded")
    error: str = Field(..., description="Error message")
    detail: Optional[str] = Field(None, description="Detailed diagnostic context")

