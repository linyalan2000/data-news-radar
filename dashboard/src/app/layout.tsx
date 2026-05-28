"use client";
import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { initSettings } from "@/lib/settings";
import "./globals.css";

const NAV = [
  { href: "/", label: "📡 实时新闻" },
  { href: "/daily-report", label: "📋 数据日报" },
  { href: "/settings", label: "⚙️ 设置" },
];

export default function RootLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [sidebarOpen, setSidebarOpen] = useState(false);

  useEffect(() => {
    initSettings();
  }, []);

  // Close sidebar on navigation (mobile)
  useEffect(() => {
    setSidebarOpen(false);
  }, [pathname]);

  return (
    <html lang="zh-CN">
      <body className="min-h-screen bg-gray-50 text-gray-900 antialiased flex flex-col md:flex-row">
        {/* Mobile hamburger */}
        <button
          onClick={() => setSidebarOpen(true)}
          aria-label="Open menu"
          className="md:hidden fixed top-3 left-3 z-30 p-2 rounded-lg bg-white border border-gray-200 shadow-sm"
        >
          <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <path d="M3 5h14M3 10h14M3 15h14" />
          </svg>
        </button>

        {/* Overlay backdrop (mobile only) */}
        {sidebarOpen && (
          <div
            className="md:hidden fixed inset-0 z-20 bg-black/30"
            onClick={() => setSidebarOpen(false)}
          />
        )}

        {/* Sidebar */}
        <aside className={`
          fixed md:sticky top-0 left-0 z-30 md:self-start
          w-64 shrink-0 bg-[#1a1a2e] text-white min-h-screen flex flex-col
          transition-transform duration-200
          ${sidebarOpen ? "translate-x-0" : "-translate-x-full"}
          md:translate-x-0
        `}>
          <div className="flex items-center justify-between px-6 py-5 border-b border-white/10">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-[#e94560] to-[#ff6b6b] flex items-center justify-center text-white font-bold text-sm">
                D
              </div>
              <div>
                <h1 className="text-lg font-bold tracking-tight">
                  <span className="text-white">Data</span><span className="text-[#e94560]">HOT</span>
                </h1>
                <p className="text-xs text-white/40">AI 新闻雷达</p>
              </div>
            </div>
            <button
              onClick={() => setSidebarOpen(false)}
              aria-label="Close menu"
              className="md:hidden p-1 rounded hover:bg-gray-100"
            >
              <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                <path d="M4 4l10 10M14 4L4 14" />
              </svg>
            </button>
          </div>
          <nav className="flex-1 px-3 py-4 space-y-1">
            {NAV.map(({ href, label }) => {
              const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
              return (
                <a
                  key={href}
                  href={href}
                  className={`flex items-center gap-3 px-4 py-3 rounded-lg text-sm font-medium transition-all duration-200 ${
                    active
                      ? "bg-[#e94560]/20 text-white"
                      : "text-white/60 hover:bg-white/5 hover:text-white"
                  }`}
                >
                  {label}
                </a>
              );
            })}
          </nav>
          <div className="px-6 py-4 border-t border-white/10 text-xs text-white/30">
            <p>AI News Radar</p>
            <p className="mt-0.5">数据要素 · AI · 数智化</p>
          </div>
        </aside>

        <main className="flex-1 min-w-0 px-4 md:px-8 pt-14 md:pt-8 pb-8">
          {children}
        </main>
      </body>
    </html>
  );
}
