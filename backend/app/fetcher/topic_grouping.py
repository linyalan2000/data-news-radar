"""Topic grouping: assign a deterministic group ID to duplicate/similar news.

Strategy (v1): Normalize the title to a canonical form, then compute an
MD5 hash.  Posts whose normalized titles match byte-for-byte share the
same ``topic_group``.

Normalization pipeline
-----------------------
1. Strip known source prefixes:  ``"焦点访谈 | "``, ``"【快讯】"``, etc.
2. Strip whitespace and common punctuation.
3. Lowercase ASCII letters (Chinese has no case, but English tokens remain).
"""

from __future__ import annotations

import hashlib
import re

# Prefixes to remove from the start of a title before comparison.
# Order matters — longer/more-specific prefixes first.
_STRIP_PREFIXES: list[str] = [
    # CLS telegraph bracket prefix
    r"^【[^】]*】\s*",
    # Common Chinese news prefixes
    r"^焦点访谈\s*[|:：]\s*",
    r"^独家\s*[|:：]?\s*",
    r"^快讯\s*[|:：]?\s*",
    r"^最新\s*[|:：]?\s*",
    r"^早报\s*[|:：]?\s*",
]

# Punctuation to strip (Chinese + ASCII)
_PUNCTUATION_PATTERN = re.compile(r"[\s,，。、；：""''「」『』【】（）()—–/\\·-]")


def _strip_prefixes(text: str) -> str:
    for pat in _STRIP_PREFIXES:
        text = re.sub(pat, "", text)
    return text


def normalize_title(title: str) -> str:
    """Normalize a news title to a canonical comparison key."""
    if not title:
        return ""
    t = title.strip()
    t = _strip_prefixes(t)
    t = _PUNCTUATION_PATTERN.sub("", t)
    t = t.lower()
    return t.strip()


def compute_topic_group(title: str) -> str | None:
    """Return a deterministic topic_group hash (first 16 hex chars of MD5).

    Returns ``None`` when the title is empty or trivial.
    """
    normalized = normalize_title(title)
    if not normalized or len(normalized) < 8:
        return None
    return hashlib.md5(normalized.encode("utf-8")).hexdigest()[:16]
