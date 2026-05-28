"""SummaryGenerator: summarize a batch of posts and assemble a zh-TW Markdown report."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.summarizer.gemini_client import GeminiClient
    from app.store.news_store import NewsStore

logger = logging.getLogger(__name__)

_LABEL_SECTION: dict[str, str] = {
    "ai-agent": "🤖 AI Agent",
    "ai-model": "🧠 AI 模型",
    "ai-tool":  "🛠 AI 工具",
    "other":    "📰 其他",
}
_RATE_LIMIT_SLEEP = 4   # seconds between Gemini calls (free tier: 15 RPM)
_CIRCUIT_BREAKER_THRESHOLD = 3


class SummaryGenerator:
    def __init__(self, gemini_client: "GeminiClient", store: "NewsStore") -> None:
        self._client = gemini_client
        self._store = store

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def summarize_batch(self, posts: list) -> None:
        """Generate and cache summary_zh for posts that don't have one yet.

        Circuit breaker: stops after 3 consecutive failures to avoid
        burning rate-limit retries on a broken API session.
        """
        consecutive_failures = 0
        for post in posts:
            if getattr(post, "summary_zh", None):
                consecutive_failures = 0
                continue
            content = getattr(post, "content", "") or ""
            if len(content) < 200:
                continue
            if consecutive_failures >= _CIRCUIT_BREAKER_THRESHOLD:
                logger.error(
                    "Gemini circuit breaker open after %d failures — skipping remaining posts",
                    _CIRCUIT_BREAKER_THRESHOLD,
                )
                break
            try:
                summary = self._client.summarize_post(post)
                self._store.update_post_summary(post.id, summary)
                consecutive_failures = 0
            except Exception as exc:
                logger.warning("Failed to summarize post %s: %s", post.id, exc)
                consecutive_failures += 1
                # If the store flush failed, the session may be in PendingRollback state.
                # Roll back to let the session continue processing remaining posts.
                try:
                    self._store.rollback()
                except Exception:
                    pass
            time.sleep(_RATE_LIMIT_SLEEP)

    def assemble_report(self, posts: list, date: str | None = None) -> str:
        """Build a Markdown report grouped by label from the given posts."""
        if not posts:
            return ""
        if date is None:
            date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        grouped: dict[str, list] = {k: [] for k in _LABEL_SECTION}
        for post in posts:
            labels = getattr(post, "labels", None) or []
            key = labels[0] if labels and labels[0] in _LABEL_SECTION else "other"
            grouped[key].append(post)

        lines: list[str] = [
            f"# AI 新聞每日彙整 — {date}",
            f"**共 {len(posts)} 篇相關文章**",
            "",
        ]

        for label_key, section_title in _LABEL_SECTION.items():
            section_posts = grouped.get(label_key, [])
            if not section_posts:
                continue
            lines.append(f"## {section_title}")
            lines.append("")
            for post in section_posts:
                lines.extend(_format_post_entry(post))
            lines.append("")

        return "\n".join(lines).rstrip() + "\n"


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

_DISCUSSION_SIGNALS = (
    "i built", "i've been", "i am", "i'm building", "i made", "i created",
    "we built", "we've been", "help with", "struggling with", "question:",
    "how do i", "how to", "what's the best", "advice on", "sharing my",
    "my experience", "lessons learned", "after", "weeks of", "months of",
    "has anyone", "does anyone",
)

_ANALYSIS_SIGNALS = (
    "benchmark", "comparison", "vs ", " vs.", "evaluation", "test result",
    "performance", "accuracy", "dataset", "measured", "compared",
)


def _post_type_label(post) -> str:
    """Return a short type label for the post to aid briefing LLM selection."""
    source = getattr(post, "source", "") or ""
    content_lower = (getattr(post, "content", "") or "").lower()

    if source == "reddit":
        if any(sig in content_lower for sig in _DISCUSSION_SIGNALS):
            return "[討論]"
        if any(sig in content_lower for sig in _ANALYSIS_SIGNALS):
            return "[實測]"
        return "[社群]"

    if source == "github":
        if any(sig in content_lower for sig in _ANALYSIS_SIGNALS):
            return "[實測]"
        return "[工具]"

    if source == "hackernews":
        if any(sig in content_lower for sig in _ANALYSIS_SIGNALS):
            return "[實測]"
        if any(sig in content_lower for sig in _DISCUSSION_SIGNALS):
            return "[討論]"
        return "[新聞]"

    return "[其他]"


def _repo_name_from_url(url: str) -> str:
    """Extract 'owner/repo' from a GitHub URL, fallback to last path segment."""
    parts = url.rstrip("/").split("/")
    if len(parts) >= 2:
        return f"{parts[-2]}/{parts[-1]}"
    return parts[-1] if parts else url


def _format_post_entry(post) -> list[str]:
    source = getattr(post, "source", "")
    score = getattr(post, "relevance_score", None)
    points = getattr(post, "points", None)
    url = getattr(post, "url", "") or ""
    discussion_url = getattr(post, "discussion_url", None)
    summary = getattr(post, "summary_zh", None) or "（摘要待生成）"
    type_label = _post_type_label(post)

    # GitHub: use "owner/repo" as title; others: use post.title or first 80 chars of content
    if source == "github" and url:
        title = _repo_name_from_url(url)
    else:
        title = getattr(post, "title", None) or (getattr(post, "content", "") or "")[:80]

    source_badge = {"hackernews": "HN", "reddit": "Reddit", "github": "GitHub"}.get(source, source)
    badge_str = f"`{source_badge}`"
    if points:
        badge_str += f" ▲ {points}"
    try:
        if score is not None:
            badge_str += f" score={float(score):.1f}"
    except (TypeError, ValueError):
        pass

    links = f"🔗 [原文]({url})"
    if source == "hackernews" and discussion_url:
        links += f" · [HN 討論]({discussion_url})"

    return [
        f"- **{type_label} {title}** ({badge_str})",
        f"  {summary}",
        f"  {links}",
        "",
    ]
