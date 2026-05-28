"""NovitaClient: wraps OpenAI-compatible Novita API for zh-TW summarization."""
from __future__ import annotations

import logging
import time

from openai import OpenAI, RateLimitError

logger = logging.getLogger(__name__)

_FALLBACK_LEN = 50


def _build_prompt(source: str, content: str) -> str:
    from app.summarizer.groq_client import _build_prompt as _bp
    return _bp(source, content)


_CONTENT_LIMIT = 1500


class NovitaClient:
    def __init__(self, api_key: str, model: str = "ring-2.6-1t") -> None:
        self._client = OpenAI(
            api_key=api_key,
            base_url="https://api.novita.ai/v3/openai",
        )
        self._model = model

    def summarize_post(self, post) -> str:
        """Return zh-TW summary with technical insight. Retries once on 429; falls back to excerpt."""
        content = (getattr(post, "content", None) or "")[:_CONTENT_LIMIT]
        source = getattr(post, "source", "unknown")
        prompt = _build_prompt(source, content)

        for attempt in range(2):
            try:
                resp = self._client.chat.completions.create(
                    model=self._model,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=400,
                )
                return resp.choices[0].message.content.strip()
            except RateLimitError as exc:
                if attempt == 0:
                    logger.warning("Novita 429 rate limit — waiting 60s before retry")
                    time.sleep(60)
                    continue
                logger.warning("Novita summarize_post failed (attempt %d): %s", attempt + 1, exc)
                break
            except Exception as exc:
                logger.warning("Novita summarize_post failed (attempt %d): %s", attempt + 1, exc)
                break

        fallback = (getattr(post, "content", None) or "")[:_FALLBACK_LEN]
        return fallback + "…" if fallback else ""
