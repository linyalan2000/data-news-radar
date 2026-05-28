# AI News Radar — Agent 執行手冊

> 這份文件給 Claude Code 或其他 AI agent 使用。
> 說明系統現況、如何執行任務、feature flag 啟用方式、常見操作。
> **優先級高於 README.md**，README 面向人類使用者，本文件面向 agent。

---

## 系統現況（2026-04-12）

### 實作完成

| 模組 | 狀態 | 備註 |
|------|------|------|
| HN / Reddit / GitHub / ArXiv fetcher | ✅ | ArXiv 需 `FEATURE_ARXIV_FETCHER=true` |
| 關鍵字權重評分（keyword weight scoring） | ✅ | 非 TF-IDF，實際公式見下方 |
| SQLite FTS5 全文搜尋 | ✅ | 需 `FEATURE_FTS_SEARCH=true` |
| 每日 briefing（Groq LLM）| ✅ | 需 `GROQ_API_KEY` |
| 週報 briefing | ✅ | 需 `FEATURE_WEEKLY_BRIEFING=true` |
| Highlight scorer（Top 3 精選）| ✅ | 需 `FEATURE_HIGHLIGHT_SCORER=true` |
| 書籤系統 | ✅ | 需 `FEATURE_BOOKMARKS=true` |
| MCP Server（7 tools）| ✅ | 見 MCP 章節 |
| Digest 非同步（202 + job_id）| ✅ | POST 回傳 202，用 GET 查狀態 |
| Email / Webhook 各自獨立 flag | ✅ | `email_sent`, `webhook_sent` 欄位 |
| Crash loop cooldown（30 分鐘）| ✅ | 讀 `system_state.last_digest_at` |
| 語言驗證（中文 / 英文）| ✅ | Unicode block 判斷，失敗自動重試 |
| Embedding pipeline | ✅ | 需 `FEATURE_EMBEDDINGS=true` + 安裝 sentence-transformers |
| Hybrid Search（FTS5 + vector + RRF）| ✅ | 需 `FEATURE_EMBEDDINGS=true` |
| Briefing 語意擴充 | ✅ | 每日 briefing 自動補入 ai-technique 文章 |

### Alembic Migration 版本

| Migration | 內容 |
|-----------|------|
| 001 | Initial schema |
| 002 | Multi-source (source + external_id) |
| 003 | points 欄位 |
| 004 | summary_zh 欄位 |
| 005 | URL index |
| 006 | FTS5 virtual table + triggers |
| 007 | bookmarks table |
| 008 | email_sent + webhook_sent 欄位 |
| 009 | embedding BLOB 欄位 |
| 010 | relevance_note 欄位 |
| 011 | title 欄位 |

現在 `alembic upgrade head` 會跑到 011。

---

## 架構重點

### 評分公式

```
score = min(10, Σ(命中詞 × 權重) + min(votes / 100, 3.0))

high_weight = 3  (ai agent, MCP, tool use, graph memory, ...)
standard_weight = 1  (LLM, GPT, Claude, ...)
threshold = 5.0  (is_relevant=True 條件)
```

**注意**：設計文件中寫的「TF-IDF」是歷史錯誤，實際上沒有 IDF。

### FTS5 workaround

`posts` 表沒有獨立 `title` 欄位。Migration 006 的 workaround：
- `title` → `substr(content, 1, 100)`
- `summary` → `COALESCE(summary_zh, '')`

Migration 011 已加入獨立 `title` 欄位，所有 fetcher 在抓取時自動填入標題。顯示程式碼優先使用 `p.title`，fallback 到 `p.content[:80]`。

### Briefing 流程

```
1. generate_digest()          → 取 top 20 相關未發送文章（keyword score 排序）
2. _semantic_augment()        → 額外加入最多 5 篇語意相關 ai-technique 文章（若 FEATURE_EMBEDDINGS=true）
3. _run_summarization()       → 逐篇生成中文摘要（Groq 優先，Gemini fallback）
4. _run_briefing()            → 4 維度 briefing（語言驗證 + 重試）
5. mark_email/webhook_sent()  → 各 channel 獨立標記
```

### Briefing 4 維度

1. **技術模式與架構** — Agent 設計、記憶管理、多代理協作
2. **實踐技巧與工具用法** — prompt 工程、claude.md、agentic workflow
3. **開源動態** — 工具釋出、框架更新
4. **產業動態** — 模型釋出、公司動向

### Digest API（v3 更新）

```
POST /api/digest/trigger  → 202 Accepted + {"job_id": "...", "status": "queued"}
GET  /api/digest/jobs/{job_id}  → {"job_id": "...", "status": "done", "result": {...}}
```

