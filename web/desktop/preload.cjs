const { contextBridge, ipcRenderer } = require("electron");

// Keep the renderer isolated: only this deliberately small desktop API is
// exposed to the Next.js application. CommonJS is used here because Electron
// loads sandboxed preload scripts reliably in both development and packaged
// modes with this format.
contextBridge.exposeInMainWorld("satSimDesktop", {
  apiBase: ipcRenderer.sendSync("desktop:api-base"),
  getSettings: () => ipcRenderer.invoke("desktop:settings:get"),
  saveSettings: (value) => ipcRenderer.invoke("desktop:settings:save", value),
  diagnostics: () => ipcRenderer.invoke("desktop:diagnostics"),
  restartGpu: () => ipcRenderer.invoke("desktop:gpu:restart"),
  restartStack: () => ipcRenderer.invoke("desktop:stack:restart"),
  openDataDirectory: () => ipcRenderer.invoke("desktop:open-data-directory"),
  openLogDirectory: () => ipcRenderer.invoke("desktop:open-log-directory"),
  openExternal: (url) => ipcRenderer.invoke("desktop:open-external", url),
});
