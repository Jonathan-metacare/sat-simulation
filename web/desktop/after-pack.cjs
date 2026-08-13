const fs = require("node:fs/promises");
const path = require("node:path");

/**
 * Next's standalone output contains a self-contained pnpm node_modules tree.
 * electron-builder intentionally omits node_modules below an extraResources
 * source, so copy it after the application bundle has been assembled.
 */
exports.default = async function afterPack(context) {
  if (context.electronPlatformName !== "darwin") return;

  const source = path.join(context.packager.projectDir, ".next", "standalone", "node_modules");
  const application = path.join(
    context.appOutDir,
    `${context.packager.appInfo.productFilename}.app`,
  );
  const destination = path.join(application, "Contents", "Resources", "web", "node_modules");

  await fs.rm(destination, { recursive: true, force: true });
  await fs.cp(source, destination, {
    recursive: true,
    // Standalone's pnpm links are relative to its node_modules root.
    verbatimSymlinks: true,
  });
};
