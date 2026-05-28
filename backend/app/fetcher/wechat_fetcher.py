"""WeChat Official Account article fetcher.

Uses mp.weixin.qq.com internal APIs (searchbiz + appmsgpublish)
to fetch articles from any WeChat public account, given valid
authentication from wechat_client.py.

Adapted from wechat-radar (https://github.com/cathyzhang0905/wechat-radar).
"""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import httpx
from bs4 import BeautifulSoup

from app.fetcher.source_post import SourcePost
from app.fetcher.wechat_client import TokenExpiredError, load_token

logger = logging.getLogger(__name__)

_RE_WECHAT_FOOTER = re.compile(r"\s*欢迎关注[^\n]*")

_BASE = "https://mp.weixin.qq.com"
_API_INTERVAL = 1.5
_last_request_time = 0.0

_FAKEID_CACHE_FILE = Path(__file__).parent / "fakeid_cache.json"

_MAX_CONTENT_LENGTH = 5000
_REQUEST_TIMEOUT = 15

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


class WeChatFetcher:
    """Fetch articles from configured WeChat public accounts.

    Requires a valid token obtained via wechat_client.login().
    """

    def __init__(
        self,
        accounts: list[str],
        fetch_limit: int = 30,
        news_store=None,
    ) -> None:
        self._accounts = accounts
        self._fetch_limit = fetch_limit
        self._store = news_store

    def fetch(self) -> list[SourcePost]:
        """Fetch recent articles from all configured accounts.

        On TokenExpiredError, starts login() in a background thread (non-blocking)
        and skips this fetch cycle. Returns up to *fetch_limit* SourcePost objects.
        """
        if not self._accounts:
            return []

        try:
            return self._fetch_all()
        except TokenExpiredError:
            logger.info("WeChat token expired — skipping fetch, user can re-login manually")
            return []

    def _fetch_all(self) -> list[SourcePost]:
        token_data = load_token()
        if not token_data:
            logger.warning("No WeChat token available")
            return []

        token = token_data.get("token", "")
        cookies = token_data.get("cookies", "")

        results: list[SourcePost] = []
        per_account = max(5, self._fetch_limit // len(self._accounts))

        for account_name in self._accounts:
            posts = self._fetch_account(
                account_name, token, cookies, per_account
            )
            logger.info(
                "WeChat %s: fetched %d posts", account_name, len(posts)
            )
            results.extend(posts)
            time.sleep(1)

        return results[: self._fetch_limit]

    @staticmethod
    def _fetch_article_body(url: str) -> str:
        """Fetch and extract article body from a WeChat article page."""
        if not url:
            return ""
        try:
            resp = httpx.get(
                url,
                headers={"User-Agent": _UA},
                timeout=_REQUEST_TIMEOUT,
                follow_redirects=True,
            )
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            content_div = soup.find("div", class_=re.compile(r"rich_media_content"))
            if not content_div:
                return ""
            text = content_div.get_text(separator="\n", strip=True)
            text = re.sub(r'\s+', ' ', text).strip()
            return text[:_MAX_CONTENT_LENGTH]
        except Exception as exc:
            logger.debug("Failed to fetch article body from %s: %s", url, exc)
            return ""

    def _fetch_account(
        self,
        account_name: str,
        token: str,
        cookies: str,
        limit: int,
    ) -> list[SourcePost]:
        """Fetch articles for a single account."""
        fakeid = self._get_fakeid(account_name, token, cookies)
        if not fakeid:
            return []

        articles = self._get_recent_articles(
            fakeid, account_name, token, cookies, hours=24 * 7
        )
        posts: list[SourcePost] = []
        for art in articles[:limit]:
            create_time = art.get("create_time")
            if create_time is None:
                continue
            try:
                posted_at = datetime.fromtimestamp(
                    int(create_time), tz=timezone.utc
                )
            except (ValueError, OSError):
                continue

            title = (art.get("title", "") or "")
            digest = (art.get("digest", "") or "")
            combined = f"{title}\n{digest}" if digest else title
            combined = _RE_WECHAT_FOOTER.sub("", combined).strip()
            url = art.get("link", "")
            body = self._fetch_article_body(url)
            if body:
                combined = f"{title}\n\n{body}"
            posts.append(
                SourcePost(
                    source="wechat",
                    external_id=art.get("link", ""),
                    author_handle=account_name,
                    title=title,
                    content=combined[:_MAX_CONTENT_LENGTH],
                    url=url,
                    posted_at=posted_at,
                )
            )
        return posts

    def _get_fakeid(
        self, account_name: str, token: str, cookies: str
    ) -> Optional[str]:
        """Search for account by name and return its fakeid.

        Uses a local JSON cache to avoid hitting the API on every cycle.
        """
        cache = _load_fakeid_cache()
        if account_name in cache:
            logger.info(
                "Fakeid cache hit for '%s': %s", account_name, cache[account_name]
            )
            return cache[account_name]

        data = _api_get(
            f"{_BASE}/cgi-bin/searchbiz",
            params={
                "action": "search_biz",
                "query": account_name,
                "count": 5,
                "begin": 0,
                "token": token,
                "lang": "zh_CN",
                "f": "json",
                "ajax": 1,
            },
            cookies=cookies,
        )
        if not data:
            return None

        items = data.get("list", [])
        if not items:
            logger.warning("No account found for: %s", account_name)
            return None

        fakeid = None
        for item in items:
            if item.get("nickname") == account_name:
                fakeid = item.get("fakeid")
                break
        if not fakeid:
            fakeid = items[0].get("fakeid")
            logger.info(
                "No exact match for '%s', using first result: fakeid=%s",
                account_name,
                fakeid,
            )
        else:
            logger.info(
                "Found exact match for '%s': fakeid=%s", account_name, fakeid
            )

        if fakeid:
            cache[account_name] = fakeid
            _save_fakeid_cache(cache)
        return fakeid

    def _get_recent_articles(
        self,
        fakeid: str,
        account_name: str,
        token: str,
        cookies: str,
        hours: int = 24,
    ) -> list[dict]:
        """Fetch articles published in the last *hours*."""
        data = _api_get(
            f"{_BASE}/cgi-bin/appmsgpublish",
            params={
                "sub": "list",
                "sub_action": "list_ex",
                "fakeid": fakeid,
                "begin": 0,
                "count": 20,
                "token": token,
                "lang": "zh_CN",
                "f": "json",
                "ajax": 1,
            },
            cookies=cookies,
        )
        if not data:
            return []

        articles = _parse_publish_list(data)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        recent = []
        for art in articles:
            create_time = art.get("create_time")
            if create_time is None:
                continue
            try:
                pub_dt = datetime.fromtimestamp(
                    int(create_time), tz=timezone.utc
                )
            except (ValueError, OSError):
                continue
            if pub_dt >= cutoff:
                recent.append(art)

        logger.info(
            "'%s': %d/%d articles in last %dh",
            account_name,
            len(recent),
            len(articles),
            hours,
        )
        return recent


def _rate_limit() -> None:
    """Ensure minimum interval between API calls."""
    global _last_request_time
    elapsed = time.time() - _last_request_time
    if elapsed < _API_INTERVAL:
        time.sleep(_API_INTERVAL - elapsed)
    _last_request_time = time.time()


def _api_get(
    url: str,
    params: dict,
    cookies: str,
    retries: int = 2,
) -> Optional[dict]:
    """GET request to WeChat API with error handling."""
    headers = {
        "Cookie": cookies,
        "User-Agent": _UA,
        "Referer": "https://mp.weixin.qq.com/",
        "X-Requested-With": "XMLHttpRequest",
    }
    for attempt in range(retries + 1):
        _rate_limit()
        try:
            resp = httpx.get(url, params=params, headers=headers, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            base_resp = data.get("base_resp", {})
            ret = base_resp.get("ret", 0)
            if ret != 0:
                logger.error(
                    "WeChat API error: ret=%s, err_msg=%s, url=%s",
                    ret,
                    base_resp.get("err_msg", ""),
                    url,
                )
                if ret in (200003, 200013, 200014, -1):
                    raise TokenExpiredError(
                        f"WeChat token expired (ret={ret})"
                    )
                return None
            return data
        except TokenExpiredError:
            raise
        except httpx.HTTPStatusError as e:
            if attempt < retries:
                logger.warning("HTTP error, retrying: %s", e)
                time.sleep(2)
            else:
                logger.error("HTTP error after retries: %s", e)
                return None
        except httpx.RequestError as e:
            if attempt < retries:
                logger.warning("Request failed, retrying: %s", e)
                time.sleep(2)
            else:
                logger.error("Request failed after retries: %s", e)
                return None
    return None


def _parse_publish_list(data: dict) -> list[dict]:
    """Parse the nested publish_list from appmsgpublish response.

    Structure: data.publish_page (JSON string) → publish_list[]
      → publish_info (JSON string) → appmsgex[]
    """
    articles: list[dict] = []
    try:
        publish_page_raw = data.get("publish_page", "")
        if not publish_page_raw:
            return []
        publish_page = json.loads(publish_page_raw)
        for item in publish_page.get("publish_list", []):
            publish_info_raw = item.get("publish_info", "")
            if not publish_info_raw:
                continue
            publish_info = json.loads(publish_info_raw)
            for art in publish_info.get("appmsgex", []):
                articles.append(art)
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        logger.error("Failed to parse publish_list: %s", e)
    return articles


def _load_fakeid_cache() -> dict:
    """Read fakeid cache from disk."""
    if _FAKEID_CACHE_FILE.exists():
        try:
            return json.loads(
                _FAKEID_CACHE_FILE.read_text(encoding="utf-8")
            )
        except Exception:
            return {}
    return {}


def _save_fakeid_cache(cache: dict) -> None:
    """Write fakeid cache to disk."""
    _FAKEID_CACHE_FILE.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8"
    )
