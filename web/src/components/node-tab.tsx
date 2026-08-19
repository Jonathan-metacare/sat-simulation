"use client";

import { useEffect, useState } from "react";
import Image from "next/image";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Cpu, Database, Download, FileArchive, FileImage, Radio, Satellite, ScanLine, ShieldCheck, Upload } from "lucide-react";

import { api, nodeArtifactURL, processorDownloadURL } from "~/lib/api";
import { translate } from "~/lib/i18n";
import type { Locale } from "~/lib/store";
import type { AIMode, MissionDetail, NodeArtifact, NodeKind, NodeSnapshot, ProcessorSource, ProcessorStage, ProcessorVersion, ScenarioConfig } from "~/lib/types";

const titles: Record<Exclude<NodeKind, "ground">, { title: Parameters<typeof translate>[1]; subtitle: Parameters<typeof translate>[1] }> = {
  platform: { title: "node.platform.title", subtitle: "node.platform.subtitle" },
  optical: { title: "node.optical.title", subtitle: "node.optical.subtitle" },
  gpu: { title: "node.gpu.title", subtitle: "node.gpu.subtitle" },
};

export function NodeTab({ node, mission, providerHealth, activeAiMode, gtxLink, scenario, onConfigurationChanged, locale = "zh" }: {
  node: Exclude<NodeKind, "ground">; mission?: MissionDetail;
  providerHealth: Record<string, { status: string }>;
  activeAiMode: AIMode;
  gtxLink?: { bandwidth_bps: number; latency_ms: number; frame_payload_bytes: number };
  scenario?: ScenarioConfig;
  onConfigurationChanged?: () => void;
  locale?: Locale;
}) {
  const t = (key: Parameters<typeof translate>[1], values?: Parameters<typeof translate>[2]) =>
    translate(locale, key, values);
  const [snapshot, setSnapshot] = useState<NodeSnapshot>();
  useEffect(() => {
    if (!mission) { setSnapshot(undefined); return; }
    let active = true;
    const load = () => api.node(mission.command.id, node).then((value) => active && setSnapshot(value));
    void load();
    const timer = window.setInterval(() => void load(), mission.execution_state === "running" ? 800 : 5000);
    return () => { active = false; window.clearInterval(timer); };
  }, [mission, node]);

  const info = titles[node];
  const thumbnail = snapshot?.artifacts.find((item) =>
    item.level === "thumbnail" || item.level === "raw_quicklook"
  );
  const aiResult = snapshot?.state.result as { result?: { content?: string; provider?: string; model_version?: string } } | undefined;
  const providerStatus = activeAiMode === "llm"
    ? providerHealth.language?.status
    : providerHealth.detection?.status;
  const observationNotice = snapshot?.observation_notice?.startsWith("仿真观察数据")
    ? t("node.observationNotice")
    : snapshot?.observation_notice?.startsWith("节点当前不可达")
      ? t("node.unreachableNotice")
      : snapshot?.observation_notice;
  const configurationLocked = Boolean(
    mission
    && !["completed", "cancelled"].includes(mission.execution_state)
    && (mission.phase !== "initialized" || mission.execution_state !== "waiting"),
  );
  return <div className="space-y-4">
    <section className="panel rounded-2xl p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div><h2 className="flex items-center gap-2 text-lg font-medium text-slate-100">{node === "platform" ? <Satellite className="text-cyan-300" /> : node === "optical" ? <ScanLine className="text-cyan-300" /> : <Cpu className="text-orange-300" />}{t(info.title)}</h2><p className="mt-1 text-xs text-slate-500">{t(info.subtitle)}</p></div>
        <span className={`rounded-full border px-3 py-1 text-[10px] ${snapshot?.reachable === false ? "border-red-300/30 text-red-300" : "border-emerald-300/25 text-emerald-300"}`}>{snapshot?.reachable === false ? t("node.unreachable") : (snapshot?.status ?? t("node.waiting"))}</span>
      </div>
      {observationNotice && <div className="mt-4 flex items-center gap-2 rounded-lg border border-orange-300/20 bg-orange-300/[.07] px-3 py-2 text-xs text-orange-200"><ShieldCheck size={14} />{observationNotice}</div>}
    </section>

    {node === "platform" && <section className="panel rounded-2xl p-4">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="flex items-center gap-2 text-sm text-cyan-100"><Radio size={15} />{t("node.gtx")}</h3>
        <span className="rounded border border-cyan-300/20 bg-cyan-300/10 px-2 py-1 text-[10px] text-cyan-200">{t("node.gtxPair")}</span>
      </div>
      <div className="grid gap-3 sm:grid-cols-3">
        <NodeMetric label={t("link.bandwidth")} value={formatRate(gtxLink?.bandwidth_bps ?? 0)} />
        <NodeMetric label={t("link.latency")} value={`${gtxLink?.latency_ms ?? 0} ms`} />
        <NodeMetric label={t("node.framePayload")} value={`${gtxLink?.frame_payload_bytes ?? 0} B`} />
      </div>
    </section>}

    {node === "gpu" && <section className="panel rounded-2xl p-4">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="flex items-center gap-2 text-sm text-cyan-100"><Cpu size={15} />{t("node.provider")}</h3>
        <span className="rounded border border-orange-300/20 bg-orange-300/10 px-2 py-1 text-[10px] text-orange-200">{providerStatus ?? "UNKNOWN"}</span>
      </div>
      <p className="text-xs leading-5 text-slate-500">{t("node.providerNote", { mode: activeAiMode.toUpperCase() })}</p>
      {mission && mission.ai_mode !== activeAiMode && <p className="mt-2 text-[10px] leading-4 text-orange-300">{t("mission.modeLocked", { missionMode: mission.ai_mode.toUpperCase(), activeMode: activeAiMode.toUpperCase() })}</p>}
    </section>}
    {node === "gpu" && mission?.ai_mode === "llm" && <MissionPromptEditor mission={mission} locale={locale} onSaved={onConfigurationChanged} />}

    {node === "optical" && scenario && <OpticalConfiguration scenario={scenario} locale={locale} onChanged={onConfigurationChanged} locked={configurationLocked} frozenAssetName={mission?.command.scene_asset?.source_name ?? mission?.command.scene_asset_id} frozenL0Processor={mission?.command.l0_processor_id} />}
    {node === "gpu" && scenario && <ProcessorConfiguration stage="l1" scenario={scenario} locale={locale} onChanged={onConfigurationChanged} locked={configurationLocked} frozenProcessorId={mission?.command.l1_processor_id} />}

    <section className="grid gap-4 xl:grid-cols-[.85fr_1.15fr]">
      <div className="panel rounded-2xl p-4">
        <h3 className="mb-4 flex items-center gap-2 text-sm text-cyan-100"><Database size={15} />{t("node.state")}</h3>
        <pre className="max-h-96 overflow-auto whitespace-pre-wrap break-all rounded-xl border border-white/[.06] bg-black/25 p-3 font-mono text-[11px] leading-5 text-slate-400">{JSON.stringify(snapshot?.state ?? { status: t("node.noState") }, null, 2)}</pre>
      </div>
      <div className="panel rounded-2xl p-4">
        <h3 className="mb-4 flex items-center gap-2 text-sm text-cyan-100"><FileImage size={15} />{t("node.artifacts")}</h3>
        {thumbnail && mission && <div className="relative mb-4 min-h-56 overflow-hidden rounded-xl border border-white/[.06] bg-black/30"><Image unoptimized fill className="object-contain" sizes="50vw" src={nodeArtifactURL(mission.command.id, node, thumbnail.key)} alt="node local thumbnail" /></div>}
        <div className="grid gap-2 sm:grid-cols-2">{snapshot?.artifacts.map((artifact) => <ArtifactCard key={artifact.key} artifact={artifact} missionId={mission!.command.id} node={node} />)}</div>
        {!snapshot?.artifacts.length && <div className="py-10 text-center text-xs text-slate-600">{t("node.noArtifacts")}</div>}
        {node === "gpu" && aiResult?.result?.content && <div className="mt-4 rounded-xl border border-cyan-300/10 bg-black/20 p-4"><div className="mb-2 text-xs text-cyan-100">{t("node.localResult")}</div><div className="llm-markdown max-h-96 overflow-auto"><ReactMarkdown remarkPlugins={[remarkGfm]}>{aiResult.result.content}</ReactMarkdown></div></div>}
      </div>
    </section>
  </div>;
}

