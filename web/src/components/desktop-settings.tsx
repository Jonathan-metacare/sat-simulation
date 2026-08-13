"use client";

import { useEffect, useState } from "react";
import { FolderOpen, LoaderCircle, RefreshCw, Settings2, X } from "lucide-react";

import { desktopBridge, type DesktopDiagnostics, type DesktopSettings } from "~/lib/desktop";
import type { Locale } from "~/lib/store";

const emptySettings: DesktopSettings = {
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

export function DesktopSettingsPanel({ open, onClose, locale }: { open: boolean; onClose(): void; locale: Locale }) {
  const bridge = desktopBridge();
  const zh = locale === "zh";
  const [value, setValue] = useState<DesktopSettings>(emptySettings);
  const [diagnostics, setDiagnostics] = useState<DesktopDiagnostics>();
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<string>();

  useEffect(() => {
    if (!open || !bridge) return;
    void Promise.all([bridge.getSettings(), bridge.diagnostics()]).then(([saved, details]) => {
      setValue(saved); setDiagnostics(details); setError(undefined);
    }).catch((cause) => setError(cause instanceof Error ? cause.message : String(cause)));
  }, [bridge, open]);

  if (!open || !bridge) return null;
  const update = <K extends keyof DesktopSettings>(key: K, next: DesktopSettings[K]) => setValue((current) => ({ ...current, [key]: next }));
  const save = async () => {
    setWorking(true); setError(undefined);
    try { setValue(await bridge.saveSettings(value)); setDiagnostics(await bridge.diagnostics()); }
    catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { setWorking(false); }
  };
  const restartAll = async () => {
    setWorking(true); setError(undefined);
    try { setDiagnostics(await bridge.restartStack()); }
    catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { setWorking(false); }
  };
  return <div className="fixed inset-0 z-[60] flex items-center justify-center bg-slate-950/80 p-4 backdrop-blur-sm">
    <section className="panel max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-2xl p-5 shadow-2xl shadow-black/60">
      <div className="mb-5 flex items-start justify-between gap-4">
        <div><h2 className="flex items-center gap-2 text-lg font-medium text-cyan-100"><Settings2 size={18} />{zh ? "桌面应用设置" : "Desktop App Settings"}</h2><p className="mt-1 text-xs leading-5 text-slate-500">{zh ? "保存后仅重启 GPU 服务；密钥只保存在本机用户数据目录。" : "Saving restarts only the GPU service. Keys remain in this device's user-data directory."}</p></div>
        <button onClick={onClose} className="rounded-lg border border-white/10 p-2 text-slate-400 hover:text-cyan-100"><X size={16} /></button>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="LLM API URL" value={value.llmApiUrl} onChange={(next) => update("llmApiUrl", next)} placeholder="http://127.0.0.1:11434" />
        <Field label={zh ? "LLM 模型" : "LLM model"} value={value.llmModel} onChange={(next) => update("llmModel", next)} placeholder="qwen3.5:4b" />
        <Field label="LLM API Key" type="password" value={value.llmApiKey} onChange={(next) => update("llmApiKey", next)} />
        <Field label={zh ? "模型超时（秒）" : "Model timeout (seconds)"} type="number" value={value.providerTimeoutSeconds} onChange={(next) => update("providerTimeoutSeconds", Number(next) || 30)} />
        <Field label="YOLO API URL" value={value.yoloApiUrl} onChange={(next) => update("yoloApiUrl", next)} placeholder="http://127.0.0.1:9000" />
        <Field label="YOLO Model" value={value.yoloModel} onChange={(next) => update("yoloModel", next)} />
        <Field label="YOLO API Key" type="password" value={value.yoloApiKey} onChange={(next) => update("yoloApiKey", next)} />
      </div>
      {diagnostics && <div className="mt-5 rounded-xl border border-white/[.07] bg-black/20 p-3 text-xs text-slate-400"><div className="mb-2 text-cyan-200">{zh ? "本地服务状态" : "Local service status"}</div><div className="flex flex-wrap gap-2">{diagnostics.services.map((item) => <span key={item.name} className={`rounded border px-2 py-1 ${item.running ? "border-emerald-300/25 text-emerald-300" : "border-orange-300/25 text-orange-300"}`}>{item.name}: {item.running ? "ready" : "stopped"}</span>)}</div><div className="mt-2 break-all text-[10px] text-slate-600">{diagnostics.dataDirectory}</div></div>}
      {error && <p className="mt-4 rounded-lg border border-orange-300/25 bg-orange-300/10 px-3 py-2 text-xs text-orange-200">{error}</p>}
      <div className="mt-5 flex flex-wrap justify-end gap-2">
        <button onClick={() => void bridge.openDataDirectory()} className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 px-3 py-2 text-xs text-slate-300 hover:text-cyan-100"><FolderOpen size={14} />{zh ? "打开数据目录" : "Open data"}</button>
        <button onClick={() => void bridge.openLogDirectory()} className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 px-3 py-2 text-xs text-slate-300 hover:text-cyan-100"><FolderOpen size={14} />{zh ? "打开日志目录" : "Open logs"}</button>
        <button disabled={working} onClick={() => void restartAll()} className="inline-flex items-center gap-1.5 rounded-lg border border-orange-300/35 px-3 py-2 text-xs text-orange-200 disabled:opacity-50"><RefreshCw size={14} />{zh ? "重启全部服务" : "Restart all"}</button>
        <button disabled={working} onClick={() => void save()} className="inline-flex items-center gap-1.5 rounded-lg border border-cyan-300/50 bg-cyan-300/15 px-3 py-2 text-xs text-cyan-100 disabled:opacity-50">{working && <LoaderCircle size={14} className="animate-spin" />}{zh ? "保存并重启 GPU" : "Save and restart GPU"}</button>
      </div>
    </section>
  </div>;
}
