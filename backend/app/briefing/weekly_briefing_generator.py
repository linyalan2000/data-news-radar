"""WeeklyBriefingGenerator: weekly AI trend briefing via Groq.

Reuses the existing BriefingGenerator infrastructure but queries the last
7 days of relevant posts and uses a trend-comparison system prompt.
Outputs to briefings/weekly/YYYY-WNN.md (ISO week number).
Controlled by FEATURES["weekly_briefing"] flag.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_WEEKLY_PROMPT = """\
你是一位資深 AI 工程師的技術助理。
以下是本週（過去 7 天）的 AI 技術新聞彙整，請生成一份開發者週報，包含：
1. 本週 3 大技術趨勢方向（各 2–3 句說明，與上週相比的變化）
2. 出現或消退的新話題
3. 最值得關注的工具發布或論文
4. 下週開發者行動建議（1–2 項具體可操作的建議）

格式：繁體中文 Markdown，不超過 800 字。

本週新聞彙整：
{report_content}"""


class WeeklyBriefingGenerator:
    """Generate a weekly Markdown briefing from the last 7 days of relevant posts."""

    def __init__(
        self,
        groq_api_key: str,
        groq_model: str = "llama-3.3-70b-versatile",
        output_dir: str | Path = "briefings/weekly",
    ) -> None:
        self._groq_api_key = groq_api_key
        self._groq_model = groq_model
        self._output_dir = Path(output_dir)

    def generate(self, posts, reference_date: datetime | None = None) -> Path | None:
        """
        Generate weekly briefing from *posts* (7-day window).
        Saves to <output_dir>/YYYY-WNN.md. Returns saved path, or None on failure.
        """
        if not self._groq_api_key:
            logger.debug("WeeklyBriefingGenerator: no GROQ_API_KEY, skipping.")
            return None

        if len(posts) < 3:
            logger.warning(
                "WeeklyBriefingGenerator: fewer than 3 posts (%d), skipping.", len(posts)
            )
            return None

        ref = reference_date or datetime.now(timezone.utc)
        iso_year, iso_week, _ = ref.isocalendar()
        filename = f"{iso_year}-W{iso_week:02d}.md"

        self._output_dir.mkdir(parents=True, exist_ok=True)
        out_path = self._output_dir / filename
        if out_path.exists():
            logger.info("Weekly briefing already exists, skipping → %s", out_path)
            return out_path

        report_content = self._assemble_content(posts)
        try:
            briefing = self._call_groq(report_content)
        except Exception as exc:
            logger.error("WeeklyBriefingGenerator: Groq call failed: %s", exc)
            return None

        header = f"# AI 技術週報 — {iso_year} 第 {iso_week} 週\n\n"
        out_path.write_text(header + briefing, encoding="utf-8")
        logger.info("Weekly briefing saved → %s", out_path)
        return out_path

    def _assemble_content(self, posts) -> str:
        lines = []
        for p in posts[:50]:  # cap to control prompt size
            date_str = p.posted_at.strftime("%Y-%m-%d") if p.posted_at else "unknown"
            summary = p.summary_zh or p.content[:100]
            title = p.title or p.content[:80]
        lines.append(f"- [{title}]({p.url}) [{p.source}] {date_str}\n  {summary}")
        return "\n".join(lines)

    def _call_groq(self, report_content: str) -> str:
        from groq import Groq

        client = Groq(api_key=self._groq_api_key)
        prompt = _WEEKLY_PROMPT.format(report_content=report_content)
        resp = client.chat.completions.create(
            model=self._groq_model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1600,
        )
        return resp.choices[0].message.content.strip()
