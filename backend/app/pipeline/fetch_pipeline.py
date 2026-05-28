"""FetchPipeline: orchestrate fetch → score → upsert → embed cycle."""
from __future__ import annotations

import dataclasses
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class FetchPipeline:
    def __init__(self, news_store, fetcher, scorer, embedding_service=None, summarizer=None) -> None:
        self._store = news_store
        self._fetcher = fetcher
        self._scorer = scorer
        self._embedding_service = embedding_service  # optional; None = embeddings disabled
        self._summarizer = summarizer  # optional; None = per-post summarization disabled

    def run(self) -> dict:
        # 1. Fetch from all sources
        raw_posts = self._fetcher.fetch()
        # Convert dataclasses to dicts if needed
        posts = [
            dataclasses.asdict(p) if dataclasses.is_dataclass(p) else p
            for p in raw_posts
        ]

        fetched_count = len(posts)
        logger.info("Pipeline: fetched %d new posts", fetched_count)

        if not posts:
            logger.info("Pipeline: nothing to score or store")
            return {"fetched": 0, "scored": 0, "stored": 0, "embedded": 0}

        # 2. Score
        scored_posts = []
        for post in posts:
            try:
                scores = self._scorer.score_post(post)
                merged = {**post, **scores}
                fetcher_labels = post.get("labels") or []
                scorer_labels = scores.get("labels") or []
                merged["labels"] = list(dict.fromkeys(fetcher_labels + scorer_labels))
                scored_posts.append(merged)
            except Exception as exc:
                logger.error("Scoring error for post %s: %s", post.get("external_id"), exc)

        logger.info("Pipeline: scored %d posts", len(scored_posts))

        # 3. Upsert
        stored_count = 0
        for post in scored_posts:
            try:
                self._store.upsert_post(post)
                stored_count += 1
            except Exception as exc:
                logger.error("Store error for post %s: %s", post.get("external_id"), exc)

        # 4. Update last fetch timestamp and commit
        self._store.update_last_fetch_at(datetime.now(timezone.utc))
        self._store.commit()
        logger.info("Pipeline: stored %d posts", stored_count)

        # 5. Assign topic groups to newly fetched posts (non-blocking)
        grouped_count = self._assign_topic_groups()

        # 6. Compute embeddings for new posts (non-blocking best-effort)
        embedded_count = 0
        if self._embedding_service is not None:
            embedded_count = self._compute_embeddings()

        # 6. Generate summaries for posts without one (non-blocking best-effort)
        summarized_count = 0
        if self._summarizer is not None:
            summarized_count = self._summarize_posts()

        return {
            "fetched": fetched_count,
            "scored": len(scored_posts),
            "stored": stored_count,
            "grouped": grouped_count,
            "embedded": embedded_count,
            "summarized": summarized_count,
        }

    def _assign_topic_groups(self) -> int:
        """Assign topic_group to any post where it is still NULL.

        Uses the deterministic MD5 hash of the normalized title; posts
        whose normalized titles match byte-for-byte share the same group.
        """
        from app.fetcher.topic_grouping import compute_topic_group

        posts = self._store.get_posts_without_topic_group(limit=200)
        if not posts:
            return 0

        count = 0
        for post in posts:
            title = post.title or post.content[:80]
            group = compute_topic_group(title)
            if group is None:
                continue
            self._store.update_topic_group(post.id, group)
            count += 1

        if count:
            self._store.commit()
            logger.info("Pipeline: assigned topic_group to %d posts", count)

        return count

    def _compute_embeddings(self) -> int:
        """Compute and store embeddings for posts that don't have one yet."""
        from app.embeddings.embedding_service import serialize

        posts_without = self._store.get_posts_without_embedding(limit=100)
        if not posts_without:
            return 0

        count = 0
        for post in posts_without:
            try:
                embedding = self._embedding_service.embed_text_for_post(post)
                self._store.update_post_embedding(post.id, serialize(embedding))
                count += 1
            except Exception as exc:
                logger.warning("Embedding failed for post %d: %s", post.id, exc)

        if count:
            self._store.commit()
            logger.info("Pipeline: computed embeddings for %d posts", count)

        return count

    def _summarize_posts(self) -> int:
        """Generate summaries for all pending posts. No relevance filter."""
        import time

        posts_pending = self._store.get_posts_without_summary(limit=50)
        if not posts_pending:
            return 0

        summarized_count = 0
        too_short_count = 0

        for post in posts_pending:
            content = getattr(post, "content", None) or ""
            if len(content) < 30:
                too_short_count += 1
                continue

            try:
                summary = self._summarizer.summarize_post(post, allow_irrelevant=False)
                if summary:
                    self._store.update_post_summary(post.id, summary)
                    summarized_count += 1
                # else: leave as NULL so next cycle retries
                time.sleep(1.5)
            except Exception as exc:
                logger.warning("Summary failed for post %d: %s", post.id, exc)

            if summarized_count % 10 == 0:
                self._store.commit()

        if summarized_count or too_short_count:
            self._store.commit()
            logger.info(
                "Pipeline: %d posts (%d too-short, %d summarized)",
                summarized_count + too_short_count, too_short_count, summarized_count,
            )

        return summarized_count
