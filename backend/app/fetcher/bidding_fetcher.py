"""BiddingFetcher: scrapes Fujian data-sector bidding/opportunity announcements."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from app.fetcher.source_post import SourcePost

logger = logging.getLogger(__name__)
_SOURCE = "bidding"

_SITES: dict[str, dict] = {
    "福建省数据管理局通知公告": {
        "url": "https://fgw.fujian.gov.cn/ztzl/szfjzt/tzgg/",
        "domain": "fgw.fujian.gov.cn",
        "link_pattern": re.compile(r"/tzgg/\d{6}/"),
        "date_in_url": re.compile(r"(\d{4})(\d{2})(\d{2})"),
        "container": "ul li",
    },
}

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

_OPPORTUNITY_TAGS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"申报|征集|遴选"), "申报机会"),
    (re.compile(r"公示|名单|入选"), "结果公示"),
    (re.compile(r"招标|采购|竞争性磋商|询价"), "招标采购"),
    (re.compile(r"资金|补助|奖补|专项资金|补贴"), "资金支持"),
    (re.compile(r"招商|签约|对接"), "招商合作"),
    (re.compile(r"数据企业|入库|标杆|培育"), "企业培育"),
    (re.compile(r"数据集|数据标注|AI|人工智能|大模型"), "AI数据"),
    (re.compile(r"可信数据空间|数据交易|数据流通|数据要素"), "数据要素"),
    (re.compile(r"数字经济|数字化|转型"), "数字经济"),
    (re.compile(r"峰会|大赛|赛道|比赛"), "活动赛事"),
]


class BiddingFetcher:
    """Fetch Fujian data-sector bidding/opportunity announcements."""

    def __init__(self, fetch_limit: int = 30, news_store=None) -> None:
        self._fetch_limit = fetch_limit
        self._store = news_store
        self._client = httpx.Client(timeout=15, follow_redirects=True)

    def fetch(self) -> list[SourcePost]:
        per_site = max(10, self._fetch_limit // len(_SITES))
        results: list[SourcePost] = []
        for name, cfg in _SITES.items():
            try:
                posts = self._fetch_site(name, cfg)
                posts = posts[:per_site]
                logger.info("Bidding %s: fetched %d posts", name, len(posts))
                results.extend(posts)
            except Exception as exc:
                logger.error("Bidding %s: fetch failed: %s", name, exc)
        return results[: self._fetch_limit]

    def _scrape_article_date(self, url: str) -> datetime | None:
        try:
            headers = {"User-Agent": _UA}
            resp = self._client.get(url, headers=headers, timeout=10)
            resp.raise_for_status()
            m = re.search(
                r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})\s+(\d{1,2}):(\d{1,2})", resp.text
            )
            if m:
                return datetime(
                    int(m.group(1)),
                    int(m.group(2)),
                    int(m.group(3)),
                    int(m.group(4)),
                    int(m.group(5)),
                    tzinfo=timezone.utc,
                )
        except Exception:
            pass
        return None

    def _make_external_id(self, url: str) -> str:
        path = url.split("://", 1)[-1] if "://" in url else url
        return re.sub(r"[^a-zA-Z0-9]", "_", path).strip("_")[:120]

    def _tag_opportunity(self, title: str) -> list[str]:
        tags = []
        for pattern, tag in _OPPORTUNITY_TAGS:
            if pattern.search(title):
                tags.append(tag)
        return tags

    def _fetch_site(self, name: str, cfg: dict) -> list[SourcePost]:
        page_url = cfg["url"]
        req_headers = {"User-Agent": _UA}
        resp = self._client.get(page_url, headers=req_headers)
        resp.raise_for_status()
        resp.encoding = "utf-8"

        soup = BeautifulSoup(resp.text, "lxml")

        base_dir = (
            page_url if page_url.endswith("/") else page_url[: page_url.rfind("/") + 1]
        )

        collected: list[SourcePost] = []
        seen_ids: set[str] = set()

        container_sel = cfg.get("container", "li")
        items = (
            soup.select(container_sel) if container_sel != "li" else soup.find_all("li")
        )

        for item in items:
            link = item.find("a", href=True)
            if not link:
                continue
            href = link["href"].strip()
            title = (link.get_text() or "").strip()
            if not title:
                continue

            if href.startswith("./"):
                href = base_dir + href[2:]
            elif href.startswith("/"):
                parsed = urlparse(page_url)
                href = f"{parsed.scheme}://{parsed.netloc}{href}"
            elif not href.startswith("http"):
                href = base_dir + href

            link_pattern = cfg.get("link_pattern")
            if link_pattern and not link_pattern.search(href):
                continue

            if cfg.get("domain") and cfg["domain"] not in href:
                continue

            ext_id = self._make_external_id(href)
            if ext_id in seen_ids:
                continue
            seen_ids.add(ext_id)

            posted_at: datetime | None = None
            date_in_url = cfg.get("date_in_url")
            if date_in_url:
                m = date_in_url.search(href)
                if m:
                    try:
                        posted_at = datetime(
                            int(m.group(1)),
                            int(m.group(2)),
                            int(m.group(3)),
                            tzinfo=timezone.utc,
                        )
                    except ValueError:
                        pass

            if posted_at is None:
                posted_at = datetime.now(timezone.utc)

            date_text = item.get_text()
            date_m = re.search(
                r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", date_text
            )
            if date_m:
                try:
                    parsed = datetime(
                        int(date_m.group(1)),
                        int(date_m.group(2)),
                        int(date_m.group(3)),
                        tzinfo=timezone.utc,
                    )
                    if parsed <= datetime.now(timezone.utc):
                        posted_at = parsed
                except ValueError:
                    pass

            tags = self._tag_opportunity(title)

            post = SourcePost(
                source=_SOURCE,
                external_id=ext_id,
                author_handle=name,
                title=title,
                content=title,
                url=href,
                posted_at=posted_at,
            )
            post.labels = tags if tags else ["商机"]
            collected.append(post)

        return collected
