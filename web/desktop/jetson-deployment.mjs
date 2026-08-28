import { createHash } from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import { Client } from "ssh2";

const MIN_FREE_BYTES = 10 * 1024 * 1024 * 1024;
const SAFE_FILE = /^[A-Za-z0-9._-]+$/;

function fingerprint(key) {
  return `SHA256:${createHash("sha256").update(key).digest("base64")}`;
}

function redact(text, secrets = []) {
  let result = String(text);
  for (const secret of secrets.filter(Boolean)) result = result.replaceAll(secret, "[REDACTED]");
  return result;
}

function connect({ host, username, password, expectedFingerprint, discover = false }) {
  return new Promise((resolve, reject) => {
    const client = new Client();
    let presented;
    client.once("ready", () => resolve({ client, fingerprint: presented }));
    client.once("error", (error) => {
      if (discover && presented) {
        error.code = "HOST_KEY_DISCOVERED";
        error.fingerprint = presented;
      }
      reject(error);
    });
    client.connect({
      host, port: 22, username, password, readyTimeout: 15_000,
      hostVerifier: (key) => {
        presented = fingerprint(key);
        return discover ? false : presented === expectedFingerprint;
      },
    });
  });
}

function execute(client, command, { onLog, password } = {}) {
  return new Promise((resolve, reject) => {
    client.exec(command, (error, channel) => {
      if (error) return reject(error);
      let output = "";
      const handle = (chunk) => { output += chunk.toString(); onLog?.(chunk.toString()); };
      channel.on("data", handle);
      channel.stderr.on("data", handle);
      channel.on("close", (code) => code === 0 ? resolve(output) : reject(new Error(`Remote command failed with exit code ${code}`)));
      if (password) channel.write(`${password}\n`);
    });
  });
}

function upload(client, localPath, remotePath, onLog) {
  return new Promise((resolve, reject) => client.sftp((error, sftp) => {
    if (error) return reject(error);
    sftp.fastPut(localPath, remotePath, (putError) => {
      sftp.end();
      if (putError) reject(putError); else { onLog?.(`Uploaded ${path.basename(localPath)}\n`); resolve(); }
    });
  }));
}

async function readPayload(payloadPath, version) {
  const bundle = path.resolve(payloadPath);
  const metadataPath = path.join(bundle, "payload.json");
  const checksumsPath = path.join(bundle, "SHA256SUMS");
  const metadata = JSON.parse(await fs.readFile(metadataPath, "utf8"));
  if (metadata.version !== version || metadata.architecture !== "linux/arm64") throw new Error("Bundled Jetson payload does not match this desktop version");
  const checksumLines = (await fs.readFile(checksumsPath, "utf8")).trim().split(/\r?\n/);
  const files = [];
  for (const line of checksumLines) {
    const match = line.match(/^([a-f0-9]{64})\s+\*?\.\/(.+)$/i);
    if (!match || !SAFE_FILE.test(match[2])) throw new Error("Bundled Jetson payload has an invalid checksum entry");
    const localPath = path.join(bundle, match[2]);
    if (!localPath.startsWith(`${bundle}${path.sep}`)) throw new Error("Bundled Jetson payload contains an unsafe path");
    const contents = await fs.readFile(localPath);
    if (createHash("sha256").update(contents).digest("hex") !== match[1].toLowerCase()) throw new Error(`Bundled Jetson payload checksum mismatch: ${match[2]}`);
    files.push({ name: match[2], localPath });
  }
  const archiveName = `spacezenith-sim-${version}-linux-arm64.tar`;
  const required = [archiveName, "docker-compose.yml", "spacezenith-gpu.env", "healthcheck.sh", "import-run.sh", "payload.json"];
  if (!required.every((name) => files.some((file) => file.name === name))) throw new Error("Bundled Jetson payload is incomplete");
  return { files, archiveName };
}

export async function discoverJetsonHostKey(connection) {
  try {
    await connect({ ...connection, discover: true });
  } catch (error) {
    if (error.code === "HOST_KEY_DISCOVERED") return error.fingerprint;
    throw error;
  }
  throw new Error("Jetson host key discovery unexpectedly completed");
}

export async function preflightJetson(connection, onLog) {
  const { client, fingerprint: remoteFingerprint } = await connect(connection);
  try {
    const output = await execute(client, "uname -m; df -Pk / | awk 'NR==2 {print $4 * 1024}'; command -v docker || true; sudo -S -p '' -v >/dev/null 2>&1 && sudo docker compose version >/dev/null 2>&1 && echo compose || true; command -v ollama || true", { onLog, password: connection.password });
    const [architecture, bytesText, docker, compose, ollama] = output.trim().split(/\r?\n/);
    return {
      fingerprint: remoteFingerprint, architecture, freeBytes: Number(bytesText),
      docker: Boolean(docker), compose: Boolean(compose), ollama: Boolean(ollama),
      readyForApplicationDeploy: architecture === "aarch64" && Number(bytesText) >= MIN_FREE_BYTES && Boolean(docker && compose && ollama),
    };
  } finally { client.end(); }
}

