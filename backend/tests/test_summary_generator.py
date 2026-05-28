"""Tests for SummaryGenerator — mocks GeminiClient."""
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.summarizer.summary_generator import SummaryGenerator


def _make_post(post_id=1, source="hackernews", content="AI agent tool that helps developers build better software fast with machine learning algorithms and natural language processing capabilities for text analysis and knowledge management across multiple domains and use cases including search and retrieval augmentation",
               labels=None, points=None, summary_zh=None,
               url="https://example.com", discussion_url=None, title=None):
    post = MagicMock()
    post.id = post_id
    post.source = source
    post.content = content
    post.labels = labels or ["ai-agent"]
    post.points = points
    post.summary_zh = summary_zh
    post.url = url
    post.discussion_url = discussion_url
    post.title = title
    return post


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.summarize_post.return_value = "AI 代理人新進展"
    return client


@pytest.fixture
def generator(mock_client, news_store):
    return SummaryGenerator(mock_client, news_store)


# ---------------------------------------------------------------------------
# summarize_batch
# ---------------------------------------------------------------------------

def test_summarize_batch_calls_client_for_posts_without_summary(generator, mock_client, news_store, mocker):
    mocker.patch("app.summarizer.summary_generator.time.sleep")
    news_store.upsert_post({
        "source": "hackernews", "external_id": "b1",
        "author_handle": "u",
        "content": "AI agent tool that helps developers build better software fast with machine learning algorithms and natural language processing capabilities for text analysis and knowledge management across multiple domains and use cases",
        "url": "https://example.com",
        "posted_at": datetime(2026, 3, 1, tzinfo=timezone.utc),
    })
    post = news_store.query_posts()[0]
    generator.summarize_batch([post])
    mock_client.summarize_post.assert_called_once_with(post)


def test_summarize_batch_skips_posts_with_existing_summary(generator, mock_client, mocker):
    mocker.patch("app.summarizer.summary_generator.time.sleep")
    post = _make_post(summary_zh="已有摘要")
    generator.summarize_batch([post])
    mock_client.summarize_post.assert_not_called()


def test_summarize_batch_circuit_breaker_stops_after_3_failures(generator, mock_client, news_store, mocker):
    mocker.patch("app.summarizer.summary_generator.time.sleep")
    mock_client.summarize_post.side_effect = Exception("Gemini down")
    posts = [_make_post(post_id=i, summary_zh=None) for i in range(10)]
    generator.summarize_batch(posts)
    # Circuit breaker opens after 3 failures — only 3 calls made
    assert mock_client.summarize_post.call_count == 3


def test_summarize_batch_saves_summary_to_store(generator, mock_client, news_store, mocker):
    mocker.patch("app.summarizer.summary_generator.time.sleep")
    news_store.upsert_post({
        "source": "hackernews", "external_id": "save1",
        "author_handle": "u",
        "content": "AI agent tool that helps developers build better software fast with machine learning algorithms and natural language processing capabilities for text analysis and knowledge management across multiple domains",
        "url": "https://example.com",
        "posted_at": datetime(2026, 3, 1, tzinfo=timezone.utc),
    })
    post = news_store.query_posts()[0]
    generator.summarize_batch([post])
    refreshed = news_store.get_post_by_id(post.id)
    assert refreshed.summary_zh == "AI 代理人新進展"


# ---------------------------------------------------------------------------
# assemble_report
# ---------------------------------------------------------------------------

def test_assemble_report_returns_markdown_string(generator):
    posts = [_make_post(summary_zh="摘要內容")]
    report = generator.assemble_report(posts, "2026-04-03")
    assert "# AI 新聞每日彙整 — 2026-04-03" in report
    assert "摘要內容" in report


def test_assemble_report_groups_by_label(generator):
    posts = [
        _make_post(post_id=1, labels=["ai-agent"], summary_zh="Agent 摘要"),
        _make_post(post_id=2, labels=["ai-model"], summary_zh="Model 摘要"),
    ]
    report = generator.assemble_report(posts, "2026-04-03")
    assert "🤖 AI Agent" in report
    assert "🧠 AI 模型" in report
    agent_pos = report.index("🤖 AI Agent")
    model_pos = report.index("🧠 AI 模型")
    assert agent_pos < model_pos


def test_assemble_report_includes_hn_discussion_link(generator):
    post = _make_post(
        source="hackernews",
        url="https://example.com/article",
        discussion_url="https://news.ycombinator.com/item?id=123",
        summary_zh="摘要",
    )
    report = generator.assemble_report([post], "2026-04-03")
    assert "HN 討論" in report
    assert "https://news.ycombinator.com/item?id=123" in report


def test_assemble_report_no_discussion_link_for_reddit(generator):
    post = _make_post(source="reddit", url="https://reddit.com/r/ML/abc", discussion_url=None, summary_zh="摘要")
    report = generator.assemble_report([post], "2026-04-03")
    assert "HN 討論" not in report


def test_assemble_report_empty_posts_returns_empty_string(generator):
    report = generator.assemble_report([], "2026-04-03")
    assert report == ""


def test_assemble_report_uses_fallback_when_no_summary_zh(generator):
    post = _make_post(content="AI breakthrough announced today in research", summary_zh=None)
    report = generator.assemble_report([post], "2026-04-03")
    assert "AI breakthrough" in report
