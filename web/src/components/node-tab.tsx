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
      {mission && mission.ai_mode !== activeAiMode && <p className="mt-2 text-[10px] leading-4 text-orange-300">{locale === "zh" ? `当前任务固定使用 ${mission.ai_mode.toUpperCase()}；设置中的 ${activeAiMode.toUpperCase()} 将用于后续新任务。` : `The current mission remains ${mission.ai_mode.toUpperCase()}; ${activeAiMode.toUpperCase()} applies to subsequent missions.`}</p>}
    </section>}

    {node === "optical" && scenario && <OpticalConfiguration scenario={scenario} locale={locale} onChanged={onConfigurationChanged} />}
    {node === "gpu" && scenario && <ProcessorConfiguration stage="l1" scenario={scenario} locale={locale} onChanged={onConfigurationChanged} />}

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

function OpticalConfiguration({ scenario, locale, onChanged }: { scenario: ScenarioConfig; locale: Locale; onChanged?: () => void }) {
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
      <div className="grid gap-3 lg:grid-cols-[1.3fr_repeat(4,minmax(0,.7fr))_auto]">
        <input type="file" accept=".tif,.tiff,.png,.jpg,.jpeg,image/tiff,image/png,image/jpeg" onChange={(event) => setFile(event.target.files?.[0])} className="min-w-0 rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-xs text-slate-300 file:mr-2 file:border-0 file:bg-transparent file:text-cyan-300" />
        <Input value={centerLatitude} onChange={setCenterLatitude} label={locale === "zh" ? "中心纬度" : "Center lat"} disabled={Boolean(isRaster)} />
        <Input value={centerLongitude} onChange={setCenterLongitude} label={locale === "zh" ? "中心经度" : "Center lon"} disabled={Boolean(isRaster)} />
        <Input value={pixelSize} onChange={setPixelSize} label={locale === "zh" ? "像元大小" : "Pixel size"} disabled={Boolean(isRaster)} />
        <Input value={crs} onChange={setCrs} label="CRS" disabled={Boolean(isRaster)} />
        <button disabled={!file || busy} onClick={() => void importScene()} className="rounded-lg border border-cyan-300/30 bg-cyan-300/10 px-4 py-2 text-xs text-cyan-100 disabled:opacity-40">{busy ? (locale === "zh" ? "校验并导入中…" : "Validating…") : (locale === "zh" ? "预检并导入" : "Validate & Import")}</button>
      </div>
      <div className="mt-3 flex flex-wrap gap-3 text-[10px] text-slate-500"><span>{locale === "zh" ? "活动资产" : "Active asset"}: {scenario.scene_asset_id ?? scenario.scene_id}</span><span>SHA / CRC {locale === "zh" ? "由 Optical 与 Ground 双端校验" : "verified by Optical and Ground"}</span></div>
      {status && <div className="mt-3 rounded-lg border border-cyan-300/15 bg-black/15 px-3 py-2 text-xs text-slate-300">{status}</div>}
    </section>
    <ProcessorConfiguration stage="l0" scenario={scenario} locale={locale} onChanged={onChanged} />
  </>;
}

function ProcessorConfiguration({ stage, scenario, locale, onChanged }: { stage: ProcessorStage; scenario: ScenarioConfig; locale: Locale; onChanged?: () => void }) {
  const [processors, setProcessors] = useState<ProcessorVersion[]>([]);
  const [selected, setSelected] = useState(stage === "l0" ? scenario.l0_processor_id : scenario.l1_processor_id);
  const [bundle, setBundle] = useState<File>();
  const [status, setStatus] = useState<string>();
  const [busy, setBusy] = useState(false);
  useEffect(() => { void api.processors(stage).then(setProcessors).catch((cause) => setStatus(String(cause))); }, [stage]);
  useEffect(() => setSelected(stage === "l0" ? scenario.l0_processor_id : scenario.l1_processor_id), [scenario, stage]);
  const builtin = stage === "l0" ? "builtin-l0" : "builtin-l1";
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
    <p className="mb-3 text-xs leading-5 text-slate-500">{locale === "zh" ? `内置 ${stage.toUpperCase()} 不依赖 Docker。自定义 Python 3.12 ZIP 仅在受限 OCI 容器中运行；运行时不可用时任务会 blocked，不会在宿主机降级执行。` : `Built-in ${stage.toUpperCase()} does not require Docker. Custom Python 3.12 ZIP bundles run only inside the restricted OCI sandbox; without a runtime, the mission is blocked and never falls back to host execution.`}</p>
    <div className="grid gap-3 md:grid-cols-[1fr_auto_1fr_auto]">
      <select value={selected} onChange={(event) => setSelected(event.target.value)} className="min-w-0 rounded-lg border border-white/10 bg-slate-950/80 px-3 py-2 text-xs text-slate-200"><option value={builtin}>{builtin}</option>{processors.map((item) => <option key={item.id} value={item.id}>{item.definition.name} · {item.definition.version}</option>)}</select>
      <button disabled={busy} onClick={() => void save()} className="rounded-lg border border-cyan-300/25 px-4 py-2 text-xs text-cyan-200 disabled:opacity-40">{locale === "zh" ? "选择" : "Select"}</button>
      <input type="file" accept=".zip,application/zip" onChange={(event) => setBundle(event.target.files?.[0])} className="min-w-0 rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-xs text-slate-300 file:mr-2 file:border-0 file:bg-transparent file:text-cyan-300" />
      <button disabled={!bundle || busy} onClick={() => void upload()} className="rounded-lg border border-cyan-300/25 px-4 py-2 text-xs text-cyan-200 disabled:opacity-40">{locale === "zh" ? "预检、上传并选择" : "Validate, Upload & Select"}</button>
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