function MissionPromptEditor({ mission, locale, onSaved }: { mission: MissionDetail; locale: Locale; onSaved?: () => void }) {
  const [prompt, setPrompt] = useState(mission.command.analysis_prompt);
  const [status, setStatus] = useState<string>();
  const [busy, setBusy] = useState(false);
  const frozen = mission.active_substage === "ai" || ["ai_complete", "completed"].includes(mission.phase);
  useEffect(() => setPrompt(mission.command.analysis_prompt), [mission.command.analysis_prompt, mission.command.id]);

  const save = async () => {
    const next = prompt.trim();
    if (!next) return;
    setBusy(true); setStatus(undefined);
    try {
      await api.updateMissionPrompt(mission.command.id, next);
      setStatus(translate(locale, "mission.promptSaved"));
      onSaved?.();
    } catch (cause) {
      setStatus(cause instanceof Error ? cause.message : String(cause));
    } finally { setBusy(false); }
  };
  return <section className="panel rounded-2xl p-4">
    <div className="mb-3 flex flex-wrap items-center justify-between gap-3"><h3 className="flex items-center gap-2 text-sm text-cyan-100"><FileArchive size={15} />{translate(locale, "mission.editPrompt")}</h3><span className={`rounded border px-2 py-1 text-[10px] ${frozen ? "border-orange-300/20 bg-orange-300/[.07] text-orange-200" : "border-emerald-300/25 text-emerald-300"}`}>{frozen ? translate(locale, "mission.promptFrozenStatus") : translate(locale, "mission.promptEditable")}</span></div>
    <p className="mb-3 text-xs leading-5 text-slate-500">{translate(locale, "mission.editPromptNote")}</p>
    <textarea value={prompt} disabled={frozen || busy} onChange={(event) => setPrompt(event.target.value)} maxLength={2000} rows={5} className="w-full resize-y rounded-xl border border-white/10 bg-black/20 px-3 py-2 text-xs leading-5 text-slate-200 outline-none focus:border-cyan-300/40 disabled:cursor-not-allowed disabled:opacity-50" />
    <div className="mt-3 flex items-center justify-between gap-3"><span className="text-[10px] text-slate-500">{prompt.length}/2000</span>{frozen ? <span className="text-[10px] text-orange-300">{translate(locale, "mission.promptFrozen")}</span> : <button disabled={busy || !prompt.trim() || prompt.trim() === mission.command.analysis_prompt} onClick={() => void save()} className="rounded-lg border border-cyan-300/35 bg-cyan-300/[.08] px-3 py-1.5 text-xs text-cyan-100 disabled:opacity-40">{translate(locale, "mission.promptSave")}</button>}</div>
    {status && <div className="mt-3 rounded-lg border border-cyan-300/15 bg-black/15 px-3 py-2 text-xs text-slate-300">{status}</div>}
  </section>;
}

