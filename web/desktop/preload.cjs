const { contextBridge, ipcRenderer } = require("electron");

// Keep the renderer isolated: only this deliberately small desktop API is
// exposed to the Next.js application. CommonJS is used here because Electron
// loads sandboxed preload scripts reliably in both development and packaged
// modes with this format.
contextBridge.exposeInMainWorld("satSimDesktop", {
  apiBase: ipcRenderer.sendSync("desktop:api-base"),
  getSettings: () => ipcRenderer.invoke("desktop:settings:get"),
  capabilities: () => ipcRenderer.invoke("desktop:capabilities"),
  saveSettings: (value) => ipcRenderer.invoke("desktop:settings:save", value),
  resetData: (action, confirmation) => ipcRenderer.invoke("desktop:data:reset", action, confirmation),
  diagnostics: () => ipcRenderer.invoke("desktop:diagnostics"),
  restartGpu: () => ipcRenderer.invoke("desktop:gpu:restart"),
  restartStack: () => ipcRenderer.invoke("desktop:stack:restart"),
  openDataDirectory: () => ipcRenderer.invoke("desktop:open-data-directory"),
  openLogDirectory: () => ipcRenderer.invoke("desktop:open-log-directory"),
  openExternal: (url) => ipcRenderer.invoke("desktop:open-external", url),
  discoverJetsonHostKey: (credentials) => ipcRenderer.invoke("desktop:jetson:discover-host-key", credentials),
  confirmJetsonHostKey: (fingerprint) => ipcRenderer.invoke("desktop:jetson:confirm-host-key", fingerprint),
  preflightJetson: (credentials) => ipcRenderer.invoke("desktop:jetson:preflight", credentials),
  deployJetson: (request) => ipcRenderer.invoke("desktop:jetson:deploy", request),
  onJetsonProgress: (listener) => { const callback = (_event, payload) => listener(payload); ipcRenderer.on("desktop:jetson:progress", callback); return () => ipcRenderer.removeListener("desktop:jetson:progress", callback); },
});
