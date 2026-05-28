"""Generic RSS/Atom feed fetcher."""

from __future__ import annotations

import logging
import re
import time
import urllib.parse
from datetime import datetime, timezone
from typing import Optional

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
_SOURCE = "rss"

_FEED_NAMES: dict[str, str] = {
    "people.com.cn": "人民网",
    "sina.com.cn": "新浪新闻",
    "36kr.com": "36氪",
    "bbc.co.uk": "BBC中文",
    "chinadaily.com.cn": "中国日报",
}


class RssFetcher:
    def __init__(
        self,
        feed_urls: list[str],
        fetch_limit: int = 20,
        news_store=None,
    ) -> None:
        self._feed_urls = feed_urls
        self._fetch_limit = fetch_limit
        self._store = news_store
        self._client = httpx.Client(timeout=15, follow_redirects=True)

    def fetch(self) -> list[SourcePost]:
        results: list[SourcePost] = []
        for url in self._feed_urls:
            try:
                posts = self._fetch_feed(url)
                logger.info("RSS %s: fetched %d posts", url, len(posts))
                results.extend(posts)
            except Exception as exc:
                logger.error("RSS %s: fetch failed: %s", url, exc)
            time.sleep(1)
        return results[: self._fetch_limit]

    def _fetch_feed(self, url: str) -> list[SourcePost]:
        resp = self._client.get(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            },
        )
        resp.raise_for_status()
        feed = feedparser.parse(resp.text)

        collected: list[SourcePost] = []
        for entry in feed.entries:
            external_id = entry.get("id") or entry.get("link", url)
            title = _strip_html(entry.get("title", ""))
            summary = _strip_html(
                entry.get("summary", "") or entry.get("description", "")
            )
            content = (title + "\n" + summary)[:2000]

            link = entry.get("link", external_id)
            domain = urllib.parse.urlparse(url).netloc
            if domain.startswith("www."):
                domain = domain[4:]
            author_entry = (entry.get("author") or "").strip()
            author = (
                _FEED_NAMES.get(domain)
                or (author_entry if author_entry else None)
                or feed.feed.get("title", "")
            )

            published = entry.get("published_parsed") or entry.get("updated_parsed")
            if published:
                posted_at = datetime(*published[:6], tzinfo=timezone.utc)
            else:
                posted_at = datetime.now(timezone.utc)

            if self._store and self._store.exists_by_source_and_external_id(
                _SOURCE, external_id
            ):
                continue

            collected.append(
                SourcePost(
                    source=_SOURCE,
                    external_id=external_id,
                    author_handle=author,
                    title=title,
                    content=content,
                    url=link,
                    posted_at=posted_at,
                )
            )

        return collected
