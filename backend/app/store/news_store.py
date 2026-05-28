"""NewsStore: persistence layer for fetched and scored posts."""

from datetime import date, datetime, timezone
from typing import Optional

import sqlalchemy as sa
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.models import Bookmark, Post, Report, SystemState

_LAST_FETCH_KEY = "last_fetch_at"
_LAST_DIGEST_KEY = "last_digest_at"


class NewsStore:
    def __init__(self, session: Session) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def upsert_post(self, data: dict) -> None:
        """Insert or update a post by (source, external_id)."""
        existing = (
            self._session.query(Post)
            .filter(
                Post.source == data["source"], Post.external_id == data["external_id"]
            )
            .first()
        )
        if existing:
            existing.relevance_score = data.get(
                "relevance_score", existing.relevance_score
            )
            existing.is_relevant = data.get("is_relevant", existing.is_relevant)
            existing.labels = data.get("labels", existing.labels)
            if data.get("title"):
                existing.title = data["title"]
        else:
            post = Post(
                source=data["source"],
                external_id=data["external_id"],
                author_handle=data["author_handle"],
                title=data.get("title", ""),
                content=data["content"],
                url=data["url"],
                posted_at=data["posted_at"],
                fetched_at=data.get("fetched_at", datetime.now(timezone.utc)),
                relevance_score=data.get("relevance_score"),
                points=data.get("points"),
                is_relevant=data.get("is_relevant", False),
                labels=data.get("labels", []),
                digest_sent=data.get("digest_sent", False),
                recommendation_reason=data.get("recommendation_reason"),
            )
            self._session.add(post)
        self._session.flush()

    def update_post_summary(self, post_id: int, summary_zh: str) -> None:
        """Cache the zh-CN summary for a post."""
        self._session.query(Post).filter(Post.id == post_id).update(
            {"summary_zh": summary_zh}, synchronize_session="fetch"
        )
        self._session.flush()

    def update_topic_group(self, post_id: int, topic_group: str | None) -> None:
        """Assign a topic_group to a post for duplicate/similar news folding."""
        self._session.query(Post).filter(Post.id == post_id).update(
            {"topic_group": topic_group}, synchronize_session="fetch"
        )
        self._session.flush()

    def update_post_relevance_note(self, post_id: int, note: str, is_relevant: bool = False) -> None:
        """Store the LLM relevance judgment result and update is_relevant flag."""
        self._session.query(Post).filter(Post.id == post_id).update(
            {"relevance_note": note, "is_relevant": is_relevant},
            synchronize_session="fetch",
        )
        self._session.flush()

    def save_report(self, content: str, post_count: int, model_used: str) -> Report:
        """Persist an assembled Markdown report."""
        report = Report(content=content, post_count=post_count, model_used=model_used)
        self._session.add(report)
        self._session.flush()
        return report

    def get_reports(self, limit: int = 50, offset: int = 0) -> list[Report]:
        """Return all reports ordered by generated_at descending."""
        return (
            self._session.query(Report)
            .order_by(Report.generated_at.desc())
            .limit(limit)
            .offset(offset)
            .all()
        )

    def get_report_by_id(self, report_id: int) -> Optional[Report]:
        """Return a specific report by ID, or None."""
        return self._session.get(Report, report_id)

    def get_latest_report(self) -> Optional[Report]:
        """Return the most recently generated report, or None."""
        return self._session.query(Report).order_by(Report.generated_at.desc()).first()

    def mark_digest_sent(self, post_ids: list[int]) -> None:
        """Mark the given post IDs as digest_sent=True (deprecated — use channel-specific methods)."""
        self._session.query(Post).filter(Post.id.in_(post_ids)).update(
            {"digest_sent": True}, synchronize_session="fetch"
        )
        self._session.flush()

    def mark_email_sent(self, post_ids: list[int]) -> None:
        """Mark the given post IDs as email_sent=True."""
        self._session.query(Post).filter(Post.id.in_(post_ids)).update(
            {"email_sent": True}, synchronize_session="fetch"
        )
        self._session.flush()

    def mark_webhook_sent(self, post_ids: list[int]) -> None:
        """Mark the given post IDs as webhook_sent=True."""
        self._session.query(Post).filter(Post.id.in_(post_ids)).update(
            {"webhook_sent": True}, synchronize_session="fetch"
        )
        self._session.flush()

    def update_post_embedding(self, post_id: int, embedding_bytes: bytes) -> None:
        """Store serialized embedding blob for a post."""
        self._session.query(Post).filter(Post.id == post_id).update(
            {"embedding": embedding_bytes}, synchronize_session="fetch"
        )
        self._session.flush()

    def get_posts_without_summary(self, limit: int = 50) -> list:
        """Return posts that don't have a valid summary yet.

        Includes NULL, '不相关', and empty string so they get retried.
        """
        return (
            self._session.query(Post)
            .filter(
                (Post.summary_zh.is_(None))
                | (Post.summary_zh == "不相关")
                | (Post.summary_zh == "")
            )
            .order_by(Post.fetched_at.desc())
            .limit(limit)
            .all()
        )

    def rollback(self) -> None:
        """Roll back the current transaction, resetting any pending error state."""
        self._session.rollback()

    def commit(self) -> None:
        """Commit the current session transaction."""
        self._session.commit()

    def update_last_fetch_at(self, timestamp: datetime) -> None:
        """Record the most recent successful fetch timestamp."""
        existing = self._session.get(SystemState, _LAST_FETCH_KEY)
        if existing:
            existing.value = timestamp.isoformat()
            existing.updated_at = datetime.now(timezone.utc)
        else:
            self._session.add(
                SystemState(
                    key=_LAST_FETCH_KEY,
                    value=timestamp.isoformat(),
                    updated_at=datetime.now(timezone.utc),
                )
            )
        self._session.flush()

    def get_last_digest_at(self) -> Optional[datetime]:
        """Return timestamp of the most recent completed digest, or None."""
        row = self._session.get(SystemState, _LAST_DIGEST_KEY)
        if row is None or row.value is None:
            return None
        return datetime.fromisoformat(row.value)

    def set_last_digest_at(self, timestamp: datetime) -> None:
        """Record the most recent completed digest timestamp."""
        existing = self._session.get(SystemState, _LAST_DIGEST_KEY)
        if existing:
            existing.value = timestamp.isoformat()
            existing.updated_at = datetime.now(timezone.utc)
        else:
            self._session.add(
                SystemState(
                    key=_LAST_DIGEST_KEY,
                    value=timestamp.isoformat(),
                    updated_at=datetime.now(timezone.utc),
                )
            )
        self._session.flush()

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def query_posts(
        self,
        *,
        label: Optional[str] = None,
        min_score: Optional[float] = None,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        since: Optional[datetime] = None,
        keyword: Optional[str] = None,
        source: Optional[str] = None,
        is_relevant: Optional[bool] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        fts_enabled: bool = False,
        sort: str = "date_desc",
        page: int = 1,
        per_page: int = 20,
    ) -> list[Post]:
        # FTS5 path: fetch matching rowids then filter the main query
        fts_active = False
        if fts_enabled and keyword:
            fts_ids = self._fts_search(keyword)
            if fts_ids is not None and fts_ids:
                fts_active = True
                q = self._session.query(Post).filter(Post.id.in_(fts_ids))
            else:
                q = self._session.query(
                    Post
                )  # FTS empty or unavailable → ilike fallback
        else:
            q = self._session.query(Post)

        q = self._apply_filters(
            q,
            label=label,
            min_score=min_score,
            from_date=from_date,
            to_date=to_date,
            since=since,
            keyword=keyword if not fts_active else None,
            source=source,
            is_relevant=is_relevant,
            date_from=date_from,
            date_to=date_to,
        )
        if sort == "score_desc":
            q = q.order_by(Post.relevance_score.desc().nullslast(), Post.id.asc())
        else:
            q = q.order_by(Post.posted_at.desc(), Post.id.asc())
        offset = (page - 1) * per_page
        return q.offset(offset).limit(per_page).all()

    def count_posts(
        self,
        *,
        label: Optional[str] = None,
        min_score: Optional[float] = None,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        since: Optional[datetime] = None,
        keyword: Optional[str] = None,
        source: Optional[str] = None,
        is_relevant: Optional[bool] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        fts_enabled: bool = False,
    ) -> int:
        fts_active = False
        if fts_enabled and keyword:
            fts_ids = self._fts_search(keyword)
            if fts_ids is not None and fts_ids:
                fts_active = True
                q = self._session.query(func.count(Post.id)).filter(
                    Post.id.in_(fts_ids)
                )
            else:
                q = self._session.query(func.count(Post.id))
        else:
            q = self._session.query(func.count(Post.id))
        q = self._apply_filters(
            q,
            label=label,
            min_score=min_score,
            from_date=from_date,
            to_date=to_date,
            since=since,
            keyword=keyword if not fts_active else None,
            source=source,
            is_relevant=is_relevant,
            date_from=date_from,
            date_to=date_to,
        )
        return q.scalar() or 0

    def _fts_search(self, keyword: str) -> list[int] | None:
        """Return Post IDs matching keyword via FTS5, or None if FTS table unavailable."""
        try:
            rows = self._session.execute(
                text(
                    "SELECT rowid FROM articles_fts WHERE articles_fts MATCH :q ORDER BY rank"
                ),
                {"q": keyword},
            ).fetchall()
            return [r[0] for r in rows]
        except Exception:
            return None

    def get_unsent_relevant_posts(
        self, limit: int = 20, since: Optional[datetime] = None
    ) -> list[Post]:
        q = self._session.query(Post).filter(
            Post.is_relevant == True, Post.digest_sent == False
        )
        if since is not None:
            q = q.filter(Post.posted_at >= since)
        return q.order_by(Post.relevance_score.desc().nullslast()).limit(limit).all()

    def get_posts_without_embedding(self, limit: int = 100) -> list[Post]:
        """Return posts that have no embedding yet (for backfill)."""
        return (
            self._session.query(Post)
            .filter(Post.embedding.is_(None))
            .order_by(Post.posted_at.desc())
            .limit(limit)
            .all()
        )

    def get_posts_without_topic_group(self, limit: int = 200) -> list[Post]:
        """Return posts that haven't been assigned a topic_group yet."""
        return (
            self._session.query(Post)
            .filter(Post.topic_group.is_(None))
            .order_by(Post.posted_at.desc())
            .limit(limit)
            .all()
        )

    def get_posts_with_embeddings(
        self,
        since=None,
        is_relevant: Optional[bool] = None,
    ) -> list[Post]:
        """Return all posts that have an embedding stored."""
        q = self._session.query(Post).filter(Post.embedding.isnot(None))
        if is_relevant is not None:
            q = q.filter(Post.is_relevant == is_relevant)
        if since is not None:
            q = q.filter(Post.posted_at >= since)
        return q.all()

    def get_post_by_url(self, url: str) -> Optional[Post]:
        """Return the first Post matching the given URL, or None."""
        return self._session.query(Post).filter(Post.url == url).first()

    def get_post_by_id(self, post_id: int) -> Optional[Post]:
        return self._session.get(Post, post_id)

    def get_post_by_source_and_external_id(
        self, source: str, external_id: str
    ) -> Optional[Post]:
        """Return the Post matching (source, external_id), or None."""
        return (
            self._session.query(Post)
            .filter(Post.source == source, Post.external_id == external_id)
            .first()
        )

    def exists_by_source_and_external_id(self, source: str, external_id: str) -> bool:
        """Return True if a post with the given (source, external_id) already exists."""
        return (
            self._session.query(Post.id)
            .filter(Post.source == source, Post.external_id == external_id)
            .first()
        ) is not None

    def get_system_state(self, key: str) -> Optional[str]:
        row = self._session.get(SystemState, key)
        return row.value if row else None

    def set_system_state(self, key: str, value: str) -> None:
        existing = self._session.get(SystemState, key)
        if existing:
            existing.value = value
            existing.updated_at = datetime.now(timezone.utc)
        else:
            self._session.add(
                SystemState(key=key, value=value, updated_at=datetime.now(timezone.utc))
            )
        self._session.flush()

    def get_last_fetch_at(self) -> Optional[datetime]:
        row = self._session.get(SystemState, _LAST_FETCH_KEY)
        if row is None or row.value is None:
            return None
        return datetime.fromisoformat(row.value)

    # ------------------------------------------------------------------
    # Bookmarks (Phase 19)
    # ------------------------------------------------------------------

    def add_bookmark(self, article_id: int, note: str = "") -> Bookmark:
        """Create a bookmark for *article_id*. Raises ValueError if article not found."""
        post = self.get_post_by_id(article_id)
        if post is None:
            raise ValueError(f"Article {article_id} not found")
        # Check for duplicate
        existing = (
            self._session.query(Bookmark)
            .filter(Bookmark.article_id == article_id)
            .first()
        )
        if existing:
            raise LookupError(f"Article {article_id} already bookmarked")
        bm = Bookmark(
            article_id=article_id,
            note=note or None,
            created_at=datetime.now(timezone.utc),
        )
        self._session.add(bm)
        self._session.flush()
        return bm

    def get_bookmarks(self, q: Optional[str] = None) -> list[Bookmark]:
        """Return bookmarks ordered by created_at desc, optionally filtered by keyword."""
        query = self._session.query(Bookmark).join(Bookmark.post)
        if q:
            like = f"%{q}%"
            query = query.filter(
                sa.or_(
                    Post.content.ilike(like),
                    Bookmark.note.ilike(like),
                )
            )
        return query.order_by(Bookmark.created_at.desc()).all()

    def delete_bookmark(self, bookmark_id: int) -> bool:
        """Delete bookmark by ID. Returns True if deleted, False if not found."""
        bm = self._session.get(Bookmark, bookmark_id)
        if bm is None:
            return False
        self._session.delete(bm)
        self._session.flush()
        return True

    def check_db_alive(self) -> bool:
        """Return True if the database is reachable."""
        try:
            self._session.execute(__import__("sqlalchemy").text("SELECT 1"))
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _apply_filters(
        self,
        q,
        *,
        label,
        min_score,
        from_date,
        to_date,
        since,
        keyword,
        source,
        is_relevant,
        date_from=None,
        date_to=None,
    ):
        if label is not None:
            encoded = label.encode("unicode_escape").decode()
            q = q.filter(
                sa.or_(
                    Post.labels.contains(label),
                    Post.labels.contains(encoded),
                )
            )
        if min_score is not None:
            q = q.filter(Post.relevance_score >= min_score)
        if from_date is not None:
            q = q.filter(Post.posted_at >= from_date)
        if to_date is not None:
            q = q.filter(Post.posted_at <= to_date)
        if date_from is not None:
            q = q.filter(sa.func.date(Post.posted_at) >= date_from.isoformat())
        if date_to is not None:
            q = q.filter(sa.func.date(Post.posted_at) <= date_to.isoformat())
        if since is not None:
            q = q.filter(Post.posted_at > since)
        if keyword is not None:
            q = q.filter(
                sa.or_(
                    Post.content.ilike(f"%{keyword}%"),
                    Post.title.ilike(f"%{keyword}%"),
                    Post.author_handle.ilike(f"%{keyword}%"),
                    Post.url.ilike(f"%{keyword}%"),
                    sa.cast(Post.labels, sa.String).ilike(f"%{keyword}%"),
                )
            )
        if source is not None:
            q = q.filter(Post.source == source)
        if is_relevant is not None:
            q = q.filter(Post.is_relevant == is_relevant)
        return q
