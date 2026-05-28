from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import DeclarativeBase, relationship
from sqlalchemy.types import JSON


class Base(DeclarativeBase):
    pass


class Post(Base):
    __tablename__ = "posts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source = Column(String, nullable=False)       # "hackernews" | "reddit" | "github"
    external_id = Column(String, nullable=False)  # source-specific unique ID
    author_handle = Column(String, nullable=False)
    title = Column(Text, nullable=False, default="")  # extracted title, populated by fetcher
    content = Column(Text, nullable=False)
    url = Column(String, nullable=False)
    posted_at = Column(DateTime(timezone=True), nullable=False)
    fetched_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    relevance_score = Column(Float, nullable=True)
    points = Column(Integer, nullable=True)
    is_relevant = Column(Boolean, nullable=False, default=False)
    labels = Column(JSON, nullable=False, default=list)
    digest_sent = Column(Boolean, nullable=False, default=False)  # deprecated: use email_sent + webhook_sent
    email_sent = Column(Boolean, nullable=False, default=False)
    webhook_sent = Column(Boolean, nullable=False, default=False)
    summary_zh = Column(Text, nullable=True)
    topic_group = Column(String(32), nullable=True)  # hash of normalized title; groups duplicate/similar news
    recommendation_reason = Column(Text, nullable=True)  # editor's recommendation reason (aihot, etc.)
    relevance_note = Column(Text, nullable=True)  # LLM judgment result; NULL=unjudged, populated=reason for skipping
    embedding = Column(LargeBinary, nullable=True)  # serialized float32 vector

    bookmarks = relationship("Bookmark", back_populates="post", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_posts_source_external_id"),
        Index("ix_posts_posted_at", "posted_at"),
        Index("ix_posts_relevance_score", "relevance_score"),
        Index("ix_posts_is_relevant", "is_relevant"),
        Index("ix_posts_source", "source"),
        Index("ix_posts_url", "url"),
        Index("ix_posts_topic_group", "topic_group"),
    )


class Report(Base):
    __tablename__ = "reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    generated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    content = Column(Text, nullable=False)       # Markdown zh-TW report
    post_count = Column(Integer, nullable=False)
    model_used = Column(String, nullable=False)


class Bookmark(Base):
    __tablename__ = "bookmarks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    article_id = Column(Integer, ForeignKey("posts.id", ondelete="CASCADE"), nullable=False)
    note = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    post = relationship("Post", back_populates="bookmarks")

    __table_args__ = (
        Index("ix_bookmarks_article_id", "article_id"),
    )


class SystemState(Base):
    __tablename__ = "system_state"

    key = Column(String, primary_key=True)
    value = Column(Text, nullable=True)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
