import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";
import fs from "node:fs";

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const webDirectory = path.resolve(scriptDirectory, "../..");
const projectDirectory = path.resolve(webDirectory, "..");
const outputDirectory = path.join(webDirectory, "desktop", "python-dist");
const workDirectory = path.join(webDirectory, "desktop", ".pyinstaller-work");

fs.mkdirSync(outputDirectory, { recursive: true });
const result = spawnSync(
  "uv",
  [
    // A one-file build unpacks the geospatial runtime on every service launch.
    // On macOS that can exceed the desktop health-check timeout, so ship the
    // PyInstaller directory build as an Electron resource instead.
    "run", "pyinstaller", "--noconfirm", "--clean", "--windowed",
    "--name", "sat-sim-service", "--distpath", outputDirectory,
    "--workpath", workDirectory, "--specpath", workDirectory,
    "--collect-all", "rasterio", "--collect-all", "cv2", "--collect-all", "pyproj",
    "--collect-all", "sgp4", "--collect-all", "sqlalchemy",
    // SQLAlchemy loads the selected async dialect at runtime.  Include the
    // desktop default explicitly so a frozen Ground service can open SQLite.
    "--collect-all", "aiosqlite",
    // The three applications are selected from a command-line argument, so
    // keep their conditional imports explicit in the frozen executable.
    "--hidden-import", "sat_simulation.services.ground",
    "--hidden-import", "sat_simulation.services.platform",
    "--hidden-import", "sat_simulation.services.gpu",
    path.join(projectDirectory, "desktop", "python_service.py"),
  ],
  { cwd: projectDirectory, stdio: "inherit" },
);
if (result.status !== 0) process.exit(result.status ?? 1);

// A frozen macOS helper is also an application bundle.  Mark it as an agent
// app so the three local simulation helpers do not get their own Dock icon.
const infoPlist = path.join(outputDirectory, "sat-sim-service.app", "Contents", "Info.plist");
const plistResult = spawnSync("plutil", ["-replace", "LSUIElement", "-bool", "true", infoPlist], {
  cwd: projectDirectory,
  stdio: "inherit",
});
if (plistResult.status !== 0) process.exit(plistResult.status ?? 1);
const backgroundResult = spawnSync("plutil", ["-replace", "LSBackgroundOnly", "-bool", "true", infoPlist], {
  cwd: projectDirectory,
  stdio: "inherit",
});
if (backgroundResult.status !== 0) process.exit(backgroundResult.status ?? 1);
