"""Manual trigger endpoints: fetch and daily report regeneration."""
from __future__ import annotations

import logging
import threading

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.auth import require_api_key
from app.api.deps import get_db, get_news_store
from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter(dependencies=[Depends(require_api_key)])


class TriggerResponse(BaseModel):
    status: str
    message: str


@router.post("/api/fetch/trigger", response_model=TriggerResponse)
def trigger_fetch(db: Session = Depends(get_db)):
    """Manually trigger a full fetch + score + store pipeline run."""
    from app.api.deps import _SessionLocal
    from app.pipeline.scheduler import _make_fetch_job
    from app.store.news_store import NewsStore

    def run():
        f = _make_fetch_job(settings, _SessionLocal)
        f()

    threading.Thread(target=run, daemon=True).start()
    return TriggerResponse(status="queued", message="抓取任务已启动，后台执行中")


@router.post("/api/daily-report/regenerate", response_model=TriggerResponse)
def regenerate_daily_report(db: Session = Depends(get_db)):
    """Regenerate today's daily report and cache it."""
    from app.api.routes.daily_report import generate_and_cache

    store = get_news_store(db)
    try:
        ok = generate_and_cache(store)
        db.commit()
        if ok:
            return TriggerResponse(status="ok", message="日报已重新生成")
        return TriggerResponse(status="error", message="日报生成失败")
    except Exception as e:
        db.rollback()
        return TriggerResponse(status="error", message=str(e))
