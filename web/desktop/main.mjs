import { app, BrowserWindow, dialog, ipcMain, safeStorage, shell } from "electron";
import { spawn } from "node:child_process";
import fs from "node:fs";
import fsp from "node:fs/promises";
import http from "node:http";
import net from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { deployJetson, discoverJetsonHostKey, preflightJetson, pullJetsonOllamaModel } from "./jetson-deployment.mjs";

const directory = path.dirname(fileURLToPath(import.meta.url));
const webDirectory = path.resolve(directory, "..");
const projectDirectory = path.resolve(webDirectory, "..");
const desktopPackage = JSON.parse(fs.readFileSync(path.join(webDirectory, "package.json"), "utf8"));
const desktopVersion = desktopPackage.version;
const defaultSettings = {
  locale: "zh",
  theme: "dark",
  activeAiMode: "llm",
  activeScenarioId: "scenario-demo-beijing",
  cesiumIonToken: "",
  keeptrackApiKey: "",
  llmModel: "",
  providerTimeoutSeconds: 300,
  gpuMode: "jetson",
  jetsonHost: "",
  jetsonSshUsername: "",
  jetsonSshPasswordEncrypted: "",
  jetsonHostKeyFingerprint: "",
  jetsonDeploymentStatus: "unconfigured",
  jetsonDeploymentVersion: "",
  jetsonDeploymentError: "",
  jetsonApiPort: 8002,
  jetsonGtxPort: 9101,
  desktopAdvertiseHost: "",
  platformGtxResultPort: 9102,
};

let mainWindow;
let runtime;
let settings = { ...defaultSettings };
let ipcRegistered = false;
let isQuitting = false;
let resetInProgress = false;
let jetsonDeploymentInProgress = false;
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
    settings = cleanSettings({ ...defaultSettings, ...loaded });
  } catch (error) {
    if (error.code !== "ENOENT") console.warn("Could not read desktop settings", error);
  }
}

function cleanSettings(value) {
  const text = (field) => typeof value?.[field] === "string" ? value[field].trim() : defaultSettings[field];
  const timeout = Number(value?.providerTimeoutSeconds);
  const port = (field, fallback) => {
    const candidate = Number(value?.[field]);
    return Number.isInteger(candidate) && candidate >= 1 && candidate <= 65535 ? candidate : fallback;
  };
  return {
    locale: value?.locale === "en" ? "en" : "zh",
    theme: value?.theme === "light" ? "light" : "dark",
    activeAiMode: "llm",
    activeScenarioId: text("activeScenarioId"),
    cesiumIonToken: text("cesiumIonToken"),
    keeptrackApiKey: text("keeptrackApiKey"),
    llmModel: text("llmModel"),
    // Migrate the former 30-second desktop default while preserving every
    // explicit non-default value the user may already have chosen.
    providerTimeoutSeconds: Number.isFinite(timeout) && timeout >= 1 && timeout <= 600
      ? (timeout === 30 ? 300 : timeout)
      : 300,
    // Normalize legacy Local GPU preferences to the only supported Jetson mode.
    gpuMode: "jetson",
    jetsonHost: text("jetsonHost"),
    jetsonSshUsername: text("jetsonSshUsername"),
    jetsonSshPasswordEncrypted: text("jetsonSshPasswordEncrypted"),
    jetsonHostKeyFingerprint: text("jetsonHostKeyFingerprint"),
    jetsonDeploymentStatus: ["unconfigured", "pending", "deploying", "ready", "failed"].includes(value?.jetsonDeploymentStatus) ? value.jetsonDeploymentStatus : "unconfigured",
    jetsonDeploymentVersion: text("jetsonDeploymentVersion"),
    jetsonDeploymentError: text("jetsonDeploymentError"),
    jetsonApiPort: port("jetsonApiPort", 8002),
    jetsonGtxPort: port("jetsonGtxPort", 9101),
    desktopAdvertiseHost: text("desktopAdvertiseHost"),
    platformGtxResultPort: port("platformGtxResultPort", 9102),
  };
}

function publicSettings() {
  const { jetsonSshPasswordEncrypted: _jetsonSshPasswordEncrypted, ...result } = settings;
  return result;
}

