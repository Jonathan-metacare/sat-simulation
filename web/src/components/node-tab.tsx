"use client";

import { useEffect, useState } from "react";
import Image from "next/image";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Cpu, Database, Download, FileArchive, FileImage, Radio, Satellite, ScanLine, ShieldCheck, Upload } from "lucide-react";

import { api, nodeArtifactURL } from "~/lib/api";
import { translate } from "~/lib/i18n";
import type { Locale } from "~/lib/store";
import type { AIMode, MissionDetail, NodeArtifact, NodeKind, NodeSnapshot, ProcessorStage, ProcessorVersion, ScenarioConfig } from "~/lib/types";

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
      setStatus(locale === "zh"
        ? `导入成功：${validation.asset.width}×${validation.asset.height}，新任务将冻结此版本。`
        : `Imported: ${validation.asset.width}×${validation.asset.height}. New missions will freeze this version.`);
      onChanged?.();
    } catch (cause) { setStatus(cause instanceof Error ? cause.message : String(cause)); }
    finally { setBusy(false); }
  };
  return <>
    <section className="panel rounded-2xl p-4">
      <div className="mb-3 flex items-center gap-2 text-sm text-cyan-100"><Upload size={15} />{locale === "zh" ? "光学场景输入" : "Optical Scene Input"}</div>
      <p className="mb-3 text-xs leading-5 text-slate-500">{locale === "zh" ? "GeoTIFF 保留原始地理参考；PNG/JPEG 会按下方参数转换为版本化 16-bit GeoTIFF。导入图片是仿真环境输入，不是 RAW。" : "GeoTIFF keeps its georeference. PNG/JPEG is converted to a versioned 16-bit GeoTIFF using the fields below. An imported image is simulation input, not RAW."}</p>
      {locked && <p className="mb-3 rounded-lg border border-orange-300/20 bg-orange-300/[.07] px-3 py-2 text-xs text-orange-200">{locale === "zh" ? `当前任务已冻结场景资产：${frozenAssetName ?? "未知资产"}；L0 处理器：${frozenL0Processor ?? "builtin-l0"}。` : `This mission has frozen scene asset: ${frozenAssetName ?? "unknown asset"}; L0 processor: ${frozenL0Processor ?? "builtin-l0"}.`}</p>}
      <div className="grid min-w-0 grid-cols-2 gap-4">
        <article className="min-w-0 rounded-xl border border-emerald-300/45 bg-emerald-300/[.08] p-4">
          <div className="flex items-start justify-between gap-3"><div><h4 className="text-sm font-medium text-cyan-100">16-bit GeoTIFF</h4><p className="mt-2 text-xs leading-5 text-slate-500">{locale === "zh" ? "保留文件内的 CRS 和地理参考；无需额外定位参数。" : "Keeps the CRS and georeference embedded in the file; no extra location fields."}</p></div>{isRaster && <span className="shrink-0 rounded-full border border-emerald-300/30 px-2 py-1 text-[10px] text-emerald-300">{locale === "zh" ? "已选择" : "SELECTED"}</span>}</div>
          <div className="mt-4 flex flex-wrap items-center gap-2"><input id="optical-geotiff" disabled={locked} type="file" accept=".tif,.tiff,image/tiff" onChange={(event) => setFile(event.target.files?.[0])} className="sr-only" /><label htmlFor="optical-geotiff" className={`rounded-lg border border-emerald-300/30 bg-emerald-300/[.08] px-3 py-1.5 text-xs text-emerald-200 transition ${locked ? "cursor-not-allowed opacity-40" : "cursor-pointer hover:border-emerald-300/50"}`}>{locale === "zh" ? "选择 GeoTIFF" : "Choose GeoTIFF"}</label>{isRaster && file && <span className="max-w-40 truncate text-[10px] text-slate-500" title={file.name}>{file.name}</span>}<button disabled={locked || !isRaster || busy} onClick={() => void importScene()} className="rounded-lg border border-emerald-300/30 bg-emerald-300/[.08] px-3 py-1.5 text-xs text-emerald-200 disabled:opacity-40">{busy ? (locale === "zh" ? "导入中…" : "Importing…") : (locale === "zh" ? "校验并导入" : "Validate & Import")}</button></div>
        </article>
        <article className="min-w-0 rounded-xl border border-emerald-300/45 bg-emerald-300/[.08] p-4">
          <div className="flex items-start justify-between gap-3"><div><h4 className="text-sm font-medium text-cyan-100">PNG / JPEG</h4><p className="mt-2 text-xs leading-5 text-slate-500">{locale === "zh" ? "需要填写地理定位参数；导入后转换为版本化 16-bit GeoTIFF。" : "Requires geolocation parameters and is converted to a versioned 16-bit GeoTIFF."}</p></div>{file && !isRaster && <span className="shrink-0 rounded-full border border-emerald-300/30 px-2 py-1 text-[10px] text-emerald-300">{locale === "zh" ? "已选择" : "SELECTED"}</span>}</div>
          <div className="mt-4 flex flex-wrap items-center gap-2"><input id="optical-image" disabled={locked} type="file" accept=".png,.jpg,.jpeg,image/png,image/jpeg" onChange={(event) => setFile(event.target.files?.[0])} className="sr-only" /><label htmlFor="optical-image" className={`rounded-lg border border-emerald-300/30 bg-emerald-300/[.08] px-3 py-1.5 text-xs text-emerald-200 transition ${locked ? "cursor-not-allowed opacity-40" : "cursor-pointer hover:border-emerald-300/50"}`}>{locale === "zh" ? "选择图片" : "Choose image"}</label>{file && !isRaster && <span className="max-w-32 truncate text-[10px] text-slate-500" title={file.name}>{file.name}</span>}</div>
          <div className="mt-3 grid grid-cols-2 gap-2"><Input value={centerLatitude} onChange={setCenterLatitude} label={locale === "zh" ? "中心纬度" : "Center lat"} disabled={locked || Boolean(isRaster)} /><Input value={centerLongitude} onChange={setCenterLongitude} label={locale === "zh" ? "中心经度" : "Center lon"} disabled={locked || Boolean(isRaster)} /><Input value={pixelSize} onChange={setPixelSize} label={locale === "zh" ? "像元大小" : "Pixel size"} disabled={locked || Boolean(isRaster)} /><Input value={crs} onChange={setCrs} label="CRS" disabled={locked || Boolean(isRaster)} /></div>
          <button disabled={locked || !file || Boolean(isRaster) || busy} onClick={() => void importScene()} className="mt-3 rounded-lg border border-emerald-300/30 bg-emerald-300/[.08] px-3 py-1.5 text-xs text-emerald-200 disabled:opacity-40">{busy ? (locale === "zh" ? "导入中…" : "Importing…") : (locale === "zh" ? "校验、转换并导入" : "Validate, convert & import")}</button>
        </article>
      </div>
      <div className="mt-3 flex flex-wrap gap-3 text-[10px] text-slate-500"><span>{locale === "zh" ? "活动资产" : "Active asset"}: {scenario.scene_asset_id ?? scenario.scene_id}</span><span>SHA / CRC {locale === "zh" ? "由 Optical 与 Ground 双端校验" : "verified by Optical and Ground"}</span></div>
      {status && <div className="mt-3 rounded-lg border border-cyan-300/15 bg-black/15 px-3 py-2 text-xs text-slate-300">{status}</div>}
    </section>
    <ProcessorConfiguration stage="l0" scenario={scenario} locale={locale} onChanged={onChanged} locked={locked} frozenProcessorId={frozenL0Processor} />
  </>;
}