function OpticalConfiguration({ scenario, locale, onChanged, locked = false, frozenAssetName, frozenL0Processor }: { scenario: ScenarioConfig; locale: Locale; onChanged?: () => void; locked?: boolean; frozenAssetName?: string; frozenL0Processor?: string }) {
  const [file, setFile] = useState<File>();
  const [centerLatitude, setCenterLatitude] = useState("39.9042");
  const [centerLongitude, setCenterLongitude] = useState("116.4074");
  const [pixelSize, setPixelSize] = useState("0.0001");
  const [crs, setCrs] = useState("EPSG:4326");
  const [status, setStatus] = useState<string>();
  const [busy, setBusy] = useState(false);
  const isRaster = file?.name.toLowerCase().match(/\.(tif|tiff)$/);
  const importScene = async () => {
    if (!file) return;
    setBusy(true); setStatus(undefined);
    try {
      const geo = isRaster ? undefined : {
        centerLatitude: Number(centerLatitude), centerLongitude: Number(centerLongitude),
        pixelSize: Number(pixelSize), crs,
      };
      const validation = await api.validateScene(file, scenario.scene_id, geo);
      await api.importScene(file, scenario.scene_id, scenario.id, geo);
      setStatus(translate(locale, "node.sceneImported", {
        width: validation.asset.width,
        height: validation.asset.height,
      }));
      onChanged?.();
    } catch (cause) { setStatus(cause instanceof Error ? cause.message : String(cause)); }
    finally { setBusy(false); }
  };
  return <>
    <section className="panel rounded-2xl p-4">
      <div className="mb-3 flex items-center gap-2 text-sm text-cyan-100"><Upload size={15} />{translate(locale, "node.sceneInput")}</div>
      <p className="mb-3 text-xs leading-5 text-slate-500">{translate(locale, "node.sceneInputNote")}</p>
      {locked && <p className="mb-3 rounded-lg border border-orange-300/20 bg-orange-300/[.07] px-3 py-2 text-xs text-orange-200">{translate(locale, "node.sceneFrozen", { asset: frozenAssetName ?? scenario.scene_asset_id ?? scenario.scene_id, processor: frozenL0Processor ?? "builtin-l0" })}</p>}
      <div className="grid min-w-0 grid-cols-2 gap-4">
        <article className="min-w-0 rounded-xl border border-emerald-300/45 bg-emerald-300/[.08] p-4">
          <div className="flex items-start justify-between gap-3"><div><h4 className="text-sm font-medium text-cyan-100">16-bit GeoTIFF</h4><p className="mt-2 text-xs leading-5 text-slate-500">{translate(locale, "node.geotiffNote")}</p></div>{isRaster && <span className="shrink-0 rounded-full border border-emerald-300/30 px-2 py-1 text-[10px] text-emerald-300">{translate(locale, "node.selected")}</span>}</div>
          <div className="mt-4 flex flex-wrap items-center gap-2"><input id="optical-geotiff" disabled={locked} type="file" accept=".tif,.tiff,image/tiff" onChange={(event) => setFile(event.target.files?.[0])} className="sr-only" /><label htmlFor="optical-geotiff" className={`rounded-lg border border-emerald-300/30 bg-emerald-300/[.08] px-3 py-1.5 text-xs text-emerald-200 transition ${locked ? "cursor-not-allowed opacity-40" : "cursor-pointer hover:border-emerald-300/50"}`}>{translate(locale, "node.chooseGeoTiff")}</label>{isRaster && file && <span className="max-w-40 truncate text-[10px] text-slate-500" title={file.name}>{file.name}</span>}<button disabled={locked || !isRaster || busy} onClick={() => void importScene()} className="rounded-lg border border-emerald-300/30 bg-emerald-300/[.08] px-3 py-1.5 text-xs text-emerald-200 disabled:opacity-40">{busy ? translate(locale, "node.importing") : translate(locale, "node.validateImport")}</button></div>
        </article>
        <article className="min-w-0 rounded-xl border border-emerald-300/45 bg-emerald-300/[.08] p-4">
          <div className="flex items-start justify-between gap-3"><div><h4 className="text-sm font-medium text-cyan-100">PNG / JPEG</h4><p className="mt-2 text-xs leading-5 text-slate-500">{translate(locale, "node.imageNote")}</p></div>{file && !isRaster && <span className="shrink-0 rounded-full border border-emerald-300/30 px-2 py-1 text-[10px] text-emerald-300">{translate(locale, "node.selected")}</span>}</div>
          <div className="mt-4 flex flex-wrap items-center gap-2"><input id="optical-image" disabled={locked} type="file" accept=".png,.jpg,.jpeg,image/png,image/jpeg" onChange={(event) => setFile(event.target.files?.[0])} className="sr-only" /><label htmlFor="optical-image" className={`rounded-lg border border-emerald-300/30 bg-emerald-300/[.08] px-3 py-1.5 text-xs text-emerald-200 transition ${locked ? "cursor-not-allowed opacity-40" : "cursor-pointer hover:border-emerald-300/50"}`}>{translate(locale, "node.chooseImage")}</label>{file && !isRaster && <span className="max-w-32 truncate text-[10px] text-slate-500" title={file.name}>{file.name}</span>}</div>
          <div className="mt-3 grid grid-cols-2 gap-2"><Input value={centerLatitude} onChange={setCenterLatitude} label={translate(locale, "node.centerLatitude")} disabled={locked || Boolean(isRaster)} /><Input value={centerLongitude} onChange={setCenterLongitude} label={translate(locale, "node.centerLongitude")} disabled={locked || Boolean(isRaster)} /><Input value={pixelSize} onChange={setPixelSize} label={translate(locale, "node.pixelSize")} disabled={locked || Boolean(isRaster)} /><Input value={crs} onChange={setCrs} label="CRS" disabled={locked || Boolean(isRaster)} /></div>
          <button disabled={locked || !file || Boolean(isRaster) || busy} onClick={() => void importScene()} className="mt-3 rounded-lg border border-emerald-300/30 bg-emerald-300/[.08] px-3 py-1.5 text-xs text-emerald-200 disabled:opacity-40">{busy ? translate(locale, "node.importing") : translate(locale, "node.validateConvertImport")}</button>
        </article>
      </div>
      <div className="mt-3 flex flex-wrap gap-3 text-[10px] text-slate-500"><span>{translate(locale, "node.activeAsset")}: {scenario.scene_asset_id ?? scenario.scene_id}</span><span>SHA / CRC {translate(locale, "node.sceneIntegrity")}</span></div>
      {status && <div className="mt-3 rounded-lg border border-cyan-300/15 bg-black/15 px-3 py-2 text-xs text-slate-300">{status}</div>}
    </section>
    <ProcessorConfiguration stage="l0" scenario={scenario} locale={locale} onChanged={onChanged} locked={locked} frozenProcessorId={frozenL0Processor} />
  </>;
}

