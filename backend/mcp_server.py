"""
MCP Server for x-ai-news-researcher (Phase 15b)

Exposes three tools to Claude Desktop / any MCP-compatible agent:
  - search_ai_news      — keyword search, all-time by default
  - get_daily_report    — retrieve a specific day's briefing report
  - get_posts_by_category — posts filtered by label

Usage (standalone):
    python mcp_server.py

Claude Desktop config (~/.claude/claude_desktop_config.json):
    {
      "mcpServers": {
        "ai-news": {
          "command": "python",
          "args": ["<absolute_path>/backend/mcp_server.py"],
          "cwd": "<absolute_path>/backend"
        }
      }
    }

Requires: GROQ_API_KEY (optional) and DATABASE_URL in .env or environment.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Resolve backend package path and set cwd so relative DB paths work correctly
_BACKEND_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_BACKEND_DIR))
os.chdir(_BACKEND_DIR)  # ensures sqlite:///./dev.db resolves to backend/dev.db

from dotenv import load_dotenv

load_dotenv(dotenv_path=_BACKEND_DIR / ".env")
load_dotenv(dotenv_path=_BACKEND_DIR.parent / ".env", override=False)

from mcp.server.fastmcp import FastMCP
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.models import Base
from app.store.news_store import NewsStore

# ---------------------------------------------------------------------------
# DB setup
# ---------------------------------------------------------------------------

_engine = create_engine(settings.database_url, connect_args={"check_same_thread": False})
Base.metadata.create_all(_engine)
_Session = sessionmaker(bind=_engine)


def _store() -> NewsStore:
    return NewsStore(session=_Session())


# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------

mcp = FastMCP("ai-news-researcher")


def _get_embedding_service():
    """Return a singleton EmbeddingService if embeddings feature is enabled."""
    if not settings.FEATURES.get("embeddings"):
        return None
    from app.embeddings.embedding_service import EmbeddingService
    svc = EmbeddingService(
        model_name=settings.embedding_model,
        use_local=not bool(settings.hf_api_token),
        hf_api_token=settings.hf_api_token,
    )
    return svc


@mcp.tool()
def search_ai_news(
    query: str,
    days: int = 0,
    limit: int = 10,
    date_from: str | None = None,
    date_to: str | None = None,
) -> str:
    """
    Search AI news posts by keyword and semantic similarity (hybrid search).

    When embeddings are enabled, results combine FTS5 keyword matching with
    vector similarity for better recall of conceptually related content.

    Args:
        query:     Search query (e.g. "agent memory management", "streaming LLM")
        days:      Only return posts from the last N days. 0 = all time (default).
        limit:     Maximum number of posts to return (default 10, max 50).
        date_from: Optional start date YYYY-MM-DD (inclusive).
        date_to:   Optional end date YYYY-MM-DD (inclusive).

    Returns:
        Markdown list of matching posts with title, source, URL, score, and summary.
    """
    from datetime import date as _date

    limit = min(limit, 50)
    since = None
    if days > 0:
        since = datetime.now(timezone.utc) - timedelta(days=days)

    df = None
    dt = None
    if date_from:
        try:
            df = _date.fromisoformat(date_from)
        except ValueError:
            return f"Invalid date_from: '{date_from}'. Use YYYY-MM-DD."
    if date_to:
        try:
            dt = _date.fromisoformat(date_to)
        except ValueError:
            return f"Invalid date_to: '{date_to}'. Use YYYY-MM-DD."

    store = _store()

    # Use hybrid search when embeddings are available
    emb_service = _get_embedding_service()
    if emb_service and not (date_from or date_to):
        try:
            from app.embeddings.vector_search import hybrid_search
            posts = hybrid_search(
                query=query,
                embedding_service=emb_service,
                store=store,
                top_k=limit,
                since=since,
                is_relevant=True,
            )
        except Exception:
            posts = []
        # Fall back to keyword search if hybrid fails
        if not posts:
            posts = store.query_posts(
                keyword=query, since=since, fts_enabled=settings.FEATURES["fts_search"],
                is_relevant=True, sort="score_desc", per_page=limit,
            )
    else:
        posts = store.query_posts(
            keyword=query, since=since, date_from=df, date_to=dt,
            fts_enabled=settings.FEATURES["fts_search"],
            is_relevant=True, sort="score_desc", per_page=limit,
        )

    if not posts:
        return f"No posts found for query: **{query}**"

    lines = [f"## Search results for: {query}\n"]
    for p in posts:
        date_str = p.posted_at.strftime("%Y-%m-%d") if p.posted_at else "unknown"
        summary = p.summary_zh or p.content[:100]
        labels = ", ".join(p.labels or [])
        title = p.title or p.content[:80]
        lines.append(
            f"### [{title}]({p.url})\n"
            f"- **來源**: {p.source}  **日期**: {date_str}  **分數**: {p.relevance_score:.1f}\n"
            f"- **標籤**: {labels}\n"
            f"- **摘要**: {summary}\n"
        )
    return "\n".join(lines)


@mcp.tool()
def get_daily_report(date: str = "today") -> str:
    """
    Retrieve a daily AI news digest report.

    Args:
        date: Date in YYYY-MM-DD format, or "today" / "yesterday" (default: "today").

    Returns:
        Full Markdown report for that day, or a message if not found.
    """
    now = datetime.now(timezone.utc)

    if date == "today":
        target = now.date()
    elif date == "yesterday":
        target = (now - timedelta(days=1)).date()
    else:
        try:
            target = datetime.strptime(date, "%Y-%m-%d").date()
        except ValueError:
            return f"Invalid date format: '{date}'. Use YYYY-MM-DD, 'today', or 'yesterday'."

    store = _store()
    reports = store.get_reports(limit=100)

    for report in reports:
        report_date = report.generated_at.date() if report.generated_at else None
        if report_date == target:
            return report.content or f"Report for {target} has no content."

    return f"No report found for {target}. Reports are generated daily at 8:00 AM."


@mcp.tool()
def get_posts_by_category(category: str, days: int = 7, limit: int = 10) -> str:
    """
    Get recent AI news posts filtered by category label.

    Args:
        category: One of "ai-agent", "ai-model", "ai-tool", or "other".
        days:     Look back N days (default 7). Use 0 for all time.
        limit:    Maximum number of posts (default 10, max 50).

    Returns:
        Markdown list of posts in the given category.
    """
    valid_categories = {"ai-agent", "ai-model", "ai-tool", "other"}
    if category not in valid_categories:
        return (
            f"Unknown category: '{category}'. "
            f"Valid options: {', '.join(sorted(valid_categories))}"
        )

    limit = min(limit, 50)
    since = None
    if days > 0:
        since = datetime.now(timezone.utc) - timedelta(days=days)

    store = _store()
    posts = store.query_posts(
        label=category,
        since=since,
        is_relevant=True,
        sort="score_desc",
        per_page=limit,
    )

    if not posts:
        period = f"last {days} days" if days > 0 else "all time"
        return f"No posts found in category **{category}** ({period})."

    category_labels = {
        "ai-agent": "🤖 AI Agent",
        "ai-model": "🧠 AI 模型",
        "ai-tool": "🛠 AI 工具",
        "other": "📰 其他",
    }
    header = category_labels.get(category, category)
    lines = [f"## {header}\n"]

    for p in posts:
        date_str = p.posted_at.strftime("%Y-%m-%d") if p.posted_at else "unknown"
        summary = p.summary_zh or p.content[:100]
        title = p.title or p.content[:80]
        lines.append(
            f"### [{title}]({p.url})\n"
            f"- **來源**: {p.source}  **日期**: {date_str}  **分數**: {p.relevance_score:.1f}\n"
            f"- **摘要**: {summary}\n"
        )
    return "\n".join(lines)


@mcp.tool()
def add_article(
    url: str,
    content: str,
    labels: list[str],
    title: str = "",
    posted_at: str = "",
    score: float = 7.0,
) -> str:
    """
    Add an external article to the knowledge base (LLM-discovered content).

    The article is stored with digest_sent=True so it never appears in the
    daily digest, but is fully searchable via search_ai_news.

    Args:
        url:       Article URL (required; used for deduplication).
        content:   Article body / abstract (required).
        labels:    Category labels list, e.g. ["ai-tool", "ai-agent"].
        title:     Optional article title (prepended to content if provided).
        posted_at: Original publish date YYYY-MM-DD (optional; defaults to today).
        score:     Relevance score 0–10 (default 7.0).

    Returns:
        Markdown confirmation message including the generated zh-TW summary.
    """
    valid_labels = {"ai-agent", "ai-model", "ai-tool", "other"}
    invalid = [lb for lb in labels if lb not in valid_labels]
    if invalid:
        return (
            f"Invalid labels: {invalid}. "
            f"Valid options: {', '.join(sorted(valid_labels))}"
        )

    store = _store()

    # Dedup by URL
    existing = store.get_post_by_url(url)
    if existing:
        return (
            f"⚠️ **Article already exists** (id={existing.id}, source={existing.source})\n\n"
            f"URL: {url}"
        )

    # Parse posted_at
    if posted_at:
        try:
            post_date = datetime.strptime(posted_at, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            return f"Invalid posted_at format: '{posted_at}'. Use YYYY-MM-DD."
    else:
        post_date = datetime.now(timezone.utc)

    # Build full content
    full_content = f"{title}\n{content}".strip() if title else content

    # Generate zh-TW summary if Groq is available
    summary_zh: str | None = None
    if settings.groq_api_key:
        try:
            from app.summarizer.groq_client import GroqClient

            class _FakePost:
                def __init__(self, src, cnt):
                    self.source = src
                    self.content = cnt

            client = GroqClient(api_key=settings.groq_api_key, model=settings.groq_model)
            summary_zh = client.summarize_post(_FakePost("llm-research", full_content[:500]))
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("add_article: Groq summary failed: %s", exc)

    store.upsert_post({
        "source": "llm-research",
        "external_id": url,
        "author_handle": "llm-agent",
        "content": full_content[:2000],
        "url": url,
        "posted_at": post_date,
        "relevance_score": score,
        "is_relevant": True,
        "labels": labels,
        "digest_sent": True,
        "summary_zh": summary_zh,
    })
    # update summary_zh separately if not stored via upsert_post
    if summary_zh:
        post = store.get_post_by_url(url)
        if post and not post.summary_zh:
            store.update_post_summary(post.id, summary_zh)
    store.commit()

    summary_display = summary_zh or "(Groq not configured — no summary generated)"
    return (
        f"✅ **Article added to knowledge base**\n\n"
        f"- **URL**: {url}\n"
        f"- **Labels**: {', '.join(labels)}\n"
        f"- **Score**: {score}\n"
        f"- **Date**: {post_date.strftime('%Y-%m-%d')}\n"
        f"- **Summary (zh-TW)**: {summary_display}\n\n"
        f"Use `search_ai_news` to retrieve this article."
    )


@mcp.tool()
def get_trending_tools(days: int = 7, limit: int = 10) -> str:
    """
    Get the most frequently mentioned AI tools in recent articles.

    Tool names are matched against the known_tools.txt keyword list.

    Args:
        days:  Look back N days (default 7). Use 0 for all time.
        limit: Maximum number of tools to return (default 10).

    Returns:
        Ranked list of tools with mention count and a sample article URL.
    """
    known_tools_path = _BACKEND_DIR / "known_tools.txt"
    if not known_tools_path.exists():
        return "known_tools.txt not found. Cannot compute trending tools."

    known_tools = []
    for line in known_tools_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            known_tools.append(line)

    if not known_tools:
        return "known_tools.txt is empty."

    since = None
    if days > 0:
        since = datetime.now(timezone.utc) - timedelta(days=days)

    store = _store()
    posts = store.query_posts(
        since=since,
        is_relevant=True,
        sort="date_desc",
        per_page=500,
    )

    if not posts:
        period = f"last {days} days" if days > 0 else "all time"
        return f"No posts found ({period})."

    # Count tool mentions
    from collections import defaultdict
    counts: dict[str, list] = defaultdict(list)  # tool -> [url, ...]

    for p in posts:
        text = ((p.content or "") + " " + (p.summary_zh or "")).lower()
        for tool in known_tools:
            if tool.lower() in text:
                counts[tool].append(p.url)

    if not counts:
        return "No known tools mentioned in recent articles."

    sorted_tools = sorted(counts.items(), key=lambda x: len(x[1]), reverse=True)[:limit]
    period_str = f"last {days} days" if days > 0 else "all time"
    lines = [f"## 🔧 Trending AI Tools ({period_str})\n"]
    for tool, urls in sorted_tools:
        sample_url = urls[0]
        lines.append(f"- **{tool}** — {len(urls)} mention(s)  [sample]({sample_url})")

    return "\n".join(lines)


@mcp.tool()
def get_weekly_summary(week_offset: int = 0) -> str:
    """
    Get the weekly AI trend briefing for a given week.

    Args:
        week_offset: 0 = current week (default), -1 = last week, etc.

    Returns:
        Full Markdown content of the weekly briefing, or a message if not found.
    """
    from datetime import date, timedelta

    today = date.today()
    # Calculate target ISO week
    target_date = today + timedelta(weeks=week_offset)
    iso_year, iso_week, _ = target_date.isocalendar()
    filename = f"{iso_year}-W{iso_week:02d}.md"

    # Try common locations
    candidates = [
        _BACKEND_DIR / "briefings" / "weekly" / filename,
        _BACKEND_DIR.parent / "briefings" / "weekly" / filename,
    ]
    if settings.briefings_output_dir_resolved:
        candidates.insert(0, Path(settings.briefings_output_dir_resolved) / "weekly" / filename)

    for path in candidates:
        if path.exists():
            content = path.read_text(encoding="utf-8")
            return content or f"Weekly briefing for {iso_year}-W{iso_week:02d} is empty."

    return (
        f"週報尚未生成（{iso_year} 第 {iso_week} 週）。"
        f"請執行 generate_weekly_briefing.py 或等待本週一排程執行。"
    )


@mcp.tool()
def list_techniques() -> str:
    """
    List all available AI technique groups defined in the keyword configuration.

    Returns:
        Markdown list of technique group names usable with get_posts_by_technique.
    """
    import yaml

    keywords_path = _BACKEND_DIR / "keywords.yaml"
    if not keywords_path.exists():
        return "keywords.yaml not found."

    with open(keywords_path, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    groups = set()
    for tier in ("high_weight", "standard_weight"):
        for group in config.get(tier, {}):
            groups.add(group)

    if not groups:
        return "No technique groups found in keywords.yaml."

    lines = ["## Available Technique Groups\n"]
    for g in sorted(groups):
        lines.append(f"- `{g}`")
    lines.append("\nUse `get_posts_by_technique(technique=<group_name>)` to query posts.")
    return "\n".join(lines)


@mcp.tool()
def get_posts_by_technique(technique: str, days: int = 7, limit: int = 10) -> str:
    """
    Get recent posts matching a specific technique group label.

    When embeddings are enabled, this performs a semantic search using the
    technique name as query, capturing posts that match conceptually even
    without exact keyword hits.

    Args:
        technique: Technique group name (use list_techniques() to see available groups).
                   Also accepts label strings like "ai-technique", "ai-agent".
        days:      Look back N days (default 7). Use 0 for all time.
        limit:     Maximum posts to return (default 10, max 50).

    Returns:
        Markdown list of matching posts.
    """
    limit = min(limit, 50)
    since = None
    if days > 0:
        since = datetime.now(timezone.utc) - timedelta(days=days)

    store = _store()

    # Try semantic search first when embeddings available
    posts = []
    emb_service = _get_embedding_service()
    if emb_service:
        try:
            from app.embeddings.vector_search import hybrid_search
            posts = hybrid_search(
                query=technique.replace("_", " "),
                embedding_service=emb_service,
                store=store,
                top_k=limit,
                since=since,
                is_relevant=True,
            )
        except Exception:
            posts = []

    # Fallback: label-based filter
    if not posts:
        # Map group name to label (e.g. "ai_collaboration_techniques" → "ai-technique")
        label = technique.replace("_", "-")
        posts = store.query_posts(
            label=label,
            since=since,
            is_relevant=True,
            sort="score_desc",
            per_page=limit,
        )

    if not posts:
        period = f"last {days} days" if days > 0 else "all time"
        return f"No posts found for technique **{technique}** ({period})."

    lines = [f"## Posts: {technique}\n"]
    for p in posts:
        date_str = p.posted_at.strftime("%Y-%m-%d") if p.posted_at else "unknown"
        summary = p.summary_zh or p.content[:120]
        title = p.title or p.content[:80]
        lines.append(
            f"### [{title}]({p.url})\n"
            f"- **來源**: {p.source}  **日期**: {date_str}  **分數**: {p.relevance_score:.1f}\n"
            f"- **摘要**: {summary}\n"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run()
