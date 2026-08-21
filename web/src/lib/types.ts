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
export type NodeKind = "ground" | "platform" | "optical" | "gpu";
export type ProtocolLinkKind = "uplink" | "downlink" | "gtx" | "payload_bus";
export type ProcessorStage = "l0" | "l1";

export interface SceneAsset {
  id: string; scene_id: string; version: number; source_name: string;
  source_mime_type: string; source_sha256: string; canonical_sha256: string;
  width: number; height: number; bands: number; dtype: string; crs: string;
  transform: number[]; conversion: Record<string, unknown>; created_at: string;
}
export interface ProcessorDefinition {
  schema_version: 1; id: string; name: string; version: string;
  stage: ProcessorStage; entrypoint: string; timeout_seconds: number;
  cpu_limit: number; memory_mb: number; output_limit_mb: number;
}
export interface ProcessorVersion {
  id: string; definition: ProcessorDefinition; sha256: string;
  runtime_status: "builtin" | "ready" | "unavailable" | "running" | "completed" | "failed";
  runtime_type?: string; source_files?: string[];
  created_at: string;
}
export interface ProcessorSource {
  id: string; processor_yaml: string; processor_py: string; readonly: boolean;
}
export interface ProcessorTemplate extends ProcessorSource {
  definition: ProcessorDefinition;
}
export interface SceneRecord {
  id: string; name: string; sha256: string; metadata: SceneAsset & { source_path?: string };
  created_at?: string;
}

export interface ScenarioConfig {
  id: string; name: string; seed: number; epoch: string; clock_rate: 1 | 10 | 100;
  tle_line1: string; tle_line2: string; satellite_name: string;
  ground_station_name: string; ground_station_latitude: number;
  ground_station_longitude: number; ground_station_altitude_m: number;
  deterministic_contact: boolean; scene_id: string; scene_asset_id?: string;
  l0_processor_id: string; l1_processor_id: string; scene_ready: boolean;
  links: Record<"gtx" | "uplink" | "downlink" | "payload_bus", {
    kind: "gtx" | "uplink" | "downlink" | "payload_bus"; bandwidth_bps: number; latency_ms: number;
    jitter_ms: number; frame_payload_bytes: number; queue_capacity_bytes: number; max_retries: number;
  }>;
  sensor: {
    bit_depth: number; gain: number; offset_dn: number; dark_current_dn: number;
    read_noise_dn: number; prnu_sigma: number; bad_pixel_rate: number;
    stripe_amplitude_dn: number; line_period_ms: number;
  };
}
export interface ClockState {
  run_id: string; simulated_at: string; rate: 1 | 10 | 100;
  paused: boolean; revision: number;
}
export interface ScenarioRecord { config: ScenarioConfig; clock: ClockState; }
export interface SatelliteCreateRequest {
  satellite_name: string; tle_line1: string; tle_line2: string;
  ground_station_name: string; latitude: number; longitude: number; altitude_m: number;
}
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
  ai_mode: AIMode; ai_model?: string | null; project_context: string; analysis_prompt: string;
  scene_asset_id?: string; l0_processor_id: string; l1_processor_id: string;
  scene_asset?: SceneAsset;
  processor_snapshots?: Record<string, { id: string; version: string; sha256: string }>;
  scenario_snapshot?: ScenarioConfig;
  planned_windows: PlannedWindows;
}
export interface TelemetryEvent {
  id: string; run_id: string; mission_id?: string; sequence: number;
  event_type: string; status: MissionStatus; message: string; simulated_at: string;
  source: string; data: Record<string, unknown>; provenance: string;
  channel: "simulation_control" | "uplink" | "gtx" | "downlink";
}
export interface ProductManifest {
  id: string; run_id: string; mission_id: string;
  level: "raw" | "l0" | "l1a" | "l1b" | "aux_context" | "thumbnail" | "stac" | "ai_result" | "result_package";
  name: string; mime_type: string; size_bytes: number; sha256: string;
  created_at: string; quality: Record<string, unknown>; lineage: string[];
}
export interface TransferRecord {
  id: string; run_id: string; mission_id: string;
  link: "gtx" | "uplink" | "downlink"; name: string;
  total_bytes: number; transferred_bytes: number; frame_count: number;
  retry_count: number; crc_failures: number; status: string;
  protocol_transaction_id?: string;
}
export interface NodeArtifact {
  key: string; name: string; level: string; mime_type: string;
  size_bytes: number; sha256: string; available: boolean;
  observation_only: boolean; previewable: boolean;
}
export interface NodeSnapshot {
  node: NodeKind; mission_id: string; reachable: boolean; status: string;
  observation_notice?: string; state: Record<string, unknown>; artifacts: NodeArtifact[];
}
export interface ProtocolPayloadView {
  kind: "json" | "binary" | "none"; mime_type?: string;
  decoded_json?: Record<string, unknown>; summary: Record<string, unknown>; redacted: boolean;
}
export interface ProtocolTransaction {
  id: string; run_id: string; mission_id: string; link: ProtocolLinkKind;
  protocol: string; message_type: string; source_node: NodeKind; target_node: NodeKind;
  direction: string; status: "running" | "completed" | "failed";
  total_bytes: number; frame_count: number; retry_count: number; crc_failures: number;
  sha256?: string; payload: ProtocolPayloadView; started_at: string; completed_at?: string;
  legacy_summary_only: boolean;
}
export interface ProtocolFrameTrace {
  id: string; transaction_id: string; sequence: number; total: number;
  message_type: string; payload_bytes: number; simulated_at: string; crc32c?: string;
  crc_valid: boolean; attempt: number;
  ack_status: "sent" | "ack" | "nak" | "dropped" | "crc_error";
  missing_sequences: number[];
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
export interface AnalysisResult {
  status: string; provenance: string; provider: string; model_version?: string;
  elapsed_ms?: number; content?: string; finish_reason?: string;
  truncated?: boolean; reason?: string;
}
export interface MissionResultResponse {
  mission_id: string;
  ai_result?: { ai_mode: AIMode; l1b_sha256: string; result: AnalysisResult };
  products: ProductManifest[];
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
