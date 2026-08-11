"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Image from "next/image";
import {
  Activity, AlertTriangle, Box, CirclePause, CirclePlay, Clock3, Database,
  FileImage, Gauge, LoaderCircle, Orbit, Radio, RefreshCw, RotateCcw,
  ShieldCheck, StepForward, Zap
} from "lucide-react";

import { api, artifactURL } from "~/lib/api";
import { useDashboardStore } from "~/lib/store";
import type {
  MissionStatus, ProductManifest, PublicConfig
} from "~/lib/types";
import { OrbitGlobe } from "./orbit-globe";
import { SystemTopology } from "./system-topology";

const stages: Array<[MissionStatus, string]> = [
  ["planned", "任务规划"], ["uplinking", "指令上注"], ["maneuvering", "姿态机动"],
  ["capturing", "光学成像"], ["l0_processing", "L0 重建"], ["l1a_processing", "L1A"],
  ["l1b_processing", "L1B"], ["gtx_transfer", "GTX"], ["ai_skipped", "AI 占位"],
  ["downlinking", "产品下传"], ["completed", "任务完成"]
];

const statusLabels: Record<MissionStatus, string> = {
  planned: "已规划", uplinking: "上注中", maneuvering: "姿态机动", capturing: "成像中",
  l0_processing: "L0 处理", l1a_processing: "L1A 处理", l1b_processing: "L1B 处理",
  gtx_transfer: "GTX 传输", ai_processing: "AI 处理中", ai_skipped: "AI 已跳过",
  downlinking: "下传中", completed: "已完成", failed: "失败"
};

function formatBytes(bytes = 0) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
}

function Button({ children, onClick, active, disabled, danger }: {
  children: React.ReactNode; onClick?: () => void; active?: boolean;
  disabled?: boolean; danger?: boolean;
}) {
  const style = danger
    ? "border-orange-400/35 bg-orange-400/10 text-orange-200 hover:bg-orange-400/15"
    : active
      ? "border-cyan-300/50 bg-cyan-300/15 text-cyan-100"
      : "border-white/10 bg-white/[.035] text-slate-300 hover:border-cyan-300/25 hover:text-cyan-100";
  return <button onClick={onClick} disabled={disabled} className={`inline-flex items-center gap-1.5 rounded-lg border px-3 py-2 text-xs transition disabled:cursor-not-allowed disabled:opacity-40 ${style}`}>{children}</button>;
}

