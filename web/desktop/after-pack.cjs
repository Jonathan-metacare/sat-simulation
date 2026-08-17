const fs = require("node:fs/promises");
const path = require("node:path");

/**
 * Next's standalone output contains a self-contained pnpm node_modules tree.
 * electron-builder intentionally omits node_modules below an extraResources
 * source, so copy it after the application bundle has been assembled.  This
 * hook also selects the native PyInstaller runtime built for the target OS.
 */
exports.default = async function afterPack(context) {
  const source = path.join(context.packager.projectDir, ".next", "standalone", "node_modules");
  const resources = context.electronPlatformName === "darwin"
    ? path.join(context.appOutDir, `${context.packager.appInfo.productFilename}.app`, "Contents", "Resources")
    : path.join(context.appOutDir, "resources");
  const destination = path.join(resources, "web", "node_modules");

  await fs.rm(destination, { recursive: true, force: true });
  await fs.cp(source, destination, {
    recursive: true,
    // Standalone's pnpm links are relative to its node_modules root.
    verbatimSymlinks: true,
  });

  const isMac = context.electronPlatformName === "darwin";
  const runtimeSource = path.join(
    context.packager.projectDir,
    "desktop",
    "python-dist",
    isMac ? "darwin" : "win32",
    isMac ? "sat-sim-service.app" : "sat-sim-service",
  );
  const runtimeDestination = path.join(
    resources,
    "python",
    isMac ? "sat-sim-service.app" : "sat-sim-service",
  );
  try {
    await fs.access(runtimeSource);
  } catch {
    throw new Error(`Missing ${isMac ? "macOS" : "Windows"} Python runtime: ${runtimeSource}. Run the matching desktop:python command first.`);
  }
  await fs.rm(runtimeDestination, { recursive: true, force: true });
  await fs.mkdir(path.dirname(runtimeDestination), { recursive: true });
  await fs.cp(runtimeSource, runtimeDestination, { recursive: true, verbatimSymlinks: true });
};
