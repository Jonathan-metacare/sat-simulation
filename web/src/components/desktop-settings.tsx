"use client";

import { useEffect, useState } from "react";
import { LoaderCircle, Settings2, X } from "lucide-react";

import { desktopBridge, type DesktopSettings } from "~/lib/desktop";
import { api } from "~/lib/api";
import { translate } from "~/lib/i18n";
import type { ScenarioRecord } from "~/lib/types";
import type { Locale } from "~/lib/store";

const emptySettings: DesktopSettings = {
  locale: "zh", theme: "dark", cesiumIonToken: "",
  activeAiMode: "yolo",
  activeScenarioId: "scenario-demo-beijing",
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

function sectionTitle(section: SettingsSection, t: (key: Parameters<typeof translate>[1]) => string) {
  return ({
    general: t("sidebar.general"),
    plugins: t("sidebar.plugins"),
    ai: "AI",
    scene: t("sidebar.scene"),
    about: t("sidebar.about"),
  })[section];
}

export function DesktopSettingsPanel({ open, onClose, locale, onLocale, onTheme, onAiMode, initialSection = "general", onScenarioImported, onSettingsSaved, activeScenarioId, onScenarioSelected }: { open: boolean; onClose(): void; locale: Locale; onLocale(value: Locale): void; onTheme(value: "dark" | "light"): void; onAiMode(value: "yolo" | "llm"): void; initialSection?: SettingsSection; onScenarioImported?(): void; onSettingsSaved?(): void; activeScenarioId?: string; onScenarioSelected?(scenario: ScenarioRecord): Promise<void> | void }) {
  const bridge = desktopBridge();
  const t = (key: Parameters<typeof translate>[1], values?: Parameters<typeof translate>[2]) => translate(locale, key, values);
  const [value, setValue] = useState<DesktopSettings>(emptySettings);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<string>();
  const [section, setSection] = useState<SettingsSection>(initialSection);
  const [yamlFile, setYamlFile] = useState<File>();
  const [sceneNotice, setSceneNotice] = useState<string>();
  const [scenarios, setScenarios] = useState<ScenarioRecord[]>([]);

  useEffect(() => {
    if (!open || !bridge) return;
    void Promise.all([bridge.getSettings(), api.scenarios()]).then(([saved, records]) => {
      setValue({ ...saved, activeScenarioId: saved.activeScenarioId || activeScenarioId || "scenario-demo-beijing" }); setScenarios(records); setError(undefined);
    }).catch((cause) => setError(cause instanceof Error ? cause.message : String(cause)));
  }, [activeScenarioId, bridge, open]);
  useEffect(() => { if (open) setSection(initialSection); }, [initialSection, open]);
  useEffect(() => {
    if (!open) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [onClose, open]);

  if (!open) return null;
  if (!bridge) return <div className="fixed inset-0 z-[60] flex items-center justify-center bg-slate-950/80 p-4 backdrop-blur-sm"><section className="panel w-full max-w-md rounded-2xl p-5"><div className="flex items-center justify-between"><h2 className="text-lg text-cyan-100">{t("sidebar.settings")}</h2><button onClick={onClose}><X size={18} /></button></div><p className="mt-4 text-sm leading-6 text-slate-400">{t("settings.desktopOnly")}</p></section></div>;
  const update = <K extends keyof DesktopSettings>(key: K, next: DesktopSettings[K]) => setValue((current) => ({ ...current, [key]: next }));
  const save = async () => {
    setWorking(true); setError(undefined);
    try {
      const saved = await bridge.saveSettings(value);
      setValue(saved); onLocale(saved.locale); onTheme(saved.theme); onAiMode(saved.activeAiMode);
      onSettingsSaved?.();
      onClose();
    }
    catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { setWorking(false); }
  };
  const importYaml = async () => {
    if (!yamlFile) return;
    setWorking(true); setSceneNotice(undefined); setError(undefined);
    try { const result = await api.importScenarioYaml(yamlFile); setScenarioId(result.config.id); setSceneId(result.config.scene_id); const records = await api.scenarios(); setScenarios(records); onScenarioImported?.(); setSceneNotice(t("settings.yamlImported", { id: result.config.id })); }
    catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { setWorking(false); }
  };
  const importTiff = async () => {
    if (!tiffFile || !sceneId) return;
    setWorking(true); setSceneNotice(undefined); setError(undefined);
    try { const result = await api.importScene(tiffFile, sceneId, scenarioId || undefined); setSceneNotice(t("settings.tiffImported", { id: result.id })); }
    catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { setWorking(false); }
  };
  return <div className="fixed inset-0 z-[60] flex items-center justify-center bg-slate-950/80 p-4 backdrop-blur-sm">
    <section className="panel max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-2xl p-5 shadow-2xl shadow-black/60">
      <div className="mb-5 flex items-start justify-between gap-4">
        <div><h2 className="flex items-center gap-2 text-lg font-medium text-cyan-100"><Settings2 size={18} />{sectionTitle(section, t)}</h2><p className="mt-1 text-xs leading-5 text-slate-500">{t("settings.localOnly")}</p></div>
        <button onClick={onClose} className="rounded-lg border border-white/10 p-2 text-slate-400 hover:text-cyan-100"><X size={16} /></button>
      </div>
      {section === "general" && <div className="grid gap-4 sm:grid-cols-2">
        <label className="text-xs text-slate-400">{t("settings.language")}<select value={value.locale} onChange={(event) => update("locale", event.target.value as Locale)} className="mt-1.5 w-full rounded-lg border border-white/10 bg-black/25 px-3 py-2 text-sm text-slate-100"><option value="zh">{t("settings.chinese")}</option><option value="en">{t("settings.english")}</option></select></label>
        <label className="text-xs text-slate-400">{t("settings.theme")}<select value={value.theme} onChange={(event) => update("theme", event.target.value as "dark" | "light")} className="mt-1.5 w-full rounded-lg border border-white/10 bg-black/25 px-3 py-2 text-sm text-slate-100"><option value="dark">{t("theme.dark")}</option><option value="light">{t("theme.light")}</option></select></label>
      </div>}
      {section === "plugins" && <div className="space-y-3"><Field label="Cesium Ion Token" type="password" value={value.cesiumIonToken} onChange={(next) => update("cesiumIonToken", next)} /></div>}
      {section === "ai" && <div className="mb-4 grid grid-cols-2 gap-3"><button onClick={() => update("activeAiMode", "yolo")} className={`rounded-xl border p-3 text-left text-sm ${value.activeAiMode === "yolo" ? "border-cyan-300/50 bg-cyan-300/10 text-cyan-100" : "border-white/10 text-slate-400"}`}>YOLO<div className="mt-1 text-[10px] opacity-70">{t("settings.yoloHint")}</div></button><button onClick={() => update("activeAiMode", "llm")} className={`rounded-xl border p-3 text-left text-sm ${value.activeAiMode === "llm" ? "border-cyan-300/50 bg-cyan-300/10 text-cyan-100" : "border-white/10 text-slate-400"}`}>LLM<div className="mt-1 text-[10px] opacity-70">{t("settings.llmHint")}</div></button></div>}
      {section === "ai" && value.activeAiMode === "llm" && <div className="grid gap-4 sm:grid-cols-2">
        <Field label="LLM API URL" value={value.llmApiUrl} onChange={(next) => update("llmApiUrl", next)} placeholder="http://127.0.0.1:11434" />
        <Field label={t("settings.llmModel")} value={value.llmModel} onChange={(next) => update("llmModel", next)} placeholder="qwen3.5:4b" />
        <Field label="LLM API Key" type="password" value={value.llmApiKey} onChange={(next) => update("llmApiKey", next)} />
        <Field label={t("settings.timeout")} type="number" value={value.providerTimeoutSeconds} onChange={(next) => update("providerTimeoutSeconds", Number(next) || 30)} />
      </div>}
      {section === "ai" && value.activeAiMode === "yolo" && <div className="grid gap-4 sm:grid-cols-2">
        <Field label="YOLO API URL" value={value.yoloApiUrl} onChange={(next) => update("yoloApiUrl", next)} placeholder="http://127.0.0.1:9000" />
        <Field label="YOLO Model" value={value.yoloModel} onChange={(next) => update("yoloModel", next)} />
        <Field label="YOLO API Key" type="password" value={value.yoloApiKey} onChange={(next) => update("yoloApiKey", next)} />
        <Field label={t("settings.timeout")} type="number" value={value.providerTimeoutSeconds} onChange={(next) => update("providerTimeoutSeconds", Number(next) || 30)} />
      </div>}
      {section === "ai" && <div className="mt-4 rounded-xl border border-white/[.07] bg-black/20 p-3 text-xs text-slate-400"><div className="text-cyan-200">{t("settings.activeSelection")}</div><div className="mt-2">{value.activeAiMode === "yolo" ? "YOLO" : "LLM"} · {t("settings.subsequentMode")}</div></div>}
      {section === "scene" && <div className="space-y-4"><p className="text-xs leading-5 text-slate-500">{t("settings.sceneDescription")}</p><label className="block text-xs text-slate-400">{t("settings.activeScenario")}<select value={value.activeScenarioId} disabled={working} onChange={(event) => { const selected = scenarios.find((item) => item.config.id === event.target.value); if (!selected) return; setWorking(true); setError(undefined); void Promise.resolve(onScenarioSelected?.(selected)).then(() => update("activeScenarioId", selected.config.id)).catch((cause) => setError(cause instanceof Error ? cause.message : String(cause))).finally(() => setWorking(false)); }} className="mt-1.5 w-full rounded-lg border border-white/10 bg-black/25 px-3 py-2 text-sm text-slate-100">{scenarios.map((item) => <option key={item.config.id} value={item.config.id} disabled={!item.config.scene_ready}>{item.config.name}{item.config.scene_ready ? "" : ` (${t("settings.geoTiffRequired")})`}</option>)}</select></label><div className="border-t border-white/[.07] pt-4"><label className="block text-xs text-slate-400">YAML<input className="mt-1.5 block w-full text-xs" type="file" accept=".yaml,.yml" onChange={(event) => setYamlFile(event.target.files?.[0])} /></label><button disabled={!yamlFile || working} onClick={() => void importYaml()} className="mt-2 rounded-lg border border-cyan-300/50 px-3 py-2 text-xs text-cyan-100">{t("settings.importYaml")}</button>{scenarioId && <p className="mt-2 text-xs text-slate-500">scenario_id: {scenarioId}</p>}<Field label="scene_id" value={sceneId} onChange={setSceneId} /><label className="mt-3 block text-xs text-slate-400">16-bit GeoTIFF<input className="mt-1.5 block w-full text-xs" type="file" accept=".tif,.tiff" onChange={(event) => setTiffFile(event.target.files?.[0])} /></label><button disabled={!tiffFile || !sceneId || !scenarioId || working} onClick={() => void importTiff()} className="mt-2 rounded-lg border border-cyan-300/50 px-3 py-2 text-xs text-cyan-100">{t("settings.importTiff")}</button></div>{sceneNotice && <p className="text-xs text-emerald-300">{sceneNotice}</p>}</div>}
      {section === "about" && <div className="rounded-xl border border-white/[.07] bg-black/20 p-4 text-sm text-slate-300"><div className="text-cyan-200">{t("settings.softwareVersion")}</div><div className="mt-3 font-mono text-lg text-cyan-100">SIL ONLINE · v0.1.1</div><div className="mt-5 text-cyan-200">{t("settings.publisher")}</div><a href="https://www.spacezenith.ai" target="_blank" rel="noreferrer" onClick={(event) => { if (typeof bridge?.openExternal !== "function") return; event.preventDefault(); void bridge.openExternal("https://www.spacezenith.ai").catch(() => window.open("https://www.spacezenith.ai", "_blank", "noopener,noreferrer")); }} className="mt-2 inline-block text-left text-sm text-cyan-100 underline decoration-cyan-300/40 underline-offset-4 hover:text-cyan-300">www.spacezenith.ai</a></div>}
      {error && <p className="mt-4 rounded-lg border border-orange-300/25 bg-orange-300/10 px-3 py-2 text-xs text-orange-200">{error}</p>}
      <div className="mt-5 flex flex-wrap justify-end gap-2">
        <button disabled={working} onClick={() => void save()} className="inline-flex items-center gap-1.5 rounded-lg border border-cyan-300/50 bg-cyan-300/15 px-3 py-2 text-xs text-cyan-100 disabled:opacity-50">{working && <LoaderCircle size={14} className="animate-spin" />}{t("settings.save")}</button>
      </div>
    </section>
  </div>;
}
