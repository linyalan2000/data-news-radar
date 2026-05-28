"use client";
import { useEffect, useState, useCallback, useMemo } from "react";
import { fetchDailyReport, fetchDailyReportDates, apiFetch, type DailyReport, type Post } from "@/lib/api";
import ReactMarkdown from "react-markdown";

type PageState =
  | { status: "loading" }
  | { status: "ok"; data: DailyReport; dates: string[]; currentDate: string }
  | { status: "error"; message: string };

const SOURCE_BADGE: Record<string, { label: string; className: string }> = {
  cls: { label: "财联社", className: "bg-red-100 text-red-700" },
  wechat: { label: "微信", className: "bg-green-100 text-green-700" },
  gov: { label: "官网", className: "bg-blue-100 text-blue-700" },
  bidding: { label: "招标", className: "bg-yellow-100 text-yellow-800" },
};

const LABEL_COLORS: Record<string, string> = {
  "政策法规": "bg-blue-50 text-blue-600",
  "数据要素": "bg-purple-50 text-purple-600",
  "人工智能": "bg-red-50 text-red-600",
  "数智化": "bg-teal-50 text-teal-600",
  "福建本地": "bg-rose-50 text-rose-600",
};

function PostCard({ post }: { post: Post }) {
  const cleaned = post.content;
  let title = post.title || cleaned.slice(0, 80);
  let body = post.summary_zh && post.summary_zh !== "不相关" ? post.summary_zh : "";
  if (!body && cleaned.length >= 15 && !post.summary_zh) {
    body = cleaned.slice(0, 300);
    if (cleaned.length > 300) body += "…";
  }

  const badge = SOURCE_BADGE[post.source] ?? { label: post.source, className: "bg-gray-100 text-gray-600" };

  return (
    <div className="py-4 border-b border-gray-100 last:border-b-0">
      <div className="flex items-center gap-2 mb-1.5 flex-wrap">
        <span className={`text-xs px-2 py-0.5 rounded font-medium ${badge.className}`}>{badge.label}</span>
        <span className="text-xs text-gray-400">@{post.author_handle}</span>
        {post.relevance_score != null && post.relevance_score >= 7 && (
          <span className="text-xs px-2 py-0.5 rounded bg-red-50 text-[#e94560] font-medium">
            {post.relevance_score.toFixed(1)}
          </span>
        )}
      </div>
      <a
        href={post.url}
        target="_blank"
        rel="noopener noreferrer"
        className="text-base font-semibold text-gray-900 hover:text-[#e94560] transition-colors leading-relaxed"
      >
        {title}
      </a>
      {body && (
        <p className="text-sm text-gray-500 mt-1.5 leading-relaxed line-clamp-3">{body}</p>
      )}
      <div className="flex flex-wrap gap-1.5 mt-2">
        {(post.labels || []).filter(l => l !== "other").map(l => (
          <span key={l} className={`text-xs px-2 py-0.5 rounded ${LABEL_COLORS[l] ?? "bg-gray-50 text-gray-500"}`}>
            {l}
          </span>
        ))}
      </div>
    </div>
  );
}