function storedJetsonPassword() {
  if (!settings.jetsonSshPasswordEncrypted) return "";
  if (!safeStorage.isEncryptionAvailable()) throw new Error("Secure credential storage is unavailable on this system");
  try {
    return safeStorage.decryptString(Buffer.from(settings.jetsonSshPasswordEncrypted, "base64"));
  } catch {
    return "";
  }
}

function encryptedJetsonPassword(rawPassword) {
  const password = typeof rawPassword === "string" ? rawPassword : "";
  if (password.length > 1024) throw new Error("Jetson SSH password is too long");
  if (password && !safeStorage.isEncryptionAvailable()) throw new Error("Secure credential storage is unavailable on this system");
  return password ? safeStorage.encryptString(password).toString("base64") : "";
}

async function saveJetsonPassword(rawPassword) {
  await saveSettings({ ...settings, jetsonSshPasswordEncrypted: encryptedJetsonPassword(rawPassword) });
}

function bundledJetsonPayload(version) {
  return app.isPackaged
    ? path.join(process.resourcesPath, "jetson-payload")
    : path.join(projectDirectory, "release", `jetson-${version}-linux-arm64`);
}

function jetsonConnection(credentials) {
  if (!settings.jetsonHost || !settings.jetsonSshUsername) throw new Error("Save Jetson host and SSH username first");
  const password = typeof credentials?.password === "string" ? credentials.password : "";
  if (!password) throw new Error("Enter the Jetson SSH password for this session");
  return {
    host: settings.jetsonHost,
    username: settings.jetsonSshUsername,
    password,
    expectedFingerprint: settings.jetsonHostKeyFingerprint || undefined,
  };
}

