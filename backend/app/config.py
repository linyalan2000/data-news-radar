"""Application configuration loaded from environment variables."""

from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Look for .env in backend/ first, then fall back to project root (../.env)
    model_config = SettingsConfigDict(env_file=["../.env", ".env"], extra="ignore")

    # Database
    database_url: str = "sqlite:///./dev.db"

    # API auth
    api_key: str = "changeme"

    # Hacker News
    hn_keywords: str = "ai agent,LLM,RAG,MCP,multi-agent,AutoGen,LangChain"
    hn_fetch_limit: int = 100

    # Reddit
    reddit_subreddits: str = (
        "MachineLearning,LocalLLaMA,singularity,artificial,ClaudeAI,PromptEngineering"
    )
    reddit_keywords: str = ""
    reddit_fetch_limit: int = 100

    # GitHub
    github_monitored_repos: str = (
        "langchain-ai/langchain,microsoft/autogen,ollama/ollama,ggerganov/llama.cpp"
    )
    github_keywords: str = "ai agent,llm,rag,mcp,agentic"
    github_fetch_limit: int = 30
    github_token: str = ""

    # RSS feeds (comma-separated URLs for generic RSS/Atom feeds)
    rss_feeds: str = ""
    rss_fetch_limit: int = 50

    # WeChat Official Account (mp.weixin.qq.com internal API)
    wechat_accounts: str = ""
    wechat_fetch_limit: int = 30

    # Scheduler
    fetch_interval_minutes: int = 15
    digest_cron: str = "0 8 * * *"
    digest_lookback_hours: int = 48
    catchup_max_days: int = 7

    # Scoring
    relevance_threshold: float = 5.0
    keywords_config_path: Optional[str] = None

    # SMTP
    smtp_host: Optional[str] = None
    smtp_port: int = 587
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None
    digest_email_from: Optional[str] = None
    digest_email_to: Optional[str] = None

    # Webhook
    digest_webhook_url: Optional[str] = None

    # Gemini AI Summarizer (optional — disabled if api key absent)
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"
    summary_post_limit: int = 20

    # Groq AI Summarizer (optional — takes priority over Gemini if both set)
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"

    # Novita AI Summarizer (optional — takes priority over Groq & Gemini if set)
    novita_api_key: str = ""
    novita_model: str = "ring-2.6-1t"

    # MiniMax Summarizer (optional — takes priority over Novita/Groq/Gemini if set)
    minimax_api_key: str = ""
    minimax_model: str = "MiniMax-M2.7"

    # Daily briefing output directory (relative to repo root, or absolute; empty = disabled)
    briefings_output_dir: str = "briefings"

    @property
    def briefings_output_dir_resolved(self) -> Optional[str]:
        """Return an absolute path string for the briefings output directory.

        Relative paths are resolved against the repo root (parent of backend/),
        so the result is CWD-independent regardless of how uvicorn is launched.
        """
        if not self.briefings_output_dir:
            return None
        raw = Path(self.briefings_output_dir)
        if raw.is_absolute():
            return str(raw)
        # This file lives at backend/app/config.py → repo root is 2 levels up
        repo_root = Path(__file__).parent.parent.parent
        return str((repo_root / raw).resolve())

    # ArXiv fetcher
    arxiv_categories: str = "cs.AI,cs.LG,cs.CL"
    arxiv_max_results: int = 50

    # 财联社 fetcher
    cls_keywords: str = "人工智能,数据要素,数智化,数字中国,数字福建,刘烈宏,国家数据局,国家数据发展研究院,高质量数据集"
    cls_fetch_limit: int = 50

    # AIHOT fetcher (aihot.virxact.com)
    aihot_fetch_limit: int = 30

    # v2 Feature Flags — all default False for safe rollout
    feature_arxiv_fetcher: bool = False
    feature_aihot_fetcher: bool = False
    feature_gov_fetcher: bool = False
    feature_fts_search: bool = False
    feature_weekly_briefing: bool = False
    feature_highlight_scorer: bool = False
    feature_bookmarks: bool = False
    feature_embeddings: bool = False
    feature_bidding_fetcher: bool = False
    feature_cls_fetcher: bool = False

    # Embeddings
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    hf_api_token: str = (
        ""  # fallback: HF Inference API when set and feature_embeddings=True
    )

    # Personalization
    user_context: str = ""

    # Highlight scorer weights (JSON string or individual env vars)
    highlight_weight_relevance: float = 0.5
    highlight_weight_source: float = 0.3
    highlight_weight_recency: float = 0.2

    @property
    def highlight_weights(self) -> dict:
        return {
            "relevance": self.highlight_weight_relevance,
            "source": self.highlight_weight_source,
            "recency": self.highlight_weight_recency,
        }

    @property
    def FEATURES(self) -> dict:
        return {
            "arxiv_fetcher": self.feature_arxiv_fetcher,
            "gov_fetcher": self.feature_gov_fetcher,
            "fts_search": self.feature_fts_search,
            "weekly_briefing": self.feature_weekly_briefing,
            "highlight_scorer": self.feature_highlight_scorer,
            "bookmarks": self.feature_bookmarks,
            "embeddings": self.feature_embeddings,
            "bidding_fetcher": self.feature_bidding_fetcher,
            "cls_fetcher": self.feature_cls_fetcher,
            "aihot_fetcher": self.feature_aihot_fetcher,
        }

    @property
    def arxiv_categories_list(self) -> list[str]:
        return [c.strip() for c in self.arxiv_categories.split(",") if c.strip()]

    @property
    def hn_keywords_list(self) -> list[str]:
        return [k.strip() for k in self.hn_keywords.split(",") if k.strip()]

    @property
    def reddit_subreddits_list(self) -> list[str]:
        return [s.strip() for s in self.reddit_subreddits.split(",") if s.strip()]

    @property
    def reddit_keywords_list(self) -> list[str]:
        return [k.strip() for k in self.reddit_keywords.split(",") if k.strip()]

    @property
    def github_monitored_repos_list(self) -> list[str]:
        return [r.strip() for r in self.github_monitored_repos.split(",") if r.strip()]

    @property
    def github_keywords_list(self) -> list[str]:
        return [k.strip() for k in self.github_keywords.split(",") if k.strip()]

    @property
    def rss_feeds_list(self) -> list[str]:
        return [f.strip() for f in self.rss_feeds.split(",") if f.strip()]

    @property
    def wechat_accounts_list(self) -> list[str]:
        return [a.strip() for a in self.wechat_accounts.split(",") if a.strip()]

    @property
    def cls_keywords_list(self) -> list[str]:
        return [k.strip() for k in self.cls_keywords.split(",") if k.strip()]

    @property
    def smtp_config(self) -> Optional[dict]:
        if not all(
            [
                self.smtp_host,
                self.smtp_user,
                self.smtp_password,
                self.digest_email_from,
                self.digest_email_to,
            ]
        ):
            return None
        return {
            "host": self.smtp_host,
            "port": self.smtp_port,
            "user": self.smtp_user,
            "password": self.smtp_password,
            "from": self.digest_email_from,
            "to": self.digest_email_to,
        }


settings = Settings()
