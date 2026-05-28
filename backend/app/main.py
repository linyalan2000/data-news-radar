"""FastAPI application entrypoint."""
import logging
import threading
from contextlib import asynccontextmanager

# Ensure apscheduler logs are visible
logging.getLogger("apscheduler").setLevel(logging.DEBUG)
logging.getLogger("apscheduler.scheduler").addHandler(logging.StreamHandler())
from datetime import date, datetime, timedelta, timezone
from typing import List

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import daily_report, digest, health, news, summary, wechat_qr, settings_api, trigger
from app.config import settings

logger = logging.getLogger(__name__)


def _get_missing_report_dates(store, max_days: int) -> List[date]:
    """Return sorted list of UTC calendar dates (up to max_days ago) that have no report."""
    limit = max(50, max_days * 2)
    reports = store.get_reports(limit=limit)
    existing_dates = {
        r.generated_at.replace(tzinfo=timezone.utc).date()
        for r in reports
    }

    now_utc = datetime.now(timezone.utc)
    today = now_utc.date()
    missing: List[date] = []

    # Check past days (yesterday and earlier), but only if adjacent to an existing report.
    # We stop at the first gap to avoid backfilling ancient empty dates that have no data.
    for days_ago in range(1, max_days + 1):
        candidate = today - timedelta(days=days_ago)
        if candidate not in existing_dates:
            missing.append(candidate)
        else:
            # Found an existing report — stop looking further back
            break

    # Check today only if scheduled time (08:00 UTC) has passed
    today_scheduled = now_utc.replace(hour=8, minute=0, second=0, microsecond=0)
    if now_utc >= today_scheduled and today not in existing_dates:
        missing.append(today)

    return sorted(missing)


def _catchup_digest() -> None:
    """On startup, backfill any missing daily reports up to CATCHUP_MAX_DAYS days."""
    try:
        from app.api.deps import _SessionLocal
        from app.store.news_store import NewsStore
        from app.notifier.digest_notifier import DigestNotifier

        # Use a short-lived session only for the date-discovery query
        db = _SessionLocal()
        try:
            store = NewsStore(session=db)
            missing_dates = _get_missing_report_dates(store, settings.catchup_max_days)
        finally:
            db.close()

        if not missing_dates:
            logger.info("Startup catch-up: no missing report dates.")
            return

        logger.info("Startup catch-up: found %d missing date(s): %s", len(missing_dates), missing_dates)

        for missing_date in missing_dates:
            ref_time = datetime(
                missing_date.year, missing_date.month, missing_date.day,
                8, 0, 0, tzinfo=timezone.utc,
            )
            # Each date gets its own fresh session to avoid cross-run session contamination
            db = _SessionLocal()
            try:
                store = NewsStore(session=db)
                window_start = ref_time - timedelta(hours=settings.digest_lookback_hours)
                posts_available = store.get_unsent_relevant_posts(limit=1, since=window_start)
                if not posts_available:
                    logger.warning(
                        "Startup catch-up: skipping %s — no posts in window [%s, %s]",
                        missing_date, window_start.date(), ref_time.date(),
                    )
                    continue

                logger.info("Startup catch-up: running digest for %s (ref_time=%s)", missing_date, ref_time)
                notifier = DigestNotifier(
                    news_store=store,
                    smtp_config=settings.smtp_config,
                    webhook_url=settings.digest_webhook_url,
                    gemini_api_key=settings.gemini_api_key,
                    gemini_model=settings.gemini_model,
                    groq_api_key=settings.groq_api_key,
                    groq_model=settings.groq_model,
                    minimax_api_key=settings.minimax_api_key,
                    minimax_model=settings.minimax_model,
                    lookback_hours=settings.digest_lookback_hours,
                    briefings_output_dir=settings.briefings_output_dir_resolved,
                    user_context=settings.user_context,
                    highlight_scorer_enabled=settings.FEATURES.get("highlight_scorer", False),
                )
                notifier.run(reference_time=ref_time)
            except Exception as exc:
                logger.error("Startup catch-up: failed for %s: %s", missing_date, exc)
                db.rollback()
            finally:
                db.close()

    except Exception as exc:
        logger.error("Startup catch-up digest failed: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.pipeline.scheduler import start_scheduler, stop_scheduler
    try:
        start_scheduler()
        logger.info("Scheduler started successfully")
    except Exception as e:
        logger.error("Scheduler failed to start: %s", e, exc_info=True)
    threading.Thread(target=_catchup_digest, daemon=True).start()
    yield
    stop_scheduler()


app = FastAPI(title="X AI News Researcher", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(news.router)
app.include_router(digest.router)
app.include_router(summary.router)
app.include_router(daily_report.router)
app.include_router(wechat_qr.router)
app.include_router(settings_api.router)
app.include_router(trigger.router)

if settings.FEATURES.get("bookmarks"):
    from app.api.routes import bookmarks
    app.include_router(bookmarks.router)
