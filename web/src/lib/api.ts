import type { AIMode, GroundStationSearchResponse, MissionDetail, MissionResultResponse, MissionSummary, NodeKind, NodeSnapshot, OrbitTrack, ProcessorSource, ProcessorStage, ProcessorTemplate, ProcessorVersion, ProtocolFrameTrace, ProtocolTransaction, PublicConfig, SatelliteCreateRequest, SatelliteNoradLookup, ScenarioConfig, ScenarioRecord, SceneAsset, SceneRecord, TransferRecord } from "./types";
import { desktopBridge } from "./desktop";

export const API_BASE = (desktopBridge()?.apiBase ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api").replace(/\/$/, "");

function formatApiError(body: string): string {
  try {
    const detail: unknown = (JSON.parse(body) as { detail?: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) return detail.map((item) => {
      if (typeof item !== "object" || item === null) return String(item);
      const value = item as { path?: unknown; loc?: unknown; message?: unknown; msg?: unknown };
      const path = typeof value.path === "string"
        ? value.path
        : Array.isArray(value.loc) ? value.loc.filter((part) => part !== "body").join(".") : undefined;
      const message = typeof value.message === "string" ? value.message : typeof value.msg === "string" ? value.msg : JSON.stringify(item);
      return path ? `${path}: ${message}` : message;
    }).join("\n");
    if (detail && typeof detail === "object") return JSON.stringify(detail);
  } catch {}
  return body;
}

async function request<T>(path:string, init?:RequestInit):Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { ...init, headers:{ "Content-Type":"application/json",...(init?.headers??{}) }, cache:"no-store" });
  if (!response.ok) throw new Error(formatApiError(await response.text()) || `API ${response.status}`);
  return response.status===204 ? undefined as T : response.json() as Promise<T>;
}

async function upload<T>(path: string, file: File): Promise<T> {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch(`${API_BASE}${path}`, { method: "POST", body: form, cache: "no-store" });
  if (!response.ok) {
    throw new Error(formatApiError(await response.text()) || `API ${response.status}`);
  }
  return response.json() as Promise<T>;
}

async function uploadWithFields<T>(path: string, file: File, fields: Record<string, string | number | undefined>): Promise<T> {
  const query = new URLSearchParams();
  Object.entries(fields).forEach(([key, value]) => { if (value !== undefined && value !== "") query.set(key, String(value)); });
  return upload<T>(`${path}?${query.toString()}`, file);
}

