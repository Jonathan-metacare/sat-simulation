import { app, BrowserWindow, dialog, ipcMain, shell } from "electron";
import { spawn } from "node:child_process";
import fs from "node:fs";
import fsp from "node:fs/promises";
import net from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";

const directory = path.dirname(fileURLToPath(import.meta.url));
const webDirectory = path.resolve(directory, "..");
const projectDirectory = path.resolve(webDirectory, "..");
const defaultSettings = {
  llmApiUrl: "http://127.0.0.1:11434",
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
const processes = new Map();

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
    SAT_SIM_LLM_API_URL: settings.llmApiUrl,
    SAT_SIM_LLM_MODEL: settings.llmModel,
    SAT_SIM_LLM_API_KEY: settings.llmApiKey,
    SAT_SIM_YOLO_API_URL: settings.yoloApiUrl,
    SAT_SIM_YOLO_MODEL: settings.yoloModel,
    SAT_SIM_YOLO_API_KEY: settings.yoloApiKey,
    SAT_SIM_PROVIDER_TIMEOUT_SECONDS: String(settings.providerTimeoutSeconds),
  };
}

function spawnTracked(name, command, commandArgs, environment, workingDirectory) {
  const child = spawn(command, commandArgs, {
    cwd: workingDirectory,
    env: environment,
    stdio: ["ignore", "pipe", "pipe"],
  });
  child.stdout.on("data", (value) => appendLog(name, value));
  child.stderr.on("data", (value) => appendLog(name, value));
  child.once("exit", (code, signal) => {
    appendLog(name, `\n[exit code=${code ?? "null"} signal=${signal ?? "none"}]\n`);
    if (processes.get(name) === child) processes.delete(name);
  });
  processes.set(name, child);
  return child;
}

function serviceCommand() {
  if (app.isPackaged) return { command: path.join(process.resourcesPath, "python", "sat-sim-service"), prefix: [] };
  return {
    command: path.join(projectDirectory, ".venv", "bin", "python"),
    prefix: [path.join(projectDirectory, "desktop", "python_service.py")],
  };
}

function startService(name, port) {
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
    ELECTRON_RUN_AS_NODE: "1",
  };
  if (app.isPackaged) {
    const server = path.join(process.resourcesPath, "web", "server.js");
    return spawnTracked("web", process.execPath, [server], environment, path.dirname(server));
  }
  const next = path.join(webDirectory, "node_modules", "next", "dist", "bin", "next");
  return spawnTracked("web", process.execPath, [next, "dev", "-p", String(runtime.ports.web)], environment, webDirectory);
}

async function waitFor(url, name, timeout = 30000) {
  const deadline = Date.now() + timeout;
  let latest;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url);
      if (response.ok) return;
      latest = `HTTP ${response.status}`;
    } catch (error) {
      latest = error instanceof Error ? error.message : String(error);
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(`${name} 未在 ${timeout / 1000} 秒内就绪：${latest ?? "unknown error"}`);
}

async function stopProcess(name) {
  const child = processes.get(name);
  if (!child || child.exitCode !== null) return;
  child.kill("SIGTERM");
  await Promise.race([
    new Promise((resolve) => child.once("exit", resolve)),
    new Promise((resolve) => setTimeout(resolve, 3000)),
  ]);
  if (child.exitCode === null) child.kill("SIGKILL");
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
  startService("gpu", runtime.ports.gpu);
  await waitFor(`http://127.0.0.1:${runtime.ports.gpu}/health`, "GPU 服务");
  startService("platform", runtime.ports.platform);
  await waitFor(`http://127.0.0.1:${runtime.ports.platform}/health`, "星务平台服务");
  startService("ground", runtime.ports.ground);
  await waitFor(`http://127.0.0.1:${runtime.ports.ground}/health`, "地面站服务");
  startWeb();
  await waitFor(`http://127.0.0.1:${runtime.ports.web}`, "Web 服务");
}

function diagnostics() {
  const locations = runtimeDirectories();
  return {
    apiBase: runtime?.apiBase ?? null,
    ports: runtime?.ports ?? {},
    dataDirectory: locations.root,
    logDirectory: locations.logs,
    services: ["gpu", "platform", "ground", "web"].map((name) => ({ name, running: processes.has(name) })),
  };
}

function registerIpc() {
  ipcMain.on("desktop:api-base", (event) => { event.returnValue = runtime?.apiBase ?? "http://127.0.0.1:8000/api"; });
  ipcMain.handle("desktop:settings:get", () => settings);
  ipcMain.handle("desktop:settings:save", async (_event, value) => {
    const saved = await saveSettings(value);
    await stopProcess("gpu");
    startService("gpu", runtime.ports.gpu);
    await waitFor(`http://127.0.0.1:${runtime.ports.gpu}/health`, "GPU 服务");
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
    title: "星上智能计算数字孪生",
    webPreferences: {
      preload: path.join(app.getAppPath(), "desktop", "preload.mjs"),
      contextIsolation: true, nodeIntegration: false, sandbox: true,
    },
  });
  await mainWindow.loadURL("data:text/html;charset=utf-8,<body style='background:%23010810;color:%23bcefff;font-family:-apple-system;padding:36px'>正在启动星上智能计算数字孪生…</body>");
  try {
    await startStack();
    await mainWindow.loadURL(`http://127.0.0.1:${runtime.ports.web}`);
  } catch (error) {
    await dialog.showMessageBox(mainWindow, {
      type: "error", title: "本地仿真服务启动失败",
      message: error instanceof Error ? error.message : String(error),
      detail: `日志目录：${runtimeDirectories().logs}`,
    });
  }
  app.on("activate", () => { if (BrowserWindow.getAllWindows().length === 0) bootstrap(); });
}

app.on("before-quit", () => { void stopStack(); });
app.on("window-all-closed", () => { if (process.platform !== "darwin") app.quit(); });
bootstrap().catch((error) => { console.error(error); app.quit(); });
