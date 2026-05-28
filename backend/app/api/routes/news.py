"""News listing and detail endpoints."""
import logging
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

from app.api.auth import require_api_key
from app.api.deps import get_db, get_news_store
from app.config import settings
from app.schemas import PaginatedNewsResponse, Post

router = APIRouter(dependencies=[Depends(require_api_key)])


@router.get("/api/news", response_model=PaginatedNewsResponse)
def list_news(
    label: Optional[str] = Query(None),
    min_score: Optional[float] = Query(None),
    from_date: Optional[datetime] = Query(None),
    to_date: Optional[datetime] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    is_relevant: Optional[bool] = Query(None),
    q: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    since: Optional[datetime] = Query(None),
    sort: str = Query("date_desc"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    fts = settings.FEATURES["fts_search"]
    store = get_news_store(db)
    kwargs = dict(
        label=label,
        min_score=min_score,
        from_date=from_date,
        to_date=to_date,
        date_from=date_from,
        date_to=date_to,
        keyword=q,
        is_relevant=is_relevant,
        source=source,
        since=since,
        fts_enabled=fts,
        sort=sort,
        page=page,
        per_page=per_page,
    )
    items = store.query_posts(**kwargs)
    total = store.count_posts(
        label=label,
        min_score=min_score,
        from_date=from_date,
        to_date=to_date,
        date_from=date_from,
        date_to=date_to,
        keyword=q,
        is_relevant=is_relevant,
        source=source,
        since=since,
        fts_enabled=fts,
    )
    return PaginatedNewsResponse(total=total, page=page, per_page=per_page, items=items)


@router.get("/api/news/{post_id}", response_model=Post)
def get_news_item(post_id: int, db: Session = Depends(get_db)):
    store = get_news_store(db)
    post = store.get_post_by_id(post_id)
    if not post:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")
    return post
