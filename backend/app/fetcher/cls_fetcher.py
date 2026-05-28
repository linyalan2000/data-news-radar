"""ClsFetcher: fetches breaking news from 财联社 telegraph API."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx

from app.fetcher.source_post import SourcePost

logger = logging.getLogger(__name__)
_SOURCE = "cls"
_API_BASE = "https://www.cls.cn/nodeapi/telegraphList"


def _strip_tags(text: str) -> str:
    import re
    text = re.sub(r'【[^】]*】', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def _from_timestamp(ts: int) -> datetime:
    return datetime.fromtimestamp(ts, tz=timezone.utc)


class ClsFetcher:
    def __init__(
        self,
        keywords: list[str] | None = None,
        fetch_limit: int = 30,
        news_store=None,
    ) -> None:
        self._keywords = keywords or []
        self._fetch_limit = min(fetch_limit, 50)
        self._store = news_store
        self._client = httpx.Client(timeout=15, follow_redirects=True)

    def fetch(self) -> list[SourcePost]:
        try:
            posts = self._fetch_latest()
            logger.info("ClsFetcher: fetched %d posts", len(posts))
            return posts
        except Exception as exc:
            logger.error("ClsFetcher: fetch failed: %s", exc)
            return []

    def _fetch_latest(self) -> list[SourcePost]:
        params = {
            "app": "CailianpressWeb",
            "os": "web",
            "rn": self._fetch_limit,
            "sv": "7.7.5",
        }
        resp = self._client.get(
            _API_BASE,
            params=params,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                "Referer": "https://www.cls.cn/telegraph",
                "Accept": "application/json",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("error") != 0 or "data" not in data:
            logger.warning("ClsFetcher: API error %s", data)
            return []

        roll_data = data["data"].get("roll_data", [])
        results: list[SourcePost] = []

        for item in roll_data:
            content = item.get("content", "")
            if not content:
                continue

            ctime = item.get("ctime", 0)
            posted_at = _from_timestamp(ctime) if ctime else datetime.now(timezone.utc)
            external_id = str(item.get("id", ""))
            title = item.get("title") or _strip_tags(content[:80])
            url = f"https://www.cls.cn/detail/{external_id}"

            # Extract subject names as labels (e.g. 环球市场情报, 人工智能)
            subjects = item.get("subjects") or []
            subject_labels = [s.get("subject_name", "") for s in subjects if s.get("subject_name")]
            labels = ["财联社", "电报"] + subject_labels

            results.append(
                SourcePost(
                    source=_SOURCE,
                    external_id=external_id,
                    author_handle="财联社",
                    title=title,
                    content=content[:2000],
                    url=url,
                    posted_at=posted_at,
                    labels=labels,
                )
            )

        if self._keywords:
            matched = [p for p in results if any(kw in p.content for kw in self._keywords)]
            logger.info("ClsFetcher: keyword filter kept %d/%d posts", len(matched), len(results))
            results = matched

        return results[: self._fetch_limit]