---

## Feature Flags

所有 feature 預設 **false**（安全上線原則）。在 `.env` 或環境變數中設定：

| 環境變數 | 預設 | 說明 |
|---------|------|------|
| `FEATURE_ARXIV_FETCHER` | false | ArXiv 論文 fetcher（cs.AI/cs.LG/cs.CL） |
| `FEATURE_FTS_SEARCH` | false | SQLite FTS5 全文搜尋（需 migration 006） |
| `FEATURE_WEEKLY_BRIEFING` | false | 每週一 8:00 自動生成週報 |
| `FEATURE_HIGHLIGHT_SCORER` | false | briefing 頂部顯示 Top 3 精選 |
| `FEATURE_BOOKMARKS` | false | 書籤 API（需 migration 007） |
| `FEATURE_EMBEDDINGS` | false | Embedding pipeline + Hybrid Search（需 migration 009 + sentence-transformers） |

### 啟用順序建議

```
# 最基本（不需要額外依賴）
FEATURE_FTS_SEARCH=true
FEATURE_HIGHLIGHT_SCORER=true
FEATURE_BOOKMARKS=true

# 進階（需要 GROQ_API_KEY）
FEATURE_WEEKLY_BRIEFING=true

# 語意搜尋（需要安裝 sentence-transformers，首次啟動會下載模型 ~22MB）
FEATURE_EMBEDDINGS=true
```

---

## Embedding 功能啟用步驟

### 完整啟用流程

```bash
cd backend

# 1. 安裝依賴
pip install -e ".[test]"
# sentence-transformers 和 numpy 已在 pyproject.toml 中

# 2. 在 .env 設定
echo "FEATURE_EMBEDDINGS=true" >> .env

# 3. 跑 migration（如果還沒到 009）
alembic upgrade head

# 4. 補算歷史文章的 embedding
python scripts/backfill_embeddings.py --force

# 5. 啟動 backend（首次會下載並載入模型，約 5–15 秒）
uvicorn app.main:app --reload --port 8000
```

### 確認 embedding 正常運作

```bash
# 查看有多少文章已有 embedding
python -c "
from sqlalchemy import create_engine, text
e = create_engine('sqlite:///./dev.db')
with e.connect() as c:
    total = c.execute(text('SELECT COUNT(*) FROM posts')).scalar()
    with_emb = c.execute(text('SELECT COUNT(*) FROM posts WHERE embedding IS NOT NULL')).scalar()
    print(f'Total: {total}, With embedding: {with_emb}')
"
```

### CPU 負載說明

- 模型大小：~22MB（all-MiniLM-L6-v2）
- 推理時間：50–200ms / 篇（CPU）
- 每次 fetch 最多 100 篇 → 約 5–20 秒額外時間
- 不使用 GPU，不影響遊戲效能（但 fetch 期間有 CPU spike）

### HF Inference API fallback

如果不想在本機跑模型：

```env
FEATURE_EMBEDDINGS=true
HF_API_TOKEN=hf_xxxxx    # 設定後自動改用 HF API，本機不載入模型
```

---

## 如何跑測試

```bash
cd backend

# 全套測試（220 tests，coverage ≥ 80%）
pytest

# 指定模組
pytest tests/test_briefing_generator.py -v
pytest tests/test_embedding_service.py -v
pytest tests/test_digest_notifier.py -v

# 快速跑（不算 coverage）
pytest --no-cov -q
```

---

## MCP Server 工具清單（7 tools）

| Tool | 說明 |
|------|------|
| `search_ai_news(query, days, limit)` | 混合搜尋（FTS5 + 語意）；FEATURE_EMBEDDINGS 關閉時用純 FTS5 |
| `get_daily_report(date)` | 取得指定日期的 briefing MD |
| `get_posts_by_category(category, days, limit)` | 依 label 篩選文章 |
| `get_trending_tools(days, limit)` | 熱門工具排行（比對 known_tools.txt） |
| `get_weekly_summary(week_offset)` | 週報內容 |
| `list_techniques()` | 列出 keywords.yaml 中的所有群組名稱 |
| `get_posts_by_technique(technique, days, limit)` | 語意搜尋特定技術群組；fallback 為 label 過濾 |

---

## 常見操作

### 手動觸發 digest

```bash
# 觸發（返回 job_id）
JOB=$(curl -s -X POST http://localhost:8000/api/digest/trigger \
  -H "X-API-Key: changeme" | python -c "import sys,json; print(json.load(sys.stdin)['job_id'])")

# 查詢狀態
curl -s http://localhost:8000/api/digest/jobs/$JOB -H "X-API-Key: changeme"
```

