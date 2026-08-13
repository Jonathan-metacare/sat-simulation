"use client";

import { useEffect, useState } from "react";
import { LoaderCircle, Settings2, X } from "lucide-react";

import { desktopBridge, type DesktopDiagnostics, type DesktopSettings } from "~/lib/desktop";
import { api } from "~/lib/api";
import type { Locale } from "~/lib/store";

const emptySettings: DesktopSettings = {
  locale: "zh", theme: "dark", cesiumIonToken: "",
  activeAiMode: "yolo",
  llmApiUrl: "http://127.0.0.1:11434", llmModel: "", llmApiKey: "",
  yoloApiUrl: "", yoloModel: "default", yoloApiKey: "", providerTimeoutSeconds: 30,
};

function Field({ label, value, onChange, type = "text", placeholder }: {
  label: string; value: string | number; type?: string; placeholder?: string;
  onChange(value: string): void;
}) {
  return <label className="block text-xs text-slate-400">{label}
    <input type={type} value={value} placeholder={placeholder} onChange={(event) => onChange(event.target.value)}
      className="mt-1.5 w-full rounded-lg border border-white/10 bg-black/25 px-3 py-2 text-sm text-slate-100 outline-none focus:border-cyan-300/45" />
  </label>;
}

export function isDesktopApp() { return Boolean(desktopBridge()); }

type SettingsSection = "general" | "plugins" | "ai" | "scene" | "about";

function sectionTitle(section: SettingsSection, zh: boolean) {
  return ({
    general: zh ? "通用" : "General",
    plugins: zh ? "插件与密钥" : "Plugins & Keys",
    ai: "AI",
    scene: zh ? "场景导入" : "Scene Import",
    about: zh ? "关于" : "About",
  })[section];
}

