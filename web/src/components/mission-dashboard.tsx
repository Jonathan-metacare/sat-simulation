"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Image from "next/image";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  Activity, AlertTriangle, Clock3, Database, FileImage, Gauge,
  ChevronDown, LoaderCircle, Orbit, PanelRightClose, PanelRightOpen, Radio, Settings2, StepForward, Zap
} from "lucide-react";

import { api, artifactURL, eventStreamURL } from "~/lib/api";
import { useDashboardStore } from "~/lib/store";
import { translate } from "~/lib/i18n";
import type {
  AIMode, MissionPhase, MissionResultResponse, NodeKind, OrbitTrack, ProductManifest, PublicConfig
} from "~/lib/types";
import { NodeTab } from "./node-tab";
import { ProtocolInspector } from "./protocol-inspector";
import { OrbitGlobe } from "./orbit-globe";
import { SystemTopology } from "./system-topology";
import { DesktopSettingsPanel } from "./desktop-settings";
import { desktopBridge } from "~/lib/desktop";

const stages: Array<[MissionPhase, Parameters<typeof translate>[1]]> = [
  ["initialized", "stage.initialized"], ["uplink_complete", "stage.uplink_complete"],
  ["capture_complete", "stage.capture_complete"], ["processing_complete", "stage.processing_complete"],
  ["gtx_complete", "stage.gtx_complete"], ["ai_complete", "stage.ai_complete"],
  ["completed", "stage.completed"]
];

function formatBytes(bytes = 0) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
}

function localizedMissionAction(
  t: (key: Parameters<typeof translate>[1], values?: Parameters<typeof translate>[2]) => string,
  action?: string | null,
) {
  return action?.startsWith("mission.action.")
    ? t(action as Parameters<typeof translate>[1])
    : action;
}