export default function DailyReportPage() {
  const [state, setState] = useState<PageState>({ status: "loading" });
  const [selectedDate, setSelectedDate] = useState("");
  const [regenerating, setRegenerating] = useState(false);

  const handleRegenerate = async () => {
    setRegenerating(true);
    try {
      await apiFetch("/api/daily-report/regenerate", { method: "POST" });
      load(selectedDate);
    } catch {}
    setTimeout(() => setRegenerating(false), 3000);
  };

  const load = useCallback((date: string) => {
    setState({ status: "loading" });
    Promise.all([
      fetchDailyReport(date || undefined),
      fetchDailyReportDates(),
    ]).then(([report, dateData]) => {
      setState({ status: "ok", data: report, dates: dateData.dates, currentDate: report.date });
    }).catch((e: Error) => setState({ status: "error", message: e.message }));
  }, []);

  useEffect(() => { load(selectedDate); }, [selectedDate, load]);

  if (state.status === "loading") {
    return <div className="flex items-center justify-center h-64"><p className="text-gray-400">加载中…</p></div>;
  }
  if (state.status === "error") {
    return <div className="flex items-center justify-center h-64"><p className="text-red-500">加载失败: {state.message}</p></div>;
  }

  const { data, dates } = state;

  // Group dates by year-month
  const monthGroups: Record<string, string[]> = {};
  for (const d of dates) {
    const ym = d.slice(0, 7);
    if (!monthGroups[ym]) monthGroups[ym] = [];
    monthGroups[ym].push(d);
  }

  const sectionColors: Record<string, string> = {
    "国家部署": "border-l-blue-500 bg-blue-50/50",
    "行业动态": "border-l-gray-500 bg-gray-50/50",
    "福建本地": "border-l-rose-500 bg-rose-50/50",
  };
  const sectionHeaders: Record<string, string> = {
    "国家部署": "🏛️ 国家部署",
    "行业动态": "📈 行业动态",
    "福建本地": "📍 福建本地",
  };

  const sectionCount = data.sections.reduce((s, sec) => s + sec.posts.length, 0);
  // 按标签统计
  const hiddenLabels = new Set(["other", "电报", "财联社"]);
  const labelCounts = data.sections.flatMap(sec =>
    sec.posts.flatMap(p => (p.labels || []).filter(l => !hiddenLabels.has(l)))
  ).reduce((acc: Record<string, number>, l: string) => {
    acc[l] = (acc[l] || 0) + 1;
    return acc;
  }, {} as Record<string, number>);
  const topLabels = Object.entries(labelCounts).sort((a, b) => b[1] - a[1]).slice(0, 6);

  const categoryColors: Record<string, { bg: string; text: string }> = {
    "政策法规": { bg: "bg-blue-50", text: "text-blue-600" },
    "数据要素": { bg: "bg-purple-50", text: "text-purple-600" },
    "人工智能": { bg: "bg-red-50", text: "text-red-600" },
    "数智化": { bg: "bg-teal-50", text: "text-teal-600" },
    "福建本地": { bg: "bg-rose-50", text: "text-rose-600" },
  };

  return (
    <div className="flex flex-col lg:flex-row gap-6">
      {/* Left: date sidebar */}
      <aside className="w-full lg:w-48 shrink-0 lg:sticky lg:top-6 lg:self-start">
        <nav className="space-y-1">
          {/* Mobile horizontal scroll */}
          <div className="flex lg:flex-col gap-1 overflow-x-auto pb-2 lg:pb-0">
            {Object.entries(monthGroups).reverse().map(([ym, days]) => (
              <div key={ym} className="flex lg:block gap-1">
                <div className="hidden lg:block text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1 px-2">
                  {ym}
                </div>
                {days.map(d => {
                  const day = parseInt(d.slice(8), 10);
                  const isActive = d === data.date;
                  return (
                    <button
                      key={d}
                      onClick={() => setSelectedDate(d)}
                      className={`whitespace-nowrap lg:w-full text-left px-3 py-2 rounded-lg text-sm transition-all duration-200 ${
                        isActive
                          ? "bg-[#e94560]/10 text-[#e94560] font-medium"
                          : "text-gray-500 hover:bg-gray-50"
                      }`}
                    >
                      <span className="font-medium">{day} 日</span>
                    </button>
                  );
                })}
              </div>
            ))}
          </div>
        </nav>
      </aside>

      {/* Right: content */}
      <div className="flex-1 min-w-0 space-y-6">
        {/* Header */}
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="text-2xl font-bold text-gray-900">数据日报</h2>
            <p className="text-sm text-gray-400 mt-1.5 leading-relaxed">
              每天早上 8:00 自动生成，汇总过去 24 小时与数据要素、人工智能、数智化相关的政策动态、行业资讯与福建本地新闻。
            </p>
            <p className="text-sm text-gray-400 mt-1 flex items-center gap-2">
              <span>{data.date}</span>
              <span>·</span>
              <span>{sectionCount} 篇</span>
            </p>
          </div>
          <button
            onClick={handleRegenerate}
            disabled={regenerating}
            className="shrink-0 px-4 py-2 rounded-lg bg-[#e94560] text-white text-sm font-medium hover:bg-[#d64059] disabled:opacity-50 transition-colors"
          >
            {regenerating ? "生成中…" : "重新生成"}
          </button>
        </div>

        {/* 分类统计卡片 */}
        {topLabels.length > 0 && (
          <div className="flex flex-wrap gap-2 w-full">
            {topLabels.map(([label, count]) => {
              const colors = categoryColors[label] || { bg: "bg-gray-50", text: "text-gray-600" };
              return (
                <div key={label} className="flex-1 min-w-[80px] bg-white rounded-xl border border-gray-100 p-4 text-center">
                  <p className={`text-2xl font-bold ${colors.text}`}>{count}</p>
                  <p className="text-sm text-gray-400 mt-1">{label}</p>
                </div>
              );
            })}
          </div>
        )}

        {data.generated === false && (
          <div className="text-center py-12 text-gray-400">{data.summary}</div>
        )}

        {/* AI Summary */}
        {data.summary && (
          <div className="bg-gradient-to-br from-[#e94560]/5 to-transparent rounded-xl border border-[#e94560]/10 p-5 lg:p-6">
            <h3 className="text-base font-bold text-[#e94560] mb-3 flex items-center gap-2">
              AI 摘要
            </h3>
            <div className="prose prose-base sm:prose-lg max-w-none text-gray-700 leading-relaxed">
              <ReactMarkdown>{data.summary}</ReactMarkdown>
            </div>
          </div>
        )}

        {/* Sections */}
        {data.sections.filter(s => s.posts.length > 0).map((section) => (
          <div key={section.title} className="bg-white rounded-xl border border-gray-100 p-4 lg:p-5 shadow-sm">
            <h3 className="text-lg lg:text-xl font-bold text-gray-800 mb-3 flex items-center gap-2">
              {sectionHeaders[section.title] || section.title}
              <span className="text-base font-normal text-gray-400">({section.posts.length})</span>
            </h3>
            <div className="divide-y divide-gray-100">
              {section.posts.map((post: Post) => (
                <PostCard key={post.id} post={post} />
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
