"""GitHub fetcher: recently-created high-star repos + monitored repo releases."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

from app.fetcher.source_post import SourcePost

logger = logging.getLogger(__name__)

_SOURCE = "github"
_API_BASE = "https://api.github.com"


class GitHubFetcher:
    def __init__(
        self,
        keywords: list[str],
        monitored_repos: list[str],
        fetch_limit: int = 30,
        github_token: str = "",
        news_store=None,
        _client: Optional[httpx.Client] = None,
    ) -> None:
        self._keywords = keywords
        self._monitored_repos = monitored_repos
        self._fetch_limit = fetch_limit
        self._authenticated = bool(github_token)
        self._news_store = news_store
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if github_token:
            headers["Authorization"] = f"Bearer {github_token}"
        self._client = _client or httpx.Client(timeout=15, headers=headers)

    def fetch(self) -> list[SourcePost]:
        results: list[SourcePost] = []
        # 1. Trending / recently-created repos by keyword
        for kw in self._keywords:
            try:
                results.extend(self._fetch_repos(kw))
            except Exception as exc:
                logger.error("GitHub: failed fetching repos for %r: %s", kw, exc)
            # Back-off between Search API calls (10 rpm unauth, 30 rpm auth)
            if not self._authenticated:
                time.sleep(6)
        # 2. New releases from monitored repos
        for repo in self._monitored_repos:
            try:
                post = self._fetch_latest_release(repo)
                if post:
                    results.append(post)
            except Exception as exc:
                logger.warning("GitHub: failed fetching release for %s: %s", repo, exc)
        return results

    def _fetch_repos(self, keyword: str) -> list[SourcePost]:
        since_date = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")
        query = f"{keyword}+created:>{since_date}"
        collected: list[SourcePost] = []
        url: Optional[str] = (
            f"{_API_BASE}/search/repositories"
            f"?q={query}&sort=stars&order=desc&per_page=30"
        )

        while url and len(collected) < self._fetch_limit:
            resp = self._client.get(url)
            self._check_rate_limit(resp)
            resp.raise_for_status()

            items = resp.json().get("items", [])
            for item in items:
                if len(collected) >= self._fetch_limit:
                    break
                post = self._repo_to_post(item)
                if self._news_store and self._news_store.exists_by_source_and_external_id(
                    _SOURCE, post.external_id
                ):
                    continue
                collected.append(post)

            link = resp.headers.get("Link", "")
            url = self._parse_next_link(link)

        return collected

    def _fetch_latest_release(self, repo: str) -> Optional[SourcePost]:
        resp = self._client.get(f"{_API_BASE}/repos/{repo}/releases/latest")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        release = resp.json()
        external_id = f"{repo}@{release.get('tag_name', release.get('id', ''))}"
        if self._news_store and self._news_store.exists_by_source_and_external_id(
            _SOURCE, external_id
        ):
            return None
        body = (release.get("body") or "")[:1000]
        content = f"{release.get('name', repo)} {body}".strip()
        published = release.get("published_at") or release.get("created_at")
        posted_at = (
            datetime.fromisoformat(published.replace("Z", "+00:00"))
            if published else datetime.now(timezone.utc)
        )
        return SourcePost(
            source=_SOURCE,
            external_id=external_id,
            author_handle=repo.split("/")[0],
            title=release.get('name', repo),
            content=content,
            url=release.get("html_url", f"https://github.com/{repo}/releases"),
            posted_at=posted_at,
            points=0,
        )

    @staticmethod
    def _repo_to_post(item: dict) -> SourcePost:
        topics = " ".join(item.get("topics", []))
        description = item.get("description") or ""
        content = (description + " " + topics).strip()[:2000]
        pushed = item.get("pushed_at") or item.get("created_at")
        posted_at = (
            datetime.fromisoformat(pushed.replace("Z", "+00:00"))
            if pushed else datetime.now(timezone.utc)
        )
        return SourcePost(
            source=_SOURCE,
            external_id=item["full_name"],
            author_handle=item.get("owner", {}).get("login", "unknown"),
            title=item.get("full_name", ""),
            content=content,
            url=item.get("html_url", ""),
            posted_at=posted_at,
            points=item.get("stargazers_count"),
        )

    def _check_rate_limit(self, resp: httpx.Response) -> None:
        remaining = resp.headers.get("X-RateLimit-Remaining")
        if remaining is not None and int(remaining) == 0:
            reset = resp.headers.get("X-RateLimit-Reset")
            if reset:
                wait = max(0, int(reset) - int(time.time())) + 1
                logger.warning("GitHub: rate limit exhausted, waiting %ds", wait)
                time.sleep(wait)

    @staticmethod
    def _parse_next_link(link_header: str) -> Optional[str]:
        for part in link_header.split(","):
            if 'rel="next"' in part:
                url_part = part.split(";")[0].strip()
                return url_part.strip("<>")
        return None
