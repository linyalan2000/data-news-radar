"""Pydantic schemas for the REST API."""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, model_validator


class Post(BaseModel):
    id: int
    source: str
    external_id: str
    author_handle: str
    title: str
    content: str
    url: str
    posted_at: datetime
    fetched_at: datetime
    relevance_score: Optional[float] = None
    points: Optional[int] = None
    summary_zh: Optional[str] = None
    topic_group: Optional[str] = None  # hash; groups duplicate/similar news
    recommendation_reason: Optional[str] = None
    is_relevant: bool
    labels: List[str]
    digest_sent: bool
    discussion_url: Optional[str] = None

    model_config = {"from_attributes": True}

    @model_validator(mode="after")
    def _compute_discussion_url(self) -> "Post":
        if self.source == "hackernews" and self.discussion_url is None:
            self.discussion_url = (
                f"https://news.ycombinator.com/item?id={self.external_id}"
            )
        return self


class ReportListItem(BaseModel):
    id: int
    generated_at: datetime
    post_count: int
    model_used: str

    model_config = {"from_attributes": True}


class ReportResponse(BaseModel):
    id: int
    generated_at: datetime
    content: str
    post_count: int
    model_used: str

    model_config = {"from_attributes": True}


class PaginatedNewsResponse(BaseModel):
    total: int
    page: int
    per_page: int
    items: List[Post]


class DigestTriggerResult(BaseModel):
    posts_included: int
    email_sent: bool
    webhook_sent: bool


class DigestJobResponse(BaseModel):
    job_id: str
    status: str  # "queued" | "running" | "done" | "failed"


class DigestJobStatus(BaseModel):
    job_id: str
    status: str  # "queued" | "running" | "done" | "failed"
    result: Optional[DigestTriggerResult] = None


class HealthResponse(BaseModel):
    status: str  # "ok" | "degraded"
    db: str  # "connected" | "disconnected"
    last_fetch_at: Optional[datetime] = None
    scheduler: bool = False
    wechat_login_needed: bool = False


class BookmarkCreate(BaseModel):
    article_id: int
    note: Optional[str] = None


class BookmarkResponse(BaseModel):
    id: int
    article_id: int
    note: Optional[str] = None
    created_at: datetime
    article: Optional[Post] = None

    model_config = {"from_attributes": True}