### 重新生成今天的 briefing

```bash
# 刪除今天的 briefing（讓系統重新生成）
rm briefings/$(date +%Y-%m-%d).md

# Trigger digest
curl -X POST http://localhost:8000/api/digest/trigger -H "X-API-Key: changeme"
```

### 手動 backfill embedding

```bash
cd backend

# 試跑（不實際計算）
python scripts/backfill_embeddings.py --force --dry-run

# 正式跑（所有文章）
python scripts/backfill_embeddings.py --force

# 限制數量（測試用）
python scripts/backfill_embeddings.py --force --limit 50
```

### 查看 DB 狀態

```bash
cd backend
python -c "
from sqlalchemy import create_engine, text
e = create_engine('sqlite:///./dev.db')
with e.connect() as c:
    print('Posts:', c.execute(text('SELECT COUNT(*) FROM posts')).scalar())
    print('Relevant:', c.execute(text('SELECT COUNT(*) FROM posts WHERE is_relevant=1')).scalar())
    print('With embedding:', c.execute(text('SELECT COUNT(*) FROM posts WHERE embedding IS NOT NULL')).scalar())
    print('ai-technique:', c.execute(text(\"SELECT COUNT(*) FROM posts WHERE labels LIKE '%ai-technique%'\")).scalar())
"
```

---

## 重要檔案位置

| 檔案 | 用途 |
|------|------|
| `backend/keywords.yaml` | 關鍵字權重設定（改完重啟生效） |
| `backend/known_tools.txt` | get_trending_tools 用的工具名稱清單 |
| `backend/app/config.py` | 所有環境變數定義和預設值 |
| `backend/app/briefing/briefing_generator.py` | LLM 生成 briefing 的 prompt 和語言驗證邏輯 |
| `backend/app/embeddings/embedding_service.py` | 模型 load、embed、serialize/deserialize |
| `backend/app/embeddings/vector_search.py` | cosine similarity、hybrid search、semantic_augment |
| `backend/mcp_server.py` | 所有 MCP tools 定義 |
| `briefings/` | 每日 briefing MD 輸出目錄 |
| `briefings/weekly/` | 週報 MD 輸出目錄 |
| `strategy/implementation-plan.md` | Phase-by-phase 實作計劃（含 checklist） |

---

## 已知限制與設計決策

1. **FTS5 workaround**：`articles_fts` 的 title 是 `substr(content, 1, 100)`，搜尋品質受限於 content 前 100 字。Migration 011 已加入獨立 `title` 欄位，但 FTS5 尚未重建。
2. **Threshold 未調整**：目前 `relevance_threshold=5.0`，Group 1 完成後觀察再決定是否提高至 7.0。
3. **ArXiv 排除 daily briefing**：ArXiv 文章不進入每日 highlight 和 briefing（太學術）。週報單獨處理。
4. **Digest job 狀態 in-memory**：`/api/digest/jobs/{job_id}` 的狀態存在進程記憶體，重啟後消失。
5. **Vector search 無外部 DB**：用 Python numpy in-memory cosine similarity，適合 <50k posts。超過後需考慮 sqlite-vec 或 pgvector。
6. **sentence-transformers 首次執行**：第一次 `warmup()` 會從 HuggingFace 下載模型，需要網路。之後 cache 在本機。
7. **Groq 語言漂移**：LLM 偶爾輸出越南文等非預期語言。`_validate_language()` 會觸發重試；二次失敗加 `⚠️` 警告 header。

---

## 開發規範

- **每個 Phase 完成後 commit**，再更新 `strategy/implementation-plan.md` 狀態
- **測試覆蓋率**：維持 ≥ 80%（`pytest.ini` 強制）
- **新功能預設 false**：所有新 feature 都透過 `FEATURES` dict 控制，預設關閉
- **不改 threshold**：`relevance_threshold=5.0` 在觀察期結束前不調整
- **Groq 優先**：摘要和 briefing 都是 `GROQ_API_KEY` 優先，Gemini 作 fallback

---

## Agent 行為規範

- **每條回復末尾必須語音播報**：每次任務結束，用 `say -v Tingting "任务完成"` 語音播報，不可遺漏。
- **改完代碼後自審**：每次修改後運行相關測試確認無損，必要時跑 `review-work` 檢查。
- **問題先解釋再動手**：用戶問「為什麼」時，先解釋邏輯，不要直接改代碼。
- **測完摘要要寫回數據庫**：調試或測試 `summarize_post` 後，務必用 `store.update_post_summary(id, summary)` 寫回，否則新摘要只存在於變量中，數據庫未更新。
