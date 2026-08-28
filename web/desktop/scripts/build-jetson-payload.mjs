import { createHash } from "node:crypto";
import { cp, mkdir, readFile, rm } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const webDirectory = path.resolve(scriptDirectory, "..", "..");
const projectDirectory = path.resolve(webDirectory, "..");
const packageJson = JSON.parse(await readFile(path.join(webDirectory, "package.json"), "utf8"));
const version = packageJson.version;
const pyproject = await readFile(path.join(projectDirectory, "pyproject.toml"), "utf8");
const runtimeVersionSource = await readFile(
  path.join(projectDirectory, "sat_simulation", "__init__.py"),
  "utf8",
);
const pythonVersion = pyproject.match(/^version\s*=\s*"([^"]+)"/m)?.[1];
const runtimeVersion = runtimeVersionSource.match(/^__version__\s*=\s*"([^"]+)"/m)?.[1];

if (pythonVersion !== version) throw new Error(`Desktop version ${version} does not match Python version ${pythonVersion ?? "<missing>"}`);
if (runtimeVersion !== version) {
  throw new Error(
    `Desktop version ${version} does not match Python runtime version ${runtimeVersion ?? "<missing>"}`,
  );
}

const bundleDirectory = path.join(projectDirectory, "release", `jetson-${version}-linux-arm64`);
const result = spawnSync("bash", [path.join(projectDirectory, "deploy", "jetson", "build-export.sh"), version, bundleDirectory], {
  cwd: projectDirectory,
  stdio: "inherit",
});
if (result.status !== 0) process.exit(result.status ?? 1);

const metadata = JSON.parse(await readFile(path.join(bundleDirectory, "payload.json"), "utf8"));
if (metadata.version !== version || metadata.architecture !== "linux/arm64") throw new Error("Jetson payload metadata does not match the desktop build");

const checksumLines = (await readFile(path.join(bundleDirectory, "SHA256SUMS"), "utf8")).trim().split(/\r?\n/);
if (checksumLines.length < 6) throw new Error("Jetson payload checksum manifest is incomplete");
for (const line of checksumLines) {
  const match = line.match(/^([a-f0-9]{64})\s+\*?\.\/(.+)$/i);
  if (!match || !/^[A-Za-z0-9._-]+$/.test(match[2])) throw new Error(`Invalid Jetson payload checksum entry: ${line}`);
  const contents = await readFile(path.join(bundleDirectory, match[2]));
  const digest = createHash("sha256").update(contents).digest("hex");
  if (digest !== match[1].toLowerCase()) throw new Error(`Jetson payload checksum mismatch: ${match[2]}`);
}

const stagedPayload = path.join(webDirectory, "desktop", "build", "jetson-payload");
await rm(stagedPayload, { recursive: true, force: true });
await mkdir(path.dirname(stagedPayload), { recursive: true });
await cp(bundleDirectory, stagedPayload, { recursive: true });
console.log(`Staged verified Jetson payload ${version} at ${stagedPayload}`);
