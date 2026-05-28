"use client";
import { useMemo } from "react";
import type { Post } from "@/lib/api";
import { useSettings } from "@/lib/settings";

interface Props {
  post: Post;
  relatedPosts?: Post[];  // same topic_group, other sources — shown as folded links
}

const SOURCE_BADGE: Record<string, { label: string; className: string }> = {
  hackernews: { label: "HN", className: "bg-orange-100 text-orange-800" },
  reddit: { label: "Reddit", className: "bg-red-100 text-red-700" },
  github: { label: "GitHub", className: "bg-gray-800 text-white" },
  rss: { label: "RSS", className: "bg-green-100 text-green-800" },
  gov: { label: "官网", className: "bg-red-100 text-red-800" },
  wechat: { label: "微信", className: "bg-green-100 text-green-800" },
  bidding: { label: "招标", className: "bg-yellow-100 text-yellow-800" },
};

const LABEL_COLORS: Record<string, string> = {
  "政策法规": "bg-blue-100 text-blue-800",
  "数据要素": "bg-purple-100 text-purple-800",
  "人工智能": "bg-red-100 text-red-800",
  "数智化": "bg-teal-100 text-teal-800",
  "福建本地": "bg-rose-100 text-rose-800",
};

/** Known boilerplate patterns in Chinese source content (WeChat footers, etc.) */
const BOILERPLATE_PATTERNS = [
  /^欢迎关注[^\n]{2,30}$/,
  /^欢迎扫码关注[^\n]{2,30}$/,
  /^长按识别二维码关注[^\n]{2,30}$/,
  /^点击关注[^\n]{2,30}$/,
  /^分享[^\n]*收藏[^\n]*点赞[^\n]*在看/,
  /^阅读原文/,
  /^在看点这里/,
  /^点个[^\n]*在看好吗/,
];

function cleanContent(raw: string): string {
  let text = raw;
  for (const pat of BOILERPLATE_PATTERNS) {
    text = text.replace(pat, "").trim();
  }
  text = text.replace(/\n{3,}/g, "\n\n").trim();
  return text;
}

/** Parse 【title】 pattern used by 财联社 (cls) posts */
function parseClsContent(raw: string): { title: string; digest: string } | null {
  const open = raw.indexOf("【");
  const close = raw.indexOf("】");
  if (open !== -1 && close !== -1 && close > open) {
    const title = raw.slice(open + 1, close).trim();
    const rest = raw.slice(close + 1).trim();
    return { title, digest: rest };
  }
  return null;
}

function parseContent(raw: string): { title: string; digest: string } {
  const idx = raw.indexOf("\n");
  if (idx !== -1) {
    return { title: raw.slice(0, idx).trim(), digest: raw.slice(idx + 1).trim() };
  }
  return { title: raw.length > 120 ? raw.slice(0, 120) + "…" : raw, digest: "" };
}

/** Thinking-preamble markers: if found, extract final clean summary */
const THINKING_MARKERS = [
  "让我分析",
  "让我写一个版本",
  "用户提供的内容",
  "用户明确说",
  "The user asks:",
  "请用简体中文生成技术摘要",
  "AI相关内容",
];

function hasThinkingPreamble(s: string): boolean {
  return THINKING_MARKERS.some((p) => s.includes(p));
}

function extractFinalSummary(s: string): string {
  // Take content after the last "让我写一个版本：" if present
  for (const m of ["让我写一个版本：", "让我写一个版本:"]) {
    const idx = s.lastIndexOf(m);
    if (idx !== -1) {
      const after = s.slice(idx + m.length).trim();
      if (after.length > 30) return after;
    }
  }
  // Otherwise, take the last non-empty paragraph
  const paragraphs = s.split(/\n\n+/).map((p) => p.trim()).filter(Boolean);
  for (let i = paragraphs.length - 1; i >= 0; i--) {
    if (paragraphs[i].length > 30 && /[\u4e00-\u9fff]/.test(paragraphs[i])) {
      return paragraphs[i];
    }
  }
  return s;
}

function normalize(s: string): string {
  return s.replace(/[\s,，。、；：""''（）()—\-]/g, "");
}

function toDate(iso: string): Date {
  // API may return naive or UTC timestamps; normalize to UTC
  return new Date(iso.endsWith("Z") || iso.includes("+") ? iso : iso + "Z");
}

function formatTime(iso: string): string {
  const d = toDate(iso);
  const now = new Date();
  const month = d.getMonth() + 1;
  const day = d.getDate();
  const hours = d.getHours().toString().padStart(2, "0");
  const mins = d.getMinutes().toString().padStart(2, "0");
  if (d.getFullYear() === now.getFullYear() && month === now.getMonth() + 1 && day === now.getDate()) {
    return `今天 ${hours}:${mins}`;
  }
  return `${month}月${day}日 ${hours}:${mins}`;
}

function isRedundantDigest(title: string, digest: string): boolean {
  if (!digest) return true;
  if (digest.length < 15) return true;
  const nt = normalize(title);
  const nd = normalize(digest);
  if (nt === nd) return true;
  // Only redundant if digest has little extra content beyond title
  if (nd.length < nt.length * 1.5) {
    if (nt.includes(nd) || nd.includes(nt)) return true;
  }
  return false;
}

