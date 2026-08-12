import type { AIMode, MissionDetail, MissionSummary, OrbitTrack, PublicConfig, ScenarioRecord, TransferRecord } from "./types";

export const API_BASE = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api").replace(/\/$/, "");

async function request<T>(path:string, init?:RequestInit):Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { ...init, headers:{ "Content-Type":"application/json",...(init?.headers??{}) }, cache:"no-store" });
  if (!response.ok) { let detail=await response.text(); try { detail=(JSON.parse(detail) as {detail?:string}).detail??detail; } catch {} throw new Error(detail||`API ${response.status}`); }
  return response.status===204 ? undefined as T : response.json() as Promise<T>;
}

export const api = {
  config:()=>request<PublicConfig>("/config"),
  scenarios:()=>request<ScenarioRecord[]>("/scenarios"),
  orbit:(scenarioId:string)=>request<OrbitTrack>(`/scenarios/${scenarioId}/orbit`),
  createScenario:()=>request<ScenarioRecord>("/scenarios",{method:"POST",body:JSON.stringify({name:"北京光学任务演示",clock_rate:10})}),
  control:(id:string,action:string,rate?:number)=>request<{clock:ScenarioRecord["clock"]}>(`/scenarios/${id}/control`,{method:"POST",body:JSON.stringify({action,rate})}),
  missions:()=>request<MissionSummary[]>("/missions"),
  mission:(id:string)=>request<MissionDetail>(`/missions/${id}`),
  createMission:(scenarioId:string,aiMode:AIMode)=>request<MissionDetail>("/missions",{method:"POST",body:JSON.stringify({scenario_id:scenarioId,name:"自动规划光学观测",scene_id:"demo-optical-scene",ai_mode:aiMode})}),
  advanceMission:(missionId:string,playbackSpeed:1|2|5,idempotencyKey:string)=>request<{mission_id:string;action:string}>(`/missions/${missionId}/advance`,{method:"POST",body:JSON.stringify({playback_speed:playbackSpeed,idempotency_key:idempotencyKey})}),
  cancelMission:(missionId:string)=>request<MissionDetail>(`/missions/${missionId}/cancel`,{method:"POST"}),
  providerHealth:()=>request<Record<string,{status:string;api_url_configured?:boolean}>>('/providers/health'),
  transfers:(runId?:string)=>request<TransferRecord[]>(`/transfers${runId?`?run_id=${runId}`:""}`),
  faults:(scenarioId:string)=>request<Array<{id:string;link:string;drop_rate:number}>>(`/scenarios/${scenarioId}/faults`),
  injectDrop:(scenarioId:string)=>request<{id:string}>(`/scenarios/${scenarioId}/faults`,{method:"POST",body:JSON.stringify({link:"downlink",drop_rate:.1,corrupt_rate:.02,enabled:true})}),
  deleteFault:(scenarioId:string,faultId:string)=>request<void>(`/scenarios/${scenarioId}/faults/${faultId}`,{method:"DELETE"})
};
export function artifactURL(productId:string){return `${API_BASE}/artifacts/${productId}`;}
export function eventStreamURL(runId:string){return `${API_BASE}/events/stream?run_id=${encodeURIComponent(runId)}`;}