async function restorePreviousRelease(client, previousRelease, onLog) {
  if (!previousRelease || !previousRelease.startsWith("/opt/spacezenith-sim/releases/")) return false;
  await execute(client, `cd '${previousRelease}' && sudo docker compose --env-file spacezenith-gpu.env up -d --force-recreate && ln -sfn '${previousRelease}' /opt/spacezenith-sim/current`, { onLog });
  return true;
}

export async function deployJetson({ connection, version, mode, model, timeoutSeconds, callbackHost, callbackPort, payloadPath }, onEvent) {
  const log = (message) => onEvent({ type: "log", message: redact(message, [connection.password]) });
  const stage = (name) => onEvent({ type: "stage", name });
  if (!/^[A-Za-z0-9._-]+$/.test(String(version))) throw new Error("Jetson release version is invalid");
  if (!/^[a-zA-Z0-9.-]+$/.test(String(callbackHost)) || !Number.isInteger(Number(callbackPort))) throw new Error("Invalid desktop callback address");
  const safeModel = String(model).replace(/[^a-zA-Z0-9:._-]/g, "");
  const safeTimeout = Math.max(1, Math.min(600, Number(timeoutSeconds) || 120));
  stage("prepare-payload");
  const payload = await readPayload(payloadPath, version);
  const releasePath = `/opt/spacezenith-sim/releases/${version}`;

  stage("connect");
  const { client } = await connect(connection);
  let previousRelease = "";
  let activationStarted = false;
  try {
    stage("preflight");
    let report = await preflightJetson(connection, log);
    if (mode === "application" && !report.readyForApplicationDeploy) throw new Error("Jetson preflight failed: Docker, Compose, Ollama, aarch64, and 10 GiB free disk are required");
    if (mode === "initialize") {
      stage("initialize");
      await execute(client, "sudo -S apt-get update && sudo -S apt-get install -y docker.io docker-compose-plugin curl && sudo -S usermod -aG docker $USER && (command -v ollama >/dev/null || curl -fsSL https://ollama.com/install.sh | sh)", { onLog: log, password: connection.password });
      report = await preflightJetson(connection, log);
      if (!report.readyForApplicationDeploy) throw new Error("Jetson initialization completed but Docker, Compose, Ollama, aarch64, or free disk requirements are still unmet");
    }
    previousRelease = (await execute(client, "readlink -f /opt/spacezenith-sim/current 2>/dev/null || true", { onLog: log })).trim();
    stage("upload");
    await execute(client, `sudo -S -p '' -v && sudo install -d -m 0755 '${releasePath}' /var/lib/spacezenith-sim && sudo chown -R "$(id -un):$(id -gn)" /opt/spacezenith-sim`, { onLog: log, password: connection.password });
    for (const file of payload.files) await upload(client, file.localPath, `${releasePath}/${file.name}`, log);
    await upload(client, path.join(path.resolve(payloadPath), "SHA256SUMS"), `${releasePath}/SHA256SUMS`, log);
    stage("verify");
    await execute(client, `cd '${releasePath}' && sha256sum -c SHA256SUMS`, { onLog: log });
    await execute(client, `sed -i 's|^SAT_SIM_LLM_MODEL=.*$|SAT_SIM_LLM_MODEL=${safeModel}|' '${releasePath}/spacezenith-gpu.env' && sed -i 's|^SAT_SIM_PROVIDER_TIMEOUT_SECONDS=.*$|SAT_SIM_PROVIDER_TIMEOUT_SECONDS=${safeTimeout}|' '${releasePath}/spacezenith-gpu.env'`, { onLog: log });
    stage("import");
    await execute(client, `sudo docker load -i '${releasePath}/${payload.archiveName}'`, { onLog: log });
    stage("start");
    activationStarted = true;
    await execute(client, "sudo docker rm -f spacezenith-gpu-api >/dev/null 2>&1 || true", { onLog: log });
    await execute(client, `cd '${releasePath}' && sudo docker compose --env-file spacezenith-gpu.env up -d --force-recreate`, { onLog: log });
    if (safeModel) {
      stage("model");
      await execute(client, `ollama show '${safeModel}' >/dev/null 2>&1 || ollama pull '${safeModel}'`, { onLog: log });
    }
    stage("verify");
    await execute(client, "for i in $(seq 1 30); do sudo docker exec spacezenith-gpu-api python -c \"from urllib.request import urlopen; urlopen('http://127.0.0.1:8002/health', timeout=2)\" >/dev/null 2>&1 && exit 0; sleep 1; done; exit 1", { onLog: log });
    await execute(client, `python3 -c 'import socket; socket.create_connection(("${callbackHost}", ${Number(callbackPort)}), 5).close(); print("GTX callback TCP OK")'`, { onLog: log });
    await execute(client, `ln -sfn '${releasePath}' /opt/spacezenith-sim/current`, { onLog: log });
    stage("complete");
    return { version, fingerprint: connection.expectedFingerprint };
  } catch (error) {
    if (activationStarted) {
      try {
        stage("rollback");
        if (await restorePreviousRelease(client, previousRelease, log)) log("Restored the previous Jetson release after deployment failure.\n");
      } catch (rollbackError) {
        log(`Jetson rollback failed: ${rollbackError instanceof Error ? rollbackError.message : String(rollbackError)}\n`);
      }
    }
    throw error;
  } finally { client.end(); }
}
