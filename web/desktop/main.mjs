import { app, BrowserWindow, dialog, ipcMain, shell } from "electron";
import { spawn } from "node:child_process";
import fs from "node:fs";
import fsp from "node:fs/promises";
import http from "node:http";
import net from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";

const directory = path.dirname(fileURLToPath(import.meta.url));
const webDirectory = path.resolve(directory, "..");
const projectDirectory = path.resolve(webDirectory, "..");
const defaultSettings = {
  locale: "zh",
  theme: "dark",
  activeAiMode: "yolo",
  activeScenarioId: "scenario-demo-beijing",
  cesiumIonToken: "",
  // A provider is an optional external integration.  Do not probe a local
  // Ollama endpoint until the user explicitly configures and enables LLM.
  llmApiUrl: "",
  llmModel: "",
  llmApiKey: "",
  yoloApiUrl: "",
  yoloModel: "default",
  yoloApiKey: "",
  providerTimeoutSeconds: 30,
};

let mainWindow;
let runtime;
let settings = { ...defaultSettings };
let ipcRegistered = false;
let isQuitting = false;
const processes = new Map();
// LaunchServices returns immediately for packaged service agents.  Retain the
// exact role-and-port identity separately so they can still be stopped later
// without keeping a visible `open -W` helper process alive in the Dock.
const packagedServicePatterns = new Map();
const hasSingleInstanceLock = app.requestSingleInstanceLock();

function runtimeDirectories() {
  const root = path.join(app.getPath("userData"), "runtime-data");
  return {
    root,
    logs: path.join(app.getPath("userData"), "logs"),
    settings: path.join(app.getPath("userData"), "desktop-settings.json"),
    database: path.join(root, "sat-simulation.db"),
  };
}

async function loadSettings() {
  const locations = runtimeDirectories();
  await fsp.mkdir(path.dirname(locations.settings), { recursive: true });
  try {
    const loaded = JSON.parse(await fsp.readFile(locations.settings, "utf8"));
    settings = { ...defaultSettings, ...loaded };
  } catch (error) {
    if (error.code !== "ENOENT") console.warn("Could not read desktop settings", error);
  }
}

function cleanSettings(value) {
  const text = (field) => typeof value?.[field] === "string" ? value[field].trim() : defaultSettings[field];
  const timeout = Number(value?.providerTimeoutSeconds);
  return {
    locale: value?.locale === "en" ? "en" : "zh",
    theme: value?.theme === "light" ? "light" : "dark",
    activeAiMode: value?.activeAiMode === "llm" ? "llm" : "yolo",
    activeScenarioId: text("activeScenarioId"),
    cesiumIonToken: text("cesiumIonToken"),
    llmApiUrl: text("llmApiUrl"), llmModel: text("llmModel"), llmApiKey: text("llmApiKey"),
    yoloApiUrl: text("yoloApiUrl"), yoloModel: text("yoloModel") || "default", yoloApiKey: text("yoloApiKey"),
    providerTimeoutSeconds: Number.isFinite(timeout) && timeout >= 1 && timeout <= 600 ? timeout : 30,
  };
}

async function saveSettings(value) {
  settings = cleanSettings(value);
  const { settings: settingsPath } = runtimeDirectories();
  const temporary = `${settingsPath}.tmp`;
  await fsp.writeFile(temporary, `${JSON.stringify(settings, null, 2)}\n`, { mode: 0o600 });
  await fsp.rename(temporary, settingsPath);
  await fsp.chmod(settingsPath, 0o600);
  return settings;
}

async function availablePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once("error", reject);
    server.listen({ host: "127.0.0.1", port: 0 }, () => {
      const address = server.address();
      server.close((error) => error ? reject(error) : resolve(address.port));
    });
  });
}

async function allocatePorts() {
  const names = ["ground", "platform", "gpu", "downlink", "uplink", "gtx", "gtxResult", "web"];
  const ports = {};
  for (const name of names) ports[name] = await availablePort();
  return ports;
}

