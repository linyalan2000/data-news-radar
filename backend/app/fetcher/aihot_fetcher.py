"""AihotFetcher: fetches AI-curated content from aihot.virxact.com via RSS feed."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

import feedparser
import httpx

from app.fetcher.source_post import SourcePost

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_HTML_ENT_RE = re.compile(r"&[a-zA-Z]+;|&#\d+;")
_WHITESPACE_RE = re.compile(r"\s+")


def _strip_html(text: str) -> str:
    text = _HTML_TAG_RE.sub(" ", text)
    text = _HTML_ENT_RE.sub(" ", text)
    text = _WHITESPACE_RE.sub(" ", text)
    return text.strip()


logger = logging.getLogger(__name__)
_SOURCE = "aihot"
_RSS_URL = "https://aihot.virxact.com/feed.xml"
_PAGE_URL = "https://aihot.virxact.com/"

# Parse author field like: "noreply@aihot.virxact.com (X：邵猛 (@shao__meng))"
_AUTHOR_HANDLE_RE = re.compile(r"\([^)]*@(\w+)[^)]*\)")
_AUTHOR_DISPLAY_RE = re.compile(r"\(([^)]+)\)")

# Extract recommendation_reason from HTML:
# <div class="timeline-reason"><span class="timeline-reason-label">推荐理由：</span>TEXT</div>
_REASON_RE = re.compile(
    r'data-item-id="([^"]+)".*?'
    r'<div class="timeline-reason">'
    r'<span class="timeline-reason-label">推荐理由：</span>'
    r'([^<]+)</div>',
    re.DOTALL,
)


def _parse_author(raw: str) -> str:
    """Extract Twitter handle from author field."""
    m = _AUTHOR_HANDLE_RE.search(raw)
    if m:
        return f"@{m.group(1)}"
    m2 = _AUTHOR_DISPLAY_RE.search(raw)
    if m2:
        return m2.group(1).strip()
    return raw.strip() or "AIHOT"


class AihotFetcher:
    def __init__(self, fetch_limit: int = 20, news_store=None) -> None:
        self._fetch_limit = fetch_limit
        self._store = news_store
        self._client = httpx.Client(timeout=15, follow_redirects=True)

    def fetch(self) -> list[SourcePost]:
        try:
            posts = self._fetch_feed()
            if not posts:
                return []
            reasons = self._fetch_recommendation_reasons()
            for p in posts:
                p.recommendation_reason = reasons.get(p.external_id)
            logger.info(
                "AihotFetcher: fetched %d posts, %d with recommendation reason",
                len(posts),
                sum(1 for p in posts if p.recommendation_reason),
            )
            return posts
        except Exception as exc:
            logger.error("AihotFetcher: fetch failed: %s", exc)
            return []

    def _fetch_recommendation_reasons(self) -> dict[str, str]:
        """Fetch HTML page and extract {external_id: recommendation_reason}."""
        try:
            resp = self._client.get(
                _PAGE_URL,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    )
                },
            )
            resp.raise_for_status()
            return {m.group(1): m.group(2).strip() for m in _REASON_RE.finditer(resp.text)}
        except Exception as exc:
            logger.warning("AihotFetcher: failed to fetch recommendation reasons: %s", exc)
            return {}

    def _fetch_feed(self) -> list[SourcePost]:
        resp = self._client.get(
            _RSS_URL,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                )
            },
        )
        resp.raise_for_status()
        feed = feedparser.parse(resp.text)

        collected: list[SourcePost] = []
        for entry in feed.entries:
            external_id = entry.get("id") or ""
            if not external_id:
                continue

            title = _strip_html(entry.get("title", ""))
            description = _strip_html(
                entry.get("summary", "") or entry.get("description", "")
            )
            content = (title + "\n" + description)[:2000]

            link = entry.get("link", "")

            raw_author = (entry.get("author") or "").strip()
            author_handle = _parse_author(raw_author)

            published = entry.get("published_parsed") or entry.get("updated_parsed")
            posted_at = (
                datetime(*published[:6], tzinfo=timezone.utc)
                if published
                else datetime.now(timezone.utc)
            )

            labels = None
            if hasattr(entry, "tags") and entry.tags:
                labels = [
                    t.get("term", "") for t in entry.tags if t.get("term")
                ] or None

            if self._store and self._store.exists_by_source_and_external_id(
                _SOURCE, external_id
            ):
                continue

            collected.append(
                SourcePost(
                    source=_SOURCE,
                    external_id=external_id,
                    author_handle=author_handle,
                    title=title,
                    content=content,
                    url=link,
                    posted_at=posted_at,
                    labels=labels,
                )
            )
            if len(collected) >= self._fetch_limit:
                break

        return collected
