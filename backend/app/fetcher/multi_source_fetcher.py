"""MultiSourceFetcher: orchestrates HN, Reddit, GitHub, ArXiv, and RSS adapters."""

from __future__ import annotations

import logging

from app.fetcher.hn_fetcher import HackerNewsFetcher
from app.fetcher.reddit_fetcher import RedditFetcher
from app.fetcher.github_fetcher import GitHubFetcher
from app.fetcher.gov_fetcher import GovFetcher
from app.fetcher.rss_fetcher import RssFetcher
from app.fetcher.source_post import SourcePost
from app.fetcher.wechat_fetcher import WeChatFetcher

logger = logging.getLogger(__name__)


class MultiSourceFetcher:
    def __init__(
        self,
        hn: HackerNewsFetcher | None = None,
        reddit: RedditFetcher | None = None,
        github: GitHubFetcher | None = None,
        arxiv=None,
        rss=None,
        gov: GovFetcher | None = None,
        wechat: WeChatFetcher | None = None,
        bidding=None,
        cls=None,
        aihot=None,
    ) -> None:
        self._adapters: list = []
        if hn is not None:
            self._adapters.append(hn)
        if reddit is not None:
            self._adapters.append(reddit)
        if github is not None:
            self._adapters.append(github)
        if arxiv is not None:
            self._adapters.append(arxiv)
        if rss is not None:
            self._adapters.append(rss)
        if gov is not None:
            self._adapters.append(gov)
        if wechat is not None:
            self._adapters.append(wechat)
        if bidding is not None:
            self._adapters.append(bidding)
        if cls is not None:
            self._adapters.append(cls)
        if aihot is not None:
            self._adapters.append(aihot)

    def fetch(self) -> list[SourcePost]:
        results: list[SourcePost] = []
        for adapter in self._adapters:
            name = adapter.__class__.__name__
            try:
                posts = adapter.fetch()
                logger.info("%s: fetched %d posts", name, len(posts))
                results.extend(posts)
            except Exception as exc:
                logger.error("%s: fetch failed, skipping: %s", name, exc)
        return results