function appendLog(name, chunk) {
  const file = path.join(runtimeDirectories().logs, `${name}.log`);
  fs.appendFileSync(file, chunk);
}

function sharedEnvironment() {
  const { root, database } = runtimeDirectories();
  const ports = runtime.ports;
  return {
    ...process.env,
    SAT_SIM_HOST: "127.0.0.1",
    SAT_SIM_DATA_DIR: root,
    SAT_SIM_DATABASE_URL: `sqlite+aiosqlite:///${database}`,
    SAT_SIM_ALLOWED_ORIGINS: `http://127.0.0.1:${ports.web}`,
    SAT_SIM_GROUND_API_PORT: String(ports.ground),
    SAT_SIM_PLATFORM_API_PORT: String(ports.platform),
    SAT_SIM_GPU_API_PORT: String(ports.gpu),
    SAT_SIM_GROUND_DOWNLINK_HOST: "127.0.0.1",
    SAT_SIM_GROUND_DOWNLINK_PORT: String(ports.downlink),
    SAT_SIM_PLATFORM_UPLINK_HOST: "127.0.0.1",
    SAT_SIM_PLATFORM_UPLINK_PORT: String(ports.uplink),
    SAT_SIM_GPU_GTX_HOST: "127.0.0.1",
    SAT_SIM_GPU_GTX_PORT: String(ports.gtx),
    SAT_SIM_PLATFORM_GTX_RESULT_HOST: "127.0.0.1",
    SAT_SIM_PLATFORM_GTX_RESULT_PORT: String(ports.gtxResult),
    SAT_SIM_PLATFORM_HTTP_URL: `http://127.0.0.1:${ports.platform}`,
    SAT_SIM_GPU_HTTP_URL: `http://127.0.0.1:${ports.gpu}`,
    SAT_SIM_GROUND_HTTP_URL: `http://127.0.0.1:${ports.ground}`,
    SAT_SIM_LLM_API_URL: settings.activeAiMode === "llm" ? settings.llmApiUrl : "",
    SAT_SIM_LLM_MODEL: settings.llmModel,
    SAT_SIM_LLM_API_KEY: settings.activeAiMode === "llm" ? settings.llmApiKey : "",
    SAT_SIM_YOLO_API_URL: settings.activeAiMode === "yolo" ? settings.yoloApiUrl : "",
    SAT_SIM_YOLO_MODEL: settings.yoloModel,
    SAT_SIM_YOLO_API_KEY: settings.activeAiMode === "yolo" ? settings.yoloApiKey : "",
    SAT_SIM_PROVIDER_TIMEOUT_SECONDS: String(settings.providerTimeoutSeconds),
  };
}

function spawnTracked(name, command, commandArgs, environment, workingDirectory) {
  const child = spawn(command, commandArgs, {
    cwd: workingDirectory,
    env: environment,
    stdio: ["ignore", "pipe", "pipe"],
    // PyInstaller's one-file bootloader spawns the actual service process.
    // A dedicated group lets shutdown terminate both the bootloader and child.
    detached: process.platform !== "win32",
  });
  child.stdout.on("data", (value) => appendLog(name, value));
  child.stderr.on("data", (value) => appendLog(name, value));
  child.once("error", (error) => {
    appendLog(name, `\n[spawn error] ${error.stack ?? error.message}\n`);
  });
  child.once("exit", (code, signal) => {
    appendLog(name, `\n[exit code=${code ?? "null"} signal=${signal ?? "none"}]\n`);
    if (processes.get(name) === child) processes.delete(name);
  });
  processes.set(name, child);
  return child;
}

