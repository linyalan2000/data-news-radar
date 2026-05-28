"""Simple threaded scheduler: fetch (interval) + digest/report (daily).

Each job creates its own SQLAlchemy session to prevent
PendingRollbackError from leaking between jobs on a shared session.

Uses threading (not APScheduler) for reliability.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

_scheduler: threading.Thread | None = None
_stop_event = threading.Event()


def _run_loop(
    fetch_interval_minutes: int,
    digest_cron: str,
    fetch_job_fn,
    digest_job_fn,
    weekly_briefing_job_fn=None,
    daily_report_job_fn=None,
) -> None:
    """Main loop: runs fetch on interval, digest/report at 8 AM daily."""
    logger.info("Scheduler loop started (fetch every %dmin)", fetch_interval_minutes)
    _reported_today = False  # track whether we've run daily jobs today

    while not _stop_event.is_set():
        now = datetime.now(timezone.utc)
        now_cst = now + timedelta(hours=8)
        h, m, d = now_cst.hour, now_cst.minute, now_cst.day

        # Reset tracker at start of new day
        if not hasattr(_run_loop, "_last_day") or _run_loop._last_day != d:
            _run_loop._last_day = d
            _reported_today = False

        # Run fetch (on interval – approximate, resets on each iteration)
        try:
            fetch_job_fn()
        except Exception as e:
            logger.error("Fetch job failed: %s", e, exc_info=True)

        # Daily jobs: run at 8-9 AM or if not yet done today
        should_report = not _reported_today and (h == 8 or (h > 8 and not _reported_today))
        if should_report:
            _reported_today = True
            try:
                digest_job_fn()
            except Exception as e:
                logger.error("Digest job failed: %s", e, exc_info=True)
            try:
                if daily_report_job_fn is not None:
                    daily_report_job_fn()
            except Exception as e:
                logger.error("Daily report job failed: %s", e, exc_info=True)
            if weekly_briefing_job_fn is not None and now_cst.weekday() == 0:  # Monday
                try:
                    weekly_briefing_job_fn()
                except Exception as e:
                    logger.error("Weekly briefing failed: %s", e, exc_info=True)

        # Sleep interval minutes (but wake up every minute for daily tasks)
        for _ in range(fetch_interval_minutes):
            if _stop_event.is_set():
                return
            time.sleep(60)


def _make_fetch_job(settings, session_factory, embedding_service=None) -> callable:
    """Return a callable that builds a fresh session + pipeline per invocation."""
    from app.fetcher.hn_fetcher import HackerNewsFetcher
    from app.fetcher.reddit_fetcher import RedditFetcher
    from app.fetcher.github_fetcher import GitHubFetcher
    from app.fetcher.multi_source_fetcher import MultiSourceFetcher
    from app.pipeline.fetch_pipeline import FetchPipeline
    from app.scorer.relevance_scorer import RelevanceScorer
    from app.store.news_store import NewsStore

    summarizer = None
    if settings.minimax_api_key:
        from app.summarizer.minimax_client import MinimaxClient
        summarizer = MinimaxClient(settings.minimax_api_key, settings.minimax_model)

    def run():
        db = session_factory()
        try:
            store = NewsStore(session=db)
            hn = HackerNewsFetcher(
                keywords=settings.hn_keywords_list,
                fetch_limit=settings.hn_fetch_limit,
                news_store=store,
            )
            reddit = None
            if settings.reddit_subreddits_list or settings.reddit_keywords_list:
                reddit = RedditFetcher(
                    subreddits=settings.reddit_subreddits_list,
                    keywords=settings.reddit_keywords_list,
                    fetch_limit=settings.reddit_fetch_limit,
                    news_store=store,
                )
            github = GitHubFetcher(
                keywords=settings.github_keywords_list,
                monitored_repos=settings.github_monitored_repos_list,
                fetch_limit=settings.github_fetch_limit,
                github_token=settings.github_token,
                news_store=store,
            )

            arxiv = None
            if settings.FEATURES.get("arxiv_fetcher"):
                from app.fetcher.arxiv_fetcher import ArxivFetcher

                arxiv = ArxivFetcher(
                    categories=settings.arxiv_categories_list,
                    keywords=settings.hn_keywords_list,
                    max_results=settings.arxiv_max_results,
                    news_store=store,
                )

            rss = None
            if settings.rss_feeds_list:
                from app.fetcher.rss_fetcher import RssFetcher

                rss = RssFetcher(
                    feed_urls=settings.rss_feeds_list,
                    fetch_limit=settings.rss_fetch_limit,
                    news_store=store,
                )

            gov = None
            if settings.feature_gov_fetcher:
                from app.fetcher.gov_fetcher import GovFetcher

                gov = GovFetcher(fetch_limit=80, news_store=store)

            wechat = None
            # Check database override first, fall back to .env
            db_wechat = store.get_system_state("sources_wechat")
            wechat_accounts = [a.strip() for a in db_wechat.split(",") if a.strip()] if db_wechat else settings.wechat_accounts_list
            if wechat_accounts:
                from app.fetcher.wechat_fetcher import WeChatFetcher

                wechat = WeChatFetcher(
                    accounts=wechat_accounts,
                    fetch_limit=settings.wechat_fetch_limit,
                    news_store=store,
                )

            bidding = None
            if settings.FEATURES.get("bidding_fetcher"):
                from app.fetcher.bidding_fetcher import BiddingFetcher

                bidding = BiddingFetcher(fetch_limit=60, news_store=store)

            cls = None
            if settings.FEATURES.get("cls_fetcher"):
                from app.fetcher.cls_fetcher import ClsFetcher

                db_cls_kw = store.get_system_state("keywords_cls")
                cls_keywords = [k.strip() for k in db_cls_kw.split(",") if k.strip()] if db_cls_kw else settings.cls_keywords_list
                cls = ClsFetcher(
                    keywords=cls_keywords,
                    fetch_limit=settings.cls_fetch_limit,
                    news_store=store,
                )

            aihot = None
            if settings.FEATURES.get("aihot_fetcher"):
                from app.fetcher.aihot_fetcher import AihotFetcher

                aihot = AihotFetcher(
                    fetch_limit=settings.aihot_fetch_limit,
                    news_store=store,
                )

            fetcher = MultiSourceFetcher(
                hn=hn,
                reddit=reddit,
                github=None,
                arxiv=arxiv,
                rss=rss,
                gov=gov,
                wechat=wechat,
                bidding=bidding,
                cls=cls,
                aihot=aihot,
            )
            scorer = RelevanceScorer(
                news_store=store,
                keywords_config_path=settings.keywords_config_path,
                threshold=settings.relevance_threshold,
            )
            pipeline = FetchPipeline(
                news_store=store,
                fetcher=fetcher,
                scorer=scorer,
                embedding_service=embedding_service,
                summarizer=summarizer,
            )
            pipeline.run()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    return run


_DIGEST_COOLDOWN_MINUTES = 30


def _make_digest_job(settings, session_factory, embedding_service=None) -> callable:
    """Return a callable that builds a fresh session + notifier per invocation.

    Includes a 30-minute cooldown guard: if the last digest ran less than
    _DIGEST_COOLDOWN_MINUTES ago, the job is skipped. This prevents crash-loop
    scenarios where APScheduler fires a missed job immediately on restart.
    """
    from app.notifier.digest_notifier import DigestNotifier
    from app.store.news_store import NewsStore

    def run():
        from datetime import datetime, timedelta, timezone

        db = session_factory()
        try:
            store = NewsStore(session=db)

            # Crash loop cooldown: skip if last digest was recent
            last_digest = store.get_last_digest_at()
            if last_digest is not None:
                now = datetime.now(timezone.utc)
                if last_digest.tzinfo is None:
                    last_digest = last_digest.replace(tzinfo=timezone.utc)
                elapsed = (now - last_digest).total_seconds() / 60
                if elapsed < _DIGEST_COOLDOWN_MINUTES:
                    logger.info(
                        "Digest cooldown active (%.1f min since last run, threshold %d min) — skipping.",
                        elapsed,
                        _DIGEST_COOLDOWN_MINUTES,
                    )
                    return

            notifier = DigestNotifier(
                news_store=store,
                smtp_config=settings.smtp_config,
                webhook_url=settings.digest_webhook_url,
                gemini_api_key=settings.gemini_api_key,
                gemini_model=settings.gemini_model,
                groq_api_key=settings.groq_api_key,
                groq_model=settings.groq_model,
                novita_api_key=settings.novita_api_key,
                novita_model=settings.novita_model,
                minimax_api_key=settings.minimax_api_key,
                minimax_model=settings.minimax_model,
                lookback_hours=settings.digest_lookback_hours,
                briefings_output_dir=settings.briefings_output_dir_resolved,
                user_context=settings.user_context,
                highlight_scorer_enabled=settings.FEATURES.get(
                    "highlight_scorer", False
                ),
                embedding_service=embedding_service,
            )
            notifier.run()
            store.set_last_digest_at(datetime.now(timezone.utc))
            store.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    return run


def _make_weekly_briefing_job(settings, session_factory) -> callable:
    """Return a callable for the weekly briefing job."""
    from app.briefing.weekly_briefing_generator import WeeklyBriefingGenerator
    from app.store.news_store import NewsStore

    def run():
        from datetime import datetime, timedelta, timezone

        db = session_factory()
        try:
            store = NewsStore(session=db)
            since = datetime.now(timezone.utc) - timedelta(days=7)
            posts = store.query_posts(
                is_relevant=True, since=since, per_page=200, sort="score_desc"
            )
            generator = WeeklyBriefingGenerator(
                groq_api_key=settings.groq_api_key,
                groq_model=settings.groq_model,
                output_dir=str(Path(settings.briefings_output_dir_resolved) / "weekly")
                if settings.briefings_output_dir_resolved
                else "briefings/weekly",
            )
            generator.generate(posts)
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    return run


def _make_daily_report_job(settings, session_factory) -> callable:
    from app.api.routes.daily_report import generate_and_cache
    from app.store.news_store import NewsStore

    def run():
        db = session_factory()
        try:
            store = NewsStore(session=db)
            ok = generate_and_cache(store)
            if ok:
                logger.info("Daily report generated and cached")
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("Daily report generation failed")
        finally:
            db.close()

    return run


def start_scheduler() -> None:
    global _scheduler, _stop_event
    from app.config import settings
    from app.api.deps import _SessionLocal

    # Set up embedding service if feature is enabled
    embedding_service = None
    if settings.FEATURES.get("embeddings"):
        from app.embeddings.embedding_service import EmbeddingService

        embedding_service = EmbeddingService(
            model_name=settings.embedding_model,
            use_local=not bool(settings.hf_api_token),
            hf_api_token=settings.hf_api_token,
        )
        embedding_service.warmup()
        logger.info("EmbeddingService warmed up: %s", settings.embedding_model)

    fetch_job = _make_fetch_job(
        settings, _SessionLocal, embedding_service=embedding_service
    )
    digest_job = _make_digest_job(
        settings, _SessionLocal, embedding_service=embedding_service
    )

    weekly_job = None
    if settings.FEATURES.get("weekly_briefing"):
        weekly_job = _make_weekly_briefing_job(settings, _SessionLocal)

    daily_report_job = _make_daily_report_job(settings, _SessionLocal)

    _stop_event.clear()
    _scheduler = threading.Thread(
        target=_run_loop,
        args=(
            settings.fetch_interval_minutes,
            settings.digest_cron,
            fetch_job,
            digest_job,
            weekly_job,
            daily_report_job,
        ),
        daemon=True,
    )
    _scheduler.start()
    logger.info(
        "Scheduler started (fetch every %dmin, digest: %s)",
        settings.fetch_interval_minutes,
        settings.digest_cron,
    )


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.is_alive():
        _stop_event.set()
        _scheduler.join(timeout=5)
        logger.info("Scheduler stopped")
