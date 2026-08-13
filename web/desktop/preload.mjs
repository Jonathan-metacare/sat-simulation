import { contextBridge, ipcRenderer } from "electron";

contextBridge.exposeInMainWorld("satSimDesktop", {
  apiBase: ipcRenderer.sendSync("desktop:api-base"),
  getSettings: () => ipcRenderer.invoke("desktop:settings:get"),
  saveSettings: (value) => ipcRenderer.invoke("desktop:settings:save", value),
  diagnostics: () => ipcRenderer.invoke("desktop:diagnostics"),
  restartGpu: () => ipcRenderer.invoke("desktop:gpu:restart"),
  restartStack: () => ipcRenderer.invoke("desktop:stack:restart"),
  openDataDirectory: () => ipcRenderer.invoke("desktop:open-data-directory"),
  openLogDirectory: () => ipcRenderer.invoke("desktop:open-log-directory"),
});
