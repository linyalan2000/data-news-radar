"""Government website scraper for data policy announcements."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

import urllib.parse

import httpx
from bs4 import BeautifulSoup

from app.fetcher.source_post import SourcePost

logger = logging.getLogger(__name__)
_SOURCE = "gov"

# Site configs: how to find news links on each government site
_SITES: dict[str, dict] = {
    "国家发展和改革委员会": {
        "urls": [
            "https://www.ndrc.gov.cn/xwdt/dt/wlddt/",
            "https://www.ndrc.gov.cn/xwdt/xwfb/",
            "https://www.ndrc.gov.cn/xwdt/tzgg/",
        ],
        "link_pattern": re.compile(r"\d{6}/t\d{8}_"),
        "domain": "www.ndrc.gov.cn",
        "detail_selector": "div.article",
        "date_in_url": re.compile(r"(\d{4})(\d{2})(\d{2})"),
        "pages": 1,
    },

    "国家数据局": {
        "urls": [
            "https://www.nda.gov.cn/sjj/swdt/list/index_pc_1.html",
            "https://www.nda.gov.cn/sjj/zwgk/list/index_pc_1.html",
            "https://www.nda.gov.cn/sjj/swdt/jlddt/list/index_pc_1.html",
        ],
        "link_pattern": re.compile(r"/sjj/(swdt|xwfb|zwgk|jgsz/jld)/"),
        "domain": "www.nda.gov.cn",
        "detail_selector": "div.article",
        "date_in_url": re.compile(r"(\d{4})(\d{2})(\d{2})"),
        "paginate": "{page}.html",
        "pages": 2,
        "headers": {
            "Referer": "https://www.nda.gov.cn/",
        },
    },

    "福建省数据管理局": {
        "url": "https://fgw.fujian.gov.cn/ztzl/szfjzt/",
        "link_pattern": re.compile(r"/(sxdt|gzdt|zwgk)/"),
        "domain": "fgw.fujian.gov.cn",
        "date_in_url": re.compile(r"(\d{4})(\d{2})(\d{2})"),
    },
"福建省科技厅": {
        "url": "https://kjt.fujian.gov.cn/xxgk/tzgg/",
        "link_pattern": re.compile(r"\d{6}/t\d{8}_"),
        "domain": "kjt.fujian.gov.cn",
        "date_in_url": re.compile(r"(\d{4})(\d{2})(\d{2})"),
    },
}

_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


class GovFetcher:
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
                logger.info("Gov %s: fetched %d posts", name, len(posts))
                results.extend(posts)
            except Exception as exc:
                logger.error("Gov %s: fetch failed: %s", name, exc)
        return results[: self._fetch_limit]

    def _scrape_article_date(
        self, url: str, extra_headers: dict | None = None
    ) -> datetime | None:
        """Scrape an article detail page for its publication date."""
        try:
            headers = {"User-Agent": _UA}
            if extra_headers:
                headers.update(extra_headers)
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

    def _scrape_article_content(
        self, url: str, cfg: dict
    ) -> str | None:
        """Scrape article detail page for full content using configured selector."""
        try:
            headers = {"User-Agent": _UA}
            headers.update(cfg.get("headers", {}))
            resp = self._client.get(url, headers=headers, timeout=10)
            resp.raise_for_status()
            resp.encoding = "utf-8"
            soup = BeautifulSoup(resp.text, "lxml")
            sel = cfg.get("detail_selector")
            if sel:
                el = soup.select_one(sel)
                if el:
                    return el.get_text(strip=True)[:2000]
            # Fallback: try common selectors
            for fallback in ["div.content", "div.maintext", "div.article-content", "div.detail"]:
                el = soup.select_one(fallback)
                if el:
                    return el.get_text(strip=True)[:2000]
        except Exception:
            pass
        return None

    def _find_article_links(self, soup, cfg) -> list:
        """Find article containers in a parsed list page."""
        container_sel = cfg.get("container", "li")
        items = (
            soup.select(container_sel) if container_sel != "li" else soup.find_all("li")
        )

        # Check if the container has our links
        article_links_found = 0
        for item in items[:5]:
            if item.find("a", href=True) and cfg["link_pattern"].search(
                item.find("a", href=True)["href"]
            ):
                article_links_found += 1

        if article_links_found < 3:
            all_as = soup.find_all("a", href=True)
            items = []
            seen_container = set()
            for a in all_as:
                if cfg["link_pattern"].search(a["href"]):
                    parent = a.find_parent(["li", "div", "p"])
                    if parent and id(parent) not in seen_container:
                        seen_container.add(id(parent))
                        items.append(parent)
        return items

    def _fetch_site(self, name: str, cfg: dict) -> list[SourcePost]:
        # Resolve page URLs to scrape
        urls: list[str] = cfg.get("urls", [])
        if not urls and "url" in cfg:
            urls = [cfg["url"]]
        if not urls:
            return []

        collected: list[SourcePost] = []
        seen_ids: set[str] = set()
        detail_sel = cfg.get("detail_selector")

        for page_url in urls:
            pages = cfg.get("pages", 1)
            for p in range(1, pages + 1):
                if pages > 1:
                    paginate = cfg.get("paginate", "")
                    if paginate and p > 1:
                        page_url_p = page_url.replace("_1.html", paginate.format(page=p))
                    else:
                        page_url_p = page_url
                else:
                    page_url_p = page_url

                req_headers = {"User-Agent": _UA}
                req_headers.update(cfg.get("headers", {}))
                try:
                    resp = self._client.get(page_url_p, headers=req_headers, timeout=10)
                    resp.raise_for_status()
                except Exception:
                    continue
                resp.encoding = "utf-8"

                soup = BeautifulSoup(resp.text, "lxml")
                base_dir = (
                    page_url_p if page_url_p.endswith("/") else page_url_p[: page_url_p.rfind("/") + 1]
                )

                items = self._find_article_links(soup, cfg)
                site_url = cfg.get("url") or (cfg.get("urls", [""])[0] if cfg.get("urls") else "")

                for li in items:
                    a = li.find("a", href=True)
                    if not a:
                        continue
                    href = a["href"]
                    text = a.get_text(strip=True)
                    if not text or len(text) < 6:
                        continue
                    if not cfg["link_pattern"].search(href):
                        continue

                    if href.startswith("http"):
                        full_url = href
                    elif href.startswith("./"):
                        full_url = urllib.parse.urljoin(base_dir, href[2:])
                    elif href.startswith("/"):
                        full_url = f"https://{cfg['domain']}{href}"
                    else:
                        full_url = urllib.parse.urljoin(base_dir, href)
                    external_id = full_url

                    if external_id in seen_ids:
                        continue
                    seen_ids.add(external_id)

                    # Skip navigation/non-news items (short titles, homepage links)
                    site_url = cfg.get("url") or (cfg.get("urls", [""])[0] if cfg.get("urls") else "")
                    if len(text) < 8 or (site_url and external_id == site_url.rstrip("/")):
                        continue

                    if self._store and self._store.exists_by_source_and_external_id(
                        _SOURCE, external_id
                    ):
                        continue

                    # Parse date: from <span> or from URL pattern
                    posted_at = datetime.now(timezone.utc)
                    span = li.find("span")
                    if span and span.get_text(strip=True):
                        try:
                            parts = re.split(r"[-/.]", span.get_text(strip=True))
                            if len(parts) == 3:
                                posted_at = datetime(
                                    int(parts[0]),
                                    int(parts[1]),
                                    int(parts[2]),
                                    tzinfo=timezone.utc,
                                )
                        except (ValueError, IndexError):
                            pass
                    elif "date_in_url" in cfg:
                        m = cfg["date_in_url"].search(href)
                        if m:
                            try:
                                posted_at = datetime(
                                    int(m.group(1)),
                                    int(m.group(2)),
                                    int(m.group(3)),
                                    tzinfo=timezone.utc,
                                )
                            except (ValueError, IndexError):
                                pass

                    # If no date found, scrape the article page for the real date
                    final_date = posted_at
                    has_date = span is not None and span.get_text(strip=True)
                    if not has_date and "date_in_url" not in cfg:
                        article_date = self._scrape_article_date(full_url, cfg.get("headers"))
                        if article_date:
                            final_date = article_date

                    # Scrape full content from detail page if configured.
                    # Use \n to separate title from body so that frontend
                    # parseContent() can correctly extract the title.
                    content = text[:2000]
                    if detail_sel and len(text) < 200:
                        detail_text = self._scrape_article_content(full_url, cfg)
                        if detail_text:
                            content = (text + "\n" + detail_text)[:2000]

                    collected.append(
                        SourcePost(
                            source=_SOURCE,
                            external_id=external_id,
                            author_handle=name,
                            title=text,
                            content=content,
                            url=full_url,
                            posted_at=final_date,
                        )
                    )

        return collected
