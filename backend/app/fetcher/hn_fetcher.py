"""Hacker News fetcher via Algolia Search API."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Optional

import httpx

from app.fetcher.source_post import SourcePost

logger = logging.getLogger(__name__)

_ALGOLIA_URL = "https://hn.algolia.com/api/v1/search"
_SOURCE = "hackernews"


class HackerNewsFetcher:
    def __init__(
        self,
        keywords: list[str],
        fetch_limit: int = 100,
        news_store=None,
        _client: Optional[httpx.Client] = None,
    ) -> None:
        self._keywords = keywords
        self._fetch_limit = fetch_limit
        self._store = news_store
        self._client = _client or httpx.Client(timeout=10)

    def fetch(self) -> list[SourcePost]:
        results: list[SourcePost] = []
        for keyword in self._keywords:
            try:
                results.extend(self._fetch_keyword(keyword))
            except Exception as exc:
                logger.error("HN: failed fetching keyword %r: %s", keyword, exc)
        return results

    def _fetch_keyword(self, keyword: str) -> list[SourcePost]:
        collected: list[SourcePost] = []
        page = 0
        consecutive_errors = 0

        while len(collected) < self._fetch_limit:
            try:
                resp = self._client.get(
                    _ALGOLIA_URL,
                    params={"query": keyword, "tags": "story", "page": page, "hitsPerPage": 20},
                )
                resp.raise_for_status()
                consecutive_errors = 0
            except Exception as exc:
                consecutive_errors += 1
                logger.warning("HN: request error (attempt %d): %s", consecutive_errors, exc)
                if consecutive_errors >= 3:
                    logger.error("HN: skipping keyword %r after 3 consecutive errors", keyword)
                    break
                continue

            hits = resp.json().get("hits", [])
            if not hits:
                break

            for hit in hits:
                if len(collected) >= self._fetch_limit:
                    break
                post = self._hit_to_post(hit)
                if post is None:
                    continue
                if self._store and self._store.exists_by_source_and_external_id(
                    _SOURCE, post.external_id
                ):
                    continue
                collected.append(post)

            page += 1
            time.sleep(1)  # conservative rate

        return collected

    @staticmethod
    def _hit_to_post(hit: dict) -> Optional[SourcePost]:
        external_id = str(hit.get("objectID", ""))
        if not external_id:
            return None
        title = hit.get("title") or ""
        body = hit.get("story_text") or ""
        content = (title + "\n" + body).strip()[:2000]
        url = hit.get("url") or f"https://news.ycombinator.com/item?id={external_id}"
        author = hit.get("author") or "unknown"
        created = hit.get("created_at")
        if created:
            try:
                posted_at = datetime.fromisoformat(created.replace("Z", "+00:00"))
            except ValueError:
                posted_at = datetime.now(timezone.utc)
        else:
            posted_at = datetime.now(timezone.utc)
        return SourcePost(
            source=_SOURCE,
            external_id=external_id,
            author_handle=author,
            title=title,
            content=content,
            url=url,
            posted_at=posted_at,
            discussion_url=f"https://news.ycombinator.com/item?id={external_id}",
            points=hit.get("points"),
        )