export function MissionDashboard() {
  const { scenario, mission, setScenario, setMission } = useDashboardStore();
  const [config, setConfig] = useState<PublicConfig>();
  const [faults, setFaults] = useState<Array<{ id: string; link: string; drop_rate: number }>>([]);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<string>();

  const reload = useCallback(async () => {
    try {
      const [publicConfig, scenarioRows, missionRows] = await Promise.all([
        api.config(), api.scenarios(), api.missions()
      ]);
      setConfig(publicConfig);
      const activeScenario = scenarioRows[0] ?? await api.createScenario();
      setScenario(activeScenario);
      // The dashboard has no historical mission selector in V1, so always follow
      // the newest mission. Using the captured mission here could overwrite a
      // just-created mission with the previously completed one.
      const activeId = missionRows[0]?.command.id ?? mission?.command.id;
      if (activeId) setMission(await api.mission(activeId));
      setFaults(await api.faults(activeScenario.config.id));
      setError(undefined);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "加载失败");
    } finally { setLoading(false); }
  }, [mission?.command.id, setMission, setScenario]);

  useEffect(() => { void reload(); }, [reload]);
  useEffect(() => {
    if (!mission || ["completed", "failed"].includes(mission.status)) return;
    const timer = window.setInterval(async () => {
      try { setMission(await api.mission(mission.command.id)); } catch { /* next poll retries */ }
    }, 900);
    return () => window.clearInterval(timer);
  }, [mission, setMission]);

  const run = async (operation: () => Promise<unknown>) => {
    setWorking(true);
    try { await operation(); await reload(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "操作失败"); }
    finally { setWorking(false); }
  };
  const createMission = () => scenario && run(async () => {
    const created = await api.createMission(scenario.config.id);
    setMission(await api.mission(created.mission_id));
  });
  const control = (action: string, rate?: number) => scenario && run(async () => {
    const changed = await api.control(scenario.config.id, action, rate);
    setScenario({ ...scenario, clock: changed.clock });
  });

  const stageIndex = Math.max(0, stages.findIndex(([key]) => key === mission?.status));
  const products = mission?.products ?? [];
  const thumbnail = products.find((item) => item.level === "thumbnail");
  const spacecraft = useMemo(() => {
    for (const event of [...(mission?.events ?? [])].reverse()) {
      const value = event.data.spacecraft;
      if (value && typeof value === "object") return value as Record<string, number | boolean>;
    }
    return undefined;
  }, [mission?.events]);

  if (loading) return <div className="flex min-h-screen items-center justify-center text-cyan-200"><LoaderCircle className="mr-2 animate-spin" />正在建立仿真控制面...</div>;

  return (
    <main className="grid-scan min-h-screen p-4 lg:p-6">
      <header className="mb-5 flex flex-wrap items-end justify-between gap-4 border-b border-cyan-200/10 pb-5">
        <div>
          <div className="mb-2 flex items-center gap-2 text-[10px] tracking-[.34em] text-cyan-300/60 uppercase"><Orbit size={13} />Satellite Onboard AI · SIL</div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-50 lg:text-3xl">星上智能计算数字孪生</h1>
          <p className="mt-1 text-xs text-slate-500">星务平台 · 光学载荷 · Virtual GTX · GPU 载荷 · 地面站</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="status-pulse mr-2 text-xs text-emerald-200">SIL ONLINE · v{config?.version}</span>
          <Button onClick={() => void reload()}><RefreshCw size={14} />刷新</Button>
          <Button onClick={createMission} active disabled={working || !scenario}><Zap size={14} />新建观测任务</Button>
        </div>
      </header>

      {error && <div className="mb-4 flex items-center gap-2 rounded-lg border border-orange-400/25 bg-orange-400/10 px-4 py-3 text-sm text-orange-100"><AlertTriangle size={16} />{error}</div>}

      <section className="mb-4 grid gap-4 xl:grid-cols-[1.55fr_1fr]">
        <div className="panel overflow-hidden rounded-2xl">
          <PanelHeader icon={<Orbit size={16} />} title="轨道与地面站可见性" note="TLE SNAPSHOT · SGP4" />
          <OrbitGlobe satelliteLatitude={Number(spacecraft?.latitude ?? 32)} satelliteLongitude={Number(spacecraft?.longitude ?? 112)} />
        </div>
        <div className="space-y-4">
          <div className="panel rounded-2xl p-4">
            <div className="mb-4 flex items-center justify-between"><Title icon={<Clock3 size={16} />} text="仿真时钟" /><span className="font-mono text-xs text-cyan-100">{scenario ? new Date(scenario.clock.simulated_at).toLocaleString("zh-CN", { hour12: false }) : "--"}</span></div>
            <div className="mb-3 flex flex-wrap gap-2">
              <Button onClick={() => control("resume")} active={!scenario?.clock.paused}><CirclePlay size={14} />运行</Button>
              <Button onClick={() => control("pause")} active={scenario?.clock.paused}><CirclePause size={14} />暂停</Button>
              <Button onClick={() => control("step")} disabled={!scenario?.clock.paused}><StepForward size={14} />单步</Button>
              <Button onClick={() => control("reset")}><RotateCcw size={14} />新 Run</Button>
            </div>
            <div className="flex gap-2">{[1, 10, 100].map((rate) => <Button key={rate} onClick={() => control("set_rate", rate)} active={scenario?.clock.rate === rate}>{rate}x</Button>)}</div>
          </div>

          <div className="panel rounded-2xl p-4">
            <div className="mb-3 flex items-center justify-between"><Title icon={<Gauge size={16} />} text="轨姿遥测" /><span className="text-[10px] text-emerald-300">{spacecraft?.in_contact === false ? "不可见" : "窗口开放"}</span></div>
            <div className="grid grid-cols-2 gap-3 text-xs">
              <Metric label="纬度" value={`${Number(spacecraft?.latitude ?? 0).toFixed(3)}°`} />
              <Metric label="经度" value={`${Number(spacecraft?.longitude ?? 0).toFixed(3)}°`} />
              <Metric label="高度" value={`${Number(spacecraft?.altitude_km ?? 0).toFixed(1)} km`} />
              <Metric label="指向误差" value={`${Number(spacecraft?.pointing_error_deg ?? 0).toFixed(3)}°`} good />
              <Metric label="Yaw / Pitch" value={`${Number(spacecraft?.yaw_deg ?? 0).toFixed(1)} / ${Number(spacecraft?.pitch_deg ?? 0).toFixed(1)}`} />
              <Metric label="Roll" value={`${Number(spacecraft?.roll_deg ?? 0).toFixed(1)}°`} />
            </div>
          </div>

          <div className="panel rounded-2xl p-4">
            <div className="mb-3 flex items-center justify-between"><Title icon={<ShieldCheck size={16} />} text="故障注入" orange /><span className="text-[10px] text-slate-500">SEED {scenario?.config.seed}</span></div>
            <p className="mb-3 text-xs leading-5 text-slate-500">确定性下行故障：10% 丢帧 + 2% CRC 错误。仅影响后续任务。</p>
            {faults.length
              ? <Button danger onClick={() => scenario && run(() => Promise.all(faults.map((fault) => api.deleteFault(scenario.config.id, fault.id))))}><AlertTriangle size={14} />清除 {faults.length} 条故障</Button>
              : <Button danger onClick={() => scenario && run(() => api.injectDrop(scenario.config.id))}><AlertTriangle size={14} />注入下行故障</Button>}
          </div>
        </div>
      </section>

      <section className="panel mb-4 rounded-2xl p-2"><SystemTopology status={mission?.status ?? "planned"} /></section>

      <section className="mb-4 grid gap-4 xl:grid-cols-[1.45fr_1fr]">
        <div className="panel rounded-2xl p-4">
          <div className="mb-4 flex items-center justify-between"><Title icon={<Activity size={16} />} text="任务时序" /><span className={`rounded-full border px-2.5 py-1 text-[10px] ${mission?.status === "failed" ? "border-red-400/30 text-red-300" : "border-cyan-300/20 text-cyan-200"}`}>{mission ? statusLabels[mission.status] : "等待任务"}</span></div>
          <div className="overflow-x-auto pb-2"><div className="flex min-w-[840px] items-start">{stages.map(([key, label], index) => <Stage key={key} label={label} complete={mission?.status === "completed" || index < stageIndex} active={key === mission?.status} last={index === stages.length - 1} />)}</div></div>
          <div className="mt-5 max-h-60 space-y-2 overflow-auto border-t border-white/[.05] pt-4">
            {mission?.events.length ? [...mission.events].reverse().map((event) => <div key={event.id} className="grid grid-cols-[72px_1fr] gap-3 text-xs"><span className="font-mono text-slate-600">{new Date(event.simulated_at).toLocaleTimeString("zh-CN", { hour12: false })}</span><div><div className="text-slate-300">{event.message}</div><div className="mt-0.5 text-[10px] text-slate-600">{event.source} · {event.provenance} · {event.event_type}</div></div></div>) : <Empty text="创建任务后，这里将显示逐阶段事件。" />}
          </div>
        </div>

        <div className="panel rounded-2xl p-4">
          <div className="mb-4 flex items-center justify-between"><Title icon={<Radio size={16} />} text="链路状态" /><span className="text-[10px] text-slate-500">CRC32C + SHA-256</span></div>
          <div className="space-y-3">
            <LinkCard title="地面上行" rate={config?.links.uplink?.bandwidth_bps} latency={config?.links.uplink?.latency_ms} accent="orange" />
            <LinkCard title="Virtual GTX" rate={config?.links.gtx?.bandwidth_bps} latency={config?.links.gtx?.latency_ms} accent="cyan" />
            <LinkCard title="地面下行" rate={config?.links.downlink?.bandwidth_bps} latency={config?.links.downlink?.latency_ms} accent="cyan" />
          </div>
          <div className="mt-4 grid grid-cols-3 gap-2">
            <Metric label="任务传输" value={String(mission?.transfers.length ?? 0)} />
            <Metric label="重传" value={String(mission?.transfers.reduce((sum, item) => sum + item.retry_count, 0) ?? 0)} />
            <Metric label="CRC 错误" value={String(mission?.transfers.reduce((sum, item) => sum + item.crc_failures, 0) ?? 0)} good />
          </div>
        </div>
      </section>

      <section className="grid gap-4 xl:grid-cols-[1.15fr_1fr]">
        <div className="panel rounded-2xl p-4">
          <div className="mb-4 flex items-center justify-between"><Title icon={<Database size={16} />} text="光学产品链" /><span className="text-[10px] text-slate-500">RAW → L0 → L1A → L1B → STAC</span></div>
          {products.length ? <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">{products.map((product) => <ProductCard key={product.id} product={product} />)}</div> : <Empty text="产品只能经模拟下行链路到达地面存储。" />}
        </div>
        <div className="space-y-4">
          <div className="panel overflow-hidden rounded-2xl">
            <PanelHeader icon={<FileImage size={16} />} title="L1B 地面预览" note="DOWNLINKED ARTIFACT" />
            <div className="relative flex min-h-56 items-center justify-center bg-black/25">{thumbnail ? <Image unoptimized fill sizes="(max-width: 1280px) 100vw, 40vw" src={artifactURL(thumbnail.id)} alt="L1B optical thumbnail" className="object-contain" /> : <Empty text="L1B 下传后显示缩略图。" />}</div>
          </div>
          <div className="panel rounded-2xl p-4">
            <div className="mb-3 flex items-center justify-between"><Title icon={<Box size={16} />} text="智能载荷 Provider" orange /><span className="rounded border border-orange-300/20 bg-orange-300/10 px-2 py-1 text-[10px] text-orange-200">NOT CONFIGURED</span></div>
            <p className="text-xs leading-5 text-slate-500">GPU 节点会真实接收并校验 L1B，但不会伪造检测目标。后续可通过 DetectionProvider 和 OpenAI-compatible LanguageProvider 接入本地服务。</p>
          </div>
        </div>
      </section>
    </main>
  );
}