function spawnPackagedService(name, port) {
  const bundle = path.join(process.resourcesPath, "python", "sat-sim-service.app");
  const serviceArguments = [name, "--host", "127.0.0.1", "--port", String(port)];
  const environment = sharedEnvironment();
  // Launch through LaunchServices rather than executing the bundle's helper
  // binary directly.  This makes macOS honor LSUIElement and keeps simulation
  // workers out of the Dock (where they otherwise appear as generic `exec`).
  const openArguments = ["-n", "-g", "-j"];
  for (const [key, value] of Object.entries(environment)) {
    if (typeof value === "string") openArguments.push("--env", `${key}=${value}`);
  }
  openArguments.push(bundle, "--args", ...serviceArguments);
  const child = spawnTracked(name, "/usr/bin/open", openArguments, process.env, projectDirectory);
  // Do not use `open -W`: those three wait processes are what macOS presents
  // as the unwanted generic `exec` Dock icon.  The helper's own argv remains
  // a precise, local-only identity for shutdown.
  packagedServicePatterns.set(name, `sat-sim-service ${name} --host 127.0.0.1 --port ${port}`);
  return child;
}

function serviceCommand() {
  if (app.isPackaged) {
    return {
      command: path.join(process.resourcesPath, "python", "sat-sim-service.app", "Contents", "MacOS", "sat-sim-service"),
      prefix: [],
    };
  }
  return {
    command: path.join(projectDirectory, ".venv", "bin", "python"),
    prefix: [path.join(projectDirectory, "desktop", "python_service.py")],
  };
}

function startService(name, port) {
  if (app.isPackaged) return spawnPackagedService(name, port);
  const executable = serviceCommand();
  return spawnTracked(
    name,
    executable.command,
    [...executable.prefix, name, "--host", "127.0.0.1", "--port", String(port)],
    sharedEnvironment(),
    projectDirectory,
  );
}

function startWeb() {
  const environment = {
    ...sharedEnvironment(),
    PORT: String(runtime.ports.web),
    HOSTNAME: "127.0.0.1",
    NEXT_PUBLIC_API_URL: runtime.apiBase,
    NEXT_PUBLIC_CESIUM_ION_ACCESS_TOKEN: settings.cesiumIonToken,
    ELECTRON_RUN_AS_NODE: "1",
  };
  if (app.isPackaged) {
    const server = path.join(process.resourcesPath, "web", "server.js");
    return spawnTracked("web", process.execPath, [server], environment, path.dirname(server));
  }
  const next = path.join(webDirectory, "node_modules", "next", "dist", "bin", "next");
  return spawnTracked("web", process.execPath, [next, "dev", "-p", String(runtime.ports.web)], environment, webDirectory);
}

async function restartWeb() {
  await stopProcess("web");
  startWeb();
  await waitFor(`http://127.0.0.1:${runtime.ports.web}`, "Web 服务");
  if (mainWindow && !mainWindow.isDestroyed()) {
    await mainWindow.loadURL(`http://127.0.0.1:${runtime.ports.web}`);
  }
}

