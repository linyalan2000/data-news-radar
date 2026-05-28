"use client";
import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import {
  fetchReports,
  fetchReportById,
  triggerDigest,
  type Report,
  type ReportListItem,
} from "@/lib/api";

const CATEGORIES = [
  { key: "all",         label: "全部",       match: null },
  { key: "policy",      label: "📋 政策法规", match: "政策法规" },
  { key: "elements",    label: "💎 数据要素", match: "数据要素" },
  { key: "ai",          label: "🤖 人工智能",  match: "人工智能" },
  { key: "digital",     label: "🌐 数智化",   match: "数智化" },
  { key: "fujian",      label: "📍 福建本地", match: "福建本地" },
];

/** Extract the content of one ## section by matching a keyword in the header. */
function filterSection(content: string, match: string | null): string {
  if (!match) return content;
  const lines = content.split("\n");
  const result: string[] = [];
  let collecting = false;
  for (const line of lines) {
    if (line.startsWith("## ")) {
      collecting = line.includes(match);
    }
    if (collecting) result.push(line);
  }
  return result.join("\n");
}

function formatDate(iso: string) {
  return new Date(iso.endsWith("Z") || iso.includes("+") ? iso : iso + "Z").toLocaleDateString("zh-TW", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
}

/** Keep only the latest report per calendar date (dedup by date string). */
function deduplicateByDate(reports: ReportListItem[]): ReportListItem[] {
  const seen = new Set<string>();
  return reports.filter((r) => {
    const dateKey = new Date(r.generated_at).toLocaleDateString("zh-TW");
    if (seen.has(dateKey)) return false;
    seen.add(dateKey);
    return true;
  });
}

type PageState =
  | { status: "loading" }
  | { status: "ok"; reports: ReportListItem[]; report: Report }
  | { status: "empty" }
  | { status: "error"; message: string };

export default function ReportPage() {
  const [state, setState] = useState<PageState>({ status: "loading" });
  const [activeCategory, setActiveCategory] = useState("all");
  const [generating, setGenerating] = useState(false);
  const [loadingId, setLoadingId] = useState<number | null>(null);

  const loadReports = () => {
    setState({ status: "loading" });
    fetchReports()
      .then(async (reports) => {
        if (reports.length === 0) {
          setState({ status: "empty" });
          return;
        }
        const dedupedReports = deduplicateByDate(reports);
        const report = await fetchReportById(dedupedReports[0].id);
        setState({ status: "ok", reports: dedupedReports, report });
      })
      .catch((e: Error) => setState({ status: "error", message: e.message }));
  };

  useEffect(() => {
    loadReports();
  }, []);

  const selectReport = async (id: number) => {
    if (state.status !== "ok") return;
    setLoadingId(id);
    setActiveCategory("all");
    try {
      const report = await fetchReportById(id);
      setState({ ...state, report });
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Unknown error";
      setState({ status: "error", message: msg });
    } finally {
      setLoadingId(null);
    }
  };

  const handleGenerate = async () => {
    setGenerating(true);
    try {
      await triggerDigest();
      await new Promise((r) => setTimeout(r, 2000));
      loadReports();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Unknown error";
      setState({ status: "error", message: msg });
    } finally {
      setGenerating(false);
    }
  };

  const activeCat = CATEGORIES.find((c) => c.key === activeCategory) ?? CATEGORIES[0];
  const visibleContent =
    state.status === "ok"
      ? filterSection(state.report.content, activeCat.match)
      : "";

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-base font-semibold text-gray-900">数据日报</h2>
        <button
          onClick={handleGenerate}
          disabled={generating}
          className="text-xs px-3 py-1.5 rounded bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50"
        >
          {generating ? "生成中…" : "重新生成"}
        </button>
      </div>

      {state.status === "loading" && (
        <p className="text-sm text-gray-500">載入中…</p>
      )}

      {state.status === "error" && (
        <div className="bg-red-50 border border-red-200 rounded p-3 text-sm text-red-700">
          {state.message}
        </div>
      )}

      {state.status === "empty" && (
        <div className="border border-dashed border-gray-300 rounded-lg p-8 text-center space-y-3">
          <p className="text-gray-500 text-sm">尚未生成任何報告</p>
          <p className="text-gray-400 text-xs">
            請先設定{" "}
            <code className="bg-gray-100 px-1 rounded">GROQ_API_KEY</code>，
            再點「重新生成」觸發 digest。
          </p>
        </div>
      )}

      {state.status === "ok" && (
        <>
          {/* Date pills */}
          <div className="flex flex-wrap gap-2">
            {state.reports.map((r) => (
              <button
                key={r.id}
                onClick={() => selectReport(r.id)}
                disabled={loadingId === r.id}
                className={`text-xs px-3 py-1 rounded-full border transition-colors ${
                  r.id === state.report.id
                    ? "bg-gray-900 text-white border-gray-900"
                    : "bg-white text-gray-600 border-gray-300 hover:border-gray-500"
                }`}
              >
                {loadingId === r.id ? "載入中…" : formatDate(r.generated_at)}
              </button>
            ))}
          </div>

          {/* Category tabs */}
          <div className="flex flex-wrap gap-1 border-b border-gray-200 pb-2">
            {CATEGORIES.map((cat) => (
              <button
                key={cat.key}
                onClick={() => setActiveCategory(cat.key)}
                className={`text-xs px-3 py-1.5 rounded-t transition-colors ${
                  activeCategory === cat.key
                    ? "bg-white border border-b-white border-gray-200 font-semibold text-gray-900 -mb-px"
                    : "text-gray-500 hover:text-gray-800"
                }`}
              >
                {cat.label}
              </button>
            ))}
          </div>

          {/* Report meta */}
          <div className="flex gap-3 text-xs text-gray-400">
            <span>
              生成時間：
              {new Date(state.report.generated_at).toLocaleString("zh-TW")}
            </span>
            <span>·</span>
            <span>{state.report.post_count} 篇文章</span>
            <span>·</span>
            <span>{state.report.model_used}</span>
          </div>

          {/* Report content */}
          <article className="prose prose-sm max-w-none bg-white border border-gray-200 rounded-lg p-6">
            <ReactMarkdown>{visibleContent}</ReactMarkdown>
          </article>
        </>
      )}
    </div>
  );
}