function sendJetsonProgress(payload) {
  if (mainWindow && !mainWindow.isDestroyed()) mainWindow.webContents.send("desktop:jetson:progress", payload);
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
  const names = ["ground", "platform", "optical", "downlink", "uplink", "gtxResult", "payload", "payloadResult", "web"];
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
  // An unconfigured desktop deliberately points at an unreachable endpoint;
  // the services can still start for configuration, but L1/AI cannot fall
  // back to a local GPU or Ollama process.
  const jetsonHttp = settings.jetsonHost
    ? `http://${settings.jetsonHost}:${settings.jetsonApiPort}`
    : "http://127.0.0.1:9";
  return {
    ...process.env,
    SAT_SIM_HOST: "127.0.0.1",
    SAT_SIM_DATA_DIR: root,
    SAT_SIM_DATABASE_URL: `sqlite+aiosqlite:///${database}`,
    SAT_SIM_ALLOWED_ORIGINS: `http://127.0.0.1:${ports.web}`,
    SAT_SIM_GROUND_API_PORT: String(ports.ground),
    SAT_SIM_PLATFORM_API_PORT: String(ports.platform),
    SAT_SIM_OPTICAL_API_PORT: String(ports.optical),
    SAT_SIM_GROUND_DOWNLINK_HOST: "127.0.0.1",
    SAT_SIM_GROUND_DOWNLINK_PORT: String(ports.downlink),
    SAT_SIM_PLATFORM_UPLINK_HOST: "127.0.0.1",
    SAT_SIM_PLATFORM_UPLINK_PORT: String(ports.uplink),
    SAT_SIM_GPU_GTX_HOST: settings.jetsonHost,
    SAT_SIM_GPU_GTX_PORT: String(settings.jetsonGtxPort),
    SAT_SIM_PLATFORM_GTX_RESULT_HOST: "127.0.0.1",
    SAT_SIM_PLATFORM_GTX_RESULT_PORT: String(settings.platformGtxResultPort),
    SAT_SIM_PLATFORM_GTX_RESULT_BIND_HOST: "0.0.0.0",
    SAT_SIM_PLATFORM_GTX_RESULT_ADVERTISE_HOST: settings.desktopAdvertiseHost,
    SAT_SIM_OPTICAL_PAYLOAD_HOST: "127.0.0.1",
    SAT_SIM_OPTICAL_PAYLOAD_PORT: String(ports.payload),
    SAT_SIM_PLATFORM_PAYLOAD_RESULT_HOST: "127.0.0.1",
    SAT_SIM_PLATFORM_PAYLOAD_RESULT_PORT: String(ports.payloadResult),
    SAT_SIM_PLATFORM_HTTP_URL: `http://127.0.0.1:${ports.platform}`,
    SAT_SIM_GPU_HTTP_URL: jetsonHttp,
    SAT_SIM_GROUND_HTTP_URL: `http://127.0.0.1:${ports.ground}`,
    SAT_SIM_OPTICAL_HTTP_URL: `http://127.0.0.1:${ports.optical}`,
    // Desktop custom processors use the application-managed macOS sandbox.
    // A non-macOS build fails closed instead of silently using host Python.
    SAT_SIM_OCI_RUNTIME: "desktop-sandbox",
    SAT_SIM_PROVIDER_TIMEOUT_SECONDS: String(settings.providerTimeoutSeconds),
    SAT_SIM_KEEPTRACK_API_KEY: settings.keeptrackApiKey,
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
    windowsHide: process.platform === "win32",
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
    if (process.platform === "win32") {
      return {
        command: path.join(process.resourcesPath, "python", "sat-sim-service", "sat-sim-service.exe"),
        prefix: [],
      };
    }
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
  if (app.isPackaged && process.platform === "darwin") return spawnPackagedService(name, port);
  const executable = serviceCommand();
  return spawnTracked(
    name,
    executable.command,
    [...executable.prefix, name, "--host", "127.0.0.1", "--port", String(port)],
    sharedEnvironment(),
    projectDirectory,
  );
}

function runDesktopUtility(name) {
  const executable = serviceCommand();
  return new Promise((resolve, reject) => {
    const child = spawn(executable.command, [...executable.prefix, name], {
      cwd: projectDirectory,
      env: sharedEnvironment(),
      windowsHide: true,
      stdio: ["ignore", "pipe", "pipe"],
    });
    child.stdout.on("data", (value) => appendLog("desktop", `[${name}] ${value}`));
    child.stderr.on("data", (value) => appendLog("desktop", `[${name}] ${value}`));
    child.once("error", reject);
    child.once("exit", (code, signal) => {
      if (code === 0) resolve();
      else reject(new Error(`${name} failed (code=${code ?? "null"}, signal=${signal ?? "none"})`));
    });
  });
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

async function loadCurrentWeb(query = "") {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  await mainWindow.loadURL(`http://127.0.0.1:${runtime.ports.web}${query}`);
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
  if (process.platform === "win32" && child.pid) {
    // The frozen Python service can load GDAL worker threads. Terminate its
    // process tree so an application exit or GPU restart cannot leave a local
    // sat-sim-service.exe holding the dynamic port or SQLite file lock.
    spawn("taskkill", ["/pid", String(child.pid), "/t", "/f"], { stdio: "ignore", windowsHide: true });
    await Promise.race([
      new Promise((resolve) => child.once("exit", resolve)),
      new Promise((resolve) => setTimeout(resolve, 3000)),
    ]);
    processes.delete(name);
    return;
  }
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
  for (const name of ["web", "ground", "platform", "optical"]) await stopProcess(name);
}

async function startStack() {
  const locations = runtimeDirectories();
  await Promise.all([fsp.mkdir(locations.root, { recursive: true }), fsp.mkdir(locations.logs, { recursive: true })]);
  runtime = { ports: await allocatePorts() };
  runtime.apiBase = `http://127.0.0.1:${runtime.ports.ground}/api`;
  // All simulation nodes are independent at boot.  Start their frozen Python
  // runtimes together: the first import of Rasterio/GDAL can take tens of
  // seconds on macOS, but it must not serialize the whole desktop startup.
  startService("optical", runtime.ports.optical);
  startService("platform", runtime.ports.platform);
  startService("ground", runtime.ports.ground);
  await Promise.all([
    waitFor(`http://127.0.0.1:${runtime.ports.platform}/health`, "星务平台服务"),
    waitFor(`http://127.0.0.1:${runtime.ports.optical}/health`, "光学载荷服务"),
    waitFor(`http://127.0.0.1:${runtime.ports.ground}/health`, "地面站服务"),
  ]);
  startWeb();
  await waitFor(`http://127.0.0.1:${runtime.ports.web}`, "Web 服务");
}

function diagnostics() {
  const locations = runtimeDirectories();
  return {
    version: desktopVersion,
    apiBase: runtime?.apiBase ?? null,
    ports: runtime?.ports ?? {},
    dataDirectory: locations.root,
    logDirectory: locations.logs,
    services: ["optical", "platform", "ground", "web"].map((name) => ({ name, version: desktopVersion, running: processes.has(name) })),
  };
}

const resetActions = new Set(["simulation-data", "catalog-caches", "settings-defaults"]);

async function resetLocalData(rawAction, rawConfirmation) {
  const action = String(rawAction ?? "");
  const confirmation = String(rawConfirmation ?? "");
  if (!resetActions.has(action)) throw new Error("Unsupported reset action");
  if ((action === "simulation-data" || action === "settings-defaults") && confirmation !== "RESET") {
    throw new Error("Type RESET to confirm this reset");
  }
  if (resetInProgress) throw new Error("A data reset is already in progress");

  resetInProgress = true;
  let actionError;
  try {
    await stopStack();
    const locations = runtimeDirectories();
    if (action === "simulation-data") {
      // `root` is derived solely from Electron's userData directory.  Never
      // accept a path from IPC, even for this user-authorized permanent reset.
      await fsp.rm(locations.root, { recursive: true, force: true });
      await saveSettings({ ...settings, activeScenarioId: defaultSettings.activeScenarioId });
    } else if (action === "catalog-caches") {
      await runDesktopUtility("reset-catalog-caches");
    } else {
      await fsp.rm(locations.settings, { force: true });
      settings = { ...defaultSettings };
    }
  } catch (error) {
    actionError = error;
  }

  try {
    await startStack();
    // A full stack restart allocates new localhost ports.  The existing
    // renderer otherwise keeps polling the now-closed Ground port.
    await loadCurrentWeb();
  } catch (restartError) {
    const detail = restartError instanceof Error ? restartError.message : String(restartError);
    if (actionError) {
      const original = actionError instanceof Error ? actionError.message : String(actionError);
      throw new Error(`${original}; service restart also failed: ${detail}. Logs: ${runtimeDirectories().logs}`);
    }
    throw new Error(`Reset completed but services could not restart: ${detail}. Logs: ${runtimeDirectories().logs}`);
  } finally {
    resetInProgress = false;
  }
  if (actionError) throw actionError;
  return { action, settings, diagnostics: diagnostics() };
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
  ipcMain.handle("desktop:settings:get", () => publicSettings());
  ipcMain.handle("desktop:jetson:password:get", () => storedJetsonPassword());
  ipcMain.handle("desktop:jetson:password:save", async (_event, password) => {
    await saveJetsonPassword(password);
  });
  ipcMain.handle("desktop:jetson:discover-host-key", async (_event, credentials) => {
    const connection = jetsonConnection(credentials);
    return { fingerprint: await discoverJetsonHostKey(connection) };
  });
  ipcMain.handle("desktop:jetson:confirm-host-key", async (_event, fingerprint) => {
    if (!/^SHA256:[A-Za-z0-9+/=]+$/.test(String(fingerprint))) throw new Error("Invalid Jetson host key fingerprint");
    await saveSettings({ ...settings, jetsonHostKeyFingerprint: String(fingerprint), jetsonDeploymentStatus: "pending", jetsonDeploymentError: "" });
    return publicSettings();
  });
  ipcMain.handle("desktop:jetson:preflight", async (_event, credentials) => {
    const connection = jetsonConnection(credentials);
    if (!connection.expectedFingerprint) throw new Error("Confirm the Jetson host key before running preflight");
    return preflightJetson(connection, (message) => sendJetsonProgress({ type: "log", message }));
  });
  ipcMain.handle("desktop:jetson:deploy", async (_event, request) => {
    if (jetsonDeploymentInProgress) throw new Error("A Jetson deployment is already running");
    const connection = jetsonConnection(request?.credentials);
    if (!connection.expectedFingerprint) throw new Error("Confirm the Jetson host key before deployment");
    if (!["application", "initialize"].includes(request?.mode)) throw new Error("Unsupported Jetson deployment mode");
    jetsonDeploymentInProgress = true;
    await saveSettings({ ...settings, jetsonDeploymentStatus: "deploying", jetsonDeploymentError: "" });
    try {
      const result = await deployJetson({
        connection, version: desktopVersion, mode: request.mode,
        model: settings.llmModel, timeoutSeconds: settings.providerTimeoutSeconds,
        callbackHost: settings.desktopAdvertiseHost, callbackPort: settings.platformGtxResultPort,
        payloadPath: bundledJetsonPayload(desktopVersion),
      }, sendJetsonProgress);
      await saveSettings({ ...settings, jetsonDeploymentStatus: "ready", jetsonDeploymentVersion: result.version, jetsonDeploymentError: "" });
      return publicSettings();
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      await saveSettings({ ...settings, jetsonDeploymentStatus: "failed", jetsonDeploymentError: message });
      sendJetsonProgress({ type: "error", message });
      throw error;
    } finally { jetsonDeploymentInProgress = false; }
  });
  ipcMain.handle("desktop:jetson:pull-model", async (_event, request) => {
    if (jetsonDeploymentInProgress) throw new Error("A Jetson deployment or model installation is already running");
    const connection = jetsonConnection(request?.credentials);
    if (!connection.expectedFingerprint) throw new Error("Confirm the Jetson host key before installing a model");
    jetsonDeploymentInProgress = true;
    try {
      const result = await pullJetsonOllamaModel({ connection, model: String(request?.model || "") }, sendJetsonProgress);
      await saveSettings({ ...settings, llmModel: result.model });
      return { settings: publicSettings(), model: result.model };
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      sendJetsonProgress({ type: "error", message });
      throw error;
    } finally { jetsonDeploymentInProgress = false; }
  });
  ipcMain.handle("desktop:data:reset", async (_event, action, confirmation) => resetLocalData(action, confirmation));
  ipcMain.handle("desktop:settings:save", async (_event, value, jetsonPassword) => {
    const prior = settings;
    const passwordPatch = typeof jetsonPassword === "string"
      ? { jetsonSshPasswordEncrypted: encryptedJetsonPassword(jetsonPassword) }
      : {};
    let saved = await saveSettings({ ...settings, ...value, ...passwordPatch });
    const connectionChanged = ["jetsonHost", "jetsonApiPort", "jetsonGtxPort", "desktopAdvertiseHost", "platformGtxResultPort"].some((key) => prior[key] !== saved[key]);
    const hostIdentityChanged = prior.jetsonHost !== saved.jetsonHost || prior.jetsonSshUsername !== saved.jetsonSshUsername;
    const keeptrackChanged = prior.keeptrackApiKey !== saved.keeptrackApiKey;
    if (!saved.jetsonHost || !saved.desktopAdvertiseHost) {
      throw new Error("Jetson 模式需要填写 Jetson 地址和桌面可访问的 LAN 地址");
    }
    if (connectionChanged) {
      saved = await saveSettings({
        ...saved, jetsonDeploymentStatus: "pending", jetsonDeploymentError: "",
        jetsonHostKeyFingerprint: hostIdentityChanged ? "" : saved.jetsonHostKeyFingerprint,
      });
    }
    if (connectionChanged) {
      await stopStack(); await startStack(); await loadCurrentWeb("?jetsonDeployment=1");
    } else if (keeptrackChanged) {
      await stopProcess("ground");
      startService("ground", runtime.ports.ground);
      await waitFor(`http://127.0.0.1:${runtime.ports.ground}/health`, "地面站服务");
    }
    if (prior.cesiumIonToken !== saved.cesiumIonToken) await restartWeb();
    return publicSettings();
  });
  ipcMain.handle("desktop:diagnostics", () => diagnostics());
  ipcMain.handle("desktop:stack:restart", async () => { await stopStack(); await startStack(); await loadCurrentWeb(); return diagnostics(); });
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
  if (!app.isPackaged) {
    mainWindow.webContents.openDevTools({ mode: "detach" });
  }
  // This app is distributed as an unsigned DMG and may be upgraded by
  // replacing the .app bundle while keeping Electron's user-data directory.
  // Next marks hashed chunks immutable, so a cached 404 from an older bundle
  // can otherwise prevent dynamic Cesium chunks from ever loading.
  await mainWindow.webContents.session.clearCache();
  mainWindow.webContents.on("console-message", (_event, details) => {
    appendLog("desktop", `[renderer] ${details.message}\n`);
  });
  mainWindow.webContents.on("did-finish-load", () => {
    void mainWindow.webContents.executeJavaScript(
      "typeof window.satSimDesktop",
    ).then((result) => appendLog("desktop", `[bridge] satSimDesktop=${result}\n`));
  });
  await mainWindow.loadURL("data:text/html;charset=utf-8,<body style='background:%23010810;color:%23bcefff;font-family:-apple-system;padding:36px'>Launching…</body>");
  try {
    await startStack();
    await loadCurrentWeb();
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
