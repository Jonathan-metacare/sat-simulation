"use client";

import { useEffect, useState } from "react";
import Image from "next/image";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Cpu, Database, Download, FileImage, Radio, Satellite, ScanLine, ShieldCheck } from "lucide-react";

import { api, nodeArtifactURL } from "~/lib/api";
import { translate } from "~/lib/i18n";
import type { Locale } from "~/lib/store";
import type { AIMode, MissionDetail, NodeArtifact, NodeKind, NodeSnapshot } from "~/lib/types";

const titles: Record<Exclude<NodeKind, "ground">, { title: Parameters<typeof translate>[1]; subtitle: Parameters<typeof translate>[1] }> = {
  platform: { title: "node.platform.title", subtitle: "node.platform.subtitle" },
  optical: { title: "node.optical.title", subtitle: "node.optical.subtitle" },
  gpu: { title: "node.gpu.title", subtitle: "node.gpu.subtitle" },
};

export function NodeTab({ node, mission, providerHealth, activeAiMode, gtxLink, locale = "zh" }: {
  node: Exclude<NodeKind, "ground">; mission?: MissionDetail;
  providerHealth: Record<string, { status: string }>;
  activeAiMode: AIMode;
  gtxLink?: { bandwidth_bps: number; latency_ms: number; frame_payload_bytes: number };
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
      {mission && mission.ai_mode !== activeAiMode && <p className="mt-2 text-[10px] leading-4 text-orange-300">{t("mission.modeLocked", { missionMode: mission.ai_mode.toUpperCase(), activeMode: activeAiMode.toUpperCase() })}</p>}
    </section>}

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
