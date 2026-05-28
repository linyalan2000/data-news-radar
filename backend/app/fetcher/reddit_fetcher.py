"""Reddit fetcher via public JSON API."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Optional

import httpx

from app.fetcher.source_post import SourcePost

logger = logging.getLogger(__name__)

_SOURCE = "reddit"
_USER_AGENT = "ai-news-researcher/1.0 (research bot)"


class RedditFetcher:
    def __init__(
        self,
        subreddits: list[str],
        keywords: Optional[list[str]] = None,
        fetch_limit: int = 100,
        news_store=None,
        _client: Optional[httpx.Client] = None,
    ) -> None:
        self._subreddits = subreddits
        self._keywords = keywords or []
        self._fetch_limit = fetch_limit
        self._store = news_store
        self._client = _client or httpx.Client(
            timeout=10,
            headers={"User-Agent": _USER_AGENT},
            follow_redirects=True,
        )

    def fetch(self) -> list[SourcePost]:
        results: list[SourcePost] = []
        for sub in self._subreddits:
            try:
                results.extend(self._fetch_subreddit(sub))
            except Exception as exc:
                logger.error("Reddit: failed fetching r/%s: %s", sub, exc)
        # Keyword search is secondary / best-effort
        for kw in self._keywords:
            try:
                results.extend(self._fetch_search(kw))
            except Exception as exc:
                logger.warning("Reddit: keyword search %r failed (non-fatal): %s", kw, exc)
        return results

    def _fetch_subreddit(self, subreddit: str) -> list[SourcePost]:
        collected: list[SourcePost] = []
        after: Optional[str] = None

        while len(collected) < self._fetch_limit:
            params: dict = {"limit": 100, "raw_json": 1}
            if after:
                params["after"] = after

            try:
                resp = self._client.get(
                    f"https://www.reddit.com/r/{subreddit}/new.json",
                    params=params,
                )
            except Exception as exc:
                logger.warning("Reddit: request error for r/%s: %s", subreddit, exc)
                break

            if resp.status_code in (403, 404):
                logger.warning("Reddit: r/%s returned %d — skipping", subreddit, resp.status_code)
                break

            if resp.status_code == 429:
                wait = int(resp.headers.get("Retry-After", "60"))
                logger.warning("Reddit: rate limited, waiting %ds", wait)
                time.sleep(wait)
                continue

            try:
                resp.raise_for_status()
                data = resp.json()["data"]
            except Exception as exc:
                logger.warning("Reddit: failed parsing r/%s response: %s", subreddit, exc)
                break

            for child in data.get("children", []):
                if len(collected) >= self._fetch_limit:
                    break
                post = self._child_to_post(child.get("data", {}))
                if post is None:
                    continue
                if self._store and self._store.exists_by_source_and_external_id(
                    _SOURCE, post.external_id
                ):
                    continue
                collected.append(post)

            after = data.get("after")
            if not after:
                break

        return collected

    def _fetch_search(self, keyword: str) -> list[SourcePost]:
        try:
            resp = self._client.get(
                "https://www.reddit.com/search.json",
                params={"q": keyword, "sort": "new", "limit": 25, "raw_json": 1},
            )
            if not resp.is_success:
                return []
            children = resp.json().get("data", {}).get("children", [])
        except Exception:
            return []

        results = []
        for child in children:
            post = self._child_to_post(child.get("data", {}))
            if post is None:
                continue
            if self._store and self._store.exists_by_source_and_external_id(
                _SOURCE, post.external_id
            ):
                continue
            results.append(post)
        return results

    @staticmethod
    def _child_to_post(data: dict) -> Optional[SourcePost]:
        external_id = data.get("id", "")
        if not external_id:
            return None
        title = data.get("title") or ""
        body = data.get("selftext") or ""
        content = (title + " " + body).strip()[:2000]
        permalink = data.get("permalink", "")
        url = f"https://www.reddit.com{permalink}" if permalink else ""
        author = data.get("author") or "unknown"
        created_utc = data.get("created_utc")
        if created_utc:
            posted_at = datetime.fromtimestamp(float(created_utc), tz=timezone.utc)
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
            points=data.get("score"),
        )
