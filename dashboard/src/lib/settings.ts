"use client";
import { useCallback, useSyncExternalStore } from "react";

export interface SourceDef {
  key: string;
  label: string;
  badgeBg: string;
  badgeText: string;
}

export interface CategoryDef {
  key: string | null;
  label: string;
}

export interface LabelMapping {
  sourceKey: string;
  categoryKey: string;
}

export interface AppSettings {
  sources: SourceDef[];
  categories: CategoryDef[];
  labelMappings: LabelMapping[];
}

export const DEFAULT_SOURCES: SourceDef[] = [
  { key: "hackernews", label: "HN", badgeBg: "bg-orange-100", badgeText: "text-orange-800" },
  { key: "reddit", label: "Reddit", badgeBg: "bg-red-100", badgeText: "text-red-700" },
  { key: "github", label: "GitHub", badgeBg: "bg-gray-800", badgeText: "text-white" },
  { key: "rss", label: "RSS", badgeBg: "bg-green-100", badgeText: "text-green-800" },
  { key: "gov", label: "官网", badgeBg: "bg-red-100", badgeText: "text-red-800" },
  { key: "wechat", label: "微信", badgeBg: "bg-green-100", badgeText: "text-green-800" },
  { key: "bidding", label: "招标", badgeBg: "bg-yellow-100", badgeText: "text-yellow-800" },
  { key: "cls", label: "财联社", badgeBg: "bg-blue-100", badgeText: "text-blue-800" },
  { key: "aihot", label: "AIHOT", badgeBg: "bg-purple-100", badgeText: "text-purple-800" },
];

export const DEFAULT_CATEGORIES: CategoryDef[] = [
  { key: null, label: "全部" },
  { key: "政策法规", label: "📋 政策法规" },
  { key: "数据要素", label: "💎 数据要素" },
  { key: "人工智能", label: "🤖 人工智能" },
  { key: "数智化", label: "🌐 数智化" },
  { key: "福建本地", label: "📍 福建本地" },
];

export const DEFAULT_LABEL_MAPPINGS: LabelMapping[] = [
  { sourceKey: "cls", categoryKey: "人工智能" },
];

export const DEFAULT_SETTINGS: AppSettings = {
  sources: DEFAULT_SOURCES,
  categories: DEFAULT_CATEGORIES,
  labelMappings: DEFAULT_LABEL_MAPPINGS,
};

const STORAGE_KEY = "datahot-settings";

function loadSettings(): AppSettings {
  if (typeof window === "undefined") return DEFAULT_SETTINGS;
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as AppSettings;
      return {
        sources: parsed.sources ?? DEFAULT_SETTINGS.sources,
        categories: parsed.categories ?? DEFAULT_SETTINGS.categories,
        labelMappings: parsed.labelMappings ?? DEFAULT_SETTINGS.labelMappings,
      };
    }
  } catch {
    // corrupted — reset
  }
  return DEFAULT_SETTINGS;
}

function saveSettings(s: AppSettings): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(s));
}

let cached = DEFAULT_SETTINGS;
const listeners = new Set<() => void>();

function subscribe(cb: () => void): () => void {
  listeners.add(cb);
  return () => listeners.delete(cb);
}

function getSnapshot(): AppSettings {
  return cached;
}

function getServerSnapshot(): AppSettings {
  return DEFAULT_SETTINGS;
}

function notify() {
  listeners.forEach((cb) => cb());
}

export function useSettings(): [AppSettings, (s: AppSettings) => void] {
  const snapshot = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);

  const update = useCallback((next: AppSettings) => {
    cached = next;
    saveSettings(next);
    notify();
  }, []);

  return [snapshot, update];
}

export function initSettings(): void {
  cached = loadSettings();
}

export function sourceBadgeClasses(s: SourceDef): string {
  return `${s.badgeBg} ${s.badgeText}`;
}
