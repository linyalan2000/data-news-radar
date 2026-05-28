"""Unified post schema shared by all source adapters."""
from dataclasses import dataclass
from datetime import datetime


@dataclass
class SourcePost:
    source: str       # "hackernews" | "reddit" | "github"
    external_id: str  # source-specific unique ID
    author_handle: str
    content: str      # title + body, truncated to 2000 chars
    url: str
    posted_at: datetime  # UTC
    title: str = ""   # extracted title (populated by fetcher); display code uses this
    discussion_url: str | None = None  # HN discussion link; None for Reddit/GitHub
    points: int | None = None  # community votes: HN points, Reddit score, GitHub stars
    labels: list[str] | None = None  # opportunity/ topic tags
    recommendation_reason: str | None = None  # editor's recommendation reason (aihot, etc.)
