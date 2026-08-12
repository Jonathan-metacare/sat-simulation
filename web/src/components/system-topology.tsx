import { Cpu, RadioTower, Satellite, ScanLine } from "lucide-react";

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
      label: substage === "downlink" && running ? "结果请求上注 / 结果包下传" : "数传链路",
    } as { state: FlowState; label: string },
    payload: {
      state: running && ["capture", "processing"].includes(substage ?? "")
        ? "active"
        : phase && [
          "capture_complete", "processing_complete", "gtx_complete", "ai_complete", "completed",
        ].includes(phase)
          ? "complete"
          : "idle",
      label: substage === "processing" && running ? "产品处理" : "载荷总线",
    } as { state: FlowState; label: string },
    gtx: {
      state: running && ["gtx", "ai"].includes(substage ?? "")
        ? "active"
        : phase && ["gtx_complete", "ai_complete", "completed"].includes(phase)
          ? "complete"
          : "idle",
      label: substage === "ai" && running ? "AI 指令 / 结果" : "GTX 2.5G",
    } as { state: FlowState; label: string },
    downlink: {
      state: running && substage === "downlink"
        ? "active"
        : phase === "completed"
          ? "complete"
          : "idle",
      label: "结果包下传",
    } as { state: FlowState; label: string },
  };
}

function Node({ icon, title, state, active, onClick }: {
  icon: React.ReactNode;
  title: string;
  state: string;
  active?: boolean;
  onClick?: () => void;
}) {
  return <button type="button" onClick={onClick} className={`relative z-10 flex w-24 flex-col items-center rounded-lg border bg-slate-950/95 px-2 py-2.5 text-center transition hover:border-cyan-200/50 ${active ? "border-cyan-200/60 shadow-[0_0_16px_rgba(81,229,255,.12)]" : "border-cyan-300/20"}`}>
    <div className="mb-1 text-cyan-300">{icon}</div>
    <div className="text-xs font-semibold text-slate-100">{title}</div>
    <div className={`mt-1 text-[10px] ${active ? "text-cyan-200" : "text-emerald-300"}`}>{state}</div>
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

export function SystemTopology({ mission, onNavigate }: { mission?: TopologyMissionState; onNavigate?: (node: NodeKind) => void }) {
  const flows = deriveTopologyFlows(mission);
  const running = mission?.executionState === "running";
  const active = mission?.activeSubstage;
  const provider = mission?.providerStatus?.toUpperCase() ?? "UNKNOWN";

  return <div className="px-1 py-1">
    <div className="relative w-full">
      <svg className="pointer-events-none absolute inset-0 h-full w-full" viewBox="0 0 1000 124" preserveAspectRatio="none" aria-hidden="true">
        <FlowPath d="M 96 62 H 452" label={flows.uplink.label} state={flows.uplink.state} reverse={active === "downlink"} />
        <FlowPath d="M 548 62 H 600 L 640 28 H 904" label={flows.payload.label} state={flows.payload.state} />
        <FlowPath d="M 548 62 H 600 L 640 96 H 904" label={flows.gtx.label} state={flows.gtx.state} reverse={active === "ai"} />
      </svg>
      <div className="relative grid h-[124px] grid-cols-[88px_minmax(32px,1fr)_88px_minmax(32px,1fr)_88px] grid-rows-2 items-center">
      <div className="row-span-2 flex justify-center">
        <Node
          icon={<RadioTower size={18} />}
          title="地面站"
          state={running && ["uplink", "downlink"].includes(active ?? "") ? "GROUND ACTIVE" : "GROUND READY"}
          active={running && ["uplink", "downlink"].includes(active ?? "")}
          onClick={() => onNavigate?.("ground")}
        />
      </div>
      <div className="row-span-2" />
      <div className="row-span-2 flex justify-center">
        <Node
          icon={<Satellite size={18} />}
          title="星务平台"
          state={running ? `${active?.toUpperCase()} RUNNING` : "PLATFORM PAUSED"}
          active={running}
          onClick={() => onNavigate?.("platform")}
        />
      </div>
      <div />
      <div className="flex justify-center">
      <Node
        icon={<ScanLine size={18} />}
        title="光学载荷"
        state={running && ["capture", "processing"].includes(active ?? "") ? "OPTICAL ACTIVE" : "OPTICAL READY"}
        active={running && ["capture", "processing"].includes(active ?? "")}
        onClick={() => onNavigate?.("optical")}
      />
      </div>
      <div />
      <div className="flex justify-center">
      <Node
        icon={<Cpu size={18} />}
        title="GPU 载荷"
        state={`${mission?.aiMode?.toUpperCase() ?? "AI"} ${provider}`}
        active={running && ["gtx", "ai"].includes(active ?? "")}
        onClick={() => onNavigate?.("gpu")}
      />
      </div>
      <span className={`absolute left-[27%] top-[68px] -translate-x-1/2 text-[8px] tracking-wider ${flows.uplink.state === "active" ? "text-cyan-200" : "text-slate-500"}`}>{flows.uplink.label}</span>
      <span className={`absolute left-[76%] top-[27px] -translate-x-1/2 -translate-y-5 text-[8px] tracking-wider ${flows.payload.state === "active" ? "text-cyan-200" : "text-slate-500"}`}>{flows.payload.label}</span>
      <span className={`absolute left-[76%] top-[96px] -translate-x-1/2 translate-y-3 text-[8px] tracking-wider ${flows.gtx.state === "active" ? "text-cyan-200" : "text-slate-500"}`}>{flows.gtx.label}</span>
      </div>
    </div>
    <div className="mt-1 flex justify-between px-[5%] text-[8px] tracking-wide text-slate-600">
      <span>所有载荷链路均以星务平台为中心</span>
      <span className={flows.downlink.state === "active" ? "text-cyan-200" : ""}>
        {flows.downlink.state === "active" ? "结果请求已上注 · 结果包正在下传" : "光学载荷与 GPU 载荷无直连"}
      </span>
    </div>
  </div>;
}
