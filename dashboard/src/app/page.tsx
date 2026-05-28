"use client";
import { useState } from "react";
import { NewsFeed } from "@/components/NewsFeed";
import { FilterBar } from "@/components/FilterBar";
import { apiFetch } from "@/lib/api";
import type { NewsQueryParams } from "@/lib/api";

export default function Home() {
  const [filters, setFilters] = useState<NewsQueryParams>({});
  const [fetching, setFetching] = useState(false);

  const handleFetch = async () => {
    setFetching(true);
    try {
      await apiFetch("/api/fetch/trigger", { method: "POST" });
      setTimeout(() => setFetching(false), 3000);
    } catch {
      setFetching(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold text-gray-900">实时新闻</h2>
          <p className="text-sm text-gray-400 mt-1">关键词匹配的 AI 数据要素相关资讯</p>
        </div>
        <button
          onClick={handleFetch}
          disabled={fetching}
          className="shrink-0 px-4 py-2 rounded-lg bg-[#e94560] text-white text-sm font-medium hover:bg-[#d64059] disabled:opacity-50 transition-colors"
        >
          {fetching ? "抓取中…" : "立即抓取"}
        </button>
      </div>
      <FilterBar onChange={setFilters} />
      <NewsFeed filters={filters} />
    </div>
  );
}