function ProcessorConfiguration({ stage, scenario, locale, onChanged, locked = false, frozenProcessorId }: { stage: ProcessorStage; scenario: ScenarioConfig; locale: Locale; onChanged?: () => void; locked?: boolean; frozenProcessorId?: string }) {
  const [processors, setProcessors] = useState<ProcessorVersion[]>([]);
  const [selected, setSelected] = useState(stage === "l0" ? scenario.l0_processor_id : scenario.l1_processor_id);
  const [bundle, setBundle] = useState<File>();
  const [status, setStatus] = useState<string>();
  const [busy, setBusy] = useState(false);
  useEffect(() => { void api.processors(stage).then(setProcessors).catch((cause) => setStatus(String(cause))); }, [stage]);
  useEffect(() => setSelected(stage === "l0" ? scenario.l0_processor_id : scenario.l1_processor_id), [scenario, stage]);
  const builtin = stage === "l0" ? "builtin-l0" : "builtin-l1";
  const customActive = selected !== builtin;
  const save = async (processorId = selected) => {
    setBusy(true); setStatus(undefined);
    try {
      await api.selectProcessors(scenario.id, stage === "l0" ? processorId : scenario.l0_processor_id, stage === "l1" ? processorId : scenario.l1_processor_id);
      setSelected(processorId);
      setStatus(locale === "zh" ? "已保存；仅后续新任务使用该处理器。" : "Saved. This processor applies only to subsequent missions.");
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
      await save(imported.id);
    } catch (cause) { setStatus(cause instanceof Error ? cause.message : String(cause)); setBusy(false); }
  };
  return <section className="panel rounded-2xl p-4">
    <div className="mb-3 flex items-center justify-between gap-3"><h3 className="flex items-center gap-2 text-sm text-cyan-100"><FileArchive size={15} />{stage.toUpperCase()} {locale === "zh" ? "处理器" : "Processor"}</h3><span className="rounded border border-orange-300/20 bg-orange-300/[.07] px-2 py-1 text-[10px] text-orange-200">OCI SANDBOX</span></div>
    <p className="mb-3 text-xs leading-5 text-slate-500">{locale === "zh" ? `为后续新任务选择 ${stage.toUpperCase()} 处理方式。当前任务始终使用创建时冻结的处理器版本。` : `Choose the ${stage.toUpperCase()} processing mode for subsequent missions. The current mission always uses its frozen processor version.`}</p>
    {locked && <p className="mb-3 rounded-lg border border-orange-300/20 bg-orange-300/[.07] px-3 py-2 text-xs text-orange-200">{locale === "zh" ? `当前任务已冻结 ${stage.toUpperCase()} 处理器：${frozenProcessorId ?? builtin}。` : `This mission has frozen ${stage.toUpperCase()} processor: ${frozenProcessorId ?? builtin}.`}</p>}
    <div className="grid min-w-0 grid-cols-2 gap-4">
      <article className={`min-w-0 rounded-xl border p-4 transition ${!customActive ? "border-emerald-300/45 bg-emerald-300/[.08]" : "border-white/[.08] bg-black/[.12]"}`}>
        <div className="flex items-start justify-between gap-3"><div className="min-w-0"><div className="flex items-center gap-2 text-sm font-medium text-cyan-100"><ShieldCheck size={16} className="shrink-0 text-emerald-300" />{locale === "zh" ? "Built-in · 内置处理" : "Built-in Processing"}</div><p className="mt-2 text-xs leading-5 text-slate-500">{locale === "zh" ? `使用 ${stage === "l0" ? "Optical" : "GPU Payload"} 内部可信处理链，不运行用户代码，不需要 Docker。` : `Runs the trusted internal ${stage === "l0" ? "Optical" : "GPU Payload"} pipeline. No user code, no Docker required.`}</p></div><span className={`shrink-0 rounded-full border px-2 py-1 text-[10px] ${!customActive ? "border-emerald-300/30 text-emerald-300" : "border-white/10 text-slate-500"}`}>{!customActive ? (locale === "zh" ? "默认生效" : "DEFAULT") : (locale === "zh" ? "备用" : "FALLBACK")}</span></div>
        <div className="mt-4 flex flex-wrap items-center gap-2"><code className="rounded bg-black/20 px-2 py-1 text-[10px] text-slate-400">{builtin}</code>{customActive ? <button disabled={locked || busy} onClick={() => void save(builtin)} className="rounded-lg border border-emerald-300/30 bg-emerald-300/[.08] px-3 py-1.5 text-xs text-emerald-200 disabled:opacity-40">{locale === "zh" ? "清除自定义" : "Clear custom"}</button> : <span className="text-[10px] text-slate-500">{locale === "zh" ? "未配置自定义处理器时自动使用" : "Used automatically when custom is not configured"}</span>}</div>
      </article>
      <article className="min-w-0 rounded-xl border border-emerald-300/45 bg-emerald-300/[.08] p-4 transition">
        <div className="flex items-start justify-between gap-3"><div><div className="flex items-center gap-2 text-sm font-medium text-cyan-100"><FileArchive size={16} className="text-emerald-300" />{locale === "zh" ? "Customized · 自定义处理" : "Customized Processing"}</div><p className="mt-2 text-xs leading-5 text-slate-500">{locale === "zh" ? "上传 Python 3.12 ZIP。代码仅在无网络、非 root、资源受限的 OCI 容器中执行。" : "Upload a Python 3.12 ZIP. Code runs only in a network-disabled, non-root, resource-limited OCI container."}</p></div>{selected !== builtin && <span className="rounded-full border border-emerald-300/30 px-2 py-1 text-[10px] text-emerald-300">{locale === "zh" ? "当前使用" : "ACTIVE"}</span>}</div>
        <div className="mt-4"><div className="mb-1.5 text-[10px] font-medium tracking-wider text-slate-500 uppercase">{locale === "zh" ? "1 · 选择已导入处理器" : "1 · Select an uploaded processor"}</div><div className="flex flex-wrap items-center gap-2"><select disabled={locked} value={customActive ? selected : ""} onChange={(event) => setSelected(event.target.value)} className="w-52 max-w-full rounded-lg border border-emerald-300/45 bg-sky-50/90 px-3 py-1.5 text-xs text-slate-700 shadow-sm disabled:opacity-40 dark:bg-slate-900/80 dark:text-slate-100"><option value="" disabled>{locale === "zh" ? "选择已上传的处理器" : "Choose uploaded processor"}</option>{processors.map((item) => <option key={item.id} value={item.id}>{item.definition.name} · {item.definition.version}</option>)}</select><button disabled={locked || busy || !customActive} onClick={() => void save()} className="rounded-lg border border-emerald-300/30 px-3 py-1.5 text-xs text-emerald-200 disabled:opacity-40">{locale === "zh" ? "启用" : "Activate"}</button></div></div>
        <div className="mt-3"><div className="mb-1.5 text-[10px] font-medium tracking-wider text-slate-500 uppercase">{locale === "zh" ? "2 · 导入新的处理器 ZIP" : "2 · Import a new processor ZIP"}</div><div className="flex flex-wrap items-center gap-2"><input id={`processor-bundle-${stage}`} disabled={locked} type="file" accept=".zip,application/zip" onChange={(event) => setBundle(event.target.files?.[0])} className="sr-only" /><label htmlFor={`processor-bundle-${stage}`} className={`rounded-lg border border-emerald-300/30 bg-emerald-300/[.08] px-3 py-1.5 text-xs text-emerald-200 transition ${locked ? "cursor-not-allowed opacity-40" : "cursor-pointer hover:border-emerald-300/50"}`}>{locale === "zh" ? "选择 ZIP 文件" : "Choose ZIP"}</label>{bundle && <span className="max-w-36 truncate text-[10px] text-slate-400" title={bundle.name}>{bundle.name}</span>}<button disabled={locked || !bundle || busy} onClick={() => void upload()} className="rounded-lg border border-emerald-300/30 bg-emerald-300/[.08] px-3 py-1.5 text-xs text-emerald-200 disabled:opacity-40">{locale === "zh" ? "校验、导入并启用" : "Validate, import & activate"}</button></div></div>
        <div className="mt-3 text-[10px] leading-4 text-orange-300">{locale === "zh" ? "需要本机 Docker/兼容 OCI Runtime 与 processor-python 镜像；不可用时任务会停在 blocked。" : "Requires local Docker/compatible OCI runtime and the processor-python image; unavailable runtime blocks the mission."}</div>
      </article>
    </div>
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