function ProcessorConfiguration({ stage, scenario, locale, onChanged, locked = false, frozenProcessorId }: { stage: ProcessorStage; scenario: ScenarioConfig; locale: Locale; onChanged?: () => void; locked?: boolean; frozenProcessorId?: string }) {
  const [processors, setProcessors] = useState<ProcessorVersion[]>([]);
  const [selected, setSelected] = useState(stage === "l0" ? scenario.l0_processor_id : scenario.l1_processor_id);
  const [bundle, setBundle] = useState<File>();
  const [source, setSource] = useState<ProcessorSource>();
  const [sourceFile, setSourceFile] = useState<"python" | "yaml">("python");
  const [draft, setDraft] = useState("");
  const [workspaceMode, setWorkspaceMode] = useState(false);
  const [processorId, setProcessorId] = useState(`custom-${stage}`);
  const [processorName, setProcessorName] = useState(`Custom ${stage.toUpperCase()} Processor`);
  const [version, setVersion] = useState("1.0.0");
  const [status, setStatus] = useState<string>();
  const [busy, setBusy] = useState(false);
  const builtin = stage === "l0" ? "builtin-l0" : "builtin-l1";
  const activeId = stage === "l0" ? scenario.l0_processor_id : scenario.l1_processor_id;
  const selectedProcessor = processors.find((item) => item.id === selected);
  useEffect(() => { void api.processors(stage).then(setProcessors).catch((cause) => setStatus(String(cause))); }, [stage]);
  useEffect(() => { setSelected(activeId); setWorkspaceMode(false); }, [activeId]);
  useEffect(() => {
    void api.processorSource(selected).then((value) => {
      setSource(value); setDraft(value.processor_py); setWorkspaceMode(false);
      const version = processors.find((item) => item.id === selected);
      if (version) {
        setProcessorId(version.definition.id);
        setProcessorName(version.definition.name);
        setVersion(version.definition.version);
      }
    }).catch((cause) => setStatus(String(cause)));
  }, [processors, selected]);
  const activate = async (nextId = selected) => {
    setBusy(true); setStatus(undefined);
    try {
      await api.selectProcessors(scenario.id, stage === "l0" ? nextId : scenario.l0_processor_id, stage === "l1" ? nextId : scenario.l1_processor_id);
      setSelected(nextId);
      setStatus(translate(locale, "node.processorSaved"));
      onChanged?.();
    } catch (cause) { setStatus(cause instanceof Error ? cause.message : String(cause)); }
    finally { setBusy(false); }
  };
  const upload = async () => {
    if (!bundle) return;
    setBusy(true); setStatus(undefined);
    try {
      const validation = await api.validateProcessor(bundle);
      if (validation.definition.stage !== stage) throw new Error(`processor stage is ${validation.definition.stage}, expected ${stage}`);
      const imported = await api.importProcessor(bundle);
      setProcessors((items) => [imported, ...items.filter((item) => item.id !== imported.id)]);
      await activate(imported.id);
    } catch (cause) { setStatus(cause instanceof Error ? cause.message : String(cause)); setBusy(false); }
  };
  const createCustom = () => {
    setProcessorId(`custom-${stage}`); setProcessorName(`Custom ${stage.toUpperCase()} Processor`); setVersion("1.0.0");
    setDraft(source?.processor_py ?? "");
    setWorkspaceMode(true);
  };
  const saveWorkspace = async () => {
    setBusy(true); setStatus(undefined);
    try {
      const saved = await api.saveProcessorWorkspace(stage, processorId, processorName, version, draft);
      setProcessors((items) => [saved, ...items.filter((item) => item.id !== saved.id)]);
      await activate(saved.id);
      setStatus(translate(locale, "node.workspaceSaved"));
    } catch (cause) { setStatus(cause instanceof Error ? cause.message : String(cause)); }
    finally { setBusy(false); }
  };
  return <section className="panel rounded-2xl p-4">
    <div className="mb-3 flex items-center justify-between gap-3"><h3 className="flex items-center gap-2 text-sm text-cyan-100"><FileArchive size={15} />{stage.toUpperCase()} {translate(locale, "node.workspace")}</h3><span className="rounded border border-emerald-300/25 bg-emerald-300/[.07] px-2 py-1 text-[10px] text-emerald-200">{translate(locale, "node.desktopSandbox")}</span></div>
    <p className="mb-3 text-xs leading-5 text-slate-500">{translate(locale, "node.workspaceNote")}</p>
    {locked && <p className="mb-3 rounded-lg border border-orange-300/20 bg-orange-300/[.07] px-3 py-2 text-xs text-orange-200">{translate(locale, "node.processorFrozen", { stage: stage.toUpperCase(), processor: frozenProcessorId ?? builtin })}</p>}
    <div className="mb-3 flex flex-wrap items-center gap-2"><span className="text-[10px] tracking-wider text-slate-500 uppercase">{translate(locale, "node.currentVersion")}</span><select disabled={locked || busy} value={selected} onChange={(event) => setSelected(event.target.value)} className="w-72 max-w-full rounded-lg border border-cyan-300/30 bg-sky-50/90 px-3 py-1.5 text-xs text-slate-700 dark:bg-slate-900/80 dark:text-slate-100"><option value={builtin}>{builtin} · {translate(locale, "node.builtinProcessing")}</option>{processors.map((item) => <option key={item.id} value={item.id}>{item.definition.name} · {item.definition.version}</option>)}</select><button disabled={locked || busy || selected === activeId || workspaceMode} onClick={() => void activate()} className="rounded-lg border border-cyan-300/30 bg-cyan-300/[.08] px-3 py-1.5 text-xs text-cyan-100 disabled:opacity-40">{translate(locale, "node.activate")}</button><button disabled={locked || busy} onClick={createCustom} className="rounded-lg border border-emerald-300/30 bg-emerald-300/[.08] px-3 py-1.5 text-xs text-emerald-200 disabled:opacity-40">{translate(locale, "node.createCustom")}</button></div>
    <div className="mb-3 flex flex-wrap gap-x-4 gap-y-1 font-mono text-[10px] text-slate-500"><span>{translate(locale, "node.runtime")}: {selectedProcessor?.runtime_type ?? "desktop-sandbox"}</span><span>SHA: {selectedProcessor?.sha256.slice(0, 16) ?? "built-in reference"}</span></div>
    {source && <div className="rounded-xl border border-emerald-300/35 bg-emerald-300/[.06] p-3"><div className="mb-3 flex flex-wrap items-center gap-2"><span className="text-xs text-cyan-100">{translate(locale, "node.processorSource")}</span><button onClick={() => setSourceFile("python")} className={`rounded px-2 py-1 text-[10px] ${sourceFile === "python" ? "bg-cyan-300/15 text-cyan-100" : "text-slate-500"}`}>{translate(locale, "node.pythonSource")}</button><button onClick={() => setSourceFile("yaml")} className={`rounded px-2 py-1 text-[10px] ${sourceFile === "yaml" ? "bg-cyan-300/15 text-cyan-100" : "text-slate-500"}`}>{translate(locale, "node.manifest")}</button><span className="ml-auto font-mono text-[10px] text-slate-500">{workspaceMode ? translate(locale, "node.createCustom") : selected}</span></div>{sourceFile === "yaml" ? <pre className="max-h-64 overflow-auto rounded-lg bg-black/20 p-3 font-mono text-[11px] leading-5 text-slate-300">{source.processor_yaml}</pre> : <textarea value={draft} readOnly={locked || (source.readonly && !workspaceMode)} onChange={(event) => setDraft(event.target.value)} spellCheck={false} className="h-80 w-full resize-y rounded-lg border border-white/10 bg-black/25 p-3 font-mono text-[11px] leading-5 text-slate-200 outline-none focus:border-cyan-300/40 read-only:opacity-75" />}{source.readonly && !workspaceMode && <p className="mt-2 text-[10px] text-slate-500">{translate(locale, "node.sourceReadonly")}</p>}</div>}
    {(workspaceMode || !source?.readonly) && <div className="mt-3 grid gap-2 sm:grid-cols-3"><Input label={translate(locale, "node.processorId")} value={processorId} onChange={setProcessorId} disabled={locked || busy} /><Input label={translate(locale, "node.processorName")} value={processorName} onChange={setProcessorName} disabled={locked || busy} /><Input label={translate(locale, "node.version")} value={version} onChange={setVersion} disabled={locked || busy} /></div>}
    <div className="mt-3 flex flex-wrap items-center gap-2"><a href={processorDownloadURL(selected)} className="rounded-lg border border-white/10 px-3 py-1.5 text-xs text-slate-300">{translate(locale, "node.download")}</a><input id={`processor-bundle-${stage}`} disabled={locked} type="file" accept=".zip,application/zip" onChange={(event) => setBundle(event.target.files?.[0])} className="sr-only" /><label htmlFor={`processor-bundle-${stage}`} className={`rounded-lg border border-emerald-300/30 bg-emerald-300/[.08] px-3 py-1.5 text-xs text-emerald-200 ${locked ? "cursor-not-allowed opacity-40" : "cursor-pointer"}`}>{translate(locale, "node.importZip")}</label>{bundle && <span className="max-w-36 truncate text-[10px] text-slate-400">{bundle.name}</span>}<button disabled={locked || !bundle || busy} onClick={() => void upload()} className="rounded-lg border border-emerald-300/30 px-3 py-1.5 text-xs text-emerald-200 disabled:opacity-40">{translate(locale, "node.importZip")}</button>{(workspaceMode || !source?.readonly) && <button disabled={locked || busy || !draft.trim()} onClick={() => void saveWorkspace()} className="rounded-lg border border-cyan-300/35 bg-cyan-300/[.08] px-3 py-1.5 text-xs text-cyan-100 disabled:opacity-40">{translate(locale, "node.saveActivate")}</button>}</div>
    {status && <div className="mt-3 rounded-lg border border-cyan-300/15 bg-black/15 px-3 py-2 text-xs text-slate-300">{status}</div>}
  </section>;
}

