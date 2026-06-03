"""Daily report endpoint: pre-generated and cached, served instantly."""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.auth import require_api_key
from app.api.deps import get_db, get_news_store
from app.schemas import Post as PostSchema

logger = logging.getLogger(__name__)

_MAX_SUMMARY_ITEMS = 5

router = APIRouter(dependencies=[Depends(require_api_key)])

_DAILY_DIR = Path(__file__).resolve().parents[4] / "briefings" / "daily"


class DailyReportSection(BaseModel):
    title: str
    posts: list[PostSchema]


class DailyReportResponse(BaseModel):
    date: str
    sections: list[DailyReportSection]
    summary: str
    generated: bool


@router.get("/api/daily-report", response_model=DailyReportResponse)
def get_daily_report(date: Optional[str] = None):
    """Return daily report for given date (default: today)."""
    target = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    cached = _load_cached(target)
    if cached:
        return DailyReportResponse(date=target, **cached, generated=True)
    return DailyReportResponse(
        date=target,
        sections=[],
        summary="（该日期暂无报告）",
        generated=False,
    )


@router.get("/api/daily-report/dates")
def list_daily_report_dates():
    """Return sorted list of dates that have cached reports."""
    if not _DAILY_DIR.exists():
        return {"dates": []}
    dates = sorted(
        (f.stem for f in _DAILY_DIR.iterdir() if f.suffix == ".json"),
        reverse=True,
    )
    return {"dates": dates}


def _load_cached(date_str: str) -> Optional[dict]:
    """Load cached report for date. Returns None if not found or stale."""
    path = _DAILY_DIR / f"{date_str}.json"
    if not path.exists():
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def generate_and_cache(store, _now=None) -> bool:
    """Generate daily report, cache to file. Returns True on success."""
    from datetime import datetime, timedelta, timezone
    from app.summarizer.minimax_client import MinimaxClient
    from openai import APITimeoutError
    from app.config import settings

    tz = timezone(timedelta(hours=8))
    now_cst = _now or datetime.now(tz)
    today_8am = now_cst.replace(hour=8, minute=0, second=0, microsecond=0)
    if now_cst.hour < 8:
        today_8am -= timedelta(days=1)
    yesterday_8am = today_8am - timedelta(hours=24)
    today = today_8am.strftime("%Y-%m-%d")
    since = yesterday_8am.astimezone(timezone.utc).replace(tzinfo=None)
    to_date = today_8am.astimezone(timezone.utc).replace(tzinfo=None)
    posts = store.query_posts(since=since, to_date=to_date, per_page=200, is_relevant=True)

    buckets: dict[str, list] = {"national": [], "industry": [], "fujian": []}
    for p in posts:
        s = getattr(p, "summary_zh", None) or ""
        if s and re.search(r'不相关|未涉及|无法生成|本文不涉及', s):
            continue
        buckets[_classify(p)].append(p)

    sections = [
        {"title": "国家部署", "posts": _posts_to_dicts(buckets["national"][:20])},
        {"title": "行业动态", "posts": _posts_to_dicts(buckets["industry"][:20])},
        {"title": "福建本地", "posts": _posts_to_dicts(buckets["fujian"][:20])},
    ]

    # Generate LLM summary with short timeout
    summary = ""
    if settings.minimax_api_key:
        try:
            prompt = _build_summary_prompt({k: v[:20] for k, v in buckets.items() if v})
            client = MinimaxClient(settings.minimax_api_key, settings.minimax_model)
            resp = client._client.chat.completions.create(
                model=client._model,
                messages=[
                    {"role": "system", "content": "只输出标题和正文。每条新闻先单独输出一行标题，再输出一段正文。不要输出编号、栏目名、格式说明、分析过程或其他额外内容。"},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=1200,
                timeout=60,
            )
            text = resp.choices[0].message.content.strip()
            text = re.sub(r'</?think>', '', text).strip()
            # 找到第一行实际新闻内容，跳过格式说明和分析语言
            lines = text.split("\n")
            start = len(lines)
            skip_keywords = ["每条新闻", "再写", "只输出", "不要分析", "让我逐", "让我整理", "用户要求", "用户提供"]
            for i, line in enumerate(lines):
                stripped = line.strip()
                if not stripped:
                    continue
                # 跳过格式样板和分析语句
                if any(kw in stripped for kw in skip_keywords):
                    continue
                if stripped.startswith("**") and len(stripped) < 10:
                    continue
                # 第一个真正的内容行
                start = i
                break
            text = "\n".join(lines[start:]).strip()
            summary = _clean_daily_summary(text, max_items=_MAX_SUMMARY_ITEMS)

            if not _summary_ok(summary):
                logger.warning("Daily report summary validation failed, using fallback")
                summary = ""
        except Exception as exc:
            logger.warning("Daily report summary generation failed: %s", exc)

    _DAILY_DIR.mkdir(parents=True, exist_ok=True)
    data = {"sections": sections, "summary": summary}
    path = _DAILY_DIR / f"{today}.json"
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, default=str)
    logger.info("Daily report cached to %s (%d sections)", path, len(sections))
    return True