export function PostCard({ post, relatedPosts }: Props) {
  const [settings] = useSettings();

  const badge = SOURCE_BADGE[post.source] ?? {
    label: post.source,
    className: "bg-gray-100 text-gray-700",
  };

  // CLS posts store the full content as title (with 【】brackets),
  // so always parse from content for CLS.
  // For other sources, use post.title when available.
  const cleaned = cleanContent(post.content);
  let title: string;
  let digest: string;
  if (post.source === "cls") {
    const parsed = parseClsContent(cleaned) ?? parseContent(cleaned);
    title = parsed.title;
    digest = parsed.digest;
  } else if (post.title) {
    title = post.title;
    digest = parseContent(cleaned).digest;
  } else {
    const parsed = parseContent(cleaned);
    title = parsed.title;
    digest = parsed.digest;
  }
  const rawSummary = post.summary_zh;
  const isUselessSummary = (s: string | null) =>
    !s || s === "不相关" || /不相关|未涉及|无法生成|本文不涉及/.test(s)
    || (s.length < 60 && s.endsWith("…"));  // truncated excerpt garbage
  const contentLen = post.source === "cls" ? post.content.length : digest.length;
  const useSummary = rawSummary && !isUselessSummary(rawSummary) && !hasThinkingPreamble(rawSummary) && contentLen >= 200;
  const displayText = (useSummary ? rawSummary : digest).replace(/^【[^】]*】\s*/, "");
  const showBody = post.source === "cls"
    ? displayText.length >= 15
    : displayText.length >= 15 && (useSummary || !isRedundantDigest(title, displayText));
  const isHN = post.source === "hackernews";

  const HIDDEN_LABELS = new Set(["other", "电报", "财联社"]);

  const displayLabels = useMemo(() => {
    const labels = [...post.labels].filter((l) => !HIDDEN_LABELS.has(l));
    for (const mapping of settings.labelMappings) {
      if (post.source === mapping.sourceKey && !labels.includes(mapping.categoryKey)) {
        labels.push(mapping.categoryKey);
      }
    }
    return labels;
  }, [post.labels, post.source, settings.labelMappings]);

  return (
    <div className="bg-white rounded-xl border border-gray-100 p-5 hover:shadow-md transition-shadow">
      {/* 顶部：来源 + 时间 + 评分 */}
      <div className="flex items-center gap-2 mb-2 flex-wrap">
        <span
          aria-label={`source ${post.source}`}
          className={`text-sm px-2.5 py-0.5 rounded font-medium ${badge.className}`}
        >
          {badge.label}
        </span>
        <span className="text-sm text-gray-400">@{post.author_handle}</span>
        <span className="text-sm text-gray-400 ml-auto flex items-center gap-1">
          {formatTime(post.posted_at)}
        </span>
        {post.points != null && post.points > 0 && (
          <span className="text-sm px-2.5 py-0.5 rounded bg-yellow-100 text-yellow-800 font-medium">
            ▲ {post.points}
          </span>
        )}
        {post.relevance_score != null && post.relevance_score >= 7 && (
          <span className="text-sm px-2.5 py-0.5 rounded bg-red-50 text-[#e94560] font-medium">
            {post.relevance_score.toFixed(1)}
          </span>
        )}
      </div>

      {/* 标题 */}
      <a
        href={post.url}
        target="_blank"
        rel="noopener noreferrer"
        className="text-lg font-semibold text-gray-900 hover:text-[#e94560] transition-colors leading-relaxed"
      >
        {title}
      </a>

      {/* 正文 */}
      {showBody && (
        <p className="text-base text-gray-500 mt-2 leading-relaxed line-clamp-3">
          {displayText}
        </p>
      )}

      {/* HN讨论链接 */}
      {isHN && post.discussion_url && (
        <a
          href={post.discussion_url}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1 text-sm text-[#e94560] hover:text-[#d64059] mt-2 transition-colors"
        >
          HN discussion →
        </a>
      )}

      {/* 关联信源 */}
      {relatedPosts && relatedPosts.length > 0 && (
        <div className="mt-3 pt-3 border-t border-gray-50">
          <span className="text-sm text-gray-400">关联 {relatedPosts.length} 信源</span>
          <div className="flex flex-wrap gap-2 mt-1.5">
            {relatedPosts.map((rp) => {
              const badge = SOURCE_BADGE[rp.source] ?? { label: rp.source, className: "bg-gray-100 text-gray-700" };
              return (
                <a
                  key={rp.id}
                  href={rp.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className={`inline-flex items-center gap-1 px-2.5 py-1 rounded text-sm font-medium ${badge.className} hover:opacity-80 transition-opacity`}
                >
                  {badge.label} @{rp.author_handle}
                </a>
              );
            })}
          </div>
        </div>
      )}

      {/* 推荐理由 */}
      {post.recommendation_reason && (
        <p className="text-sm text-[#e94560]/70 mt-2 leading-relaxed">
          {post.recommendation_reason}
        </p>
      )}

      {/* 标签 */}
      {displayLabels.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mt-3">
          {displayLabels.map((l) => (
            <span
              key={l}
              className={`text-sm px-2.5 py-0.5 rounded ${LABEL_COLORS[l] ?? "bg-gray-50 text-gray-500"}`}
            >
              {l}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