async function waitFor(url, name, timeout = 90000) {
  const deadline = Date.now() + timeout;
  let latest;
  while (Date.now() < deadline) {
    try {
      const status = await localHttpStatus(url);
      if (status >= 200 && status < 300) return;
      latest = `HTTP ${status}`;
    } catch (error) {
      latest = error instanceof Error ? error.message : String(error);
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(`${name} 未在 ${timeout / 1000} 秒内就绪：${latest ?? "unknown error"}`);
}

function localHttpStatus(url) {
  return new Promise((resolve, reject) => {
    const request = http.get(url, { timeout: 2000 }, (response) => {
      response.resume();
      resolve(response.statusCode ?? 0);
    });
    request.once("timeout", () => request.destroy(new Error("request timeout")));
    request.once("error", reject);
  });
}

async function stopProcess(name) {
  const serviceProcessPattern = packagedServicePatterns.get(name);
  if (serviceProcessPattern) {
    // The pattern includes the dynamically allocated port and service role;
    // it cannot match a worker from a different desktop launch.
    spawn("/usr/bin/pkill", ["-TERM", "-f", serviceProcessPattern], { stdio: "ignore" });
    packagedServicePatterns.delete(name);
    processes.delete(name);
    await new Promise((resolve) => setTimeout(resolve, 150));
    return;
  }
  const child = processes.get(name);
  if (!child || child.exitCode !== null) return;
  const terminate = (signal) => {
    if (process.platform !== "win32" && child.pid) {
      try { process.kill(-child.pid, signal); return; } catch { /* process may have already exited */ }
    }
    child.kill(signal);
  };
  terminate("SIGTERM");
  await Promise.race([
    new Promise((resolve) => child.once("exit", resolve)),
    new Promise((resolve) => setTimeout(resolve, 3000)),
  ]);
  if (child.exitCode === null) terminate("SIGKILL");
  processes.delete(name);
}

async function stopStack() {
  for (const name of ["web", "ground", "platform", "gpu"]) await stopProcess(name);
}

async function startStack() {
  const locations = runtimeDirectories();
  await Promise.all([fsp.mkdir(locations.root, { recursive: true }), fsp.mkdir(locations.logs, { recursive: true })]);
  runtime = { ports: await allocatePorts() };
  runtime.apiBase = `http://127.0.0.1:${runtime.ports.ground}/api`;
  // All simulation nodes are independent at boot.  Start their frozen Python
  // runtimes together: the first import of Rasterio/GDAL can take tens of
  // seconds on macOS, but it must not serialize the whole desktop startup.
  startService("gpu", runtime.ports.gpu);
  startService("platform", runtime.ports.platform);
  startService("ground", runtime.ports.ground);
  await Promise.all([
    waitFor(`http://127.0.0.1:${runtime.ports.gpu}/health`, "GPU 服务"),
    waitFor(`http://127.0.0.1:${runtime.ports.platform}/health`, "星务平台服务"),
    waitFor(`http://127.0.0.1:${runtime.ports.ground}/health`, "地面站服务"),
  ]);
  startWeb();
  await waitFor(`http://127.0.0.1:${runtime.ports.web}`, "Web 服务");
}

function diagnostics() {
  const locations = runtimeDirectories();
  return {
    version: app.getVersion(),
    apiBase: runtime?.apiBase ?? null,
    ports: runtime?.ports ?? {},
    dataDirectory: locations.root,
    logDirectory: locations.logs,
    services: ["gpu", "platform", "ground", "web"].map((name) => ({ name, version: app.getVersion(), running: processes.has(name) })),
  };
}

function registerExternalHandler() {
  // This is deliberately replaced on every bootstrap: it allows a reopened
  // macOS window to use the current preload bridge even after dev reloads.
  ipcMain.removeHandler("desktop:open-external");
  ipcMain.handle("desktop:open-external", (_event, rawUrl) => {
    const url = new URL(String(rawUrl));
    if (url.protocol !== "https:" || url.hostname !== "www.spacezenith.ai") {
      throw new Error("External URL is not allowed");
    }
    return shell.openExternal(url.toString());
  });
}

function registerIpc() {
  registerExternalHandler();
  // macOS may invoke bootstrap again after all windows are closed and the app
  // is reactivated. IPC handlers belong to the process, not a window, so they
  // must only be registered once.
  if (ipcRegistered) return;
  ipcRegistered = true;
  ipcMain.on("desktop:api-base", (event) => { event.returnValue = runtime?.apiBase ?? "http://127.0.0.1:8000/api"; });
  ipcMain.handle("desktop:settings:get", () => settings);
  ipcMain.handle("desktop:settings:save", async (_event, value) => {
    const prior = settings;
    const saved = await saveSettings(value);
    const providerChanged = ["activeAiMode", "llmApiUrl", "llmModel", "llmApiKey", "yoloApiUrl", "yoloModel", "yoloApiKey", "providerTimeoutSeconds"].some((key) => prior[key] !== saved[key]);
    if (providerChanged) {
      await stopProcess("gpu");
      startService("gpu", runtime.ports.gpu);
      await waitFor(`http://127.0.0.1:${runtime.ports.gpu}/health`, "GPU 服务");
    }
    if (prior.cesiumIonToken !== saved.cesiumIonToken) await restartWeb();
    return saved;
  });
  ipcMain.handle("desktop:diagnostics", () => diagnostics());
  ipcMain.handle("desktop:gpu:restart", async () => {
    await stopProcess("gpu"); startService("gpu", runtime.ports.gpu);
    await waitFor(`http://127.0.0.1:${runtime.ports.gpu}/health`, "GPU 服务");
    return diagnostics();
  });
  ipcMain.handle("desktop:stack:restart", async () => { await stopStack(); await startStack(); return diagnostics(); });
  ipcMain.handle("desktop:open-data-directory", () => shell.openPath(runtimeDirectories().root));
  ipcMain.handle("desktop:open-log-directory", () => shell.openPath(runtimeDirectories().logs));
}

async function bootstrap() {
  await app.whenReady();
  await loadSettings();
  registerIpc();
  mainWindow = new BrowserWindow({
    width: 1500, height: 980, minWidth: 1080, minHeight: 720,
    title: "SpaceZenith-Sim",
    webPreferences: {
      // In `electron desktop/main.mjs` development app.getAppPath() resolves
      // to web/desktop; packaged builds resolve to the application root.
      preload: app.isPackaged
        ? path.join(app.getAppPath(), "desktop", "preload.cjs")
        : path.join(webDirectory, "desktop", "preload.cjs"),
      // The renderer remains isolated from Node.  We deliberately keep the
      // Chromium sandbox disabled here because the desktop bridge is an
      // Electron preload IPC boundary and must load identically in development
      // and packaged modes on macOS.
      contextIsolation: true, nodeIntegration: false, sandbox: false,
    },
  });
  // This app is distributed as an unsigned DMG and may be upgraded by
  // replacing the .app bundle while keeping Electron's user-data directory.
  // Next marks hashed chunks immutable, so a cached 404 from an older bundle
  // can otherwise prevent dynamic Cesium chunks from ever loading.
  await mainWindow.webContents.session.clearCache();
  mainWindow.webContents.on("console-message", (_event, _level, message) => {
    appendLog("desktop", `[renderer] ${message}\n`);
  });
  mainWindow.webContents.on("did-finish-load", () => {
    void mainWindow.webContents.executeJavaScript(
      "typeof window.satSimDesktop",
    ).then((result) => appendLog("desktop", `[bridge] satSimDesktop=${result}\n`));
  });
  await mainWindow.loadURL("data:text/html;charset=utf-8,<body style='background:%23010810;color:%23bcefff;font-family:-apple-system;padding:36px'>正在启动 SpaceZenith-Sim…</body>");
  try {
    await startStack();
    await mainWindow.loadURL(`http://127.0.0.1:${runtime.ports.web}`);
  } catch (error) {
    appendLog("desktop", `[startup failed] ${error instanceof Error ? error.stack ?? error.message : String(error)}\n`);
    await stopStack();
    await dialog.showMessageBox(mainWindow, {
      type: "error", title: "本地仿真服务启动失败",
      message: error instanceof Error ? error.message : String(error),
      detail: `日志目录：${runtimeDirectories().logs}`,
    });
  }
  app.on("activate", () => { if (BrowserWindow.getAllWindows().length === 0) bootstrap(); });
}

if (!hasSingleInstanceLock) {
  // The mounted DMG and /Applications can both appear in Spotlight.  Running
  // both copies would start two service stacks against the same local data.
  app.quit();
} else {
  app.on("second-instance", () => {
    if (!mainWindow || mainWindow.isDestroyed()) return;
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.show();
    mainWindow.focus();
  });
  app.on("before-quit", (event) => {
    if (isQuitting) return;
    event.preventDefault();
    isQuitting = true;
    void stopStack().finally(() => app.quit());
  });
  app.on("window-all-closed", () => { if (process.platform !== "darwin") app.quit(); });
  bootstrap().catch((error) => { console.error(error); app.quit(); });
}
