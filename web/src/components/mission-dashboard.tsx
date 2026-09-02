"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Image from "next/image";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  Activity, AlertTriangle, Clock3, Database, FileImage, Gauge,
  ListTodo, LoaderCircle, Orbit, Radio, Settings2, StepForward, Zap
} from "lucide-react";

import { api, artifactURL, eventStreamURL } from "~/lib/api";
import { useDashboardStore } from "~/lib/store";
import { formatDateTime, formatTime, localeTag, translate } from "~/lib/i18n";
import type {
  AIMode, MissionPhase, MissionResultResponse, MissionSummary, NodeKind, OrbitTrack, ProductManifest, PublicConfig, ScenarioRecord
} from "~/lib/types";
import { NodeTab } from "./node-tab";
import { ProtocolInspector } from "./protocol-inspector";
import { OrbitGlobe } from "./orbit-globe";
import { SystemTopology } from "./system-topology";
import { DesktopSettingsPanel } from "./desktop-settings";
import { NewSatelliteWizard } from "./new-satellite-wizard";
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
  const [newSatelliteOpen, setNewSatelliteOpen] = useState(false);
  const [replaceConfirmOpen, setReplaceConfirmOpen] = useState(false);
  const aiMode: AIMode = "llm";
  const [projectContext, setProjectContext] = useState(() => t("mission.defaultProjectContext"));
  const [analysisPrompt, setAnalysisPrompt] = useState(() => t("mission.defaultAnalysisPrompt"));
  const [missionResult, setMissionResult] = useState<MissionResultResponse>();
  const [playbackSpeed] = useState<1 | 2 | 5>(1);
  const [activeTab, setActiveTab] = useState<NodeKind>("ground");
  const [activeSidebar, setActiveSidebar] = useState<"mission" | "protocol" | "tasks">();
  const [missionScope, setMissionScope] = useState<"all" | "active">("all");
  const [missionSummaries, setMissionSummaries] = useState<MissionSummary[]>([]);
  const [scenarioRecords, setScenarioRecords] = useState<ScenarioRecord[]>([]);
  const [viewedMissionId, setViewedMissionId] = useState<string>();
  const [historyView, setHistoryView] = useState(false);
  const [desktopSettingsOpen, setDesktopSettingsOpen] = useState(false);
  const [settingsMenuOpen, setSettingsMenuOpen] = useState(false);
  const [settingsSection, setSettingsSection] = useState<"general" | "plugins" | "ai" | "agent" | "scene" | "data" | "about">("general");
  const [savedScenarioId, setSavedScenarioId] = useState<string>();
  const settingsMenuRef = useRef<HTMLDivElement>(null);
  const missionId = mission?.command.id;
  const runId = mission?.command.run_id;
  const activeScenarioId = scenario?.config.id;
  useEffect(() => {
    if (new URLSearchParams(window.location.search).get("jetsonDeployment") !== "1") return;
    setSettingsSection("ai");
    setDesktopSettingsOpen(true);
    window.history.replaceState({}, "", window.location.pathname);
  }, []);
  const viewedScenario = useMemo(() => mission
    ? scenarioRecords.find((item) => item.config.id === mission.command.scenario_id) ?? scenario
    : scenario, [mission, scenario, scenarioRecords]);
  const viewedScenarioId = viewedScenario?.config.id;
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
        setSavedScenarioId(saved.activeScenarioId);
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
    const closeTransientUi = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      if (replaceConfirmOpen) { setReplaceConfirmOpen(false); return; }
      if (createOpen) { setCreateOpen(false); return; }
      if (newSatelliteOpen) { setNewSatelliteOpen(false); return; }
      if (desktopSettingsOpen) { setDesktopSettingsOpen(false); return; }
      if (settingsMenuOpen) { setSettingsMenuOpen(false); return; }
      if (activeSidebar) setActiveSidebar(undefined);
    };
    window.addEventListener("keydown", closeTransientUi);
    return () => window.removeEventListener("keydown", closeTransientUi);
  }, [activeSidebar, createOpen, desktopSettingsOpen, newSatelliteOpen, replaceConfirmOpen, settingsMenuOpen]);
  useEffect(() => {
    document.documentElement.lang = localeTag(locale);
    window.localStorage.setItem("sat-sim-locale", locale);
  }, [locale]);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    window.localStorage.setItem("sat-sim-theme", theme);
  }, [theme]);

  const reload = useCallback(async (preferredMissionId?: string) => {
    try {
      const [publicConfig, scenarioRows, missions, providers] = await Promise.all([
        api.config(), api.scenarios(), api.missions(), api.providerHealth()
      ]);
      setConfig(publicConfig);
      setProviderHealth(providers);
      setScenarioRecords(scenarioRows);
      setMissionSummaries(missions);
      const activeScenario = scenarioRows.find((item) => item.config.id === savedScenarioId)
        ?? scenarioRows.find((item) => item.config.id === scenario?.config.id)
        ?? scenarioRows.find((item) => item.config.scene_ready)
        ?? scenarioRows[0]
        ?? await api.createScenario(t("scenario.defaultName"));
      setScenario(activeScenario);
      const visibleMissionId = preferredMissionId ?? viewedMissionId
        ?? (mission?.command.scenario_id === activeScenario.config.id ? mission.command.id : undefined);
      if (visibleMissionId && missions.some((item) => item.command.id === visibleMissionId)) {
        const detail = await api.mission(visibleMissionId);
        setMission(detail);
        const missionScenarioId = detail.command.scenario_id;
        try { setOrbit(await api.orbit(missionScenarioId)); }
        catch { setOrbit(undefined); }
      } else {
        setMission(undefined);
        try { setOrbit(await api.orbit(activeScenario.config.id)); }
        catch { setOrbit(undefined); }
      }
      setError(undefined);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : t("errors.load"));
    } finally { setLoading(false); }
  }, [mission?.command.id, mission?.command.scenario_id, savedScenarioId, scenario?.config.id, setMission, setScenario, viewedMissionId]);

  useEffect(() => { void reload(); }, [reload]);
  useEffect(() => {
    const readTab = () => {
      const params = new URLSearchParams(window.location.search);
      const value = params.get("tab");
      setActiveTab(["ground", "platform", "optical", "gpu"].includes(value ?? "")
        ? value as NodeKind : "ground");
      const missionFromUrl = params.get("mission") ?? undefined;
      setViewedMissionId(missionFromUrl);
      setHistoryView(Boolean(missionFromUrl));
      if (!missionFromUrl) setMission(undefined);
    };
    readTab();
    window.addEventListener("popstate", readTab);
    return () => window.removeEventListener("popstate", readTab);
  }, [setMission]);
  useEffect(() => {
    if (!viewedScenarioId) return;
    const timer = window.setInterval(async () => {
      try { setOrbit(await api.orbit(viewedScenarioId)); } catch { /* next refresh retries */ }
    }, 10_000);
    return () => window.clearInterval(timer);
  }, [viewedScenarioId]);
  useEffect(() => {
    if (!missionId) return;
    const timer = window.setInterval(async () => {
      try {
        const detail = await api.mission(missionId);
        setMission(detail);
        setMissionSummaries((items) => items.map((item) => item.command.id === detail.command.id ? detail : item));
      } catch { /* next poll retries */ }
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
    if (!missionId || !runId || !viewedScenarioId) return;
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
            api.mission(missionId), api.orbit(viewedScenarioId), api.scenarios(),
          ]);
          setMission(detail);
          setMissionSummaries((items) => items.map((item) => item.command.id === detail.command.id ? detail : item));
          setOrbit(track);
          setScenarioRecords(scenarios);
        } catch { /* polling remains as fallback */ }
      } while (eventRefreshQueued.current);
      eventRefreshActive.current = false;
    };
    stream.addEventListener("telemetry", () => { void refreshLatest(); });
    return () => stream.close();
  }, [missionId, runId, viewedScenarioId, setMission]);

  const run = async (operation: () => Promise<unknown>) => {
    setWorking(true);
    try { await operation(); await reload(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : t("errors.operation")); }
    finally { setWorking(false); }
  };
  const createMission = () => scenario && (async () => {
    setWorking(true);
    setError(undefined);
    try {
      // A non-terminal mission can be selected through the history drawer.
      // It still owns the scenario, so treating it as read-only must not leave
      // the user unable either to continue or to start a new run.
      const scenarioActiveMission = missionSummaries.find((item) =>
        item.command.scenario_id === scenario.config.id
        && !["completed", "cancelled"].includes(item.execution_state)
      );
      if (scenarioActiveMission) {
        await api.cancelMission(scenarioActiveMission.command.id);
      }
      const configuredModel = (await desktopBridge()?.getSettings())?.llmModel;
      const created = await api.createMission(
        scenario.config.id, t("mission.defaultName"), aiMode, projectContext.trim(), analysisPrompt.trim(), configuredModel || undefined
      );
      setMission(created);
      setViewedMissionId(created.command.id);
      setHistoryView(false);
      setHistoricalMissionUrl();
      setCreateOpen(false);
      await reload(created.command.id);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : t("errors.operation"));
    } finally {
      setWorking(false);
    }
  })();
  const activeScenarioMission = scenario && missionSummaries.find((item) =>
    item.command.scenario_id === scenario.config.id
    && !["completed", "cancelled"].includes(item.execution_state)
  );
  const requestCreateMission = () => {
    if (activeScenarioMission) {
      setReplaceConfirmOpen(true);
      return;
    }
    setCreateOpen(true);
  };
  const activateNewSatellite = async (selected: ScenarioRecord) => {
    setWorking(true);
    setError(undefined);
    try {
      if (mission && !["completed", "cancelled"].includes(mission.execution_state)) {
        await api.cancelMission(mission.command.id);
      }
      setMission(undefined);
      setViewedMissionId(undefined);
      setHistoryView(false);
      setHistoricalMissionUrl();
      setSavedScenarioId(selected.config.id);
      setScenario(selected);
      setScenarioRecords(await api.scenarios());
      setOrbit(await api.orbit(selected.config.id));
      const bridge = desktopBridge();
      if (bridge) {
        const saved = await bridge.getSettings();
        await bridge.saveSettings({ ...saved, activeScenarioId: selected.config.id });
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : t("errors.sceneSwitch"));
      throw cause;
    } finally { setWorking(false); }
  };
  const advanceMission = () => mission && !historyView && run(async () => {
    await api.advanceMission(
      mission.command.id,
      playbackSpeed,
      `${mission.phase}-${crypto.randomUUID()}`
    );
    setMission(await api.mission(mission.command.id));
  });
  const missionCompleted = mission?.execution_state === "completed" || mission?.phase === "completed";
  const historyReadOnlyLabel = t("mission.historyReadOnly");
  const openSettings = (section: "general" | "plugins" | "ai" | "agent" | "scene" | "data" | "about") => {
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
  const setHistoricalMissionUrl = (selectedMissionId?: string) => {
    const url = new URL(window.location.href);
    if (selectedMissionId) url.searchParams.set("mission", selectedMissionId);
    else url.searchParams.delete("mission");
    window.history.pushState({}, "", url);
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
  const filteredMissionSummaries = useMemo(() => missionSummaries
    .filter((item) => missionScope === "all" || item.command.scenario_id === activeScenarioId)
    .sort((left, right) => new Date(right.created_at).getTime() - new Date(left.created_at).getTime()),
    [activeScenarioId, missionScope, missionSummaries]);
  const selectHistoricalMission = async (summary: MissionSummary) => {
    setWorking(true);
    setError(undefined);
    try {
      const detail = await api.mission(summary.command.id);
      setMission(detail);
      setViewedMissionId(detail.command.id);
      setHistoryView(true);
      setHistoricalMissionUrl(detail.command.id);
      const sourceScenario = scenarioRecords.find((item) => item.config.id === detail.command.scenario_id);
      if (sourceScenario) setOrbit(await api.orbit(sourceScenario.config.id));
      else setOrbit(undefined);
      setActiveSidebar(undefined);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : t("errors.missionLoad"));
    } finally {
      setWorking(false);
    }
  };
  const latestVisibleEventId = visibleEvents.at(-1)?.id;
  useEffect(() => {
    eventListRef.current?.scrollTo({ top: 0, behavior: "smooth" });
  }, [latestVisibleEventId]);

  if (loading) return <div className="flex min-h-screen items-center justify-center text-cyan-200"><LoaderCircle className="mr-2 animate-spin" />{t("mission.loading")}</div>;

  const sidebarOpen = Boolean(activeSidebar);
  const toggleSidebar = (view: "mission" | "protocol" | "tasks") => {
    setSettingsMenuOpen(false);
    setActiveSidebar((current) => current === view ? undefined : view);
  };
  const topologyMission = mission ? {
    phase: mission.phase,
    executionState: mission.execution_state,
    activeSubstage: mission.active_substage,
    aiMode: mission.ai_mode,
    providerStatus: mission.ai_mode === "llm"
      ? providerHealth.language?.status
      : "retired",
  } : undefined;

  return <div className="workspace-shell">
    <aside className="activity-bar z-[60] flex w-16 flex-col items-center border-r border-cyan-200/15 py-3 shadow-xl shadow-black/20" aria-label={t("sidebar.activity")}>
      <button type="button" title={t("sidebar.mission")} aria-label={t("sidebar.mission")} onClick={() => toggleSidebar("mission")} className={`activity-bar-button ${activeSidebar === "mission" ? "activity-bar-button--active" : ""}`}><Activity size={22} /></button>
      <button type="button" title={t("sidebar.protocol")} aria-label={t("sidebar.protocol")} onClick={() => toggleSidebar("protocol")} className={`activity-bar-button ${activeSidebar === "protocol" ? "activity-bar-button--active" : ""}`}><Radio size={22} /></button>
      <button type="button" title={t("sidebar.tasks")} aria-label={t("sidebar.tasks")} onClick={() => toggleSidebar("tasks")} className={`activity-bar-button ${activeSidebar === "tasks" ? "activity-bar-button--active" : ""}`}><ListTodo size={22} /></button>
      <div ref={settingsMenuRef} className="relative mt-auto">
        <button type="button" title={t("sidebar.settings")} aria-label={t("sidebar.settings")} onClick={() => { setActiveSidebar(undefined); setSettingsMenuOpen((open) => !open); }} className={`activity-bar-button ${settingsMenuOpen ? "activity-bar-button--active" : ""}`}><Settings2 size={22} /></button>
        {settingsMenuOpen && <div className="settings-activity-menu absolute bottom-0 left-14 z-[70] min-w-44 rounded-xl border border-cyan-200/25 bg-slate-950/95 p-1.5 shadow-xl shadow-black/50 backdrop-blur"><button onClick={() => openSettings("general")} className="settings-menu-item w-full rounded-lg px-3 py-2.5 text-left text-xs font-medium text-slate-200 transition hover:bg-cyan-300/25 hover:text-cyan-50">{t("sidebar.general")}</button><button onClick={() => openSettings("plugins")} className="settings-menu-item w-full rounded-lg px-3 py-2.5 text-left text-xs font-medium text-slate-200 transition hover:bg-cyan-300/25 hover:text-cyan-50">{t("sidebar.plugins")}</button><button onClick={() => openSettings("ai")} className="settings-menu-item w-full rounded-lg px-3 py-2.5 text-left text-xs font-medium text-slate-200 transition hover:bg-cyan-300/25 hover:text-cyan-50">AI</button><button onClick={() => openSettings("agent")} className="settings-menu-item w-full rounded-lg px-3 py-2.5 text-left text-xs font-medium text-slate-200 transition hover:bg-cyan-300/25 hover:text-cyan-50">{t("sidebar.agent")}</button><button onClick={() => openSettings("scene")} className="settings-menu-item w-full rounded-lg px-3 py-2.5 text-left text-xs font-medium text-slate-200 transition hover:bg-cyan-300/25 hover:text-cyan-50">{t("sidebar.scene")}</button><button onClick={() => openSettings("data")} className="settings-menu-item settings-menu-item--danger w-full rounded-lg px-3 py-2.5 text-left text-xs font-medium transition">{t("sidebar.data")}</button><button onClick={() => openSettings("about")} className="settings-menu-item w-full rounded-lg px-3 py-2.5 text-left text-xs font-medium text-slate-200 transition hover:bg-cyan-300/25 hover:text-cyan-50">{t("sidebar.about")}</button></div>}
      </div>
    </aside>
    {sidebarOpen && <aside aria-label={activeSidebar === "protocol" ? t("sidebar.protocol") : activeSidebar === "tasks" ? t("sidebar.tasks") : t("sidebar.mission")} className="workspace-sidebar z-50 flex max-w-none flex-col border-r border-cyan-300/20 shadow-2xl shadow-black/50">
      {activeSidebar === "tasks" ? <>
        <div className="border-b border-cyan-200/10 px-5 py-4"><div className="text-sm font-medium text-cyan-100">{t("sidebar.tasks")}</div><div className="mt-1 text-[10px] tracking-wider text-slate-500">{t("sidebar.tasksSubtitle")}</div></div>
        <div className="min-h-0 flex-1 overflow-y-auto p-4">
          <div className="mb-4 grid grid-cols-2 rounded-xl border border-white/[.06] bg-black/15 p-1"><button onClick={() => setMissionScope("all")} className={`rounded-lg px-3 py-2 text-xs transition ${missionScope === "all" ? "bg-cyan-300/15 text-cyan-100" : "text-slate-500 hover:text-slate-300"}`}>{t("mission.all")}</button><button onClick={() => setMissionScope("active")} className={`rounded-lg px-3 py-2 text-xs transition ${missionScope === "active" ? "bg-cyan-300/15 text-cyan-100" : "text-slate-500 hover:text-slate-300"}`}>{t("mission.activeScene")}</button></div>
          <p className="mb-3 text-[11px] leading-5 text-slate-500">{t("mission.historyHint")}</p>
          <div className="space-y-2">{filteredMissionSummaries.map((item) => { const sourceScenario = scenarioRecords.find((entry) => entry.config.id === item.command.scenario_id); const selected = item.command.id === mission?.command.id; const issue = item.block_reason ?? item.error; return <button key={item.command.id} onClick={() => void selectHistoricalMission(item)} disabled={working} className={`w-full rounded-xl border p-3 text-left transition disabled:cursor-wait disabled:opacity-60 ${selected ? "border-cyan-300/55 bg-cyan-300/12 shadow-[inset_0_0_0_1px_rgba(81,229,255,.12)]" : "border-white/[.07] bg-black/15 hover:border-cyan-300/30 hover:bg-cyan-300/[.05]"}`}><div className="flex items-start justify-between gap-3"><span className="line-clamp-2 text-xs font-medium text-slate-200">{item.command.name}</span><span className={`shrink-0 rounded border px-1.5 py-0.5 font-mono text-[9px] ${item.execution_state === "completed" ? "border-emerald-300/25 text-emerald-300" : item.execution_state === "blocked" || item.execution_state === "retryable_error" ? "border-orange-300/25 text-orange-300" : "border-cyan-300/20 text-cyan-200"}`}>{item.execution_state}</span></div><div className="mt-2 text-[10px] text-slate-500">{sourceScenario?.config.name ?? item.command.scenario_id}</div><div className="mt-1 flex flex-wrap gap-x-2 gap-y-1 text-[10px] text-slate-600"><span>{t(`stage.${item.phase}` as Parameters<typeof t>[0])}</span><span>{item.ai_mode.toUpperCase()}</span><span>{formatDateTime(locale, item.created_at)}</span></div>{issue && <div className="mt-2 line-clamp-2 text-[10px] leading-4 text-orange-300">{issue}</div>}</button>; })}{!filteredMissionSummaries.length && <Empty text={t("mission.noMatching")} />}</div>
        </div>
      </> : activeSidebar === "protocol" ? <>
        <div className="border-b border-cyan-200/10 px-5 py-4"><div className="text-sm font-medium text-cyan-100">{t("sidebar.protocol")}</div><div className="mt-1 text-[10px] tracking-wider text-slate-500">{t("sidebar.protocolSubtitle")}</div></div>
        <div className="min-h-0 flex-1 overflow-y-auto p-4"><ProtocolInspector missionId={mission?.command.id} runId={mission?.command.run_id} locale={locale} /></div>
      </> : <>
        <div className="border-b border-cyan-200/10 px-5 py-4"><div className="text-sm font-medium text-cyan-100">{t("sidebar.mission")}</div><div className="mt-1 text-[10px] tracking-wider text-slate-500">{t("sidebar.missionSubtitle")}</div></div>
        <div className="min-h-0 flex-1 overflow-y-auto p-4"><section className="panel rounded-2xl p-4">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3 border-b border-white/[.06] pb-4"><div className="flex flex-wrap items-center gap-3"><Title icon={<Clock3 size={16} />} text={t("controls.mission")} /><span className="font-mono text-xs text-cyan-100">{viewedScenario ? formatDateTime(locale, viewedScenario.clock.simulated_at) : "--"}</span><span className={`rounded border px-2 py-1 text-[10px] ${viewedScenario?.clock.paused ? "border-emerald-300/20 text-emerald-300" : "border-orange-300/20 text-orange-300"}`}>{viewedScenario?.clock.paused ? t("controls.paused") : t("controls.running")}</span></div>{historyView ? <span className="rounded border border-orange-300/25 bg-orange-300/[.06] px-3 py-2 text-xs text-orange-200">{historyReadOnlyLabel}</span> : <Button onClick={advanceMission} active disabled={!mission?.can_advance || mission?.execution_state === "running" || working}>{mission?.execution_state === "running" ? <LoaderCircle size={14} className="animate-spin" /> : <StepForward size={14} />}{mission?.execution_state === "running" ? t("controls.stageRunning") : advanceLabel}</Button>}</div>
          <div className="mb-4 flex items-center justify-between gap-3"><Title icon={<Activity size={16} />} text={t("mission.timeline")} /><span className={`rounded-full border px-2.5 py-1 text-[10px] ${mission?.execution_state === "blocked" ? "border-orange-400/30 text-orange-300" : "border-cyan-300/20 text-cyan-200"}`}>{mission ? `${mission.phase} · ${mission.execution_state}` : t("mission.waiting")}</span></div>
          <div className="overflow-x-auto pb-2"><div className="flex min-w-[700px] items-start">{stages.map(([key, label], index) => <Stage key={key} label={t(label)} complete={mission?.phase === "completed" || index < stageIndex} active={key === mission?.phase} last={index === stages.length - 1} />)}</div></div>
          {mission?.planned_windows && <div className="mt-4 grid gap-2 border-t border-white/[.05] pt-4 sm:grid-cols-3"><Metric label={t("mission.uplinkAos")} value={formatDateTime(locale, mission.planned_windows.uplink.aos)} /><Metric label={t("mission.captureAt")} value={formatDateTime(locale, mission.planned_windows.capture.max_elevation_at)} /><Metric label={t("mission.downlinkAos")} value={formatDateTime(locale, mission.planned_windows.downlink.aos)} /></div>}
          {mission?.execution_state === "blocked" && <p className="mt-3 text-xs leading-5 text-orange-200">{mission.block_reason}</p>}{mission?.execution_state === "retryable_error" && <p className="mt-3 text-xs leading-5 text-red-300">{t("mission.retryable")}{mission.error}</p>}
          <div ref={eventListRef} className="mt-4 max-h-56 space-y-2 overflow-auto border-t border-white/[.05] pt-4">{visibleEvents.length ? [...visibleEvents].reverse().map((event) => <div key={event.id} className={`grid grid-cols-[72px_1fr] gap-3 rounded-lg px-2 py-1.5 text-xs ${["macro_phase_blocked", "macro_phase_failed"].includes(event.event_type) ? "bg-orange-400/[.06]" : ""}`}><span className="font-mono text-slate-600">{formatTime(locale, event.simulated_at)}</span><div><div className="text-slate-300">{localizedEventMessage(t, event)}</div><div className="mt-0.5 text-[10px] text-slate-600">{event.source} · {event.channel} · {event.event_type}</div></div></div>) : <Empty text={t("mission.events.empty")} />}</div>
        </section></div>
      </>}
    </aside>}
    <main className="mission-content grid-scan min-h-screen p-4 lg:p-6">
      <header className="mb-5 flex flex-wrap items-end justify-between gap-4 border-b border-cyan-200/10 pb-5">
        <div>
          <div className="mb-2 flex items-center gap-2 text-[10px] tracking-[.34em] text-cyan-300/60 uppercase"><Orbit size={13} />Satellite Onboard AI · SIL</div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-50 lg:text-3xl">{t("app.title")}</h1>
          {/* <p className="mt-1 text-xs text-slate-500">{t("app.subtitle")}</p> */}
        </div>
        <div className="flex gap-2"><Button onClick={() => setNewSatelliteOpen(true)} active disabled={working}><Orbit size={14} />{t("actions.newSat")}</Button><Button onClick={requestCreateMission} active disabled={!scenario || working}><Zap size={14} />{t("actions.newMission")}</Button></div>
      </header>
      {error && <div className="mb-4 flex items-center gap-2 rounded-lg border border-orange-400/25 bg-orange-400/10 px-4 py-3 text-sm text-orange-100"><AlertTriangle size={16} />{error}</div>}

      <DesktopSettingsPanel open={desktopSettingsOpen} onClose={() => setDesktopSettingsOpen(false)} locale={locale} onLocale={setLocale} onTheme={setTheme} initialSection={settingsSection} onScenarioImported={() => void reload()} onSettingsSaved={() => void reload()} activeScenarioId={scenario?.config.id} onScenarioSelected={(selected) => {
        return (async () => {
          if (selected.config.id === scenario?.config.id) return;
          setWorking(true);
          setError(undefined);
          try {
            // Preserve the old run for audit/replay, but make it terminal before
            // its frozen YAML snapshot can no longer be the active scene.
            if (mission && !["completed", "cancelled"].includes(mission.execution_state)) {
              await api.cancelMission(mission.command.id);
            }
            setMission(undefined);
            setViewedMissionId(undefined);
            setHistoryView(false);
            setHistoricalMissionUrl();
            setSavedScenarioId(selected.config.id);
            setScenario(selected);
            setOrbit(await api.orbit(selected.config.id));
          } catch (cause) {
            setError(cause instanceof Error ? cause.message : t("errors.sceneSwitch"));
            throw cause;
          } finally {
            setWorking(false);
          }
        })();
      }} />
      {newSatelliteOpen && <NewSatelliteWizard locale={locale} onClose={() => setNewSatelliteOpen(false)} onCompleted={activateNewSatellite} />}

      <section className="panel mb-4 rounded-2xl p-2">
        <SystemTopology onNavigate={navigateTab} mission={topologyMission} locale={locale} />
      </section>
      <nav className="panel mb-4 flex overflow-x-auto rounded-2xl p-1.5" aria-label={t("nav.nodes")}>
        {(["ground", "platform", "optical", "gpu"] as NodeKind[]).map((tab) => <button key={tab} onClick={() => navigateTab(tab)} className={`min-w-32 flex-1 rounded-xl px-4 py-3 text-xs transition ${activeTab === tab ? "bg-cyan-300/12 text-cyan-100 shadow-[inset_0_0_0_1px_rgba(81,229,255,.25)]" : "text-slate-500 hover:bg-white/[.035] hover:text-slate-300"}`}>{t(`tabs.${tab}` as Parameters<typeof t>[0])}</button>)}
      </nav>

      {activeTab === "ground" ? <>

        <section
          className="ground-panel-pair mb-4"
          style={{ gridTemplateColumns: "minmax(0, 1.2fr) minmax(22.5rem, .8fr)" }}
        >
          <div className="panel flex min-w-0 flex-col overflow-hidden rounded-2xl">
            <PanelHeader icon={<Orbit size={16} />} title={t("ground.orbit")} note="TLE SNAPSHOT · SGP4" />
            <OrbitGlobe
              track={orbit}
              station={{
                name: viewedScenario?.config.ground_station_name ?? "GS-DEMO-BEIJING",
                latitude: viewedScenario?.config.ground_station_latitude ?? 39.9042,
                longitude: viewedScenario?.config.ground_station_longitude ?? 116.4074,
                altitudeM: viewedScenario?.config.ground_station_altitude_m ?? 50,
              }}
              target={mission ? {
                name: mission.command.target_name,
                latitude: mission.command.target_latitude,
                longitude: mission.command.target_longitude,
              } : undefined}
              locale={locale}
            />
          </div>
          <div className="panel rounded-2xl p-4">
            <div className="mb-3 flex items-center justify-between"><Title icon={<Orbit size={16} />} text={t("ground.satelliteConfig")} /><span className="text-[10px] text-slate-500">{t("ground.satelliteConfigNote")}</span></div>
            <div className="grid grid-cols-2 gap-3 text-xs">
              <Metric label={t("ground.satelliteName")} value={viewedScenario?.config.satellite_name ?? "—"} good />
              <Metric label={t("ground.sceneStatus")} value={viewedScenario?.config.scene_ready ? t("ground.sceneReady") : t("ground.scenePending")} good={viewedScenario?.config.scene_ready} />
              <Metric label={t("ground.groundStation")} value={viewedScenario?.config.ground_station_name ?? "—"} />
              <Metric label={t("ground.altitude")} value={`${Number(viewedScenario?.config.ground_station_altitude_m ?? 0).toFixed(0)} m`} />
              <Metric label={t("ground.latitude")} value={`${Number(viewedScenario?.config.ground_station_latitude ?? 0).toFixed(4)}°`} />
              <Metric label={t("ground.longitude")} value={`${Number(viewedScenario?.config.ground_station_longitude ?? 0).toFixed(4)}°`} />
            </div>
            <div className="mt-3 rounded-lg border border-white/[.055] bg-black/15 px-3 py-2"><div className="text-[9px] tracking-wider text-slate-600 uppercase">{t("ground.tle")}</div><div className="mt-1 break-all font-mono text-[10px] leading-4 text-slate-400">{viewedScenario?.config.tle_line1 ?? "—"}<br />{viewedScenario?.config.tle_line2 ?? ""}</div></div>
          </div>
        </section>
        <section
          className="ground-panel-pair mb-4"
          style={{ gridTemplateColumns: "minmax(0, 1.2fr) minmax(22.5rem, .8fr)" }}
        >
          <div className="panel rounded-2xl p-4">
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

      </> : <NodeTab node={activeTab} mission={mission} providerHealth={providerHealth} activeAiMode={aiMode} gtxLink={config?.links.gtx} scenario={scenario?.config} onConfigurationChanged={() => void reload(mission?.command.id)} locale={locale} />}
      {replaceConfirmOpen && <div className="fixed inset-0 z-[80] flex items-center justify-center bg-slate-950/80 p-4 backdrop-blur-sm" role="dialog" aria-modal="true" aria-labelledby="replace-mission-title">
        <div className="panel w-full max-w-md rounded-2xl p-5 shadow-2xl shadow-cyan-950/50">
          <h2 id="replace-mission-title" className="text-lg font-medium text-slate-50">{t("mission.replaceTitle")}</h2>
          <p className="mt-3 text-sm leading-6 text-slate-400">{t("mission.replaceDescription", { name: activeScenarioMission?.command.name ?? "" })}</p>
          <div className="mt-5 flex justify-end gap-2"><Button onClick={() => setReplaceConfirmOpen(false)}>{t("actions.cancel")}</Button><Button onClick={() => { setReplaceConfirmOpen(false); setCreateOpen(true); }} active>{t("mission.continue")}</Button></div>
        </div>
      </div>}
      {createOpen && <div className="fixed inset-0 z-[80] flex items-center justify-center bg-slate-950/80 p-4 backdrop-blur-sm">
        <div className="panel w-full max-w-md rounded-2xl p-5 shadow-2xl shadow-cyan-950/50">
          <div className="mb-1 text-lg font-medium text-slate-50">{t("mission.createTitle")}</div>
          <p className="mb-5 text-xs leading-5 text-slate-500">{mission && !["completed", "cancelled"].includes(mission.execution_state) ? t("mission.createReplaceDesc") : t("mission.createDesc")}</p>
          {/* <div className="mb-5 rounded-xl border border-cyan-300/20 bg-cyan-300/[.06] p-3 text-xs text-slate-300">{t("mission.aiModeNotice", { mode: "LLM" })}</div> */}
          <div className="mb-5 space-y-3"><label className="block text-xs text-slate-400">{t("mission.projectContext")}<textarea value={projectContext} onChange={(event) => setProjectContext(event.target.value)} maxLength={4000} rows={3} className="mt-1 w-full resize-y rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-xs leading-5 text-slate-200 outline-none focus:border-cyan-300/40" placeholder={t("mission.projectPlaceholder")} /></label><label className="block text-xs text-slate-400">{t("mission.analysisPrompt")}<textarea value={analysisPrompt} onChange={(event) => setAnalysisPrompt(event.target.value)} maxLength={2000} rows={3} className="mt-1 w-full resize-y rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-xs leading-5 text-slate-200 outline-none focus:border-cyan-300/40" placeholder={t("mission.promptPlaceholder")} /></label></div>
          <div className="flex justify-end gap-2"><Button onClick={() => setCreateOpen(false)}>{t("actions.cancel")}</Button><Button onClick={createMission} active disabled={working}>{working ? t("actions.initRunning") : mission && !["completed", "cancelled"].includes(mission.execution_state) ? t("actions.endAndCreate") : t("actions.initMission")}</Button></div>
        </div>
      </div>}
    </main>
  </div>;
}

