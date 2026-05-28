"""GroqClient: wraps Groq SDK for per-post zh-TW summarization."""
from __future__ import annotations

import logging
import time

from groq import Groq, RateLimitError

logger = logging.getLogger(__name__)

# Source-aware prompts: Reddit discussions need different treatment than GitHub repos
_PROMPT_REDDIT = """\
以下是一篇 Reddit 讨论贴文，请用简体中文生成技术摘要（100-150字）。

摘要必须涵盖三个方面：
1. 作者遇到的具体问题或分享的核心内容（一句话，说清楚场景）
2. 作者采用的具体技术方法（说出方法名称或步骤，不要泛称"AI 方案"）
3. 为什么值得工程师点进去看（找出让人意外或特别实用的点）

禁止使用的结尾："可以帮助开发者..."、"具有重要意义"、"展示了...多样性"

内容：
{content}

请直接输出摘要，不需要标题或额外说明。"""

_PROMPT_GITHUB = """\
以下是一个 GitHub 项目描述，请用简体中文生成技术摘要（80-120字）。

摘要必须涵盖：
1. 这个工具解决的核心问题（说出具体痛点，不是泛称"AI 应用程序问题"）
2. 和现有方案不同的设计决策（说出技术差异）
3. 适合什么场景使用（一句话）

禁止使用的结尾："可以帮助开发者..."、"具有重要意义"

内容：
{content}

请直接输出摘要，不需要标题或额外说明。"""

_PROMPT_DEFAULT = """\
以下是一篇长文资讯，请根据文章标题和正文提取与"数据要素"或"人工智能/AI"相关的内容，用简体中文生成技术摘要（80-120字）。

文章标题：{title}

正文：
{content}

要求：
1. 以标题为最优先判断依据——标题提到相关主题则文章必然相关
2. 只提取涉及数据要素、数据流通、数据交易、算力、AI模型、AI芯片、AI应用等方向的内容
3. 如果正文后半段包含广告、课程推荐等无关内容，忽略它们，以标题为判断基准
4. 如果文章不涉及上述主题，输出"不相关"
5. 摘要须说明具体的技术要点（方法、数字、设计决策）
6. 禁止使用英文单词，公司名、产品名、技术术语等也请使用中文表述。例如用"人工智能"而非"AI"，用"图形处理器"而非"GPU"
7. 禁止使用结尾："可以帮助开发者..."、"具有重要意义"

请直接输出摘要或"不相关"，不需要标题或额外说明。"""

_CONTENT_LIMIT = 1500  # increased from 500 — Reddit posts can be 2000 chars
_FALLBACK_LEN = 50


def _build_prompt(source: str, content: str, title: str = "") -> str:
    if source == "reddit":
        return _PROMPT_REDDIT.format(content=content)
    if source == "github":
        return _PROMPT_GITHUB.format(content=content)
    return _PROMPT_DEFAULT.format(title=title, content=content)


class GroqClient:
    def __init__(self, api_key: str, model: str = "llama-3.3-70b-versatile") -> None:
        self._client = Groq(api_key=api_key)
        self._model = model

    def summarize_post(self, post) -> str:
        """Return zh-TW summary with technical insight. Retries once on 429; falls back to excerpt."""
        content = (getattr(post, "content", None) or "")[:_CONTENT_LIMIT]
        source = getattr(post, "source", "unknown")
        title = getattr(post, "title", None) or getattr(post, "content", "")[:80]
        prompt = _build_prompt(source, content, title=title)

        for attempt in range(2):
            try:
                resp = self._client.chat.completions.create(
                    model=self._model,
                    messages=[
                        {"role": "system", "content": "只输出摘要本身，不要包含任何思考过程、分析步骤或英文说明。"},
                        {"role": "user", "content": prompt},
                    ],
                    max_tokens=400,
                )
                return resp.choices[0].message.content.strip()
            except RateLimitError as exc:
                if attempt == 0:
                    logger.warning("Groq 429 rate limit — waiting 60s before retry")
                    time.sleep(60)
                    continue
                logger.warning("Groq summarize_post failed (attempt %d): %s", attempt + 1, exc)
                break
            except Exception as exc:
                logger.warning("Groq summarize_post failed (attempt %d): %s", attempt + 1, exc)
                break

        fallback = (getattr(post, "content", None) or "")[:_FALLBACK_LEN]
        return fallback + "…" if fallback else ""
