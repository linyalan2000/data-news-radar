"""DigestNotifier: generate and deliver periodic AI news digests."""
from __future__ import annotations

import logging
import smtplib
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

import httpx

from app.models import Post

logger = logging.getLogger(__name__)


class DigestNotifier:
    def __init__(
        self,
        news_store,
        smtp_config: Optional[dict],
        webhook_url: Optional[str],
        top_n: int = 20,
        gemini_api_key: str = "",
        gemini_model: str = "gemini-2.0-flash",
        groq_api_key: str = "",
        groq_model: str = "llama-3.3-70b-versatile",
        novita_api_key: str = "",
        novita_model: str = "ring-2.6-1t",
        minimax_api_key: str = "",
        minimax_model: str = "MiniMax-M2.7",
        lookback_hours: int = 48,
        briefings_output_dir: Optional[str] = None,
        user_context: str = "",
        highlight_scorer_enabled: bool = False,
        highlight_weights: Optional[dict] = None,
        embedding_service=None,
    ) -> None:
        self._store = news_store
        self._smtp = smtp_config
        self._webhook_url = webhook_url
        self._top_n = top_n
        self._gemini_api_key = gemini_api_key
        self._gemini_model = gemini_model
        self._groq_api_key = groq_api_key
        self._groq_model = groq_model
        self._novita_api_key = novita_api_key
        self._novita_model = novita_model
        self._minimax_api_key = minimax_api_key
        self._minimax_model = minimax_model
        self._lookback_hours = lookback_hours
        self._briefings_output_dir = briefings_output_dir
        self._user_context = user_context
        self._highlight_scorer_enabled = highlight_scorer_enabled
        self._highlight_weights = highlight_weights
        self._embedding_service = embedding_service

    # ------------------------------------------------------------------
    # Orchestration
    # ------------------------------------------------------------------

    def run(self, reference_time: Optional[datetime] = None) -> dict:
        posts = self.generate_digest(reference_time=reference_time)
        if not posts:
            return {"posts_included": 0, "email_sent": False, "webhook_sent": False}

        # Semantic augmentation — add ai-technique posts missed by keyword scoring
        if self._embedding_service is not None:
            technique_posts = self._semantic_augment(posts)
            if technique_posts:
                logger.info("DigestNotifier: adding %d semantic ai-technique posts", len(technique_posts))
                posts = posts + technique_posts

        report_markdown: Optional[str] = None
        if self._minimax_api_key or self._groq_api_key or self._gemini_api_key:
            report_markdown = self._run_summarization(posts, reference_time=reference_time)

        post_ids = [p.id for p in posts]

        email_ok = self.send_email(posts, report_markdown) if self._smtp else False
        webhook_ok = self.send_webhook(posts, report_markdown) if self._webhook_url else False

        # Mark per-channel flags independently
        if self._smtp and email_ok:
            self._store.mark_email_sent(post_ids)
        if self._webhook_url and webhook_ok:
            self._store.mark_webhook_sent(post_ids)

        # Mark digest_sent=True only when ALL configured channels succeed (backward compat)
        configured_channels = []
        if self._smtp:
            configured_channels.append(email_ok)
        if self._webhook_url:
            configured_channels.append(webhook_ok)

        all_ok = all(configured_channels) if configured_channels else True
        if all_ok and posts:
            self._store.mark_digest_sent(post_ids)

        self._store.commit()

        return {
            "posts_included": len(posts),
            "email_sent": email_ok,
            "webhook_sent": webhook_ok,
        }

    def _run_summarization(self, posts: list[Post], reference_time: Optional[datetime] = None) -> Optional[str]:
        """Run AI summarization and assemble report. Returns Markdown or None on total failure."""
        try:
            from app.summarizer.summary_generator import SummaryGenerator

            if self._novita_api_key:
                from app.summarizer.novita_client import NovitaClient
                client = NovitaClient(self._novita_api_key, self._novita_model)
                model_used = self._novita_model
            elif self._minimax_api_key:
                from app.summarizer.minimax_client import MinimaxClient
                client = MinimaxClient(self._minimax_api_key, self._minimax_model)
                model_used = self._minimax_model
            elif self._groq_api_key:
                from app.summarizer.groq_client import GroqClient
                client = GroqClient(self._groq_api_key, self._groq_model)
                model_used = self._groq_model
            else:
                from app.summarizer.gemini_client import GeminiClient
                client = GeminiClient(self._gemini_api_key, self._gemini_model)
                model_used = self._gemini_model

            generator = SummaryGenerator(client, self._store)
            generator.summarize_batch(posts)

            ref = reference_time or datetime.now(timezone.utc)
            today = ref.strftime("%Y-%m-%d")
            # Refresh posts from session to pick up summary_zh values
            refreshed = [self._store.get_post_by_id(p.id) or p for p in posts]
            report_content = generator.assemble_report(refreshed, today)

            if report_content:
                self._store.save_report(
                    content=report_content,
                    post_count=len(posts),
                    model_used=model_used,
                )
            return report_content or None
        except Exception as exc:
            logger.error("Summarization pipeline failed: %s", exc)
            # Reset session so subsequent operations (mark_digest_sent, commit) can proceed
            try:
                self._store.rollback()
            except Exception:
                pass
            return None

    def _run_briefing(
        self,
        report_markdown: str,
        reference_time: Optional[datetime] = None,
        posts=None,
    ) -> None:
        """Generate and save a developer briefing Markdown file."""
        try:
            from app.briefing.briefing_generator import BriefingGenerator

            highlight_posts = None
            if self._highlight_scorer_enabled and posts:
                from app.briefing.highlight_scorer import get_top_highlights
                non_arxiv = [p for p in posts if (p.source or "") != "arxiv"]
                highlight_posts = get_top_highlights(
                    non_arxiv, n=3, reference_time=reference_time, weights=self._highlight_weights
                )

            gen = BriefingGenerator(
                groq_api_key=self._groq_api_key,
                groq_model=self._groq_model,
                output_dir=self._briefings_output_dir,
                user_context=self._user_context,
                highlight_posts=highlight_posts,
                highlight_weights=self._highlight_weights,
            )
            gen.generate(report_markdown, date=reference_time)
        except Exception as exc:
            logger.error("Briefing generation failed: %s", exc)

    def _semantic_augment(self, existing_posts: list[Post], n: int = 5) -> list[Post]:
        """Find posts semantically relevant to AI collaboration techniques
        that keyword scoring may have missed."""
        try:
            from app.embeddings.vector_search import semantic_augment_for_briefing
            return semantic_augment_for_briefing(
                existing_posts, self._embedding_service, self._store, n=n
            )
        except Exception as exc:
            logger.warning("DigestNotifier: semantic augmentation failed — %s", exc)
            return []

    # ------------------------------------------------------------------
    # Digest generation
    # ------------------------------------------------------------------

    def generate_digest(self, reference_time: Optional[datetime] = None) -> list[Post]:
        since = None
        if self._lookback_hours > 0:
            ref = reference_time or datetime.now(timezone.utc)
            since = ref - timedelta(hours=self._lookback_hours)

        # Fetch a larger candidate pool when semantic re-ranking is available,
        # so the re-ranker has room to surface lower-ranked but more relevant posts.
        candidate_limit = self._top_n * 2 if self._embedding_service and self._user_context else self._top_n
        candidates = self._store.get_unsent_relevant_posts(limit=candidate_limit, since=since)

        if self._embedding_service and self._user_context and len(candidates) > self._top_n:
            try:
                from app.embeddings.vector_search import rank_by_user_context
                candidates = rank_by_user_context(
                    candidates,
                    user_context=self._user_context,
                    embedding_service=self._embedding_service,
                )
                logger.info("DigestNotifier: re-ranked %d candidates by user context", len(candidates))
            except Exception as exc:
                logger.warning("DigestNotifier: user-context re-ranking failed — %s", exc)

        return candidates[: self._top_n]

    # ------------------------------------------------------------------
    # Email delivery
    # ------------------------------------------------------------------

    def send_email(self, posts: list[Post], report_markdown: Optional[str] = None) -> bool:
        if not self._smtp:
            return False
        try:
            html = _render_email_html(posts, report_markdown)
            msg = MIMEMultipart("alternative")
            msg["Subject"] = f"AI News Digest — {len(posts)} posts"
            msg["From"] = self._smtp["from"]
            msg["To"] = self._smtp["to"]
            msg.attach(MIMEText(html, "html"))

            with smtplib.SMTP(self._smtp["host"], self._smtp["port"]) as server:
                server.starttls()
                server.login(self._smtp["user"], self._smtp["password"])
                server.send_message(msg)

            return True
        except Exception as exc:
            logger.error("Email delivery failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Webhook delivery
    # ------------------------------------------------------------------

    def send_webhook(self, posts: list[Post], report_markdown: Optional[str] = None) -> bool:
        if not self._webhook_url:
            return True  # not configured — no-op
        try:
            payload = {
                "digest": [
                    {
                        "source": p.source,
                        "external_id": p.external_id,
                        "author": p.author_handle,
                        "content": p.content,
                        "url": p.url,
                        "score": p.relevance_score,
                        "labels": p.labels,
                        "summary_zh": p.summary_zh,
                    }
                    for p in posts
                ],
                "report_markdown": report_markdown,
            }
            resp = httpx.post(self._webhook_url, json=payload, timeout=10)
            resp.raise_for_status()
            return True
        except Exception as exc:
            logger.error("Webhook delivery failed: %s", exc)
            return False


# ---------------------------------------------------------------------------
# HTML email template
# ---------------------------------------------------------------------------

def _render_email_html(posts: list[Post], report_markdown: Optional[str] = None) -> str:
    rows = "\n".join(
        f"""
        <tr>
          <td style="padding:8px 0; border-bottom:1px solid #eee;">
            <a href="{p.url}" style="font-weight:bold;">{p.author_handle}</a>
            <span style="color:#888; margin-left:8px;">score: {p.relevance_score:.1f}</span>
            <span style="color:#555; margin-left:8px;">{', '.join(p.labels or [])}</span>
            <p style="margin:4px 0 0;">{p.content[:280]}</p>
            {f'<p style="margin:4px 0 0; color:#333;"><em>{p.summary_zh}</em></p>' if p.summary_zh else ""}
          </td>
        </tr>
        """
        for p in posts
    )
    summary_section = ""
    if report_markdown:
        summary_section = f"""
        <hr style="margin:24px 0;">
        <h2>中文摘要</h2>
        <pre style="white-space:pre-wrap; font-family:sans-serif; font-size:14px;">{report_markdown}</pre>
        """
    return f"""
    <html><body>
    <h2>AI News Digest — {len(posts)} posts</h2>
    <table style="width:100%; font-family:sans-serif; font-size:14px;">
      {rows}
    </table>
    {summary_section}
    </body></html>
    """