function localizedEventMessage(
  t: (key: Parameters<typeof translate>[1], values?: Parameters<typeof translate>[2]) => string,
  event: { message: string; data: Record<string, unknown> },
) {
  const key = event.data.message_key;
  if (key === "mission.event.phaseStarted") {
    return t("mission.event.phaseStarted", {
      action: localizedMissionAction(t, typeof event.data.action_key === "string" ? event.data.action_key : undefined),
    });
  }
  if (typeof key === "string" && key.startsWith("mission.")) {
    return t(key as Parameters<typeof translate>[1]);
  }
  return event.message;
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
  const { scenario, mission, locale, theme, setScenario, setMission, setLocale, setTheme } = useDashboardStore();
  const t = (key: Parameters<typeof translate>[1], values?: Parameters<typeof translate>[2]) =>
    translate(locale, key, values);
  const [config, setConfig] = useState<PublicConfig>();
  const [orbit, setOrbit] = useState<OrbitTrack>();
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
  const [activeTab, setActiveTab] = useState<NodeKind>("ground");
  const [missionPanelOpen, setMissionPanelOpen] = useState(false);
  const [desktopSettingsOpen, setDesktopSettingsOpen] = useState(false);
  const [settingsMenuOpen, setSettingsMenuOpen] = useState(false);
  const [settingsSection, setSettingsSection] = useState<"general" | "plugins" | "ai" | "scene" | "about">("general");
  const settingsMenuRef = useRef<HTMLDivElement>(null);
  const missionId = mission?.command.id;
  const runId = mission?.command.run_id;
  const scenarioId = scenario?.config.id;
  const executionState = mission?.execution_state;
  const eventRefreshActive = useRef(false);
  const eventRefreshQueued = useRef(false);
  const eventListRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const bridge = desktopBridge();
    if (bridge) {
      void bridge.getSettings().then((saved) => {
        setLocale(saved.locale);
        setTheme(saved.theme);
        setAiMode(saved.activeAiMode);
      });
      return;
    }
    const savedLocale = window.localStorage.getItem("sat-sim-locale");
    const savedTheme = window.localStorage.getItem("sat-sim-theme");
    if (savedLocale === "zh" || savedLocale === "en") setLocale(savedLocale);
    if (savedTheme === "dark" || savedTheme === "light") setTheme(savedTheme);
  }, [setLocale, setTheme]);
  useEffect(() => {
    if (!settingsMenuOpen) return;
    const closeOnOutsidePointer = (event: PointerEvent) => {
      if (!settingsMenuRef.current?.contains(event.target as Node)) setSettingsMenuOpen(false);
    };
    window.addEventListener("pointerdown", closeOnOutsidePointer);
    return () => window.removeEventListener("pointerdown", closeOnOutsidePointer);
  }, [settingsMenuOpen]);
  useEffect(() => {
    document.documentElement.lang = locale === "zh" ? "zh-CN" : "en";
    window.localStorage.setItem("sat-sim-locale", locale);
  }, [locale]);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    window.localStorage.setItem("sat-sim-theme", theme);
  }, [theme]);

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
      setError(undefined);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "加载失败");
    } finally { setLoading(false); }
  }, [mission?.command.id, setMission, setScenario]);

  useEffect(() => { void reload(); }, [reload]);
  useEffect(() => {
    const readTab = () => {
      const value = new URLSearchParams(window.location.search).get("tab");
      setActiveTab(["ground", "platform", "optical", "gpu"].includes(value ?? "")
        ? value as NodeKind : "ground");
    };
    readTab();
    window.addEventListener("popstate", readTab);
    return () => window.removeEventListener("popstate", readTab);
  }, []);
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
  const missionCompleted = mission?.execution_state === "completed" || mission?.phase === "completed";
  const openSettings = (section: "general" | "plugins" | "ai" | "scene" | "about") => {
    setSettingsSection(section);
    setSettingsMenuOpen(false);
    setDesktopSettingsOpen(true);
  };
  const advanceLabel = missionCompleted
    ? t("controls.missionCompleted")
    : localizedMissionAction(t, mission?.next_action) ?? t("controls.createFirst");
  const navigateTab = (tab: NodeKind) => {
    const url = new URL(window.location.href);
    url.searchParams.set("tab", tab);
    window.history.pushState({}, "", url);
    setActiveTab(tab);
  };

  const stageIndex = Math.max(0, stages.findIndex(([key]) => key === mission?.phase));
  const products = mission?.products ?? [];
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

  if (loading) return <div className="flex min-h-screen items-center justify-center text-cyan-200"><LoaderCircle className="mr-2 animate-spin" />{locale === "zh" ? "正在建立仿真控制面..." : "Starting simulation control plane..."}</div>;

  return (
    <main className={`mission-content grid-scan min-h-screen p-4 lg:p-6 ${missionPanelOpen ? "mission-content--drawer-open" : ""}`}>
      <header className="mb-5 flex flex-wrap items-end justify-between gap-4 border-b border-cyan-200/10 pb-5">
        <div>
          <div className="mb-2 flex items-center gap-2 text-[10px] tracking-[.34em] text-cyan-300/60 uppercase"><Orbit size={13} />Satellite Onboard AI · SIL</div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-50 lg:text-3xl">{t("app.title")}</h1>
          <p className="mt-1 text-xs text-slate-500">{t("app.subtitle")}</p>
        </div>
        <div ref={settingsMenuRef} className="relative flex flex-wrap items-center gap-2">
          <Button onClick={() => setSettingsMenuOpen((open) => !open)} active={settingsMenuOpen}><Settings2 size={14} /><ChevronDown size={13} /></Button>
          {settingsMenuOpen && <div className="absolute right-0 top-10 z-[55] min-w-44 rounded-xl border border-cyan-200/25 bg-slate-950/95 p-1.5 shadow-xl shadow-black/50 backdrop-blur"><button onClick={() => openSettings("general")} className="settings-menu-item w-full rounded-lg px-3 py-2.5 text-left text-xs font-medium text-slate-200 transition hover:bg-cyan-300/25 hover:text-cyan-50">{locale === "zh" ? "通用" : "General"}</button><button onClick={() => openSettings("plugins")} className="settings-menu-item w-full rounded-lg px-3 py-2.5 text-left text-xs font-medium text-slate-200 transition hover:bg-cyan-300/25 hover:text-cyan-50">{locale === "zh" ? "插件与密钥" : "Plugins & Keys"}</button><button onClick={() => openSettings("ai")} className="settings-menu-item w-full rounded-lg px-3 py-2.5 text-left text-xs font-medium text-slate-200 transition hover:bg-cyan-300/25 hover:text-cyan-50">AI</button><button onClick={() => openSettings("scene")} className="settings-menu-item w-full rounded-lg px-3 py-2.5 text-left text-xs font-medium text-slate-200 transition hover:bg-cyan-300/25 hover:text-cyan-50">{locale === "zh" ? "场景导入" : "Scene Import"}</button><button onClick={() => openSettings("about")} className="settings-menu-item w-full rounded-lg px-3 py-2.5 text-left text-xs font-medium text-slate-200 transition hover:bg-cyan-300/25 hover:text-cyan-50">{locale === "zh" ? "关于" : "About"}</button></div>}
          <Button onClick={() => { setSettingsMenuOpen(false); setMissionPanelOpen((open) => !open); }} active={missionPanelOpen}>{missionPanelOpen ? <PanelRightClose size={16} /> : <PanelRightOpen size={16} />}</Button>
        </div>
      </header>

      {error && <div className="mb-4 flex items-center gap-2 rounded-lg border border-orange-400/25 bg-orange-400/10 px-4 py-3 text-sm text-orange-100"><AlertTriangle size={16} />{error}</div>}

      <DesktopSettingsPanel open={desktopSettingsOpen} onClose={() => setDesktopSettingsOpen(false)} locale={locale} onLocale={setLocale} onTheme={setTheme} onAiMode={setAiMode} initialSection={settingsSection} onScenarioImported={() => void reload()} onSettingsSaved={() => void reload()} />
      <aside aria-label="任务控制面板" className={`mission-drawer fixed inset-y-0 right-0 z-50 flex w-full max-w-none flex-col border-l border-cyan-300/20 shadow-2xl shadow-black/50 transition-transform duration-300 ${missionPanelOpen ? "translate-x-0" : "translate-x-full"}`}>
        <div className="flex items-center justify-between border-b border-cyan-200/10 px-5 py-4">
          <div><div className="text-sm font-medium text-cyan-100">{t("panel.title")}</div><div className="mt-1 text-[10px] tracking-wider text-slate-500">{t("panel.subtitle")}</div></div>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto p-4">
          <section className="panel mb-4 rounded-2xl p-2"><SystemTopology onNavigate={(node) => { navigateTab(node); setMissionPanelOpen(false); }} mission={mission ? {
            phase: mission.phase,
            executionState: mission.execution_state,
            activeSubstage: mission.active_substage,
            aiMode: mission.ai_mode,
            providerStatus: mission.ai_mode === "llm"
              ? providerHealth.language?.status
              : providerHealth.detection?.status,
          } : undefined} locale={locale} /></section>

          <section className="panel mb-4 rounded-2xl p-4">
            <div className="mb-4 flex flex-wrap items-center justify-between gap-3 border-b border-white/[.06] pb-4">
              <div className="flex flex-wrap items-center gap-3">
                <Title icon={<Clock3 size={16} />} text={t("controls.mission")} />
                <span className="font-mono text-xs text-cyan-100">{scenario ? new Date(scenario.clock.simulated_at).toLocaleString("zh-CN", { hour12: false }) : "--"}</span>
                <span className={`rounded border px-2 py-1 text-[10px] ${scenario?.clock.paused ? "border-emerald-300/20 text-emerald-300" : "border-orange-300/20 text-orange-300"}`}>{scenario?.clock.paused ? t("controls.paused") : t("controls.running")}</span>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                {([1, 2, 5] as const).map((rate) => <Button key={rate} onClick={() => setPlaybackSpeed(rate)} active={playbackSpeed === rate}>{rate}x</Button>)}
                <Button onClick={() => setCreateOpen(true)} disabled={!scenario || mission?.execution_state === "running"}><Zap size={14} />{t("actions.newMission")}</Button>
                <Button onClick={advanceMission} active disabled={!mission?.can_advance || mission?.execution_state === "running" || working}>
                  {mission?.execution_state === "running" ? <LoaderCircle size={14} className="animate-spin" /> : <StepForward size={14} />}
                  {mission?.execution_state === "running" ? t("controls.stageRunning") : advanceLabel}
                </Button>
              </div>
            </div>
            <div className="mb-4 flex items-center justify-between gap-3"><Title icon={<Activity size={16} />} text={t("mission.timeline")} /><span className={`rounded-full border px-2.5 py-1 text-[10px] ${mission?.execution_state === "blocked" ? "border-orange-400/30 text-orange-300" : "border-cyan-300/20 text-cyan-200"}`}>{mission ? `${mission.phase} · ${mission.execution_state}` : t("mission.waiting")}</span></div>
            <div className="overflow-x-auto pb-2"><div className="flex min-w-[700px] items-start">{stages.map(([key, label], index) => <Stage key={key} label={t(label)} complete={mission?.phase === "completed" || index < stageIndex} active={key === mission?.phase} last={index === stages.length - 1} />)}</div></div>
            {mission?.planned_windows && <div className="mt-4 grid gap-2 border-t border-white/[.05] pt-4 sm:grid-cols-3">
              <Metric label={t("mission.uplinkAos")} value={new Date(mission.planned_windows.uplink.aos).toLocaleString("zh-CN", { hour12: false })} />
              <Metric label={t("mission.captureAt")} value={new Date(mission.planned_windows.capture.max_elevation_at).toLocaleString("zh-CN", { hour12: false })} />
              <Metric label={t("mission.downlinkAos")} value={new Date(mission.planned_windows.downlink.aos).toLocaleString("zh-CN", { hour12: false })} />
            </div>}
            {mission?.execution_state === "blocked" && <p className="mt-3 text-xs leading-5 text-orange-200">{mission.block_reason}</p>}
            {mission?.execution_state === "retryable_error" && <p className="mt-3 text-xs leading-5 text-red-300">可重试：{mission.error}</p>}
            <div ref={eventListRef} className="mt-4 max-h-56 space-y-2 overflow-auto border-t border-white/[.05] pt-4">
              {visibleEvents.length ? [...visibleEvents].reverse().map((event) => <div key={event.id} className={`grid grid-cols-[72px_1fr] gap-3 rounded-lg px-2 py-1.5 text-xs ${["macro_phase_blocked", "macro_phase_failed"].includes(event.event_type) ? "bg-orange-400/[.06]" : ""}`}><span className="font-mono text-slate-600">{new Date(event.simulated_at).toLocaleTimeString("zh-CN", { hour12: false })}</span><div><div className="text-slate-300">{localizedEventMessage(t, event)}</div><div className="mt-0.5 text-[10px] text-slate-600">{event.source} · {event.channel} · {event.event_type}</div></div></div>) : <Empty text={t("mission.events.empty")} />}
            </div>
          </section>
          <ProtocolInspector missionId={mission?.command.id} runId={mission?.command.run_id} locale={locale} />
        </div>
      </aside>

      <nav className="panel mb-4 flex overflow-x-auto rounded-2xl p-1.5" aria-label="节点页面">
        {(["ground", "platform", "optical", "gpu"] as NodeKind[]).map((tab) => <button key={tab} onClick={() => navigateTab(tab)} className={`min-w-32 flex-1 rounded-xl px-4 py-3 text-xs transition ${activeTab === tab ? "bg-cyan-300/12 text-cyan-100 shadow-[inset_0_0_0_1px_rgba(81,229,255,.25)]" : "text-slate-500 hover:bg-white/[.035] hover:text-slate-300"}`}>{t(`tabs.${tab}` as Parameters<typeof t>[0])}</button>)}
      </nav>

      {activeTab === "ground" ? <>

        <section className="mb-4 grid items-stretch gap-4 xl:grid-cols-[minmax(0,1.3fr)_minmax(360px,1fr)]">
          <div className="panel flex min-w-0 flex-col overflow-hidden rounded-2xl">
            <PanelHeader icon={<Orbit size={16} />} title={t("ground.orbit")} note="TLE SNAPSHOT · SGP4" />
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
              locale={locale}
            />
          </div>
          <div className="flex flex-col gap-4">
            <div className="panel flex-1 rounded-2xl p-4">
              <div className="mb-3 flex items-center justify-between"><Title icon={<Gauge size={16} />} text={t("ground.telemetry")} /><span className="text-[10px] text-emerald-300">{spacecraft?.in_contact === false ? t("ground.notVisible") : t("ground.visible")}</span></div>
              <div className="grid grid-cols-2 gap-3 text-xs">
                <Metric label={t("ground.latitude")} value={`${Number(spacecraft?.latitude ?? 0).toFixed(3)}°`} />
                <Metric label={t("ground.longitude")} value={`${Number(spacecraft?.longitude ?? 0).toFixed(3)}°`} />
                <Metric label={t("ground.altitude")} value={`${Number(spacecraft?.altitude_km ?? 0).toFixed(1)} km`} />
                <Metric label={t("ground.pointingError")} value={`${Number(spacecraft?.pointing_error_deg ?? 0).toFixed(3)}°`} good />
                <Metric label="Yaw / Pitch" value={`${Number(spacecraft?.yaw_deg ?? 0).toFixed(1)} / ${Number(spacecraft?.pitch_deg ?? 0).toFixed(1)}`} />
                <Metric label="Roll" value={`${Number(spacecraft?.roll_deg ?? 0).toFixed(1)}°`} />
              </div>
            </div>

            <div className="panel rounded-2xl p-4">
              <div className="mb-4 flex items-center justify-between"><Title icon={<Radio size={16} />} text={t("ground.link")} /><span className="text-[10px] text-slate-500">{t("ground.linkNote")}</span></div>
              <div className="space-y-3">
                <LinkCard title={t("ground.uplink")} rate={config?.links.uplink?.bandwidth_bps} latency={config?.links.uplink?.latency_ms} accent="orange" locale={locale} />
                <LinkCard title={t("ground.downlink")} rate={config?.links.downlink?.bandwidth_bps} latency={config?.links.downlink?.latency_ms} accent="cyan" locale={locale} />
              </div>
              <div className="mt-4 grid grid-cols-3 gap-2">
                <Metric label={t("ground.transferCount")} value={String(mission?.transfers.length ?? 0)} />
                <Metric label={t("ground.retry")} value={String(mission?.transfers.reduce((sum, item) => sum + item.retry_count, 0) ?? 0)} />
                <Metric label={t("ground.crcError")} value={String(mission?.transfers.reduce((sum, item) => sum + item.crc_failures, 0) ?? 0)} good />
              </div>
            </div>
          </div>
        </section>

        <section className="space-y-4">
          <div className="panel rounded-2xl p-4">
            <div className="mb-4 flex items-center justify-between"><Title icon={<Database size={16} />} text={t("ground.products")} /><span className="text-[10px] text-slate-500">{t("ground.productChainNote")}</span></div>
            {products.length ? <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">{products.map((product) => <ProductCard key={product.id} product={product} />)}</div> : <Empty text={t("ground.productsEmpty")} />}
          </div>
          <div className="panel overflow-hidden rounded-2xl">
            <PanelHeader icon={<FileImage size={16} />} title={t("ground.analysis")} note={t("ground.downlinked")} />
            <div className="relative flex min-h-64 items-center justify-center bg-black/25">{thumbnail ? <Image unoptimized fill sizes="100vw" src={artifactURL(thumbnail.id)} alt="L1B optical thumbnail" className="object-contain" /> : <Empty text={t("ground.thumbnailEmpty")} />}</div>
            <div className="border-t border-white/[.06] p-4">
              <div className="mb-2 flex items-center justify-between"><span className="text-xs font-medium text-cyan-100">{t("ground.modelResult")}</span>{l1b && <a className="text-[10px] text-cyan-300 hover:text-cyan-100" href={artifactURL(l1b.id)} target="_blank" rel="noreferrer">{t("actions.downloadL1b")}</a>}</div>
              {analysis?.content ? <><div className="mb-3 flex flex-wrap gap-2 text-[10px] text-slate-500"><span>{analysis.provider}</span><span>{analysis.model_version ?? "unknown model"}</span>{analysis.elapsed_ms !== undefined && <span>{(analysis.elapsed_ms / 1000).toFixed(1)} s</span>}</div>{analysis.truncated && <div className="mb-3 rounded-lg border border-orange-300/25 bg-orange-300/10 px-3 py-2 text-xs text-orange-200">{analysis.reason ?? t("ground.truncated")}</div>}<div className="llm-markdown"><ReactMarkdown remarkPlugins={[remarkGfm]}>{analysis.content}</ReactMarkdown></div></> : <Empty text={mission?.phase === "completed" ? t("ground.resultEmpty") : t("ground.resultPending")} />}
            </div>
          </div>
        </section>

        {createOpen && <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 p-4 backdrop-blur-sm">
          <div className="panel w-full max-w-md rounded-2xl p-5 shadow-2xl shadow-cyan-950/50">
            <div className="mb-1 text-lg font-medium text-slate-50">{t("mission.createTitle")}</div>
            <p className="mb-5 text-xs leading-5 text-slate-500">{mission && !["completed", "cancelled"].includes(mission.execution_state) ? t("mission.createReplaceDesc") : t("mission.createDesc")}</p>
            <div className="mb-5 rounded-xl border border-cyan-300/20 bg-cyan-300/[.06] p-3 text-xs text-slate-300">{locale === "zh" ? `本任务将使用设置中选择的 ${aiMode.toUpperCase()}。可在 设置 → AI 中切换。` : `This mission will use ${aiMode.toUpperCase()} selected in Settings → AI.`}</div>
            {aiMode === "llm" && <div className="mb-5 space-y-3">
              <label className="block text-xs text-slate-400">{t("mission.projectContext")}<textarea value={projectContext} onChange={(event) => setProjectContext(event.target.value)} maxLength={4000} rows={3} className="mt-1 w-full resize-y rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-xs leading-5 text-slate-200 outline-none focus:border-cyan-300/40" placeholder={t("mission.projectPlaceholder")} /></label>
              <label className="block text-xs text-slate-400">{t("mission.analysisPrompt")}<textarea value={analysisPrompt} onChange={(event) => setAnalysisPrompt(event.target.value)} maxLength={2000} rows={3} className="mt-1 w-full resize-y rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-xs leading-5 text-slate-200 outline-none focus:border-cyan-300/40" placeholder={t("mission.promptPlaceholder")} /></label>
              <p className="text-[10px] leading-4 text-slate-600">{t("mission.llmNotice")}</p>
            </div>}
            <div className="flex justify-end gap-2"><Button onClick={() => setCreateOpen(false)}>{t("actions.cancel")}</Button><Button onClick={createMission} active disabled={working}>{working ? t("actions.initRunning") : mission && !["completed", "cancelled"].includes(mission.execution_state) ? t("actions.endAndCreate") : t("actions.initMission")}</Button></div>
          </div>
        </div>}
      </> : <NodeTab node={activeTab} mission={mission} providerHealth={providerHealth} activeAiMode={aiMode} gtxLink={config?.links.gtx} locale={locale} />}
    </main>
  );
}

