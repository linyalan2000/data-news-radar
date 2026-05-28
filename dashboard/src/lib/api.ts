/**
 * API client — injects X-API-Key header on every request.
 */

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const API_KEY = process.env.NEXT_PUBLIC_API_KEY ?? "";

export interface Post {
  id: number;
  source: string;
  external_id: string;
  author_handle: string;
  title: string;
  content: string;
  url: string;
  posted_at: string;
  fetched_at: string;
  relevance_score: number | null;
  points: number | null;
  is_relevant: boolean;
  labels: string[];
  digest_sent: boolean;
  discussion_url: string | null;
  summary_zh: string | null;
  topic_group: string | null;
  recommendation_reason: string | null;
}

export interface PaginatedNewsResponse {
  total: number;
  page: number;
  per_page: number;
  items: Post[];
}

export interface DigestResult {
  posts_included: number;
  email_sent: boolean;
  webhook_sent: boolean;
}

export interface NewsQueryParams {
  label?: string;
  min_score?: number;
  q?: string;
  source?: "hackernews" | "reddit" | "github";
  since?: string;
  page?: number;
  per_page?: number;
  sort?: "date_desc" | "score_desc";
}

export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      "X-API-Key": API_KEY,
      ...init.headers,
    },
  });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`API error ${res.status}: ${text}`);
  }
  return res.json() as Promise<T>;
}

export function fetchNews(params: NewsQueryParams = {}): Promise<PaginatedNewsResponse> {
  const qs = new URLSearchParams();
  if (params.label) qs.set("label", params.label);
  if (params.min_score !== undefined) qs.set("min_score", String(params.min_score));
  if (params.q) qs.set("q", params.q);
  if (params.source) qs.set("source", params.source);
  if (params.since) qs.set("since", params.since);
  if (params.page) qs.set("page", String(params.page));
  if (params.per_page) qs.set("per_page", String(params.per_page));
  if (params.sort) qs.set("sort", params.sort);
  return apiFetch<PaginatedNewsResponse>(`/api/news?${qs}`);
}

export function triggerDigest(): Promise<DigestResult> {
  return apiFetch<DigestResult>("/api/digest/trigger", { method: "POST" });
}

export interface ReportListItem {
  id: number;
  generated_at: string;
  post_count: number;
  model_used: string;
}

export interface Report {
  id: number;
  generated_at: string;
  content: string;
  post_count: number;
  model_used: string;
}

export function fetchLatestReport(): Promise<Report> {
  return apiFetch<Report>("/api/summary/latest");
}

export function fetchReports(): Promise<ReportListItem[]> {
  return apiFetch<ReportListItem[]>("/api/summary/reports");
}

export function fetchReportById(id: number): Promise<Report> {
  return apiFetch<Report>(`/api/summary/reports/${id}`);
}

export interface DailyReportSection {
  title: string;
  posts: Post[];
}

export interface DailyReport {
  date: string;
  sections: DailyReportSection[];
  summary: string;
  generated: boolean;
}

export function fetchDailyReport(date?: string): Promise<DailyReport> {
  const qs = date ? `?date=${date}` : "";
  return apiFetch<DailyReport>(`/api/daily-report${qs}`);
}

export function fetchDailyReportDates(): Promise<{ dates: string[] }> {
  return apiFetch<{ dates: string[] }>("/api/daily-report/dates");
}
