"use client";

import { useEffect, useState } from "react";
import { CircleAlert, LoaderCircle, Settings2, X } from "lucide-react";

import { desktopBridge, type DesktopResetAction, type DesktopSettings } from "~/lib/desktop";
import { api } from "~/lib/api";
import { translate } from "~/lib/i18n";
import type { ScenarioRecord } from "~/lib/types";
import type { Locale } from "~/lib/store";

const emptySettings: DesktopSettings = {
  locale: "zh", theme: "dark", cesiumIonToken: "", keeptrackApiKey: "",
  activeAiMode: "llm",
  activeScenarioId: "scenario-demo-beijing",
  llmModel: "",
  providerTimeoutSeconds: 300,
  agentEnabled: false,
  agentModel: "",
  agentSystemPrompt: "你是星载光学遥感图像分析助手。直接输出最终分析，不输出思考过程；明确区分图像可见事实、结合元数据的推断和不确定性。",
  agentTools: [],
  gpuMode: "jetson", jetsonHost: "", jetsonSshUsername: "", jetsonHostKeyFingerprint: "", jetsonDeploymentStatus: "unconfigured", jetsonDeploymentVersion: "", jetsonDeploymentError: "", jetsonApiPort: 8002, jetsonGtxPort: 9101,
  desktopAdvertiseHost: "", platformGtxResultPort: 9102,
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

function TextArea({ label, value, onChange }: { label: string; value: string; onChange(value: string): void }) {
  return <label className="block text-xs text-slate-400">{label}
    <textarea value={value} maxLength={4000} rows={7} onChange={(event) => onChange(event.target.value)} className="mt-1.5 w-full resize-y rounded-lg border border-white/10 bg-black/25 px-3 py-2 text-sm text-slate-100 outline-none focus:border-cyan-300/45" />
  </label>;
}

export function isDesktopApp() { return Boolean(desktopBridge()); }

type SettingsSection = "general" | "plugins" | "ai" | "agent" | "scene" | "data" | "about";

function sectionTitle(section: SettingsSection, t: (key: Parameters<typeof translate>[1]) => string) {
  return ({
    general: t("sidebar.general"),
    plugins: t("sidebar.plugins"),
    ai: "AI",
    agent: t("sidebar.agent"),
    scene: t("sidebar.scene"),
    data: t("sidebar.data"),
    about: t("sidebar.about"),
  })[section];
}

export function DesktopSettingsPanel({ open, onClose, locale, onLocale, onTheme, initialSection = "general", onScenarioImported, onSettingsSaved, activeScenarioId, onScenarioSelected }: { open: boolean; onClose(): void; locale: Locale; onLocale(value: Locale): void; onTheme(value: "dark" | "light"): void; initialSection?: SettingsSection; onScenarioImported?(): void; onSettingsSaved?(): void; activeScenarioId?: string; onScenarioSelected?(scenario: ScenarioRecord): Promise<void> | void }) {
  const bridge = desktopBridge();
  const t = (key: Parameters<typeof translate>[1], values?: Parameters<typeof translate>[2]) => translate(locale, key, values);
  const [value, setValue] = useState<DesktopSettings>(emptySettings);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<string>();
  const [section, setSection] = useState<SettingsSection>(initialSection);
  const [yamlFile, setYamlFile] = useState<File>();
  const [sceneNotice, setSceneNotice] = useState<string>();
  const [scenarios, setScenarios] = useState<ScenarioRecord[]>([]);
  const [visionModels, setVisionModels] = useState<Array<{ name: string; capabilities: string[] }>>([]);
  const [pendingReset, setPendingReset] = useState<DesktopResetAction>();
  const [resetConfirmation, setResetConfirmation] = useState("");
  const [resetNotice, setResetNotice] = useState<string>();
  const [jetsonPassword, setJetsonPassword] = useState("");
  const [jetsonLogs, setJetsonLogs] = useState<string[]>([]);
  const [jetsonStage, setJetsonStage] = useState<string>();
  const [modelToInstall, setModelToInstall] = useState("qwen3-vl:8b");

  useEffect(() => {
    if (!open || !bridge) return;
    void Promise.all([bridge.getSettings(), bridge.getJetsonPassword(), api.scenarios()]).then(([saved, password, records]) => {
      setValue({ ...saved, activeScenarioId: saved.activeScenarioId || activeScenarioId || "scenario-demo-beijing" }); setJetsonPassword(password); setScenarios(records); setError(undefined);
    }).catch((cause) => setError(cause instanceof Error ? cause.message : String(cause)));
  }, [activeScenarioId, bridge, open]);
  useEffect(() => {
    if (!bridge) return;
    return bridge.onJetsonProgress((event) => {
      if (event.type === "stage") setJetsonStage(event.name);
      if (event.message) setJetsonLogs((current) => [...current.slice(-199), event.message!]);
    });
  }, [bridge]);
  useEffect(() => {
    if (!open) return;
    setSection(initialSection); setPendingReset(undefined); setResetConfirmation(""); setResetNotice(undefined);
  }, [initialSection, open]);
  useEffect(() => {
    if (!open || (section !== "ai" && section !== "agent")) return;
    void api.providerModels().then((result) => setVisionModels(result.models)).catch(() => setVisionModels([]));
  }, [open, section]);
  useEffect(() => {
    if (!open) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !working) onClose();
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [onClose, open, working]);

  if (!open) return null;
  if (!bridge) return <div className="fixed inset-0 z-[60] flex items-center justify-center bg-slate-950/80 p-4 backdrop-blur-sm"><section className="panel w-full max-w-md rounded-2xl p-5"><div className="flex items-center justify-between"><h2 className="text-lg text-cyan-100">{t("sidebar.settings")}</h2><button onClick={onClose}><X size={18} /></button></div><p className="mt-4 text-sm leading-6 text-slate-400">{t("settings.desktopOnly")}</p></section></div>;
  const update = <K extends keyof DesktopSettings>(key: K, next: DesktopSettings[K]) => setValue((current) => ({ ...current, [key]: next }));
  const save = async () => {
    setWorking(true); setError(undefined);
    try {
      const saved = await bridge.saveSettings(value, jetsonPassword);
      setValue(saved); onLocale(saved.locale); onTheme(saved.theme);
      onSettingsSaved?.();
      onClose();
    }
    catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { setWorking(false); }
  };
  const importYaml = async () => {
    if (!yamlFile) return;
    setWorking(true); setSceneNotice(undefined); setError(undefined);
    try { const result = await api.importScenarioYaml(yamlFile); update("activeScenarioId", result.config.id); const records = await api.scenarios(); setScenarios(records); onScenarioImported?.(); setSceneNotice(t("settings.yamlImported", { id: result.config.id })); }
    catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { setWorking(false); }
  };
  const needsResetToken = pendingReset === "simulation-data" || pendingReset === "settings-defaults";
  const runReset = async () => {
    if (!pendingReset) return;
    setWorking(true); setError(undefined); setResetNotice(undefined);
    try {
      const result = await bridge.resetData(pendingReset, resetConfirmation);
      setValue(result.settings); onLocale(result.settings.locale); onTheme(result.settings.theme);
      setPendingReset(undefined); setResetConfirmation("");
      setResetNotice(t("settings.resetCompleted"));
      onSettingsSaved?.();
      if (pendingReset === "simulation-data") {
        const records = await api.scenarios();
        setScenarios(records);
      }
    } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { setWorking(false); }
  };
  const discoverJetson = async () => {
    setWorking(true); setError(undefined); setJetsonLogs([]);
    try {
      const result = await bridge.discoverJetsonHostKey({ password: jetsonPassword });
      const saved = await bridge.confirmJetsonHostKey(result.fingerprint);
      setValue(saved); setJetsonStage("host-key-confirmed");
    } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { setWorking(false); }
  };
  const deployJetson = async (mode: "application" | "initialize") => {
    setWorking(true); setError(undefined); setJetsonLogs([]);
    try { const saved = await bridge.deployJetson({ credentials: { password: jetsonPassword }, mode }); setValue(saved); setJetsonStage("complete"); }
    catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { setWorking(false); }
  };
  const installJetsonModel = async () => {
    setWorking(true); setError(undefined); setJetsonLogs([]); setJetsonStage("model");
    try {
      const result = await bridge.pullJetsonModel({ credentials: { password: jetsonPassword }, model: modelToInstall.trim() });
      setValue(result.settings); setModelToInstall(result.model);
      const listed = await api.providerModels(); setVisionModels(listed.models);
      setJetsonStage("model-complete"); onSettingsSaved?.();
    } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { setWorking(false); }
  };
  return <div className="fixed inset-0 z-[60] flex items-center justify-center bg-slate-950/80 p-4 backdrop-blur-sm">
    <section className="panel max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-2xl p-5 shadow-2xl shadow-black/60">
      <div className="mb-5 flex items-start justify-between gap-4">
        <div><h2 className="flex items-center gap-2 text-lg font-medium text-cyan-100"><Settings2 size={18} />{sectionTitle(section, t)}</h2><p className="mt-1 text-xs leading-5 text-slate-500">{t("settings.localOnly")}</p></div>
        <button disabled={working} onClick={onClose} className="rounded-lg border border-white/10 p-2 text-slate-400 hover:text-cyan-100 disabled:opacity-40"><X size={16} /></button>
      </div>
      {section === "general" && <div className="grid gap-4 sm:grid-cols-2">
        <label className="text-xs text-slate-400">{t("settings.language")}<select value={value.locale} onChange={(event) => update("locale", event.target.value as Locale)} className="mt-1.5 w-full rounded-lg border border-white/10 bg-black/25 px-3 py-2 text-sm text-slate-100"><option value="zh">{t("settings.chinese")}</option><option value="en">{t("settings.english")}</option></select></label>
        <label className="text-xs text-slate-400">{t("settings.theme")}<select value={value.theme} onChange={(event) => update("theme", event.target.value as "dark" | "light")} className="mt-1.5 w-full rounded-lg border border-white/10 bg-black/25 px-3 py-2 text-sm text-slate-100"><option value="dark">{t("theme.dark")}</option><option value="light">{t("theme.light")}</option></select></label>
      </div>}
      {section === "plugins" && <div className="space-y-3"><Field label="Cesium Ion Token" type="password" value={value.cesiumIonToken} onChange={(next) => update("cesiumIonToken", next)} /><Field label="KeepTrack API Key" type="password" value={value.keeptrackApiKey} onChange={(next) => update("keeptrackApiKey", next)} /><p className="text-xs leading-5 text-slate-500">Used only by the local Ground service to look up NORAD data.</p></div>}
      {section === "ai" && <><div className="mb-4 rounded-xl border border-cyan-300/50 bg-cyan-300/10 p-3 text-left text-sm text-cyan-100">Jetson GPU<div className="mt-1 text-[10px] opacity-70">Remote GPU payload</div></div><div className="mb-4 space-y-4 rounded-xl border border-cyan-300/20 bg-cyan-300/[.04] p-3"><div className="grid gap-4 sm:grid-cols-2"><Field label="Jetson host" value={value.jetsonHost} onChange={(next) => update("jetsonHost", next)} placeholder="192.168.1.20" /><Field label="SSH username" value={value.jetsonSshUsername} onChange={(next) => update("jetsonSshUsername", next)} placeholder="ubuntu" /><Field label="Jetson API port" type="number" value={value.jetsonApiPort} onChange={(next) => update("jetsonApiPort", Number(next) || 8002)} /><Field label="Jetson GTX port" type="number" value={value.jetsonGtxPort} onChange={(next) => update("jetsonGtxPort", Number(next) || 9101)} /><Field label="LAN address" value={value.desktopAdvertiseHost} onChange={(next) => update("desktopAdvertiseHost", next)} placeholder="192.168.1.10" /><Field label="Platform result port" type="number" value={value.platformGtxResultPort} onChange={(next) => update("platformGtxResultPort", Number(next) || 9102)} /></div><div className="border-t border-cyan-300/15 pt-3"><div className="flex items-center justify-between gap-3"><div><div className="text-sm text-cyan-100">Jetson Deployment</div><div className="mt-1 text-xs text-slate-400">Status: {value.jetsonDeploymentStatus}{value.jetsonDeploymentVersion ? ` · ${value.jetsonDeploymentVersion}` : ""}</div></div></div><Field label="SSH password (stored securely in this app)" type="password" value={jetsonPassword} onChange={setJetsonPassword} /><div className="mt-3 flex flex-wrap gap-2"><button disabled={working || !jetsonPassword || Boolean(value.jetsonHostKeyFingerprint)} onClick={() => void discoverJetson()} className="rounded-lg border border-cyan-300/45 px-3 py-2 text-xs text-cyan-100 disabled:opacity-40">Confirm host key</button><button disabled={working || !jetsonPassword || !value.jetsonHostKeyFingerprint} onClick={() => void deployJetson("application")} className="rounded-lg border border-cyan-300/45 bg-cyan-300/10 px-3 py-2 text-xs text-cyan-100 disabled:opacity-40">Deploy application</button><button disabled={working || !jetsonPassword || !value.jetsonHostKeyFingerprint} onClick={() => void deployJetson("initialize")} className="rounded-lg border border-orange-300/40 px-3 py-2 text-xs text-orange-200 disabled:opacity-40">Initialize + deploy</button></div>{jetsonStage && <p className="mt-3 text-xs text-cyan-200">{jetsonStage}</p>}{jetsonLogs.length > 0 && <pre className="mt-3 h-44 overflow-x-auto overflow-y-scroll whitespace-pre-wrap break-words rounded-lg bg-black/20 p-2 text-[10px] text-slate-300">{jetsonLogs.join("")}</pre>}</div></div></>}
      {section === "ai" && <><div className="grid gap-4 sm:grid-cols-2"><label className="block text-xs text-slate-400">Jetson vision model<select value={value.llmModel} onChange={(event) => update("llmModel", event.target.value)} className="mt-1.5 w-full rounded-lg border border-white/10 bg-black/25 px-3 py-2 text-sm text-slate-100"><option value="">Select a vision model</option>{visionModels.map((model) => <option key={model.name} value={model.name}>{model.name}</option>)}</select></label><Field label={t("settings.timeout")} type="number" value={value.providerTimeoutSeconds} onChange={(next) => update("providerTimeoutSeconds", Number(next) || 300)} /></div><div className="mt-4 rounded-xl border border-cyan-300/20 bg-cyan-300/[.04] p-3"><div className="text-sm text-cyan-100">Jetson Ollama models</div><div className="mt-1 text-xs text-slate-400">Install a vision model on Jetson; the successful model becomes the current LLM model.</div><div className="mt-3 grid gap-2 sm:grid-cols-[1fr_auto]"><input value={modelToInstall} onChange={(event) => setModelToInstall(event.target.value)} placeholder="qwen3-vl:8b" className="rounded-lg border border-white/10 bg-black/25 px-3 py-2 text-sm text-slate-100" /><button disabled={working || !jetsonPassword || !value.jetsonHostKeyFingerprint || !modelToInstall.trim()} onClick={() => void installJetsonModel()} className="rounded-lg border border-cyan-300/45 bg-cyan-300/10 px-3 py-2 text-xs text-cyan-100 disabled:opacity-40">Install model</button></div><p className="mt-2 text-[10px] text-slate-500">Recommended: qwen3-vl:4b, qwen3-vl:8b, qwen3-vl:30b.</p></div></>}
      {section === "scene" && <div className="space-y-4"><p className="text-xs leading-5 text-slate-500">{t("settings.sceneDescription")}</p><label className="block text-xs text-slate-400">{t("settings.activeScenario")}<select value={value.activeScenarioId} disabled={working} onChange={(event) => { const selected = scenarios.find((item) => item.config.id === event.target.value); if (!selected) return; setWorking(true); setError(undefined); void Promise.resolve(onScenarioSelected?.(selected)).then(() => update("activeScenarioId", selected.config.id)).catch((cause) => setError(cause instanceof Error ? cause.message : String(cause))).finally(() => setWorking(false)); }} className="mt-1.5 w-full rounded-lg border border-white/10 bg-black/25 px-3 py-2 text-sm text-slate-100">{scenarios.map((item) => <option key={item.config.id} value={item.config.id} disabled={!item.config.scene_ready}>{item.config.name}{item.config.scene_ready ? "" : ` (${t("settings.geoTiffRequired")})`}</option>)}</select></label><div className="border-t border-white/[.07] pt-4"><label className="block text-xs text-slate-400">YAML<input className="mt-1.5 block w-full text-xs" type="file" accept=".yaml,.yml" onChange={(event) => setYamlFile(event.target.files?.[0])} /></label><button disabled={!yamlFile || working} onClick={() => void importYaml()} className="mt-2 rounded-lg border border-cyan-300/50 px-3 py-2 text-xs text-cyan-100">{t("settings.importYaml")}</button></div>{sceneNotice && <p className="text-xs text-emerald-300">{sceneNotice}</p>}</div>}
      {section === "data" && <div className="w-full space-y-2 md:w-1/2">{(["simulation-data", "catalog-caches", "settings-defaults"] as DesktopResetAction[]).map((action) => <div key={action} className={`reset-row rounded-xl border px-3 py-2.5 ${pendingReset === action ? "reset-row--active" : ""}`}><div className="flex flex-wrap items-center justify-between gap-3"><div className="flex min-w-0 items-center gap-2"><h3 className="truncate text-sm font-medium">{t(`settings.reset.${action}.title`)}</h3><span tabIndex={0} role="img" aria-label={t(`settings.reset.${action}.tooltip`)} title={t(`settings.reset.${action}.tooltip`)} className="reset-help shrink-0"><CircleAlert size={16} /></span></div><button disabled={working} onClick={() => { setPendingReset(action); setResetConfirmation(""); setError(undefined); setResetNotice(undefined); }} className="reset-action rounded-lg border px-3 py-1.5 text-xs font-medium disabled:opacity-50">{t("settings.resetAction")}</button></div>{pendingReset === action && <div className="reset-confirm mt-3 border-t pt-3"><p className="text-xs leading-5">{t(needsResetToken ? "settings.resetType" : "settings.resetConfirm")}</p>{needsResetToken && <input autoFocus value={resetConfirmation} onChange={(event) => setResetConfirmation(event.target.value)} placeholder="RESET" className="mt-2 w-full rounded-lg border border-white/10 bg-black/25 px-3 py-2 font-mono text-sm text-slate-100 outline-none focus:border-orange-300/50" />}<div className="mt-3 flex gap-2"><button disabled={working || (needsResetToken && resetConfirmation !== "RESET")} onClick={() => void runReset()} className="reset-action inline-flex items-center gap-1.5 rounded-lg border px-3 py-2 text-xs font-medium disabled:opacity-50">{working && <LoaderCircle size={14} className="animate-spin" />}{t("settings.resetConfirmButton")}</button><button disabled={working} onClick={() => { setPendingReset(undefined); setResetConfirmation(""); }} className="rounded-lg border border-white/10 px-3 py-2 text-xs text-slate-300">{t("settings.resetCancel")}</button></div></div>}</div>)}</div>}
      {section === "about" && <div className="rounded-xl border border-white/[.07] bg-black/20 p-4 text-sm text-slate-300"><div className="text-cyan-200">{t("settings.softwareVersion")}</div><div className="mt-3 font-mono text-lg text-cyan-100">SIL ONLINE · v0.1.2</div><div className="mt-5 text-cyan-200">{t("settings.publisher")}</div><a href="https://www.spacezenith.ai" target="_blank" rel="noreferrer" onClick={(event) => { if (typeof bridge?.openExternal !== "function") return; event.preventDefault(); void bridge.openExternal("https://www.spacezenith.ai").catch(() => window.open("https://www.spacezenith.ai", "_blank", "noopener,noreferrer")); }} className="mt-2 inline-block text-left text-sm text-cyan-100 underline decoration-cyan-300/40 underline-offset-4 hover:text-cyan-300">www.spacezenith.ai</a></div>}
      {error && <p className="mt-4 rounded-lg border border-orange-300/25 bg-orange-300/10 px-3 py-2 text-xs text-orange-200">{error}</p>}
      {resetNotice && <p className="mt-4 rounded-lg border border-emerald-300/25 bg-emerald-300/10 px-3 py-2 text-xs text-emerald-200">{resetNotice}</p>}
      {section !== "data" && section !== "agent" && <div className="mt-5 flex flex-wrap justify-end gap-2">
        <button disabled={working} onClick={() => void save()} className="inline-flex items-center gap-1.5 rounded-lg border border-cyan-300/50 bg-cyan-300/15 px-3 py-2 text-xs text-cyan-100 disabled:opacity-50">{working && <LoaderCircle size={14} className="animate-spin" />}{t("settings.save")}</button>
      </div>}
      {section === "agent" && <div className="space-y-4">
        <div className="rounded-xl border border-cyan-300/20 bg-cyan-300/[.04] p-3">
          <label className="flex cursor-pointer items-center justify-between gap-3 text-sm text-cyan-100">
            <span><span className="block">{t("settings.agent.enabled")}</span><span className="mt-1 block text-xs text-slate-400">{t("settings.agent.enabledHint")}</span></span>
            <input type="checkbox" checked={value.agentEnabled} onChange={(event) => {
              const enabled = event.target.checked;
              update("agentEnabled", enabled);
              if (enabled && !value.agentModel && value.llmModel) update("agentModel", value.llmModel);
            }} className="h-4 w-4 accent-cyan-300" />
          </label>
        </div>
        <label className="block text-xs text-slate-400">{t("settings.agent.model")}
          <select disabled={!value.agentEnabled} value={value.agentModel} onChange={(event) => update("agentModel", event.target.value)} className="mt-1.5 w-full rounded-lg border border-white/10 bg-black/25 px-3 py-2 text-sm text-slate-100 disabled:opacity-50">
            <option value="">{t("settings.agent.selectModel")}</option>
            {visionModels.map((model) => <option key={model.name} value={model.name}>{model.name}</option>)}
          </select>
          <span className="mt-1 block text-[10px] text-slate-500">{t("settings.agent.modelHint")}</span>
        </label>
        <TextArea label={t("settings.agent.systemPrompt")} value={value.agentSystemPrompt} onChange={(next) => update("agentSystemPrompt", next)} />
        <fieldset disabled={!value.agentEnabled} className="rounded-xl border border-white/10 p-3 disabled:opacity-50">
          <legend className="px-1 text-sm text-cyan-100">{t("settings.agent.tools")}</legend>
          <p className="mb-3 text-xs text-slate-400">{t("settings.agent.toolsHint")}</p>
          {(["mission_context", "verified_products", "l1b_metadata"] as const).map((tool) => <label key={tool} className="mb-2 flex cursor-pointer items-start gap-2 text-xs text-slate-300 last:mb-0"><input type="checkbox" checked={value.agentTools.includes(tool)} onChange={(event) => update("agentTools", event.target.checked ? [...value.agentTools, tool] : value.agentTools.filter((item) => item !== tool))} className="mt-0.5 h-3.5 w-3.5 accent-cyan-300" /><span>{t(`settings.agent.tool.${tool}`)}</span></label>)}
        </fieldset>
        <p className="text-xs leading-5 text-slate-500">{t("settings.agent.restartHint")}</p>
      </div>}
      {section === "agent" && <div className="mt-5 flex flex-wrap justify-end gap-2">
        <button disabled={working} onClick={() => void save()} className="inline-flex items-center gap-1.5 rounded-lg border border-cyan-300/50 bg-cyan-300/15 px-3 py-2 text-xs text-cyan-100 disabled:opacity-50">{working && <LoaderCircle size={14} className="animate-spin" />}{t("settings.save")}</button>
      </div>}
    </section>
  </div>;
}