function Title({ icon, text, orange }: { icon: React.ReactNode; text: string; orange?: boolean }) { return <h2 className={`flex items-center gap-2 text-sm font-medium ${orange ? "[&>svg]:text-orange-300" : "[&>svg]:text-cyan-300"}`}>{icon}{text}</h2>; }
function PanelHeader({ icon, title, note }: { icon: React.ReactNode; title: string; note: string }) { return <div className="flex items-center justify-between border-b border-white/[.06] px-4 py-3"><Title icon={icon} text={title} /><span className="text-[10px] tracking-wider text-slate-500">{note}</span></div>; }
function Metric({ label, value, good }: { label: string; value: string; good?: boolean }) { return <div className="rounded-lg border border-white/[.055] bg-black/15 px-3 py-2"><div className="text-[9px] tracking-wider text-slate-600 uppercase">{label}</div><div className={`mt-1 font-mono text-xs ${good ? "text-emerald-300" : "text-slate-200"}`}>{value}</div></div>; }
function Empty({ text }: { text: string }) { return <div className="py-8 text-center text-xs text-slate-600">{text}</div>; }
function Stage({ label, complete, active, last }: { label: string; complete: boolean; active: boolean; last: boolean }) { return <div className="relative flex flex-1 flex-col items-center text-center"><div className={`relative z-10 size-3 rounded-full border ${active ? "border-cyan-100 bg-cyan-300 shadow-[0_0_14px_#51e5ff]" : complete ? "border-emerald-300 bg-emerald-400" : "border-slate-600 bg-slate-900"}`} />{!last && <div className={`absolute left-1/2 top-[5px] h-px w-full ${complete ? "bg-emerald-400/60" : "bg-slate-700"}`} />}<span className={`mt-3 text-[10px] ${active ? "text-cyan-100" : complete ? "text-emerald-200/80" : "text-slate-600"}`}>{label}</span></div>; }
function LinkCard({ title, rate = 0, latency = 0, accent, locale }: { title: string; rate?: number; latency?: number; accent: "cyan" | "orange"; locale: Parameters<typeof translate>[0] }) { return <div className="rounded-xl border border-white/[.055] bg-black/15 p-3"><div className="mb-2 flex items-center justify-between text-xs"><span className="text-slate-300">{title}</span><span className="text-cyan-300">{translate(locale, "link.ready")}</span></div><div className="grid grid-cols-2 gap-2"><Metric label={translate(locale, "link.bandwidth")} value={rate >= 1e9 ? `${(rate / 1e9).toFixed(1)} Gbps` : `${(rate / 1e6).toFixed(0)} Mbps`} /><Metric label={translate(locale, "link.latency")} value={`${latency} ms`} /></div></div>; }
function ProductCard({ product }: { product: ProductManifest }) { return <a href={artifactURL(product.id)} target="_blank" rel="noreferrer" className="rounded-xl border border-white/[.06] bg-black/15 p-3 transition hover:border-cyan-300/25"><div className="mb-2 flex items-center justify-between"><span className="rounded bg-cyan-300/10 px-2 py-1 text-[10px] font-semibold text-cyan-200">{product.level.toUpperCase()}</span><span className="text-[10px] text-slate-600">{formatBytes(product.size_bytes)}</span></div><div className="truncate text-xs text-slate-300">{product.name}</div><div className="mt-2 truncate font-mono text-[9px] text-slate-600">SHA {product.sha256.slice(0, 16)}…</div></a>; }
