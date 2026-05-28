# DataHOT 添加数据源指南

## 一、添加微信公众号

1. 编辑 `backend/.env`
2. 找到 `WECHAT_ACCOUNTS=` 这一行，把公众号名加在末尾，逗号分隔
   ```
   WECHAT_ACCOUNTS=数据要素社,中国政府网,数字经济小喇叭,新公众号名
   ```
3. 重启后端：`kill 端口号 && cd backend && nohup .venv/bin/python3 -m uvicorn app.main:app --port 8000 --host 0.0.0.0 &`

系统自动通过微信搜索 API 找到该账号的 fakeid，后续每次 fetch 自动拉取近 24h 文章。

## 二、添加政府/资讯网站

1. 编辑 `backend/app/fetcher/gov_fetcher.py`
2. 在 `_SITES` 字典里加一条，格式参考已有站点：

```python
"站点名称": {
    "url": "https://example.com/news/",       # 列表页 URL
    "link_pattern": re.compile(r"/article/"),   # 匹配文章链接的正则
    "domain": "example.com",                   # 域名
    "date_in_url": re.compile(r"(\d{4})(\d{2})(\d{2})"),  # 可选：从 URL 提取日期
}
```

3. 重启后端

## 三、删除数据源

### 停止抓取（不再拉新）
- **微信**: 从 `WECHAT_ACCOUNTS` 删掉名称
- **网站**: 从 `_SITES` 删掉对应条目

### 清除历史数据（可选）
```bash
cd backend && .venv/bin/python3 -c "
import sqlite3
conn = sqlite3.connect('dev.db')
conn.execute(\"DELETE FROM posts WHERE source='wechat' AND author_handle='公众号名'\")
conn.commit()
conn.close()
"
```