function Title({ icon, text, orange }: { icon: React.ReactNode; text: string; orange?: boolean }) { return <h2 className={`flex items-center gap-2 text-sm font-medium ${orange ? "[&>svg]:text-orange-300" : "[&>svg]:text-cyan-300"}`}>{icon}{text}</h2>; }
function PanelHeader({ icon, title, note }: { icon: React.ReactNode; title: string; note: string }) { return <div className="flex items-center justify-between border-b border-white/[.06] px-4 py-3"><Title icon={icon} text={title} /><span className="text-[10px] tracking-wider text-slate-500">{note}</span></div>; }
function Metric({ label, value, good }: { label: string; value: string; good?: boolean }) { return <div className="rounded-lg border border-white/[.055] bg-black/15 px-3 py-2"><div className="text-[9px] tracking-wider text-slate-600 uppercase">{label}</div><div className={`mt-1 font-mono text-xs ${good ? "text-emerald-300" : "text-slate-200"}`}>{value}</div></div>; }
function Empty({ text }: { text: string }) { return <div className="py-8 text-center text-xs text-slate-600">{text}</div>; }
function Stage({ label, complete, active, last }: { label: string; complete: boolean; active: boolean; last: boolean }) { return <div className="relative flex flex-1 flex-col items-center text-center"><div className={`relative z-10 size-3 rounded-full border ${active ? "border-cyan-100 bg-cyan-300 shadow-[0_0_14px_#51e5ff]" : complete ? "border-emerald-300 bg-emerald-400" : "border-slate-600 bg-slate-900"}`} />{!last && <div className={`absolute left-1/2 top-[5px] h-px w-full ${complete ? "bg-emerald-400/60" : "bg-slate-700"}`} />}<span className={`mt-3 text-[10px] ${active ? "text-cyan-100" : complete ? "text-emerald-200/80" : "text-slate-600"}`}>{label}</span></div>; }
function LinkCard({ title, rate = 0, latency = 0, accent }: { title: string; rate?: number; latency?: number; accent: "cyan" | "orange" }) { return <div className="rounded-xl border border-white/[.055] bg-black/15 p-3"><div className="mb-2 flex items-center justify-between text-xs"><span className="text-slate-300">{title}</span><span className={accent === "orange" ? "text-orange-300" : "text-cyan-300"}>LINK READY</span></div><div className="grid grid-cols-2 gap-2"><Metric label="带宽" value={rate >= 1e9 ? `${(rate / 1e9).toFixed(1)} Gbps` : `${(rate / 1e6).toFixed(0)} Mbps`} /><Metric label="单向延迟" value={`${latency} ms`} /></div></div>; }
function ProductCard({ product }: { product: ProductManifest }) { return <a href={artifactURL(product.id)} target="_blank" rel="noreferrer" className="rounded-xl border border-white/[.06] bg-black/15 p-3 transition hover:border-cyan-300/25"><div className="mb-2 flex items-center justify-between"><span className="rounded bg-cyan-300/10 px-2 py-1 text-[10px] font-semibold text-cyan-200">{product.level.toUpperCase()}</span><span className="text-[10px] text-slate-600">{formatBytes(product.size_bytes)}</span></div><div className="truncate text-xs text-slate-300">{product.name}</div><div className="mt-2 truncate font-mono text-[9px] text-slate-600">SHA {product.sha256.slice(0, 16)}…</div></a>; }
