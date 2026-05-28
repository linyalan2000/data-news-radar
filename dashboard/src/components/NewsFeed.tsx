"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { fetchNews, type Post, type NewsQueryParams } from "@/lib/api";
import { PostCard } from "./PostCard";
import { SearchBox } from "./SearchBox";

interface Props {
  pollIntervalMs?: number;
  filters?: NewsQueryParams;
}

function formatDateLabel(iso: string): string {
  // iso is always YYYY-MM-DD (local date) — treat as UTC midnight for stable comparison
  const d = new Date(iso + "T00:00:00Z");
  const month = d.getMonth() + 1;
  const day = d.getDate();
  const today = new Date();
  if (d.getFullYear() === today.getFullYear() && month === today.getMonth() + 1 && day === today.getDate()) {
    return "今天";
  }
  const yesterday = new Date(today);
  yesterday.setDate(yesterday.getDate() - 1);
  if (d.getFullYear() === yesterday.getFullYear() && month === yesterday.getMonth() + 1 && day === yesterday.getDate()) {
    return "昨天";
  }
  if (d.getFullYear() === today.getFullYear()) {
    return `${month}月${day}日`;
  }
  return `${d.getFullYear()}年${month}月${day}日`;
}

export function NewsFeed({ pollIntervalMs = 5 * 60 * 1000, filters = {} }: Props) {
  const [posts, setPosts] = useState<Post[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [hasBanner, setHasBanner] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const latestDateRef = useRef<string | null>(null);

  const activeFilters: NewsQueryParams = {
    ...filters,
    ...(searchQuery ? { q: searchQuery } : {}),
  };

  const load = useCallback(async (p: number, params: NewsQueryParams) => {
    setLoading(true);
    try {
      const { page: _p, per_page: _pp, ...rest } = params;
      const data = await fetchNews({ page: p, per_page: 50, ...rest });
      if (p === 1) {
        setPosts(data.items);
      } else {
        setPosts((prev) => [...prev, ...data.items]);
      }
      setTotal(data.total);
      if (data.items.length > 0) {
        const newest = data.items.reduce((a, b) => (a.posted_at > b.posted_at ? a : b));
        if (!latestDateRef.current || newest.posted_at > latestDateRef.current) {
          latestDateRef.current = newest.posted_at;
        }
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    setPage(1);
    setHasBanner(false);
    load(1, activeFilters);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [load, JSON.stringify(activeFilters)]);

  useEffect(() => {
    const timer = setInterval(async () => {
      const since = latestDateRef.current;
      if (!since) return;
      try {
        const data = await fetchNews({ ...activeFilters, since, per_page: 1, page: 1 });
        if (data.total > 0) {
          setHasBanner(true);
        }
      } catch {} // eslint-disable-line no-empty
    }, pollIntervalMs);
    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pollIntervalMs, JSON.stringify(activeFilters)]);

  const handleRefresh = () => {
    setHasBanner(false);
    setPage(1);
    load(1, activeFilters);
  };

  const handleLoadMore = () => {
    const next = page + 1;
    setPage(next);
    load(next, activeFilters);
  };

  const hasMore = posts.length < total;

  function localDateKey(iso: string): string {
    const d = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : iso + "Z");
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  }

  // 全局折叠：跨日期的同 topic_group 也折叠
  const groupMap = new Map<string, { primary: Post; related: Post[] }>();
  const noGroup: Post[] = [];

  for (const p of posts) {
    if (!p.topic_group) {
      noGroup.push(p);
      continue;
    }
    const existing = groupMap.get(p.topic_group);
    if (existing) {
      // 同一来源+同一标题的不当作关联（同文章重复抓取）
      if (p.source === existing.primary.source && p.title === existing.primary.title) {
        continue;
      }
      const ps = existing.primary.relevance_score ?? 0;
      const ts = p.relevance_score ?? 0;
      if (ts > ps || (ts === ps && p.posted_at > existing.primary.posted_at)) {
        existing.related.push(existing.primary);
        existing.primary = p;
      } else {
        existing.related.push(p);
      }
    } else {
      groupMap.set(p.topic_group, { primary: p, related: [] });
    }
  }

  // 合并所有行，按发布日期排序
  const groupedRows = Array.from(groupMap.values()).map((r) => ({
    ...r,
    dateKey: localDateKey(r.primary.posted_at),
  }));
  const allRows: { primary: Post; related: Post[]; dateKey: string }[] = [
    ...groupedRows,
    ...noGroup.map((p) => ({ primary: p, related: [], dateKey: localDateKey(p.posted_at) })),
  ].sort((a, b) => b.primary.posted_at.localeCompare(a.primary.posted_at));

  // 按日期分组用于日期标题
  const GROUPS: { date: string; rows: { primary: Post; related: Post[] }[] }[] = [];
  for (const row of allRows) {
    let g = GROUPS.find((g) => g.date === row.dateKey);
    if (!g) {
      g = { date: row.dateKey, rows: [] };
      GROUPS.push(g);
    }
    g.rows.push({ primary: row.primary, related: row.related });
  }

  return (
    <div>
      <SearchBox onSearch={setSearchQuery} />

      {hasBanner && (
        <button
          onClick={handleRefresh}
          className="w-full mb-4 py-2 bg-blue-50 border border-blue-200 rounded text-sm text-blue-700 hover:bg-blue-100 transition-colors"
        >
          New posts available — click to refresh
        </button>
      )}

      {loading && posts.length === 0 ? (
        <div className="space-y-3 mt-4">
          {[...Array(5)].map((_, i) => (
            <div key={i} className="h-24 bg-white rounded-lg animate-pulse" />
          ))}
        </div>
      ) : posts.length === 0 ? (
        <p className="text-gray-400 text-center py-12 text-sm">暂无内容</p>
      ) : (
        <div className="space-y-6">
          {GROUPS.map((g) => (
            <section key={g.date}>
              <div className="sticky top-0 z-10 pb-3 pt-1">
                <span className="text-xs font-semibold text-gray-400 uppercase tracking-wider">
                  {formatDateLabel(g.date)}
                </span>
              </div>
              <div className="space-y-3">
                {g.rows.map((row) => (
                  <PostCard key={row.primary.id} post={row.primary} relatedPosts={row.related} />
                ))}
              </div>
            </section>
          ))}
        </div>
      )}

      {hasMore && (
        <button
          onClick={handleLoadMore}
          disabled={loading}
          className="mt-6 w-full py-3 bg-white border border-gray-200 rounded-lg text-sm text-gray-500 hover:text-gray-700 hover:border-gray-300 transition-colors"
        >
          {loading ? "加载中…" : "加载更多"}
        </button>
      )}
    </div>
  );
}
