export type DesktopSettings = {
  locale: "zh" | "en";
  theme: "dark" | "light";
  activeAiMode: "llm";
  activeScenarioId: string;
  cesiumIonToken: string;
  keeptrackApiKey: string;
  llmModel: string;
  providerTimeoutSeconds: number;
  agentEnabled: boolean;
  agentModel: string;
  agentSystemPrompt: string;
  agentTools: Array<"mission_context" | "verified_products" | "l1b_metadata">;
  gpuMode: "jetson";
  jetsonHost: string;
  jetsonSshUsername: string;
  jetsonHostKeyFingerprint: string;
  jetsonDeploymentStatus: "unconfigured" | "pending" | "deploying" | "ready" | "failed";
  jetsonDeploymentVersion: string;
  jetsonDeploymentError: string;
  jetsonApiPort: number;
  jetsonGtxPort: number;
  desktopAdvertiseHost: string;
  platformGtxResultPort: number;
};

export type DesktopDiagnostics = {
  version: string;
  apiBase: string | null;
  ports: Record<string, number>;
  dataDirectory: string;
  logDirectory: string;
  services: Array<{ name: string; version: string; running: boolean }>;
};

export type DesktopResetAction = "simulation-data" | "catalog-caches" | "settings-defaults";

export type DesktopResetResult = {
  action: DesktopResetAction;
  settings: DesktopSettings;
  diagnostics: DesktopDiagnostics;
};

export type DesktopBridge = {
  apiBase: string;
  getSettings(): Promise<DesktopSettings>;
  saveSettings(value: DesktopSettings, jetsonPassword?: string): Promise<DesktopSettings>;
  getJetsonPassword(): Promise<string>;
  saveJetsonPassword(password: string): Promise<void>;
  resetData(action: DesktopResetAction, confirmation?: string): Promise<DesktopResetResult>;
  diagnostics(): Promise<DesktopDiagnostics>;
  restartStack(): Promise<DesktopDiagnostics>;
  openDataDirectory(): Promise<string>;
  openLogDirectory(): Promise<string>;
  openExternal(url: string): Promise<void>;
  discoverJetsonHostKey(credentials: { password: string }): Promise<{ fingerprint: string }>;
  confirmJetsonHostKey(fingerprint: string): Promise<DesktopSettings>;
  preflightJetson(credentials: { password: string }): Promise<{ fingerprint: string; architecture: string; freeBytes: number; docker: boolean; compose: boolean; ollama: boolean; readyForApplicationDeploy: boolean }>;
  deployJetson(request: { credentials: { password: string }; mode: "application" | "initialize" }): Promise<DesktopSettings>;
  pullJetsonModel(request: { credentials: { password: string }; model: string }): Promise<{ settings: DesktopSettings; model: string }>;
  onJetsonProgress(listener: (event: { type: "stage" | "log" | "error"; name?: string; message?: string }) => void): () => void;
};

declare global {
  interface Window { satSimDesktop?: DesktopBridge; }
}

export function desktopBridge(): DesktopBridge | undefined {
  return typeof window === "undefined" ? undefined : window.satSimDesktop;
}
