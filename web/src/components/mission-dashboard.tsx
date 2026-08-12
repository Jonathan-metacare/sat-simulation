"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Image from "next/image";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  Activity, AlertTriangle, Box, Clock3, Database, FileImage, Gauge,
  LoaderCircle, Orbit, Radio, RefreshCw, ShieldCheck, StepForward, Zap
} from "lucide-react";

import { api, artifactURL, eventStreamURL } from "~/lib/api";
import { useDashboardStore } from "~/lib/store";
import type {
  AIMode, MissionPhase, MissionResultResponse, OrbitTrack, ProductManifest, PublicConfig
} from "~/lib/types";
import { OrbitGlobe } from "./orbit-globe";
import { SystemTopology } from "./system-topology";

const stages: Array<[MissionPhase, string]> = [
  ["initialized", "任务初始化"], ["uplink_complete", "任务上注"],
  ["capture_complete", "姿态与拍摄"], ["processing_complete", "产品处理"],
  ["gtx_complete", "GTX 传输"], ["ai_complete", "智能分析"],
  ["completed", "结果下传"]
];

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
  const [orbit, setOrbit] = useState<OrbitTrack>();
  const [faults, setFaults] = useState<Array<{ id: string; link: string; drop_rate: number }>>([]);
  const [providerHealth, setProviderHealth] = useState<Record<string, { status: string }>>({});
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<string>();
  const [createOpen, setCreateOpen] = useState(false);
  const [aiMode, setAiMode] = useState<AIMode>("yolo");
  const [projectContext, setProjectContext] = useState("星上智能计算数字孪生光学观测任务");
  const [analysisPrompt, setAnalysisPrompt] = useState("识别图像中的主要地物、目标和异常，说明判断依据与不确定性。");
  const [missionResult, setMissionResult] = useState<MissionResultResponse>();
  const [playbackSpeed, setPlaybackSpeed] = useState<1 | 2 | 5>(1);
  const missionId = mission?.command.id;
  const runId = mission?.command.run_id;
  const scenarioId = scenario?.config.id;
  const executionState = mission?.execution_state;
  const eventRefreshActive = useRef(false);
  const eventRefreshQueued = useRef(false);
  const eventListRef = useRef<HTMLDivElement>(null);

  const reload = useCallback(async () => {
    try {
      const [publicConfig, scenarioRows, missionRows, providers] = await Promise.all([
        api.config(), api.scenarios(), api.missions(), api.providerHealth()
      ]);
      setConfig(publicConfig);
      setProviderHealth(providers);
      const activeScenario = scenarioRows[0] ?? await api.createScenario();
      setScenario(activeScenario);
      try { setOrbit(await api.orbit(activeScenario.config.id)); }
      catch { setOrbit(undefined); }
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
    if (!scenario) return;
    const timer = window.setInterval(async () => {
      try { setOrbit(await api.orbit(scenario.config.id)); } catch { /* next refresh retries */ }
    }, 10_000);
    return () => window.clearInterval(timer);
  }, [scenario]);
  useEffect(() => {
    if (!missionId) return;
    const timer = window.setInterval(async () => {
      try { setMission(await api.mission(missionId)); } catch { /* next poll retries */ }
    }, executionState === "running" ? 700 : 4_000);
    return () => window.clearInterval(timer);
  }, [executionState, missionId, setMission]);
  useEffect(() => {
    if (!missionId || mission?.phase !== "completed") {
      setMissionResult(undefined);
      return;
    }
    void api.missionResult(missionId).then(setMissionResult).catch(() => setMissionResult(undefined));
  }, [mission?.phase, missionId]);
  useEffect(() => {
    if (!missionId || !runId || !scenarioId) return;
    const stream = new EventSource(eventStreamURL(runId));
    const refreshLatest = async () => {
      if (eventRefreshActive.current) {
        eventRefreshQueued.current = true;
        return;
      }
      eventRefreshActive.current = true;
      do {
        eventRefreshQueued.current = false;
        try {
          const [detail, track, scenarios] = await Promise.all([
            api.mission(missionId), api.orbit(scenarioId), api.scenarios(),
          ]);
          setMission(detail);
          setOrbit(track);
          const current = scenarios.find((item) => item.config.id === scenarioId);
          if (current) setScenario(current);
        } catch { /* polling remains as fallback */ }
      } while (eventRefreshQueued.current);
      eventRefreshActive.current = false;
    };
    stream.addEventListener("telemetry", () => { void refreshLatest(); });
    return () => stream.close();
  }, [missionId, runId, scenarioId, setMission, setScenario]);

  const run = async (operation: () => Promise<unknown>) => {
    setWorking(true);
    try { await operation(); await reload(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "操作失败"); }
    finally { setWorking(false); }
  };
  const createMission = () => scenario && run(async () => {
    if (mission && !["completed", "cancelled"].includes(mission.execution_state)) {
      await api.cancelMission(mission.command.id);
    }
    const created = await api.createMission(
      scenario.config.id, aiMode, projectContext.trim(), analysisPrompt.trim()
    );
    setMission(created);
    setCreateOpen(false);
  });
  const advanceMission = () => mission && run(async () => {
    await api.advanceMission(
      mission.command.id,
      playbackSpeed,
      `${mission.phase}-${crypto.randomUUID()}`
    );
    setMission(await api.mission(mission.command.id));
  });

  const stageIndex = Math.max(0, stages.findIndex(([key]) => key === mission?.phase));
  const products = mission?.products ?? [];
  const onboardProducts = mission?.onboard_products ?? [];
  const thumbnail = products.find((item) => item.level === "thumbnail");
  const l1b = products.find((item) => item.level === "l1b");
  const analysis = missionResult?.ai_result?.result;
  const spacecraft = useMemo(() => {
    for (const event of [...(mission?.events ?? [])].reverse()) {
      const value = event.data.spacecraft;
      if (value && typeof value === "object") return value as Record<string, number | boolean>;
    }
    return undefined;
  }, [mission?.events]);
  const visibleEvents = useMemo(() => {
    const events = mission?.events ?? [];
    const important = events.filter((event) => !["simulation_tick", "stage_progress"].includes(event.event_type));
    const latestProgress = [...events].reverse().find((event) =>
      ["simulation_tick", "stage_progress"].includes(event.event_type)
    );
    const activeProgress = mission?.execution_state === "running"
      && Number(latestProgress?.data.progress ?? 1) < 1
      ? latestProgress
      : undefined;
    return activeProgress ? [...important, activeProgress] : important;
  }, [mission?.events, mission?.execution_state]);
  const latestVisibleEventId = visibleEvents.at(-1)?.id;
  useEffect(() => {
    eventListRef.current?.scrollTo({ top: 0, behavior: "smooth" });
  }, [latestVisibleEventId]);

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
          <Button onClick={() => setCreateOpen(true)} active disabled={working || !scenario || mission?.execution_state === "running"}><Zap size={14} />新建观测任务</Button>
        </div>
      </header>

      {error && <div className="mb-4 flex items-center gap-2 rounded-lg border border-orange-400/25 bg-orange-400/10 px-4 py-3 text-sm text-orange-100"><AlertTriangle size={16} />{error}</div>}

      <section className="mb-4 grid items-start gap-4 xl:grid-cols-[minmax(0,1.3fr)_minmax(360px,1fr)]">
        <div className="panel min-w-0 overflow-hidden rounded-2xl">
          <PanelHeader icon={<Orbit size={16} />} title="轨道态势与过站窗口" note="TLE SNAPSHOT · SGP4" />
          <OrbitGlobe
            track={orbit}
            station={{
              name: scenario?.config.ground_station_name ?? "GS-DEMO-BEIJING",
              latitude: scenario?.config.ground_station_latitude ?? 39.9042,
              longitude: scenario?.config.ground_station_longitude ?? 116.4074,
              altitudeM: scenario?.config.ground_station_altitude_m ?? 50,
            }}
            target={mission ? {
              name: mission.command.target_name,
              latitude: mission.command.target_latitude,
              longitude: mission.command.target_longitude,
            } : undefined}
          />
        </div>
        <div className="space-y-4">
          <div className="panel rounded-2xl p-4">
            <div className="mb-4 flex items-center justify-between"><Title icon={<Clock3 size={16} />} text="仿真时钟" /><span className="font-mono text-xs text-cyan-100">{scenario ? new Date(scenario.clock.simulated_at).toLocaleString("zh-CN", { hour12: false }) : "--"}</span></div>
            <div className="mb-3 flex items-center justify-between rounded-lg border border-white/[.06] bg-black/15 px-3 py-2 text-xs">
              <span className="text-slate-500">时钟状态</span>
              <span className={scenario?.clock.paused ? "text-emerald-300" : "text-orange-300"}>{scenario?.clock.paused ? "已暂停" : "运行中"}</span>
            </div>
            <div className="mb-3 flex gap-2">{([1, 2, 5] as const).map((rate) => <Button key={rate} onClick={() => setPlaybackSpeed(rate)} active={playbackSpeed === rate}>{rate}x</Button>)}</div>
            <Button onClick={advanceMission} active disabled={!mission?.can_advance || mission?.execution_state === "running" || working}>
              {mission?.execution_state === "running" ? <LoaderCircle size={14} className="animate-spin" /> : <StepForward size={14} />}
              {mission?.execution_state === "running" ? "阶段执行中" : (mission?.next_action ?? "请先新建任务")}
            </Button>
            {mission?.execution_state === "blocked" && <p className="mt-3 text-xs leading-5 text-orange-200">{mission.block_reason}</p>}
            {mission?.execution_state === "retryable_error" && <p className="mt-3 text-xs leading-5 text-red-300">可重试：{mission.error}</p>}
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

      <section className="panel mb-4 rounded-2xl p-2"><SystemTopology mission={mission ? {
        phase: mission.phase,
        executionState: mission.execution_state,
        activeSubstage: mission.active_substage,
        aiMode: mission.ai_mode,
        providerStatus: mission.ai_mode === "llm"
          ? providerHealth.language?.status
          : providerHealth.detection?.status,
      } : undefined} /></section>

      <section className="mb-4 grid gap-4 xl:grid-cols-[1.45fr_1fr]">
        <div className="panel rounded-2xl p-4">
          <div className="mb-4 flex items-center justify-between"><Title icon={<Activity size={16} />} text="任务时序" /><span className={`rounded-full border px-2.5 py-1 text-[10px] ${mission?.execution_state === "blocked" ? "border-orange-400/30 text-orange-300" : "border-cyan-300/20 text-cyan-200"}`}>{mission ? `${mission.phase} · ${mission.execution_state}` : "等待任务"}</span></div>
          <div className="overflow-x-auto pb-2"><div className="flex min-w-[700px] items-start">{stages.map(([key, label], index) => <Stage key={key} label={label} complete={mission?.phase === "completed" || index < stageIndex} active={key === mission?.phase} last={index === stages.length - 1} />)}</div></div>
          {mission?.planned_windows && <div className="mt-4 grid gap-2 border-t border-white/[.05] pt-4 sm:grid-cols-3">
            <Metric label="上注窗口 AOS" value={new Date(mission.planned_windows.uplink.aos).toLocaleString("zh-CN", { hour12: false })} />
            <Metric label="自动拍摄时刻" value={new Date(mission.planned_windows.capture.max_elevation_at).toLocaleString("zh-CN", { hour12: false })} />
            <Metric label="结果下传 AOS" value={new Date(mission.planned_windows.downlink.aos).toLocaleString("zh-CN", { hour12: false })} />
          </div>}
          <div ref={eventListRef} className="mt-5 max-h-72 space-y-2 overflow-auto border-t border-white/[.05] pt-4">
            {visibleEvents.length ? [...visibleEvents].reverse().map((event) => <div key={event.id} className={`grid grid-cols-[72px_1fr] gap-3 rounded-lg px-2 py-1.5 text-xs ${["macro_phase_blocked", "macro_phase_failed"].includes(event.event_type) ? "bg-orange-400/[.06]" : ""}`}><span className="font-mono text-slate-600">{new Date(event.simulated_at).toLocaleTimeString("zh-CN", { hour12: false })}</span><div><div className="text-slate-300">{event.message}</div><div className="mt-0.5 text-[10px] text-slate-600">{event.source} · {event.channel} · {event.event_type}</div></div></div>) : <Empty text="创建任务后，这里将显示逐阶段事件。" />}
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
          {products.length ? <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">{products.map((product) => <ProductCard key={product.id} product={product} />)}</div> : onboardProducts.length ? <div><div className="mb-3 text-[10px] tracking-wider text-orange-200">星上目录 · 尚未下传</div><div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">{onboardProducts.map((product) => <OnboardProductCard key={product.id} product={product} />)}</div></div> : <Empty text="第六步结果包真正下传前，地面只知道星上目录状态，不可访问产品。" />}
        </div>
        <div className="space-y-4">
          <div className="panel overflow-hidden rounded-2xl">
            <PanelHeader icon={<FileImage size={16} />} title="L1B 与智能分析" note="DOWNLINKED RESULT" />
            <div className="relative flex min-h-56 items-center justify-center bg-black/25">{thumbnail ? <Image unoptimized fill sizes="(max-width: 1280px) 100vw, 40vw" src={artifactURL(thumbnail.id)} alt="L1B optical thumbnail" className="object-contain" /> : <Empty text="L1B 下传后显示缩略图。" />}</div>
            <div className="border-t border-white/[.06] p-4">
              <div className="mb-2 flex items-center justify-between"><span className="text-xs font-medium text-cyan-100">模型分析结果</span>{l1b && <a className="text-[10px] text-cyan-300 hover:text-cyan-100" href={artifactURL(l1b.id)} target="_blank" rel="noreferrer">下载 L1B GeoTIFF</a>}</div>
              {analysis?.content ? <><div className="mb-3 flex flex-wrap gap-2 text-[10px] text-slate-500"><span>{analysis.provider}</span><span>{analysis.model_version ?? "unknown model"}</span>{analysis.elapsed_ms !== undefined && <span>{(analysis.elapsed_ms / 1000).toFixed(1)} s</span>}</div>{analysis.truncated && <div className="mb-3 rounded-lg border border-orange-300/25 bg-orange-300/10 px-3 py-2 text-xs text-orange-200">{analysis.reason ?? "模型输出达到长度上限，报告可能不完整。"}</div>}<div className="llm-markdown"><ReactMarkdown remarkPlugins={[remarkGfm]}>{analysis.content}</ReactMarkdown></div></> : <Empty text={mission?.phase === "completed" ? "结果包中没有可展示的模型分析。" : "第六步结果包下传后，模型分析将在这里与 L1B 一起展示。"} />}
            </div>
          </div>
          <div className="panel rounded-2xl p-4">
            <div className="mb-3 flex items-center justify-between"><Title icon={<Box size={16} />} text="智能载荷 Provider" orange /><span className="rounded border border-orange-300/20 bg-orange-300/10 px-2 py-1 text-[10px] text-orange-200">{mission?.ai_mode === "llm" ? (providerHealth.language?.status ?? "UNKNOWN") : (providerHealth.detection?.status ?? "UNKNOWN")}</span></div>
            <p className="text-xs leading-5 text-slate-500">本任务固定使用 {mission?.ai_mode?.toUpperCase() ?? "YOLO"}。未配置或健康检查失败时，第五步会停在 blocked，可修复服务后原步重试；系统不会伪造结果。</p>
          </div>
        </div>
      </section>

      {createOpen && <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 p-4 backdrop-blur-sm">
        <div className="panel w-full max-w-md rounded-2xl p-5 shadow-2xl shadow-cyan-950/50">
          <div className="mb-1 text-lg font-medium text-slate-50">新建观测任务</div>
          <p className="mb-5 text-xs leading-5 text-slate-500">{mission && !["completed", "cancelled"].includes(mission.execution_state) ? "当前任务将结束，但历史事件和星上产品会完整保留；随后创建独立 Run 并保持暂停。" : "系统将创建独立 Run，按固定 TLE 自动规划上注、拍摄和下一次结果下传窗口。创建后保持暂停。"}</p>
          <div className="mb-5 grid grid-cols-2 gap-3">
            <button onClick={() => setAiMode("yolo")} className={`rounded-xl border p-4 text-left ${aiMode === "yolo" ? "border-cyan-300/50 bg-cyan-300/10" : "border-white/10 bg-black/20"}`}><div className="text-sm text-slate-100">YOLO 检测</div><div className="mt-1 text-[10px] text-slate-500">舰船 / 飞机 / 车辆</div></button>
            <button onClick={() => setAiMode("llm")} className={`rounded-xl border p-4 text-left ${aiMode === "llm" ? "border-cyan-300/50 bg-cyan-300/10" : "border-white/10 bg-black/20"}`}><div className="text-sm text-slate-100">LLM 分析</div><div className="mt-1 text-[10px] text-slate-500">多模态图像解译</div></button>
          </div>
          {aiMode === "llm" && <div className="mb-5 space-y-3">
            <label className="block text-xs text-slate-400">项目/用户背景<textarea value={projectContext} onChange={(event) => setProjectContext(event.target.value)} maxLength={4000} rows={3} className="mt-1 w-full resize-y rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-xs leading-5 text-slate-200 outline-none focus:border-cyan-300/40" placeholder="例如：海上目标监测项目，重点关注船舶和异常航迹。" /></label>
            <label className="block text-xs text-slate-400">本次分析要求<textarea value={analysisPrompt} onChange={(event) => setAnalysisPrompt(event.target.value)} maxLength={2000} rows={3} className="mt-1 w-full resize-y rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-xs leading-5 text-slate-200 outline-none focus:border-cyan-300/40" placeholder="例如：识别主要目标，说明数量、位置和置信程度。" /></label>
            <p className="text-[10px] leading-4 text-slate-600">第五步将把 L1B 生成的视觉预览、L1B 元数据和上述背景一起发送给模型。</p>
          </div>}
          <div className="flex justify-end gap-2"><Button onClick={() => setCreateOpen(false)}>取消</Button><Button onClick={createMission} active disabled={working}>{working ? "初始化中" : mission && !["completed", "cancelled"].includes(mission.execution_state) ? "结束当前任务并新建" : "初始化任务"}</Button></div>
        </div>
      </div>}
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
function OnboardProductCard({ product }: { product: ProductManifest }) { return <div className="rounded-xl border border-orange-300/10 bg-black/15 p-3"><div className="mb-2 flex items-center justify-between"><span className="rounded bg-orange-300/10 px-2 py-1 text-[10px] font-semibold text-orange-200">{product.level.toUpperCase()}</span><span className="text-[10px] text-slate-600">{formatBytes(product.size_bytes)}</span></div><div className="truncate text-xs text-slate-400">{product.name}</div><div className="mt-2 text-[9px] text-orange-200/60">仅星务可访问</div></div>; }
