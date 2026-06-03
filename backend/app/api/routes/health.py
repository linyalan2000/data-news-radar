"""Health check endpoint."""
from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_news_store
from app.schemas import HealthResponse
from app.store.news_store import NewsStore

router = APIRouter()


@router.get("/api/health", response_model=HealthResponse)
def health(db: Session = Depends(get_db)):
    store = get_news_store(db)
    db_ok = store.check_db_alive()
    last_fetch = store.get_last_fetch_at()
    try:
        import app.pipeline.scheduler as sched
        scheduler_ok = sched._scheduler is not None and sched._scheduler.is_alive()
    except Exception:
        scheduler_ok = False
    try:
        from app.fetcher.wechat_client import load_token, is_token_valid

        wechat_login = not is_token_valid(load_token())
        if wechat_login:
            Path("/tmp/wechat_login_needed").touch()
        else:
            Path("/tmp/wechat_login_needed").unlink(missing_ok=True)
    except Exception:
        wechat_login = Path("/tmp/wechat_login_needed").exists()
    if db_ok:
        return HealthResponse(
            status="ok", db="connected",
            last_fetch_at=last_fetch,
            scheduler=scheduler_ok,
            wechat_login_needed=wechat_login,
        )
    return JSONResponse(
        status_code=503,
        content={
            "status": "degraded", "db": "disconnected",
            "last_fetch_at": None, "scheduler": scheduler_ok,
            "wechat_login_needed": wechat_login,
        },
    )
