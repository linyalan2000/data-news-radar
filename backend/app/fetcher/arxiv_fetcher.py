"""ArXiv Atom feed fetcher for AI/ML papers (Phase 17.3).

Fetches recent papers from ArXiv filtered by cs.AI / cs.LG / cs.CL categories.
Controlled by FEATURES["arxiv_fetcher"] flag in config.py.
"""
from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

from app.fetcher.source_post import SourcePost

logger = logging.getLogger(__name__)

_ARXIV_API = "http://export.arxiv.org/api/query"
_NS = {"atom": "http://www.w3.org/2005/Atom"}
_MAX_AGE_DAYS = 7


class ArxivFetcher:
    """Fetch recent AI/ML papers from ArXiv Atom API."""

    def __init__(
        self,
        categories: list[str],
        keywords: list[str],
        max_results: int = 50,
        news_store=None,
        _client: Optional[httpx.Client] = None,
    ) -> None:
        self._categories = categories or ["cs.AI", "cs.LG", "cs.CL"]
        self._keywords = keywords
        self._max_results = min(max_results, 200)
        self._store = news_store
        self._client = _client or httpx.Client(timeout=30)

    def fetch(self) -> list[SourcePost]:
        cat_query = " OR ".join(f"cat:{c}" for c in self._categories)
        if self._keywords:
            kw_query = " OR ".join(f'ti:"{k}"' for k in self._keywords[:5])
            search_query = f"({cat_query}) AND ({kw_query})"
        else:
            search_query = cat_query

        try:
            resp = self._client.get(
                _ARXIV_API,
                params={
                    "search_query": search_query,
                    "max_results": self._max_results,
                    "sortBy": "submittedDate",
                    "sortOrder": "descending",
                },
            )
            resp.raise_for_status()
        except Exception as exc:
            logger.error("ArxivFetcher: HTTP error: %s", exc)
            return []

        try:
            return self._parse(resp.text)
        except Exception as exc:
            logger.error("ArxivFetcher: parse error: %s", exc)
            return []

    def _parse(self, xml_text: str) -> list[SourcePost]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=_MAX_AGE_DAYS)
        root = ET.fromstring(xml_text)
        results: list[SourcePost] = []

        for entry in root.findall("atom:entry", _NS):
            try:
                arxiv_id = self._get_text(entry, "atom:id").split("/abs/")[-1]
                title = self._get_text(entry, "atom:title").replace("\n", " ").strip()
                abstract = self._get_text(entry, "atom:summary").replace("\n", " ").strip()
                published_str = self._get_text(entry, "atom:published")
                published = datetime.fromisoformat(published_str.replace("Z", "+00:00"))
                url = f"https://arxiv.org/abs/{arxiv_id}"

                # Pre-filter: skip papers older than MAX_AGE_DAYS
                if published < cutoff:
                    continue

                # Skip if already in DB
                if self._store and self._store.exists_by_source_and_external_id("arxiv", arxiv_id):
                    continue

                content = f"{title}. {abstract}"[:2000]
                results.append(SourcePost(
                    source="arxiv",
                    external_id=arxiv_id,
                    author_handle="arxiv",
                    title=title,
                    content=content,
                    url=url,
                    posted_at=published,
                    points=None,
                    discussion_url=None,
                ))
            except Exception as exc:
                logger.warning("ArxivFetcher: skipping entry due to parse error: %s", exc)
                continue

        logger.info("ArxivFetcher: fetched %d papers", len(results))
        return results

    @staticmethod
    def _get_text(element, tag: str) -> str:
        node = element.find(tag, _NS)
        return (node.text or "").strip() if node is not None else ""
