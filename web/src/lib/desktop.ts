export type DesktopSettings = {
  locale: "zh" | "en";
  theme: "dark" | "light";
  activeAiMode: "yolo" | "llm";
  activeScenarioId: string;
  cesiumIonToken: string;
  llmApiUrl: string;
  llmModel: string;
  llmApiKey: string;
  yoloApiUrl: string;
  yoloModel: string;
  yoloApiKey: string;
  providerTimeoutSeconds: number;
  gpuMode: "local" | "jetson";
  jetsonHost: string;
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

export type DesktopBridge = {
  apiBase: string;
  getSettings(): Promise<DesktopSettings>;
  saveSettings(value: DesktopSettings): Promise<DesktopSettings>;
  diagnostics(): Promise<DesktopDiagnostics>;
  restartGpu(): Promise<DesktopDiagnostics>;
  restartStack(): Promise<DesktopDiagnostics>;
  openDataDirectory(): Promise<string>;
  openLogDirectory(): Promise<string>;
  openExternal(url: string): Promise<void>;
};

declare global {
  interface Window { satSimDesktop?: DesktopBridge; }
}

export function desktopBridge(): DesktopBridge | undefined {
  return typeof window === "undefined" ? undefined : window.satSimDesktop;
}
