"use client";
import { useState, useEffect } from "react";
import { useSettings, type SourceDef, type CategoryDef } from "@/lib/settings";
import { apiFetch } from "@/lib/api";

export default function SettingsPage() {
  const [settings, updateSettings] = useSettings();
  const [editingSource, setEditingSource] = useState<SourceDef | null>(null);
  const [editingCat, setEditingCat] = useState<CategoryDef | null>(null);
  const [showSourceForm, setShowSourceForm] = useState(false);
  const [showCatForm, setShowCatForm] = useState(false);

  const [formSource, setFormSource] = useState<SourceDef>({ key: "", label: "", badgeBg: "bg-gray-100", badgeText: "text-gray-700" });
  const [formCat, setFormCat] = useState<CategoryDef>({ key: "", label: "" });
  const [webhookUrl, setWebhookUrl] = useState("");
  const [webhookSaved, setWebhookSaved] = useState(false);
  const [settingsData, setSettingsData] = useState<Record<string,string>>({});
  const [allSaved, setAllSaved] = useState(false);
  const [newTag, setNewTag] = useState<Record<string,string>>({sources_wechat: "", keywords_cls: ""});
  const [wechatLoginNeeded, setWechatLoginNeeded] = useState(false);

  const refreshLoginStatus = () => {
    apiFetch<{ wechat_login_needed: boolean }>("/api/health").then(d =>
      setWechatLoginNeeded(d.wechat_login_needed)
    ).catch(() => {});
  };
  const [qrRefreshing, setQrRefreshing] = useState(false);
  const refreshQR = () => {
    setQrRefreshing(true);
    apiFetch("/api/wechat/qr/refresh", { method: "POST" }).then(() => {
      setTimeout(() => { setQrRefreshing(false); refreshLoginStatus(); }, 2000);
    }).catch(() => { setQrRefreshing(false); });
  };

  const getTags = (val: string | undefined) => (val || "").split(",").map(s => s.trim()).filter(Boolean);
  const addTag = (key: string) => {
    const val = (newTag[key] || "").trim();
    if (!val) return;
    setSettingsData(s => {
      const existing = getTags(s[key]);
      if (existing.includes(val)) return s;
      return {...s, [key]: [...existing, val].join(",")};
    });
    setNewTag(t => ({...t, [key]: ""}));
  };
  const removeTag = (key: string, tag: string) => {
    setSettingsData(s => {
      const existing = getTags(s[key]);
      return {...s, [key]: existing.filter(t => t !== tag).join(",")};
    });
  };

  useEffect(() => {
    apiFetch<{ settings: Record<string,string> }>("/api/settings/all").then(d =>
      setSettingsData(d.settings)
    ).catch(() => {});
    refreshLoginStatus();
  }, []);

  const saveWebhook = () => {
    apiFetch("/api/settings/all", {
      method: "PUT",
      body: JSON.stringify({ settings: { ...settingsData, webhook_url: webhookUrl } }),
    }).then(() => {
      setWebhookSaved(true);
      setTimeout(() => setWebhookSaved(false), 2000);
    }).catch(() => {});
  };

  const saveAllSettings = () => {
    apiFetch("/api/settings/all", {
      method: "PUT",
      body: JSON.stringify({ settings: settingsData }),
    }).then(() => {
      setAllSaved(true);
      setTimeout(() => setAllSaved(false), 2000);
    }).catch(() => {});
  };

  const openNewSource = () => {
    setFormSource({ key: "", label: "", badgeBg: "bg-gray-100", badgeText: "text-gray-700" });
    setEditingSource(null);
    setShowSourceForm(true);
  };

  const openEditSource = (s: SourceDef) => {
    setFormSource({ ...s });
    setEditingSource(s);
    setShowSourceForm(true);
  };

  const saveSource = () => {
    if (!formSource.key.trim() || !formSource.label.trim()) return;
    const next = { ...settings };
    if (editingSource) {
      const idx = next.sources.findIndex((s) => s.key === editingSource.key);
      if (idx !== -1) next.sources[idx] = formSource;
    } else {
      if (next.sources.some((s) => s.key === formSource.key)) return;
      next.sources.push(formSource);
    }
    updateSettings(next);
    setShowSourceForm(false);
    setEditingSource(null);
  };

  const removeSource = (key: string) => {
    const next = { ...settings };
    next.sources = next.sources.filter((s) => s.key !== key);
    next.labelMappings = next.labelMappings.filter((m) => m.sourceKey !== key);
    updateSettings(next);
  };

  const openNewCategory = () => {
    setFormCat({ key: "", label: "" });
    setEditingCat(null);
    setShowCatForm(true);
  };

  const openEditCategory = (c: CategoryDef) => {
    setFormCat({ ...c });
    setEditingCat(c);
    setShowCatForm(true);
  };

  const saveCategory = () => {
    if (!formCat.key || !formCat.label.trim()) return;
    const next = { ...settings };
    if (editingCat) {
      const idx = next.categories.findIndex((c) => c.key === editingCat.key);
      if (idx !== -1) next.categories[idx] = formCat;
    } else {
      if (next.categories.some((c) => c.key === formCat.key)) return;
      next.categories.push(formCat);
    }
    updateSettings(next);
    setShowCatForm(false);
    setEditingCat(null);
  };

  const removeCategory = (key: string | null) => {
    const next = { ...settings };
    next.categories = next.categories.filter((c) => c.key !== key);
    next.labelMappings = next.labelMappings.filter((m) => m.categoryKey !== key);
    updateSettings(next);
  };

  return (
    <div className="space-y-8">
      <h2 className="text-base font-semibold text-gray-900">设置</h2>

      <section>
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold text-gray-800">来源管理</h3>
          <button onClick={openNewSource} className="text-xs px-3 py-1 rounded bg-blue-600 text-white hover:bg-blue-700">
            + 新增来源
          </button>
        </div>
        <div className="bg-white border border-gray-200 rounded-lg divide-y divide-gray-100">
          {settings.sources.map((s) => (
            <div key={s.key} className="flex items-center justify-between px-4 py-2.5 text-sm">
              <div className="flex items-center gap-3">
                <span className={`text-xs px-2 py-0.5 rounded font-medium ${s.badgeBg} ${s.badgeText}`}>
                  {s.label}
                </span>
                <code className="text-xs text-gray-400">{s.key}</code>
              </div>
              <div className="flex items-center gap-2">
                <button onClick={() => openEditSource(s)} className="text-xs text-gray-500 hover:text-blue-600">
                  编辑
                </button>
                <button onClick={() => removeSource(s.key)} className="text-xs text-red-500 hover:text-red-700">
                  删除
                </button>
              </div>
            </div>
          ))}
        </div>
        {showSourceForm && (
          <div className="mt-3 p-4 bg-gray-50 border border-gray-200 rounded-lg space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs text-gray-500 mb-1">标识 key</label>
                <input
                  value={formSource.key}
                  onChange={(e) => setFormSource({ ...formSource, key: e.target.value })}
                  disabled={!!editingSource}
                  className="w-full border rounded px-2 py-1.5 text-sm"
                  placeholder="e.g. hackernews"
                />
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1">显示名称</label>
                <input
                  value={formSource.label}
                  onChange={(e) => setFormSource({ ...formSource, label: e.target.value })}
                  className="w-full border rounded px-2 py-1.5 text-sm"
                  placeholder="e.g. HN"
                />
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1">背景色 (Tailwind)</label>
                <input
                  value={formSource.badgeBg}
                  onChange={(e) => setFormSource({ ...formSource, badgeBg: e.target.value })}
                  className="w-full border rounded px-2 py-1.5 text-sm font-mono"
                  placeholder="bg-orange-100"
                />
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1">文字色 (Tailwind)</label>
                <input
                  value={formSource.badgeText}
                  onChange={(e) => setFormSource({ ...formSource, badgeText: e.target.value })}
                  className="w-full border rounded px-2 py-1.5 text-sm font-mono"
                  placeholder="text-orange-800"
                />
              </div>
            </div>
            <div className="flex gap-2">
              <button onClick={saveSource} className="text-xs px-4 py-1.5 rounded bg-blue-600 text-white hover:bg-blue-700">
                保存
              </button>
              <button onClick={() => setShowSourceForm(false)} className="text-xs px-4 py-1.5 rounded border text-gray-600 hover:text-gray-900">
                取消
              </button>
            </div>
          </div>
        )}
      </section>

      <section>
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold text-gray-800">分类管理</h3>
          <button onClick={openNewCategory} className="text-xs px-3 py-1 rounded bg-blue-600 text-white hover:bg-blue-700">
            + 新增分类
          </button>
        </div>
        <div className="bg-white border border-gray-200 rounded-lg divide-y divide-gray-100">
          {settings.categories.map((c) => (
            <div key={c.key ?? "__all__"} className="flex items-center justify-between px-4 py-2.5 text-sm">
              <span>{c.label}</span>
              <div className="flex items-center gap-2">
                <button onClick={() => openEditCategory(c)} className="text-xs text-gray-500 hover:text-blue-600">
                  编辑
                </button>
                {c.key !== null && (
                  <button onClick={() => removeCategory(c.key)} className="text-xs text-red-500 hover:text-red-700">
                    删除
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
        {showCatForm && (
          <div className="mt-3 p-4 bg-gray-50 border border-gray-200 rounded-lg space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs text-gray-500 mb-1">标识 key</label>
                <input
                  value={formCat.key ?? ""}
                  onChange={(e) => setFormCat({ ...formCat, key: e.target.value || null })}
                  disabled={!!editingCat}
                  className="w-full border rounded px-2 py-1.5 text-sm"
                  placeholder="e.g. 人工智能"
                />
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1">显示名称（可含 emoji）</label>
                <input
                  value={formCat.label}
                  onChange={(e) => setFormCat({ ...formCat, label: e.target.value })}
                  className="w-full border rounded px-2 py-1.5 text-sm"
                  placeholder="e.g. 🤖 人工智能"
                />
              </div>
            </div>
            <div className="flex gap-2">
              <button onClick={saveCategory} className="text-xs px-4 py-1.5 rounded bg-blue-600 text-white hover:bg-blue-700">
                保存
              </button>
              <button onClick={() => setShowCatForm(false)} className="text-xs px-4 py-1.5 rounded border text-gray-600 hover:text-gray-900">
                取消
              </button>
            </div>
          </div>
        )}
      </section>

      <section>
        <h3 className="text-sm font-semibold text-gray-800 mb-3">自动归类规则</h3>
        <p className="text-xs text-gray-500 mb-2">当文章来源匹配时，自动打上对应分类标签。</p>
        <div className="bg-white border border-gray-200 rounded-lg divide-y divide-gray-100">
          {settings.labelMappings.length === 0 && (
            <p className="px-4 py-3 text-xs text-gray-400">暂无规则</p>
          )}
          {settings.labelMappings.map((m, i) => {
            const src = settings.sources.find((s) => s.key === m.sourceKey);
            const cat = settings.categories.find((c) => c.key === m.categoryKey);
            return (
              <div key={i} className="flex items-center justify-between px-4 py-2.5 text-sm">
                <div className="flex items-center gap-2">
                  {src && <span className={`text-xs px-2 py-0.5 rounded font-medium ${src.badgeBg} ${src.badgeText}`}>{src.label}</span>}
                  <span className="text-gray-400">→</span>
                  <span className="text-xs bg-blue-100 text-blue-800 px-2 py-0.5 rounded">{cat?.label ?? m.categoryKey}</span>
                </div>
                <button
                  onClick={() => {
                    const next = { ...settings };
                    next.labelMappings = next.labelMappings.filter((_, j) => j !== i);
                    updateSettings(next);
                  }}
                  className="text-xs text-red-500 hover:text-red-700"
                >
                  删除
                </button>
              </div>
            );
          })}
        </div>
      </section>

      {/* 数据源管理 */}
      <section>
        <h3 className="text-sm font-semibold text-gray-800 mb-3">数据源管理</h3>
        <div className="space-y-4">
          {/* 微信公众号 */}
          <div className="bg-white border border-gray-200 rounded-lg p-4">
            <label className="block text-xs text-gray-500 mb-2">微信公众号</label>
            <div className="flex flex-wrap gap-2 mb-2">
              {getTags(settingsData.sources_wechat).map(tag => (
                <span key={tag} className="inline-flex items-center gap-1 px-3 py-1 rounded-full text-sm bg-green-50 text-green-700 border border-green-200">
                  {tag}
                  <button onClick={() => removeTag('sources_wechat', tag)} className="text-green-400 hover:text-green-600">✕</button>
                </span>
              ))}
            </div>
            <div className="flex gap-2">
              <input
                value={newTag.sources_wechat}
                onChange={e => setNewTag(t => ({...t, sources_wechat: e.target.value}))}
                onKeyDown={e => e.key === 'Enter' && addTag('sources_wechat')}
                className="flex-1 border rounded px-3 py-1.5 text-sm"
                placeholder="输入公众号名称，回车添加"
              />
              <button onClick={() => addTag('sources_wechat')} className="px-3 py-1.5 rounded bg-gray-100 text-sm text-gray-600 hover:bg-gray-200">添加</button>
            </div>
          </div>

          {/* 官网源 */}
          <div className="bg-white border border-gray-200 rounded-lg p-4">
            <label className="block text-xs text-gray-500 mb-1">官网源</label>
            <div className="flex flex-wrap gap-2 mb-1">
              {[
                "国家发展和改革委员会",
                "国家数据局",
                "福建省数据管理局",
                "福建省科技厅",
              ].map(name => (
                <span key={name} className="inline-flex items-center px-3 py-1 rounded-full text-sm bg-blue-50 text-blue-700 border border-blue-200">
                  {name}
                </span>
              ))}
            </div>
            <p className="text-xs text-gray-400 mt-1">官网源暂不支持在线编辑，如需增删联系管理员修改配置文件</p>
          </div>

          {/* 财联社关键词 */}
          <div className="bg-white border border-gray-200 rounded-lg p-4">
            <label className="block text-xs text-gray-500 mb-2">财联社关键词</label>
            <div className="flex flex-wrap gap-2 mb-2">
              {getTags(settingsData.keywords_cls).map(tag => (
                <span key={tag} className="inline-flex items-center gap-1 px-3 py-1 rounded-full text-sm bg-red-50 text-red-700 border border-red-200">
                  {tag}
                  <button onClick={() => removeTag('keywords_cls', tag)} className="text-red-400 hover:text-red-600">✕</button>
                </span>
              ))}
            </div>
            <div className="flex gap-2">
              <input
                value={newTag.keywords_cls}
                onChange={e => setNewTag(t => ({...t, keywords_cls: e.target.value}))}
                onKeyDown={e => e.key === 'Enter' && addTag('keywords_cls')}
                className="flex-1 border rounded px-3 py-1.5 text-sm"
                placeholder="输入关键词，回车添加"
              />
              <button onClick={() => addTag('keywords_cls')} className="px-3 py-1.5 rounded bg-gray-100 text-sm text-gray-600 hover:bg-gray-200">添加</button>
            </div>
          </div>

          <div className="flex gap-2">
            <button onClick={saveAllSettings} className="px-5 py-2.5 rounded-lg bg-[#e94560] text-white text-sm font-medium hover:bg-[#d64059]">
              保存数据源配置
            </button>
            {allSaved && <span className="text-xs text-green-600 self-center">已保存</span>}
          </div>
        </div>
      </section>

      {/* 微信登录 */}
      <section>
        <h3 className="text-sm font-semibold text-gray-800 mb-3">微信公众号登录</h3>
        <div className="bg-white border border-gray-200 rounded-lg p-4">
          {wechatLoginNeeded ? (
            <div className="text-center">
              <p className="text-sm text-[#e94560] font-medium mb-3">⚠️ 微信登录已过期，请扫码重新登录</p>
              <img src={"/api/wechat/qr/img?" + Date.now()} alt="微信二维码" className="w-48 h-48 mx-auto border rounded-lg mb-3" />
              <div className="flex gap-2 justify-center">
                <button onClick={refreshQR} disabled={qrRefreshing} className="px-4 py-2 rounded-lg bg-[#e94560] text-white text-sm font-medium hover:bg-[#d64059] disabled:opacity-50">
                  {qrRefreshing ? "生成中…" : "刷新二维码"}
                </button>
              </div>
            </div>
          ) : (
            <div className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-green-500" />
              <span className="text-sm text-gray-700">微信登录正常</span>
            </div>
          )}
        </div>
      </section>

      {/* 企业微信通知 */}
      <section>
        <h3 className="text-sm font-semibold text-gray-800 mb-3">企业微信通知</h3>
        <div className="bg-white border border-gray-200 rounded-lg p-4">
          <label className="block text-xs text-gray-500 mb-1">Webhook URL（微信过期时自动推送扫码提醒）</label>
          <div className="flex gap-2">
            <input
              value={webhookUrl}
              onChange={(e) => setWebhookUrl(e.target.value)}
              className="flex-1 border rounded px-3 py-2 text-sm"
              placeholder="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx"
            />
            <button
              onClick={saveWebhook}
              className="px-4 py-2 rounded-lg bg-[#e94560] text-white text-sm font-medium hover:bg-[#d64059]"
            >
              保存
            </button>
          </div>
          {webhookSaved && <p className="text-xs text-green-600 mt-1">已保存</p>}
        </div>
      </section>
    </div>
  );
}
