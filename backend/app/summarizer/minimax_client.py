"""MinimaxClient: wraps OpenAI-compatible MiniMax API for per-post summarization."""
from __future__ import annotations

import logging
import re
import time

from openai import OpenAI, RateLimitError

logger = logging.getLogger(__name__)

_FALLBACK_LEN = 50
_CONTENT_LIMIT = 1500
_JUDGE_CONTENT_LIMIT = 800


def _build_prompt(source: str, content: str, title: str = "") -> str:
    """Return source-aware summarization prompt. Imported from groq_client for DRY."""
    from app.summarizer.groq_client import _build_prompt as _bp
    return _bp(source, content, title=title)


class MinimaxClient:
    def __init__(self, api_key: str, model: str = "MiniMax-M2.7") -> None:
        self._client = OpenAI(
            api_key=api_key,
            base_url="https://api.minimax.chat/v1",
        )
        self._model = model

    @staticmethod
    def _clean_summary(text: str) -> str:
        """Remove MiniMax's thinking preamble from the output.

        MiniMax may wrap reasoning inside <think></think> tags, or
        start the response with analysis before the actual summary.
        We extract the last Chinese-heavy paragraph.
        """
        # Strip think tags, then find last paragraph with >50% Chinese chars
        clean = re.sub(r'</?think>', '', text).strip()
        paragraphs = [p.strip() for p in clean.split("\n\n") if p.strip()]
        for para in reversed(paragraphs):
            cn = len(re.findall(r'[\u4e00-\u9fff]', para))
            if cn > 0 and cn / max(len(para), 1) > 0.3:
                return para
        return paragraphs[-1] if paragraphs else clean[:100]

    @staticmethod
    def _validate_summary(text: str) -> bool:
        """Check if the generated summary looks valid.

        Returns False for common failure patterns: character-by-character
        annotation, English-dominated output, or unrecognizable garbage.
        """
        if not text or text == "不相关":
            return True
        if len(text) < 15:
            return False
        if re.search(r'"[^"]+"\d+\s', text):
            return False
        eng = len(re.findall(r'[a-zA-Z]', text))
        if eng / len(text) > 0.5:
            return False
        return True

    @staticmethod
    def _parse_judgment(text: str) -> tuple[bool, str]:
        """Extract is_relevant from MiniMax's verbose output by scanning last lines.

        MiniMax typically outputs reasoning followed by a standalone 是/否 on the
        final line.  We scan bottom-up through non-empty lines and return the
        first unambiguous signal.
        """
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        for line in reversed(lines):
            if line == "是":
                return True, text
            if line in ("否", "不"):
                return False, text
        tail = text[-50:]
        if "是" in tail:
            return True, text
        if "否" in tail or "不" in tail:
            return False, text
        return False, text

    def judge_post(self, post) -> tuple[bool, str]:
        content = (getattr(post, "content", None) or "")[:_JUDGE_CONTENT_LIMIT]
        prompt = f"判断下面内容是否与AI/数据行业相关，只回复\"是\"或\"否\"：\n\n{content}"

        for attempt in range(2):
            try:
                resp = self._client.chat.completions.create(
                    model=self._model,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=200,
                )
                text = resp.choices[0].message.content.strip()
                text = re.sub(r'</?think>', '', text).strip()
                return self._parse_judgment(text)

            except RateLimitError as exc:
                if attempt == 0:
                    logger.warning("MiniMax 429 rate limit — waiting 60s before retry")
                    time.sleep(60)
                    continue
                logger.warning("MiniMax judge_post failed (attempt %d): %s", attempt + 1, exc)
                break
            except Exception as exc:
                logger.warning("MiniMax judge_post failed (attempt %d): %s", attempt + 1, exc)
                break

        return False, "judge call failed"

    def summarize_post(self, post, allow_irrelevant: bool = True) -> str:
        """Return zh-CN summary with technical insight.

        When allow_irrelevant=False (CLS), the summarizer never returns
        "不相关" — if the LLM says so, it retries without the irrelevant option.
        """
        content = (getattr(post, "content", None) or "")[:_CONTENT_LIMIT]
        source = getattr(post, "source", "unknown")
        title = getattr(post, "title", None) or getattr(post, "content", "")[:80]

        # 无实质内容（只有图片/链接），跳过摘要
        cn_chars = len(re.findall(r'[\u4e00-\u9fff]', content))
        if cn_chars < 30:
            logger.info("Content too short (%d Chinese chars), skipping summary", cn_chars)
            return ""

        prompt = _build_prompt(source, content, title=title)

        best_text = ""
        for attempt in range(3):
            try:
                resp = self._client.chat.completions.create(
                    model=self._model,
                    messages=[
                        {"role": "system", "content": "不要使用<think>标签，不要展示思考过程，直接输出摘要。只使用简体中文，禁止任何英文单词。"},
                        {"role": "user", "content": prompt},
                    ],
                    max_tokens=800,
                )
                text = resp.choices[0].message.content.strip()
                text = re.sub(r'</?think>', '', text).strip()
                text = self._clean_summary(text)
                if not best_text or len(text) > len(best_text):
                    best_text = text
                if self._validate_summary(text):
                    if any(kw in text.lower() for kw in ("学制", "学时", "学费", "报名", "研修班", "培训费", "结业证", "授课")):
                        best_text = "不相关"
                        continue
                    if text.strip() == "不相关":
                        if allow_irrelevant:
                            t = title.lower()
                            if any(kw in t for kw in ("报名", "研修班", "课程", "培训", "学费", "招生", "热线", "咨询")):
                                continue
                            judge = self._client.chat.completions.create(
                                model=self._model,
                                messages=[{"role": "user", "content": f"标题与数据要素/AI相关吗？只回答「相关」或「不相关」。\n\n标题：{t[:80]}"}],
                                max_tokens=50, timeout=15,
                            )
                            jt = re.sub(r'</?think>', '', judge.choices[0].message.content.strip()).strip()
                            if "相关" not in jt:
                                continue
                        # allow_irrelevant=False or title judge says 相关 → retry without the option
                        logger.info("MiniMax returned 不相关 — force-retrying for CLS")
                        prompt_no_opt = prompt.replace(
                            '如果文章不涉及上述主题，输出"不相关"',
                            ""
                        ).replace(
                            '请直接输出摘要或"不相关"，不需要标题或额外说明。',
                            "请直接输出摘要，不需要标题或额外说明。"
                        )
                        retry_resp = self._client.chat.completions.create(
                            model=self._model,
                            messages=[
                                {"role": "system", "content": "不要使用<think>标签，不要展示思考过程，直接输出摘要。只使用简体中文，禁止任何英文单词。"},
                                {"role": "user", "content": prompt_no_opt},
                            ],
                            max_tokens=800, timeout=30,
                        )
                        retry_text = retry_resp.choices[0].message.content.strip()
                        retry_text = re.sub(r'</?think>', '', retry_text).strip()
                        retry_text = self._clean_summary(retry_text)
                        if self._validate_summary(retry_text):
                            return retry_text
                        if not allow_irrelevant and len(retry_text) > len(best_text):
                            best_text = retry_text
                        continue
                    return text
            except RateLimitError as exc:
                if attempt == 0:
                    logger.warning("MiniMax 429 rate limit — waiting 60s before retry")
                    time.sleep(60)
                    continue
                logger.warning("MiniMax summarize_post failed (attempt %d): %s", attempt + 1, exc)
                break
            except Exception as exc:
                logger.warning("MiniMax summarize_post failed (attempt %d): %s", attempt + 1, exc)
                break

        # Return best attempt (even if validation didn't pass)
        if best_text and len(best_text) >= 15 and not best_text.startswith("【"):
            return best_text
        # No valid summary → return empty so caller stores NULL (frontend shows digest)
        return ""