def _posts_to_dicts(posts: list) -> list[dict]:
    """Convert Post ORM objects to dicts for JSON serialization."""
    result = []
    for p in posts:
        d = {
            "id": p.id, "source": p.source, "external_id": p.external_id,
            "author_handle": p.author_handle, "title": p.title,
            "content": p.content, "url": p.url,
            "posted_at": str(p.posted_at), "fetched_at": str(p.fetched_at),
            "relevance_score": p.relevance_score, "points": p.points,
            "summary_zh": p.summary_zh, "recommendation_reason": p.recommendation_reason,
            "is_relevant": p.is_relevant, "labels": p.labels,
            "digest_sent": p.digest_sent, "discussion_url": None,
        }
        if p.source == "hackernews" and not d["discussion_url"]:
            d["discussion_url"] = f"https://news.ycombinator.com/item?id={p.external_id}"
        result.append(d)
    return result


def _classify(post) -> str:
    labels = [l for l in getattr(post, "labels", []) or [] if l]
    source = getattr(post, "source", "") or ""
    author = getattr(post, "author_handle", "") or ""
    content = (getattr(post, "content", None) or "") + (getattr(post, "title", None) or "")
    _FUJIAN_KW = ("福建", "福州", "厦门", "泉州")
    _NATIONAL_KW = ("国家数据局", "国家发改委", "国务院", "工信部", "发改委", "财政部")
    if "福建本地" in labels or any(kw in author for kw in _FUJIAN_KW) or "福建" in content:
        return "fujian"
    if source == "gov" and any(kw in content for kw in _NATIONAL_KW):
        return "national"
    return "industry"


def _summary_ok(text: str) -> bool:
    if not text or len(text) < 100:
        return False
    # Must contain enough Chinese content
    cn = len(re.findall(r'[\u4e00-\u9fff]', text))
    if cn / max(len(text), 1) < 0.3:
        return False
    return True


def _clean_daily_summary(text: str, max_items: int = 5) -> str:
    """Normalize LLM output to clean 'title + body' blocks.

    Keeps only high-signal lines and enforces a compact number of items.
    """
    if not text:
        return ""

    noise_keywords = [
        "输出格式", "只输出", "不要输出", "分析过程", "筛选理由",
        "国家部署", "行业动态", "福建本地", "候选", "总结如下", "说明：",
    ]

    raw_lines = [ln.strip() for ln in text.splitlines()]
    clean_lines = []
    for line in raw_lines:
        if not line:
            continue
        if any(kw in line for kw in noise_keywords):
            continue
        # Remove common list markers but keep the line content.
        line = re.sub(r"^\s*(\d+[.)、]|[-*•])\s*", "", line).strip()
        # Remove markdown heading markers that occasionally leak into output.
        line = re.sub(r"^#{1,6}\s*", "", line).strip()
        if not line:
            continue
        clean_lines.append(line)

    if len(clean_lines) < 2:
        return ""

    # Pair every title with the following body line.
    pairs = []
    i = 0
    while i + 1 < len(clean_lines) and len(pairs) < max_items:
        title = clean_lines[i]
        body = clean_lines[i + 1]
        pairs.append(f"{title}\n{body}")
        i += 2

    return "\n\n".join(pairs).strip()


def _build_summary_prompt(sections: dict) -> str:
    lines = [
        "今天数据要素与AI资讯候选如下。请从候选中挑选最重要的新闻生成日报摘要，不要逐条复述全部候选。",
        "挑选标准：优先选择政策权威性高、行业影响大、技术或商业模式有新增量、与福建本地相关性强的新闻。",
        "输出数量：总共输出3-5条；如果候选不足，可以少于3条。",
    ]
    for section_name, posts in sections.items():
        label = {"national": "【国家部署】", "industry": "【行业动态】", "fujian": "【福建本地】"}.get(section_name, section_name)
        lines.append(f"\n{label}")
        for p in posts:
            title = getattr(p, "title", None) or ""
            summary = getattr(p, "summary_zh", None) or ""
            snippet = summary[:100] if summary and summary != "不相关" else ""
            lines.append(f"- {title[:60]}")
            if snippet:
                lines.append(f"  {snippet}")
    lines.append("\n输出格式（严格）：\n新闻标题\n这段新闻的主要内容总结。\n\n每条仅两行（标题+正文），条目之间空一行。只输出中文标题和正文，不要输出栏目名、编号、筛选理由或分析过程。")
    return "\n".join(lines)