function Input({ label, value, onChange, disabled }: { label: string; value: string; onChange: (value: string) => void; disabled?: boolean }) {
  return <label className="min-w-0 text-[9px] tracking-wider text-slate-500 uppercase"><span className="mb-1 block">{label}</span><input disabled={disabled} value={value} onChange={(event) => onChange(event.target.value)} className="w-full rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-xs normal-case text-slate-200 disabled:opacity-35" /></label>;
}

function formatRate(rate: number) {
  if (rate >= 1e9) return `${(rate / 1e9).toFixed(1)} Gbps`;
  if (rate >= 1e6) return `${(rate / 1e6).toFixed(0)} Mbps`;
  if (rate >= 1e3) return `${(rate / 1e3).toFixed(0)} Kbps`;
  return `${rate} bps`;
}

function NodeMetric({ label, value }: { label: string; value: string }) {
  return <div className="rounded-lg border border-white/[.055] bg-black/15 px-3 py-2"><div className="text-[9px] tracking-wider text-slate-600 uppercase">{label}</div><div className="mt-1 font-mono text-xs text-slate-200">{value}</div></div>;
}

function ArtifactCard({ artifact, missionId, node }: { artifact: NodeArtifact; missionId: string; node: NodeKind }) {
  return <a href={nodeArtifactURL(missionId, node, artifact.key)} target="_blank" rel="noreferrer" className="rounded-xl border border-white/[.06] bg-black/15 p-3 transition hover:border-cyan-300/25"><div className="flex items-center justify-between"><span className="rounded bg-cyan-300/10 px-2 py-1 text-[10px] text-cyan-200">{artifact.level.toUpperCase()}</span><Download size={13} className="text-slate-500" /></div><div className="mt-2 truncate text-xs text-slate-300">{artifact.name}</div><div className="mt-2 truncate font-mono text-[9px] text-slate-600">SHA {artifact.sha256.slice(0, 18)}…</div></a>;
}
