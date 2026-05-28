"""One-off script: fetch only gov sources (国家数据局 + 各省数据局) and score/store."""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("fetch_gov_now")

from app.config import settings
from app.store.news_store import NewsStore
from app.fetcher.gov_fetcher import GovFetcher
from app.fetcher.bidding_fetcher import BiddingFetcher
from app.scorer.relevance_scorer import RelevanceScorer
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

engine = create_engine(settings.database_url, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)
db = SessionLocal()

try:
    store = NewsStore(session=db)

    logger.info("Starting GovFetcher...")
    gov = GovFetcher(fetch_limit=80, news_store=store)
    gov_posts = gov.fetch()
    logger.info("GovFetcher returned %d posts", len(gov_posts))

    bidding_posts = []
    if settings.FEATURES.get("bidding_fetcher"):
        logger.info("Starting BiddingFetcher...")
        bidding = BiddingFetcher(fetch_limit=60, news_store=store)
        bidding_posts = bidding.fetch()
        logger.info("BiddingFetcher returned %d posts", len(bidding_posts))

    all_posts = gov_posts + bidding_posts

    if not all_posts:
        logger.warning("No posts fetched from any gov source!")
        db.rollback()
        sys.exit(0)

    import dataclasses
    logger.info("Scoring %d posts...", len(all_posts))
    scorer = RelevanceScorer(
        news_store=store,
        keywords_config_path=settings.keywords_config_path,
        threshold=settings.relevance_threshold,
    )
    scored = 0
    for post in all_posts:
        post_dict = dataclasses.asdict(post)
        scores = scorer.score_post(post_dict)
        for k, v in scores.items():
            setattr(post, k, v)
        scored += 1
    logger.info("Scored %d posts", scored)

    logger.info("Storing posts...")
    stored = 0
    for post in all_posts:
        store.upsert_post(dataclasses.asdict(post))
        stored += 1

    db.commit()
    logger.info("✅ Done! Fetched=%d, Scored=%d, Stored=%d", len(all_posts), scored, stored)

except Exception as e:
    db.rollback()
    logger.error("❌ %s", e)
    raise
finally:
    db.close()
