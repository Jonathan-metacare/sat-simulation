export type MissionStatus =
  | "planned" | "uplinking" | "maneuvering" | "capturing"
  | "l0_processing" | "l1a_processing" | "l1b_processing"
  | "gtx_transfer" | "ai_processing" | "ai_skipped"
  | "downlinking" | "completed" | "failed" | "cancelled";
export type MissionPhase =
  | "initialized" | "uplink_complete" | "capture_complete"
  | "processing_complete" | "gtx_complete" | "ai_complete" | "completed";
export type ExecutionState =
  | "waiting" | "running" | "blocked" | "retryable_error" | "completed" | "cancelled";
export type AIMode = "yolo" | "llm";

export interface ScenarioConfig {
  id: string; name: string; seed: number; epoch: string; clock_rate: 1 | 10 | 100;
  tle_line1: string; tle_line2: string; satellite_name: string;
  ground_station_name: string; ground_station_latitude: number;
  ground_station_longitude: number; ground_station_altitude_m: number;
  deterministic_contact: boolean; scene_id: string;
}
export interface ClockState {
  run_id: string; simulated_at: string; rate: 1 | 10 | 100;
  paused: boolean; revision: number;
}
export interface ScenarioRecord { config: ScenarioConfig; clock: ClockState; }
export interface ContactWindow {
  aos: string; los: string; max_elevation_at: string; max_elevation_deg: number;
}
export interface PlannedWindows {
  uplink: ContactWindow; capture: ContactWindow; downlink: ContactWindow;
  target_name: string; target_latitude: number; target_longitude: number;
  tle_line1: string; tle_line2: string; minimum_elevation_deg: number;
}
export interface MissionCommand {
  id: string; run_id: string; scenario_id: string; name: string;
  target_name: string; target_latitude: number; target_longitude: number;
  requested_at: string; scene_id: string; enable_ai: boolean;
  ai_mode: AIMode; planned_windows: PlannedWindows;
}
export interface TelemetryEvent {
  id: string; run_id: string; mission_id?: string; sequence: number;
  event_type: string; status: MissionStatus; message: string; simulated_at: string;
  source: string; data: Record<string, unknown>; provenance: string;
  channel: "simulation_control" | "uplink" | "gtx" | "downlink";
}
export interface ProductManifest {
  id: string; run_id: string; mission_id: string;
  level: "raw" | "l0" | "l1a" | "l1b" | "thumbnail" | "stac" | "ai_result" | "result_package";
  name: string; mime_type: string; size_bytes: number; sha256: string;
  created_at: string; quality: Record<string, unknown>; lineage: string[];
}
export interface TransferRecord {
  id: string; run_id: string; mission_id: string;
  link: "gtx" | "uplink" | "downlink"; name: string;
  total_bytes: number; transferred_bytes: number; frame_count: number;
  retry_count: number; crc_failures: number; status: string;
}
export interface StepAttempt {
  id: string; mission_id: string; from_phase: MissionPhase; target_phase: MissionPhase;
  attempt_number: number; idempotency_key: string; state: ExecutionState;
  started_at: string; finished_at?: string; error?: string;
}
export interface MissionSummary {
  command: MissionCommand; status: MissionStatus; error?: string;
  phase: MissionPhase; execution_state: ExecutionState; active_substage?: string;
  ai_mode: AIMode; planned_windows: PlannedWindows; block_reason?: string;
  legacy_terminal: boolean; next_action?: string; can_advance: boolean;
  created_at: string; updated_at: string;
}
export interface MissionDetail extends MissionSummary {
  events: TelemetryEvent[]; products: ProductManifest[];
  onboard_products: ProductManifest[];
  transfers: TransferRecord[]; step_attempts: StepAttempt[];
}
export interface PublicConfig {
  version: string; ai: { detection: string; language: string };
  links: Record<string, { bandwidth_bps: number; latency_ms: number; frame_payload_bytes: number }>;
}
export interface OrbitSample {
  sampled_at: string; latitude: number; longitude: number;
  altitude_km: number; elevation_deg: number; visible: boolean;
}
export interface OrbitTrack {
  generated_at: string; satellite_name: string; ground_station_name: string;
  minimum_elevation_deg: number; visibility_radius_m: number;
  contact_mode: "geometric" | "deterministic"; current: OrbitSample;
  history: OrbitSample[]; forecast: OrbitSample[]; contact_windows: ContactWindow[];
}
