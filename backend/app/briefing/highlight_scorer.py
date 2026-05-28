"""Algorithmic Top 3 highlight scorer for daily briefing (Phase 18.2).

Computes a composite highlight_score for each post using:
  highlight_score = relevance_score * w_relevance
                  + source_weight   * w_source
                  + recency_decay   * w_recency

Default weights are configurable via config.py highlight_weights.
Controlled by FEATURES["highlight_scorer"] flag.
"""
from __future__ import annotations

from datetime import datetime, timezone

# Source weights (raw, before multiplying by w_source)
# arxiv excluded: daily briefing only uses non-arxiv posts (arxiv is weekly-only)
_SOURCE_WEIGHTS: dict[str, float] = {
    "github": 3.0,
    "hackernews": 2.0,
    "reddit": 1.0,
}

DEFAULT_WEIGHTS = {
    "relevance": 0.5,
    "source": 0.3,
    "recency": 0.2,
}


def compute_highlight_score(
    post,
    reference_time: datetime | None = None,
    weights: dict | None = None,
) -> float:
    """Return composite highlight score for *post*."""
    w = weights or DEFAULT_WEIGHTS
    now = reference_time or datetime.now(timezone.utc)

    relevance = float(post.relevance_score or 0.0)
    source_raw = _SOURCE_WEIGHTS.get(post.source or "", 1.0)

    age_hours = 0.0
    if post.posted_at:
        posted = post.posted_at
        if posted.tzinfo is None:
            posted = posted.replace(tzinfo=timezone.utc)
        age_hours = max((now - posted).total_seconds() / 3600, 0.0)

    if age_hours < 24:
        recency = 1.0
    elif age_hours < 48:
        recency = 0.5
    else:
        recency = 0.0

    return (
        relevance * w.get("relevance", 0.5)
        + source_raw * w.get("source", 0.3)
        + recency * w.get("recency", 0.2)
    )


def get_top_highlights(posts, n: int = 3, **kwargs) -> list:
    """Return top *n* posts sorted by highlight_score descending."""
    scored = [(compute_highlight_score(p, **kwargs), p) for p in posts]
    scored.sort(key=lambda x: x[0], reverse=True)
    return [p for _, p in scored[:n]]


def format_highlight_section(posts, reference_time: datetime | None = None, weights: dict | None = None) -> str:
    """Return Markdown string for the ⭐ 今日精選 section."""
    lines = ["## ⭐ 今日精選\n"]
    for p in posts:
        score = compute_highlight_score(p, reference_time=reference_time, weights=weights)
        # GitHub: use owner/repo name; others: use content[:80]
        url = getattr(p, "url", "") or ""
        source = getattr(p, "source", "")
        if source == "github" and url:
            parts = url.rstrip("/").split("/")
            title = f"{parts[-2]}/{parts[-1]}" if len(parts) >= 2 else (p.title or p.content[:80] or "(no title)")
        else:
            title = p.title or p.content[:80] or "(no title)"
        lines.append(
            f"- **[{title}]({p.url})**"
            f" `{p.source}` 綜合分數: {score:.2f}\n"
        )
    lines.append("")
    return "\n".join(lines)