export function DesktopSettingsPanel({ open, onClose, locale, onLocale, onTheme, onAiMode, initialSection = "general", onScenarioImported }: { open: boolean; onClose(): void; locale: Locale; onLocale(value: Locale): void; onTheme(value: "dark" | "light"): void; onAiMode(value: "yolo" | "llm"): void; initialSection?: SettingsSection; onScenarioImported?(): void }) {
  const bridge = desktopBridge();
  const zh = locale === "zh";
  const [value, setValue] = useState<DesktopSettings>(emptySettings);
  const [diagnostics, setDiagnostics] = useState<DesktopDiagnostics>();
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<string>();
  const [section, setSection] = useState<SettingsSection>(initialSection);
  const [yamlFile, setYamlFile] = useState<File>();
  const [tiffFile, setTiffFile] = useState<File>();
  const [sceneId, setSceneId] = useState("");
  const [scenarioId, setScenarioId] = useState("");
  const [sceneNotice, setSceneNotice] = useState<string>();

  useEffect(() => {
    if (!open || !bridge) return;
    void Promise.all([bridge.getSettings(), bridge.diagnostics()]).then(([saved, details]) => {
      setValue(saved); setDiagnostics(details); setError(undefined);
    }).catch((cause) => setError(cause instanceof Error ? cause.message : String(cause)));
  }, [bridge, open]);
  useEffect(() => { if (open) setSection(initialSection); }, [initialSection, open]);

  if (!open) return null;
  if (!bridge) return <div className="fixed inset-0 z-[60] flex items-center justify-center bg-slate-950/80 p-4 backdrop-blur-sm"><section className="panel w-full max-w-md rounded-2xl p-5"><div className="flex items-center justify-between"><h2 className="text-lg text-cyan-100">{locale === "zh" ? "设置" : "Settings"}</h2><button onClick={onClose}><X size={18} /></button></div><p className="mt-4 text-sm leading-6 text-slate-400">{locale === "zh" ? "请使用桌面应用配置本机 Cesium、YOLO、LLM 和场景导入。浏览器版仅提供只读仿真控制。" : "Use the desktop application to configure local Cesium, YOLO, LLM, and scene imports. The browser edition is read-only for local settings."}</p></section></div>;
  const update = <K extends keyof DesktopSettings>(key: K, next: DesktopSettings[K]) => setValue((current) => ({ ...current, [key]: next }));
  const save = async () => {
    setWorking(true); setError(undefined);
    try {
      const saved = await bridge.saveSettings(value);
      setValue(saved); onLocale(saved.locale); onTheme(saved.theme); onAiMode(saved.activeAiMode);
      onClose();
    }
    catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { setWorking(false); }
  };
  const importYaml = async () => {
    if (!yamlFile) return;
    setWorking(true); setSceneNotice(undefined); setError(undefined);
    try { const result = await api.importScenarioYaml(yamlFile); setScenarioId(result.config.id); setSceneId(result.config.scene_id); onScenarioImported?.(); setSceneNotice(`${zh ? "YAML 校验成功，场景已创建：" : "YAML validated and scenario created: "}${result.config.id}`); }
    catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { setWorking(false); }
  };
  const importTiff = async () => {
    if (!tiffFile || !sceneId) return;
    setWorking(true); setSceneNotice(undefined); setError(undefined);
    try { const result = await api.importScene(tiffFile, sceneId, scenarioId || undefined); setSceneNotice(`${zh ? "GeoTIFF 已校验并关联：" : "GeoTIFF validated and linked: "}${result.id}`); }
    catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { setWorking(false); }
  };
  return <div className="fixed inset-0 z-[60] flex items-center justify-center bg-slate-950/80 p-4 backdrop-blur-sm">
    <section className="panel max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-2xl p-5 shadow-2xl shadow-black/60">
      <div className="mb-5 flex items-start justify-between gap-4">
        <div><h2 className="flex items-center gap-2 text-lg font-medium text-cyan-100"><Settings2 size={18} />{sectionTitle(section, zh)}</h2><p className="mt-1 text-xs leading-5 text-slate-500">{zh ? "本机配置仅保存在此设备。" : "Local configuration is stored on this device only."}</p></div>
        <button onClick={onClose} className="rounded-lg border border-white/10 p-2 text-slate-400 hover:text-cyan-100"><X size={16} /></button>
      </div>
      {section === "general" && <div className="grid gap-4 sm:grid-cols-2">
        <label className="text-xs text-slate-400">{zh ? "语言" : "Language"}<select value={value.locale} onChange={(event) => update("locale", event.target.value as Locale)} className="mt-1.5 w-full rounded-lg border border-white/10 bg-black/25 px-3 py-2 text-sm text-slate-100"><option value="zh">中文</option><option value="en">English</option></select></label>
        <label className="text-xs text-slate-400">{zh ? "主题" : "Theme"}<select value={value.theme} onChange={(event) => update("theme", event.target.value as "dark" | "light")} className="mt-1.5 w-full rounded-lg border border-white/10 bg-black/25 px-3 py-2 text-sm text-slate-100"><option value="dark">Dark</option><option value="light">Light</option></select></label>
      </div>}
      {section === "plugins" && <div className="space-y-3"><Field label="Cesium Ion Token" type="password" value={value.cesiumIonToken} onChange={(next) => update("cesiumIonToken", next)} /></div>}
      {section === "ai" && <div className="mb-4 grid grid-cols-2 gap-3"><button onClick={() => update("activeAiMode", "yolo")} className={`rounded-xl border p-3 text-left text-sm ${value.activeAiMode === "yolo" ? "border-cyan-300/50 bg-cyan-300/10 text-cyan-100" : "border-white/10 text-slate-400"}`}>YOLO<div className="mt-1 text-[10px] opacity-70">{zh ? "目标检测" : "Object detection"}</div></button><button onClick={() => update("activeAiMode", "llm")} className={`rounded-xl border p-3 text-left text-sm ${value.activeAiMode === "llm" ? "border-cyan-300/50 bg-cyan-300/10 text-cyan-100" : "border-white/10 text-slate-400"}`}>LLM<div className="mt-1 text-[10px] opacity-70">{zh ? "图像与任务分析" : "Image and mission analysis"}</div></button></div>}
      {section === "ai" && value.activeAiMode === "llm" && <div className="grid gap-4 sm:grid-cols-2">
        <Field label="LLM API URL" value={value.llmApiUrl} onChange={(next) => update("llmApiUrl", next)} placeholder="http://127.0.0.1:11434" />
        <Field label={zh ? "LLM 模型" : "LLM model"} value={value.llmModel} onChange={(next) => update("llmModel", next)} placeholder="qwen3.5:4b" />
        <Field label="LLM API Key" type="password" value={value.llmApiKey} onChange={(next) => update("llmApiKey", next)} />
        <Field label={zh ? "模型超时（秒）" : "Model timeout (seconds)"} type="number" value={value.providerTimeoutSeconds} onChange={(next) => update("providerTimeoutSeconds", Number(next) || 30)} />
      </div>}
      {section === "ai" && value.activeAiMode === "yolo" && <div className="grid gap-4 sm:grid-cols-2">
        <Field label="YOLO API URL" value={value.yoloApiUrl} onChange={(next) => update("yoloApiUrl", next)} placeholder="http://127.0.0.1:9000" />
        <Field label="YOLO Model" value={value.yoloModel} onChange={(next) => update("yoloModel", next)} />
        <Field label="YOLO API Key" type="password" value={value.yoloApiKey} onChange={(next) => update("yoloApiKey", next)} />
        <Field label={zh ? "模型超时（秒）" : "Model timeout (seconds)"} type="number" value={value.providerTimeoutSeconds} onChange={(next) => update("providerTimeoutSeconds", Number(next) || 30)} />
      </div>}
      {section === "ai" && <div className="mt-4 rounded-xl border border-white/[.07] bg-black/20 p-3 text-xs text-slate-400"><div className="text-cyan-200">{zh ? "当前选择" : "Active selection"}</div><div className="mt-2">{value.activeAiMode === "yolo" ? "YOLO" : "LLM"} · {zh ? "后续新任务将使用此模式" : "Subsequent missions will use this mode"}</div></div>}
      {section === "scene" && <div className="space-y-4"><p className="text-xs leading-5 text-slate-500">{zh ? "先导入严格校验的 YAML，再导入关联的 16-bit GeoTIFF。未知字段和非法值会被拒绝；两步都成功后，场景才可创建新任务。" : "Import a strictly validated YAML first, then its linked 16-bit GeoTIFF. Unknown fields and invalid values are rejected; a mission can only be created after both steps succeed."}</p><label className="block text-xs text-slate-400">YAML<input className="mt-1.5 block w-full text-xs" type="file" accept=".yaml,.yml" onChange={(event) => setYamlFile(event.target.files?.[0])} /></label><button disabled={!yamlFile || working} onClick={() => void importYaml()} className="rounded-lg border border-cyan-300/50 px-3 py-2 text-xs text-cyan-100">{zh ? "校验并导入 YAML" : "Validate and import YAML"}</button>{scenarioId && <p className="text-xs text-slate-500">scenario_id: {scenarioId}</p>}<Field label="scene_id" value={sceneId} onChange={setSceneId} /><label className="block text-xs text-slate-400">16-bit GeoTIFF<input className="mt-1.5 block w-full text-xs" type="file" accept=".tif,.tiff" onChange={(event) => setTiffFile(event.target.files?.[0])} /></label><button disabled={!tiffFile || !sceneId || !scenarioId || working} onClick={() => void importTiff()} className="rounded-lg border border-cyan-300/50 px-3 py-2 text-xs text-cyan-100">{zh ? "校验并关联 GeoTIFF" : "Validate and link GeoTIFF"}</button>{sceneNotice && <p className="text-xs text-emerald-300">{sceneNotice}</p>}</div>}
      {section === "about" && <div className="rounded-xl border border-white/[.07] bg-black/20 p-4 text-sm text-slate-300"><div className="text-cyan-200">{zh ? "软件版本" : "Software version"}</div><div className="mt-3 font-mono text-lg text-cyan-100">SIL ONLINE · v0.1.1</div><div className="mt-5 text-cyan-200">{zh ? "出品" : "Publisher"}</div><a href="https://www.spacezenith.ai" target="_blank" rel="noreferrer" onClick={(event) => { if (typeof bridge?.openExternal !== "function") return; event.preventDefault(); void bridge.openExternal("https://www.spacezenith.ai").catch(() => window.open("https://www.spacezenith.ai", "_blank", "noopener,noreferrer")); }} className="mt-2 inline-block text-left text-sm text-cyan-100 underline decoration-cyan-300/40 underline-offset-4 hover:text-cyan-300">www.spacezenith.ai</a></div>}
      {error && <p className="mt-4 rounded-lg border border-orange-300/25 bg-orange-300/10 px-3 py-2 text-xs text-orange-200">{error}</p>}
      <div className="mt-5 flex flex-wrap justify-end gap-2">
        <button disabled={working} onClick={() => void save()} className="inline-flex items-center gap-1.5 rounded-lg border border-cyan-300/50 bg-cyan-300/15 px-3 py-2 text-xs text-cyan-100 disabled:opacity-50">{working && <LoaderCircle size={14} className="animate-spin" />}{zh ? "保存设置" : "Save settings"}</button>
      </div>
    </section>
  </div>;
}
