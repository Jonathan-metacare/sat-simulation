import { Cpu, RadioTower, Satellite, ScanLine } from "lucide-react";

import { translate } from "~/lib/i18n";
import type { Locale } from "~/lib/store";
import type { AIMode, ExecutionState, MissionPhase, NodeKind } from "~/lib/types";

type FlowState = "idle" | "active" | "complete";

export interface TopologyMissionState {
  phase: MissionPhase;
  executionState: ExecutionState;
  activeSubstage?: string;
  aiMode: AIMode;
  providerStatus?: string;
}

export function deriveTopologyFlows(mission?: TopologyMissionState) {
  const running = mission?.executionState === "running";
  const substage = mission?.activeSubstage;
  const phase = mission?.phase;

  return {
    uplink: {
      state: running && ["uplink", "downlink"].includes(substage ?? "")
        ? "active"
        : phase && phase !== "initialized"
          ? "complete"
          : "idle",
      label: substage === "downlink" && running ? "topology.uplinkDownlink" : "topology.datalink",
    } as { state: FlowState; label: string },
    payload: {
      state: running && ["capture", "processing"].includes(substage ?? "")
        ? "active"
        : phase && [
          "capture_complete", "processing_complete", "gtx_complete", "ai_complete", "completed",
        ].includes(phase)
          ? "complete"
          : "idle",
      label: substage === "processing" && running ? "topology.processing" : "topology.payloadBus",
    } as { state: FlowState; label: string },
    gtx: {
      state: running && ["gtx", "ai"].includes(substage ?? "")
        ? "active"
        : phase && ["gtx_complete", "ai_complete", "completed"].includes(phase)
          ? "complete"
          : "idle",
      label: substage === "ai" && running ? "topology.aiResult" : "GTX 2.5G",
    } as { state: FlowState; label: string },
    downlink: {
      state: running && substage === "downlink"
        ? "active"
        : phase === "completed"
          ? "complete"
          : "idle",
      label: "topology.downlink",
    } as { state: FlowState; label: string },
  };
}

export function deriveTopologyFlowStates(mission?: TopologyMissionState) {
  return deriveTopologyFlows(mission);
}

function Node({ icon, title, state, active, onClick }: {
  icon: React.ReactNode;
  title: string;
  state: string;
  active?: boolean;
  onClick?: () => void;
}) {
  return <button type="button" onClick={onClick} className={`relative z-10 flex min-h-[68px] w-28 flex-col items-center justify-center rounded-lg border bg-slate-950/95 px-2 py-2 text-center transition hover:border-cyan-200/50 ${active ? "border-cyan-200/60 shadow-[0_0_16px_rgba(81,229,255,.12)]" : "border-cyan-300/20"}`}>
    <div className="mb-1 text-cyan-300">{icon}</div>
    <div className="text-xs font-semibold text-slate-100">{title}</div>
    <div className={`mt-1 max-w-full text-[9px] leading-3 ${active ? "text-cyan-200" : "text-emerald-300"}`}>{state}</div>
  </button>;
}

function FlowPath({ d, label, state, reverse = false }: {
  d: string;
  label: string;
  state: FlowState;
  reverse?: boolean;
}) {
  const stroke = state === "active" ? "#51e5ff" : state === "complete" ? "#237b83" : "#29414d";
  return <path
    d={d}
    fill="none"
    stroke={stroke}
    strokeWidth="3"
    strokeLinejoin="round"
    strokeLinecap="round"
    aria-label={`${label} ${state}`}
    className={state === "active" ? `flow-line${reverse ? " flow-line-reverse" : ""}` : ""}
  />;
}