function Title({ icon, text, orange }: { icon: React.ReactNode; text: string; orange?: boolean }) { return <h2 className={`flex items-center gap-2 text-sm font-medium ${orange ? "[&>svg]:text-orange-300" : "[&>svg]:text-cyan-300"}`}>{icon}{text}</h2>; }
function PanelHeader({ icon, title, note }: { icon: React.ReactNode; title: string; note: string }) { return <div className="flex items-center justify-between border-b border-white/[.06] px-4 py-3"><Title icon={icon} text={title} /><span className="text-[10px] tracking-wider text-slate-500">{note}</span></div>; }
function Metric({ label, value, good }: { label: string; value: string; good?: boolean }) { return <div className="rounded-lg border border-white/[.055] bg-black/15 px-3 py-2"><div className="text-[9px] tracking-wider text-slate-600 uppercase">{label}</div><div className={`mt-1 font-mono text-xs ${good ? "text-emerald-300" : "text-slate-200"}`}>{value}</div></div>; }
function Empty({ text }: { text: string }) { return <div className="py-8 text-center text-xs text-slate-600">{text}</div>; }
function Stage({ label, complete, active, last }: { label: string; complete: boolean; active: boolean; last: boolean }) { return <div className="relative flex flex-1 flex-col items-center text-center"><div className={`relative z-10 size-3 rounded-full border ${active ? "border-cyan-100 bg-cyan-300 shadow-[0_0_14px_#51e5ff]" : complete ? "border-emerald-300 bg-emerald-400" : "border-slate-600 bg-slate-900"}`} />{!last && <div className={`absolute left-1/2 top-[5px] h-px w-full ${complete ? "bg-emerald-400/60" : "bg-slate-700"}`} />}<span className={`mt-3 text-[10px] ${active ? "text-cyan-100" : complete ? "text-emerald-200/80" : "text-slate-600"}`}>{label}</span></div>; }
function LinkCard({ title, rate = 0, latency = 0, accent, locale }: { title: string; rate?: number; latency?: number; accent: "cyan" | "orange"; locale: Parameters<typeof translate>[0] }) { const accentClass = accent === "orange" ? "text-orange-300" : "text-cyan-300"; return <div className="rounded-xl border border-white/[.055] bg-black/15 p-3"><div className="mb-2 flex items-center justify-between text-xs"><span className="text-slate-300">{title}</span><span className={accentClass}>{translate(locale, "link.ready")}</span></div><div className="grid grid-cols-2 gap-2"><Metric label={translate(locale, "link.bandwidth")} value={rate >= 1e9 ? `${(rate / 1e9).toFixed(1)} Gbps` : `${(rate / 1e6).toFixed(0)} Mbps`} /><Metric label={translate(locale, "link.latency")} value={`${latency} ms`} /></div></div>; }
function ProductCard({ product }: { product: ProductManifest }) { return <a href={artifactURL(product.id)} target="_blank" rel="noreferrer" className="rounded-xl border border-white/[.06] bg-black/15 p-3 transition hover:border-cyan-300/25"><div className="mb-2 flex items-center justify-between"><span className="rounded bg-cyan-300/10 px-2 py-1 text-[10px] font-semibold text-cyan-200">{product.level.toUpperCase()}</span><span className="text-[10px] text-slate-600">{formatBytes(product.size_bytes)}</span></div><div className="truncate text-xs text-slate-300">{product.name}</div><div className="mt-2 truncate font-mono text-[9px] text-slate-600">SHA {product.sha256.slice(0, 16)}…</div></a>; }
