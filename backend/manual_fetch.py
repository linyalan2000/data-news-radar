import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

from app.config import settings
from app.store.news_store import NewsStore
from app.fetcher.wechat_fetcher import WeChatFetcher
from app.fetcher.gov_fetcher import GovFetcher
from app.fetcher.bidding_fetcher import BiddingFetcher
from app.fetcher.cls_fetcher import ClsFetcher
from app.fetcher.multi_source_fetcher import MultiSourceFetcher
from app.scorer.relevance_scorer import RelevanceScorer
from app.pipeline.fetch_pipeline import FetchPipeline
from app.summarizer.minimax_client import MinimaxClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

engine = create_engine(settings.database_url, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)
db = SessionLocal()

try:
    store = NewsStore(session=db)

    wechat = WeChatFetcher(
        accounts=settings.wechat_accounts_list,
        fetch_limit=settings.wechat_fetch_limit,
        news_store=store,
    )
    gov = GovFetcher(fetch_limit=80, news_store=store) if settings.feature_gov_fetcher else None
    bidding = None
    if settings.FEATURES.get("bidding_fetcher"):
        from app.fetcher.bidding_fetcher import BiddingFetcher
        bidding = BiddingFetcher(fetch_limit=60, news_store=store)

    cls = None
    if settings.FEATURES.get("cls_fetcher"):
        cls = ClsFetcher(
            keywords=settings.cls_keywords_list,
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

    from app.fetcher.hn_fetcher import HackerNewsFetcher
    hn = HackerNewsFetcher(keywords=settings.hn_keywords_list, fetch_limit=settings.hn_fetch_limit, news_store=store)
    from app.fetcher.github_fetcher import GitHubFetcher
    github = GitHubFetcher(keywords=settings.github_keywords_list, monitored_repos=settings.github_monitored_repos_list, fetch_limit=settings.github_fetch_limit, github_token=settings.github_token, news_store=store)

    fetcher = MultiSourceFetcher(hn=hn, reddit=None, github=None, rss=None, gov=gov, wechat=wechat, bidding=bidding, cls=cls, aihot=aihot)

    scorer = RelevanceScorer(
        news_store=store,
        keywords_config_path=settings.keywords_config_path,
        threshold=settings.relevance_threshold,
    )

    summarizer = None
    if settings.minimax_api_key:
        summarizer = MinimaxClient(api_key=settings.minimax_api_key, model=settings.minimax_model)

    pipeline = FetchPipeline(news_store=store, fetcher=fetcher, scorer=scorer, summarizer=summarizer)
    result = pipeline.run()
    print(f"\n✅ fetched={result['fetched']}, scored={result['scored']}, stored={result['stored']}, summarized={result.get('summarized', 0)}")
except Exception as e:
    db.rollback()
    print(f"\n❌ {e}")
    raise
finally:
    db.close()
