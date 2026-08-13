export type DesktopSettings = {
  llmApiUrl: string;
  llmModel: string;
  llmApiKey: string;
  yoloApiUrl: string;
  yoloModel: string;
  yoloApiKey: string;
  providerTimeoutSeconds: number;
};

export type DesktopDiagnostics = {
  apiBase: string | null;
  ports: Record<string, number>;
  dataDirectory: string;
  logDirectory: string;
  services: Array<{ name: string; running: boolean }>;
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
};

declare global {
  interface Window { satSimDesktop?: DesktopBridge; }
}

export function desktopBridge(): DesktopBridge | undefined {
  return typeof window === "undefined" ? undefined : window.satSimDesktop;
}
