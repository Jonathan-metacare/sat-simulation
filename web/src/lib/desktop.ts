export type DesktopSettings = {
  locale: "zh" | "en";
  theme: "dark" | "light";
  activeAiMode: "yolo" | "llm";
  activeScenarioId: string;
  cesiumIonToken: string;
  keeptrackApiKey: string;
  llmApiUrl: string;
  llmModel: string;
  llmApiKey: string;
  yoloApiUrl: string;
  yoloModel: string;
  yoloApiKey: string;
  providerTimeoutSeconds: number;
  gpuMode: "local" | "jetson";
  jetsonHost: string;
  jetsonSshUsername: string;
  jetsonSshPassword: string;
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
  capabilities(): Promise<{ localGpuAllowed: boolean }>;
  saveSettings(value: DesktopSettings): Promise<DesktopSettings>;
  resetData(action: DesktopResetAction, confirmation?: string): Promise<DesktopResetResult>;
  diagnostics(): Promise<DesktopDiagnostics>;
  restartGpu(): Promise<DesktopDiagnostics>;
  restartStack(): Promise<DesktopDiagnostics>;
  openDataDirectory(): Promise<string>;
  openLogDirectory(): Promise<string>;
  openExternal(url: string): Promise<void>;
  discoverJetsonHostKey(credentials: { password: string }): Promise<{ fingerprint: string }>;
  confirmJetsonHostKey(fingerprint: string): Promise<DesktopSettings>;
  preflightJetson(credentials: { password: string }): Promise<{ fingerprint: string; architecture: string; freeBytes: number; docker: boolean; compose: boolean; ollama: boolean; readyForApplicationDeploy: boolean }>;
  deployJetson(request: { credentials: { password: string }; mode: "application" | "initialize" }): Promise<DesktopSettings>;
  onJetsonProgress(listener: (event: { type: "stage" | "log" | "error"; name?: string; message?: string }) => void): () => void;
};

declare global {
  interface Window { satSimDesktop?: DesktopBridge; }
}

export function desktopBridge(): DesktopBridge | undefined {
  return typeof window === "undefined" ? undefined : window.satSimDesktop;
}
