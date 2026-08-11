export type MissionStatus = "planned"|"uplinking"|"maneuvering"|"capturing"|"l0_processing"|"l1a_processing"|"l1b_processing"|"gtx_transfer"|"ai_processing"|"ai_skipped"|"downlinking"|"completed"|"failed";
export interface ScenarioConfig { id:string; name:string; seed:number; epoch:string; clock_rate:1|10|100; satellite_name:string; ground_station_name:string; ground_station_latitude:number; ground_station_longitude:number; deterministic_contact:boolean; scene_id:string; }
export interface ClockState { run_id:string; simulated_at:string; rate:1|10|100; paused:boolean; revision:number; }
export interface ScenarioRecord { config:ScenarioConfig; clock:ClockState; }
export interface MissionCommand { id:string; run_id:string; scenario_id:string; name:string; target_name:string; target_latitude:number; target_longitude:number; requested_at:string; scene_id:string; enable_ai:boolean; }
export interface TelemetryEvent { id:string; run_id:string; mission_id?:string; sequence:number; event_type:string; status:MissionStatus; message:string; simulated_at:string; source:string; data:Record<string,unknown>; provenance:string; }
export interface ProductManifest { id:string; run_id:string; mission_id:string; level:"raw"|"l0"|"l1a"|"l1b"|"thumbnail"|"stac"|"ai_result"; name:string; mime_type:string; size_bytes:number; sha256:string; created_at:string; quality:Record<string,unknown>; lineage:string[]; }
export interface TransferRecord { id:string; run_id:string; mission_id:string; link:"gtx"|"uplink"|"downlink"; name:string; total_bytes:number; transferred_bytes:number; frame_count:number; retry_count:number; crc_failures:number; status:string; }
export interface MissionSummary { command:MissionCommand; status:MissionStatus; error?:string; created_at:string; updated_at:string; }
export interface MissionDetail extends MissionSummary { events:TelemetryEvent[]; products:ProductManifest[]; transfers:TransferRecord[]; }
export interface PublicConfig { version:string; ai:{ detection:string; language:string }; links:Record<string,{ bandwidth_bps:number; latency_ms:number; frame_payload_bytes:number }>; }