export const api = {
  config:()=>request<PublicConfig>("/config"),
  scenarios:()=>request<ScenarioRecord[]>("/scenarios"),
  orbit:(scenarioId:string)=>request<OrbitTrack>(`/scenarios/${scenarioId}/orbit`),
  createScenario:(name:string)=>request<ScenarioRecord>("/scenarios",{method:"POST",body:JSON.stringify({name,clock_rate:10})}),
  createSatellite:(body:SatelliteCreateRequest)=>request<ScenarioRecord>("/scenarios/satellite",{method:"POST",body:JSON.stringify(body)}),
  lookupSatelliteNorad:(noradId:number)=>request<SatelliteNoradLookup>(`/satellites/norad/${noradId}`,{method:"POST"}),
  searchGroundStations:(name:string)=>request<GroundStationSearchResponse>(`/ground-stations?name=${encodeURIComponent(name)}`),
  importScenarioYaml:(file:File)=>upload<{config:ScenarioConfig;clock:ScenarioRecord["clock"];validation:{status:string;scene_ready:boolean;required_scene_id:string}}>("/scenarios/import/yaml",file),
  validateScene:(file:File,sceneId:string,geo?:{centerLatitude?:number;centerLongitude?:number;pixelSize?:number;crs?:string})=>uploadWithFields<{status:string;asset:SceneAsset}>("/scenes/validate",file,{scene_id:sceneId,center_latitude:geo?.centerLatitude,center_longitude:geo?.centerLongitude,pixel_size:geo?.pixelSize,crs:geo?.crs}),
  importScene:(file:File,sceneId:string,scenarioId?:string,geo?:{centerLatitude?:number;centerLongitude?:number;pixelSize?:number;crs?:string})=>uploadWithFields<{id:string;sha256:string;metadata:SceneAsset;scene_ready:boolean}>("/scenes/import",file,{scene_id:sceneId,scenario_id:scenarioId,center_latitude:geo?.centerLatitude,center_longitude:geo?.centerLongitude,pixel_size:geo?.pixelSize,crs:geo?.crs}),
  scenes:()=>request<SceneRecord[]>("/scenes"),
  validateProcessor:(file:File)=>upload<{status:string;definition:ProcessorVersion["definition"];sha256:string}>("/processors/validate",file),
  importProcessor:(file:File)=>upload<ProcessorVersion>("/processors",file),
  processors:(stage?:ProcessorStage)=>request<ProcessorVersion[]>(`/processors${stage?`?stage=${stage}`:""}`),
  processorTemplate:(stage:ProcessorStage)=>request<ProcessorTemplate>(`/processors/templates?stage=${stage}`),
  processorSource:(processorId:string)=>request<ProcessorSource>(`/processors/${processorId}/source`),
  saveProcessorWorkspace:(stage:ProcessorStage,id:string,name:string,version:string,source:string)=>request<ProcessorVersion>("/processors/workspace",{method:"POST",body:JSON.stringify({stage,id,name,version,source})}),
  selectProcessors:(scenarioId:string,l0ProcessorId:string,l1ProcessorId:string)=>request<ScenarioConfig>(`/scenarios/${scenarioId}/processors`,{method:"POST",body:JSON.stringify({l0_processor_id:l0ProcessorId,l1_processor_id:l1ProcessorId})}),
  control:(id:string,action:string,rate?:number)=>request<{clock:ScenarioRecord["clock"]}>(`/scenarios/${id}/control`,{method:"POST",body:JSON.stringify({action,rate})}),
  missions:()=>request<MissionSummary[]>("/missions"),
  mission:(id:string)=>request<MissionDetail>(`/missions/${id}`),
  createMission:(scenarioId:string,name:string,_aiMode:AIMode,projectContext:string,analysisPrompt:string,aiModel?:string)=>request<MissionDetail>("/missions",{method:"POST",body:JSON.stringify({scenario_id:scenarioId,name,project_context:projectContext,analysis_prompt:analysisPrompt,ai_model:aiModel})}),
  updateMissionPrompt:(missionId:string,analysisPrompt:string)=>request<MissionDetail>(`/missions/${missionId}/prompt`,{method:"PATCH",body:JSON.stringify({analysis_prompt:analysisPrompt})}),
  advanceMission:(missionId:string,playbackSpeed:1|2|5,idempotencyKey:string)=>request<{mission_id:string;action:string}>(`/missions/${missionId}/advance`,{method:"POST",body:JSON.stringify({playback_speed:playbackSpeed,idempotency_key:idempotencyKey})}),
  cancelMission:(missionId:string)=>request<MissionDetail>(`/missions/${missionId}/cancel`,{method:"POST"}),
  missionResult:(missionId:string)=>request<MissionResultResponse>(`/missions/${missionId}/result`),
  node:(missionId:string,node:NodeKind)=>request<NodeSnapshot>(`/missions/${missionId}/nodes/${node}`),
  protocolTransactions:(missionId:string)=>request<ProtocolTransaction[]>(`/missions/${missionId}/protocol/transactions`),
  protocolTransaction:(id:string)=>request<ProtocolTransaction>(`/protocol/transactions/${id}`),
  protocolFrames:(id:string)=>request<ProtocolFrameTrace[]>(`/protocol/transactions/${id}/frames`),
  providerHealth:()=>request<Record<string,{status:string;api_url_configured?:boolean}>>('/providers/health'),
  providerModels:()=>request<{provider:string;models:Array<{name:string;capabilities:string[]}>}>("/providers/models?provider=ollama"),
  transfers:(runId?:string)=>request<TransferRecord[]>(`/transfers${runId?`?run_id=${runId}`:""}`),
  faults:(scenarioId:string)=>request<Array<{id:string;link:string;drop_rate:number}>>(`/scenarios/${scenarioId}/faults`),
  injectDrop:(scenarioId:string)=>request<{id:string}>(`/scenarios/${scenarioId}/faults`,{method:"POST",body:JSON.stringify({link:"downlink",drop_rate:.1,corrupt_rate:.02,enabled:true})}),
  deleteFault:(scenarioId:string,faultId:string)=>request<void>(`/scenarios/${scenarioId}/faults/${faultId}`,{method:"DELETE"})
};
export function artifactURL(productId:string){return `${API_BASE}/artifacts/${productId}`;}
export function eventStreamURL(runId:string){return `${API_BASE}/events/stream?run_id=${encodeURIComponent(runId)}`;}
export function protocolStreamURL(runId:string){return `${API_BASE}/protocol/stream?run_id=${encodeURIComponent(runId)}`;}
export function nodeArtifactURL(missionId:string,node:NodeKind,key:string){return `${API_BASE}/missions/${missionId}/nodes/${node}/artifacts/${encodeURIComponent(key)}`;}
export function processorDownloadURL(processorId:string){return `${API_BASE}/processors/${encodeURIComponent(processorId)}/download`;}
