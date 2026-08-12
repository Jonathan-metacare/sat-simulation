import { Cpu, RadioTower, Satellite, ScanLine } from "lucide-react";

import type { AIMode, ExecutionState, MissionPhase } from "~/lib/types";

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

function Node({ icon, title, state, active }: {
  icon: React.ReactNode;
  title: string;
  state: string;
  active?: boolean;
}) {
  return <div className={`relative z-10 flex min-w-28 flex-col items-center rounded-xl border bg-slate-950/90 px-3 py-4 text-center transition ${active ? "border-cyan-200/60 shadow-[0_0_20px_rgba(81,229,255,.12)]" : "border-cyan-300/20"}`}>
    <div className="mb-2 text-cyan-300">{icon}</div>
    <div className="text-xs font-semibold text-slate-100">{title}</div>
    <div className={`mt-1 text-[10px] ${active ? "text-cyan-200" : "text-emerald-300"}`}>{state}</div>
  </div>;
}

function Link({ label, state, reverse = false }: {
  label: string;
  state: FlowState;
  reverse?: boolean;
}) {
  const stroke = state === "active" ? "#51e5ff" : state === "complete" ? "#237b83" : "#29414d";
  return <div className="min-w-14 flex-1 text-center">
    <svg viewBox="0 0 100 16" className="w-full" aria-label={`${label} ${state}`}>
      <line
        x1="0" y1="8" x2="100" y2="8"
        stroke={stroke}
        strokeWidth="2"
        className={state === "active" ? `flow-line${reverse ? " flow-line-reverse" : ""}` : ""}
      />
    </svg>
    <span className={`text-[9px] tracking-wider uppercase ${state === "active" ? "text-cyan-200" : "text-slate-500"}`}>{label}</span>
  </div>;
}

export function SystemTopology({ mission }: { mission?: TopologyMissionState }) {
  const flows = deriveTopologyFlows(mission);
  const running = mission?.executionState === "running";
  const active = mission?.activeSubstage;
  const provider = mission?.providerStatus?.toUpperCase() ?? "UNKNOWN";

  return <div className="min-h-52 overflow-x-auto px-3 py-3">
    <div className="grid min-w-[900px] grid-cols-[112px_minmax(100px,1fr)_112px_minmax(100px,1fr)_112px] grid-rows-2 items-center gap-x-2 gap-y-4">
      <div className="row-span-2">
        <Node
          icon={<RadioTower size={22} />}
          title="地面站"
          state={running && ["uplink", "downlink"].includes(active ?? "") ? "GROUND ACTIVE" : "GROUND READY"}
          active={running && ["uplink", "downlink"].includes(active ?? "")}
        />
      </div>
      <div className="row-span-2"><Link label={flows.uplink.label} state={flows.uplink.state} reverse={active === "downlink"} /></div>
      <div className="row-span-2">
        <Node
          icon={<Satellite size={22} />}
          title="星务平台"
          state={running ? `${active?.toUpperCase()} RUNNING` : "PLATFORM PAUSED"}
          active={running}
        />
      </div>
      <Link label={flows.payload.label} state={flows.payload.state} />
      <Node
        icon={<ScanLine size={22} />}
        title="光学载荷"
        state={running && ["capture", "processing"].includes(active ?? "") ? "OPTICAL ACTIVE" : "OPTICAL READY"}
        active={running && ["capture", "processing"].includes(active ?? "")}
      />
      <Link label={flows.gtx.label} state={flows.gtx.state} reverse={active === "ai"} />
      <Node
        icon={<Cpu size={22} />}
        title="GPU 载荷"
        state={`${mission?.aiMode?.toUpperCase() ?? "AI"} ${provider}`}
        active={running && ["gtx", "ai"].includes(active ?? "")}
      />
    </div>
    <div className="mt-3 flex min-w-[900px] justify-between px-[8%] text-[9px] tracking-wide text-slate-600">
      <span>所有载荷链路均以星务平台为中心</span>
      <span className={flows.downlink.state === "active" ? "text-cyan-200" : ""}>
        {flows.downlink.state === "active" ? "结果请求已上注 · 结果包正在下传" : "光学载荷与 GPU 载荷无直连"}
      </span>
    </div>
  </div>;
}