export function SystemTopology({ mission, onNavigate, locale = "zh" }: { mission?: TopologyMissionState; onNavigate?: (node: NodeKind) => void; locale?: Locale }) {
  const t = (key: Parameters<typeof translate>[1], values?: Parameters<typeof translate>[2]) =>
    translate(locale, key, values);
  const flows = deriveTopologyFlows(mission);
  const running = mission?.executionState === "running";
  const active = mission?.activeSubstage;
  const provider = mission?.providerStatus?.toUpperCase() ?? "UNKNOWN";
  const labels = {
    uplink: active === "downlink" && running ? t("topology.uplinkDownlink") : t("topology.datalink"),
    payload: active === "processing" && running ? t("topology.processing") : t("topology.payloadBus"),
    gtx: active === "ai" && running ? t("topology.aiResult") : "GTX 2.5G",
  };

  return <div className="px-1 py-1">
    <div className="relative w-full">
      <svg className="pointer-events-none absolute inset-0 h-full w-full" viewBox="0 0 1000 170" preserveAspectRatio="none" aria-hidden="true">
        <FlowPath d="M 112 85 H 452" label={labels.uplink} state={flows.uplink.state} reverse={active === "downlink"} />
        <FlowPath d="M 548 85 H 600 L 640 35 H 888" label={labels.payload} state={flows.payload.state} />
        <FlowPath d="M 548 85 H 600 L 640 135 H 888" label={labels.gtx} state={flows.gtx.state} reverse={active === "ai"} />
      </svg>
      <div className="relative grid h-[170px] grid-cols-[112px_minmax(32px,1fr)_112px_minmax(32px,1fr)_112px] grid-rows-2 items-center">
      <div className="row-span-2 flex justify-center">
        <Node
          icon={<RadioTower size={18} />}
          title={t("topology.ground")}
          state={running && ["uplink", "downlink"].includes(active ?? "") ? t("topology.groundActive") : t("topology.groundReady")}
          active={running && ["uplink", "downlink"].includes(active ?? "")}
          onClick={() => onNavigate?.("ground")}
        />
      </div>
      <div className="row-span-2" />
      <div className="row-span-2 flex justify-center">
        <Node
          icon={<Satellite size={18} />}
          title={t("topology.platform")}
          state={running ? `${active?.toUpperCase()} RUNNING` : t("topology.platformPaused")}
          active={running}
          onClick={() => onNavigate?.("platform")}
        />
      </div>
      <div />
      <div className="row-span-2 flex h-full flex-col items-center justify-between py-2">
        <Node
          icon={<ScanLine size={18} />}
          title={t("topology.optical")}
          state={running && ["capture", "processing"].includes(active ?? "") ? t("topology.opticalActive") : t("topology.opticalReady")}
          active={running && ["capture", "processing"].includes(active ?? "")}
          onClick={() => onNavigate?.("optical")}
        />
        <Node
          icon={<Cpu size={18} />}
          title={t("topology.gpu")}
          state={`${mission?.aiMode?.toUpperCase() ?? "AI"} ${provider}`}
          active={running && ["gtx", "ai"].includes(active ?? "")}
          onClick={() => onNavigate?.("gpu")}
        />
      </div>
      <span className={`absolute left-[27%] top-[89px] -translate-x-1/2 text-[8px] tracking-wider ${flows.uplink.state === "active" ? "text-cyan-200" : "text-slate-500"}`}>{labels.uplink}</span>
      <span className={`absolute left-[76%] top-[35px] -translate-x-1/2 -translate-y-5 text-[8px] tracking-wider ${flows.payload.state === "active" ? "text-cyan-200" : "text-slate-500"}`}>{labels.payload}</span>
      <span className={`absolute left-[76%] top-[135px] -translate-x-1/2 translate-y-3 text-[8px] tracking-wider ${flows.gtx.state === "active" ? "text-cyan-200" : "text-slate-500"}`}>{labels.gtx}</span>
      </div>
    </div>
    {/* <div className="mt-1 flex justify-between px-[5%] text-[8px] tracking-wide text-slate-600">
      <span>{t("topology.center")}</span>
      <span className={flows.downlink.state === "active" ? "text-cyan-200" : ""}>
        {flows.downlink.state === "active" ? t("topology.downlinkActive") : t("topology.noDirect")}
      </span>
    </div> */}
  </div>;
}
