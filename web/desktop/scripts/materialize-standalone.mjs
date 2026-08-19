import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const webDirectory = path.resolve(scriptDirectory, "../..");
const modulesDirectory = path.join(webDirectory, ".next", "standalone", "node_modules");
const pnpmStoreDirectory = path.join(modulesDirectory, ".pnpm");

async function packageDirectories(nodeModulesDirectory) {
  const entries = await fs.readdir(nodeModulesDirectory, { withFileTypes: true });
  const packages = [];
  for (const entry of entries) {
    if (entry.name === ".pnpm") continue;
    const entryPath = path.join(nodeModulesDirectory, entry.name);
    if (entry.name.startsWith("@")) {
      const scopedEntries = await fs.readdir(entryPath, { withFileTypes: true });
      for (const scopedEntry of scopedEntries) {
        if (scopedEntry.isDirectory() || scopedEntry.isSymbolicLink()) {
          packages.push({ name: path.join(entry.name, scopedEntry.name), source: path.join(entryPath, scopedEntry.name) });
        }
      }
    } else if (entry.isDirectory() || entry.isSymbolicLink()) {
      packages.push({ name: entry.name, source: entryPath });
    }
  }
  return packages;
}

/**
 * Next's file tracing retains pnpm's virtual store but can omit the module
 * links that make the store resolvable.  That produces a standalone server
 * which is structurally complete yet cannot resolve Next's own dependencies
 * after electron-builder copies it to Windows resources.  Materialize every
 * package already traced into the standalone store as a normal module folder.
 * No package names are hand-maintained here; the build output is authoritative.
 */
async function main() {
  let storeEntries;
  try {
    storeEntries = await fs.readdir(pnpmStoreDirectory, { withFileTypes: true });
  } catch (error) {
    if (error?.code === "ENOENT") {
      throw new Error(`Next standalone output was not found at ${modulesDirectory}. Run next build first.`);
    }
    throw error;
  }

  const packages = new Map();
  for (const storeEntry of storeEntries) {
    if (!storeEntry.isDirectory()) continue;
    const nestedModules = path.join(pnpmStoreDirectory, storeEntry.name, "node_modules");
    try {
      for (const candidate of await packageDirectories(nestedModules)) {
        packages.set(candidate.name, candidate.source);
      }
    } catch (error) {
      if (error?.code !== "ENOENT") throw error;
    }
  }

  if (packages.size === 0) throw new Error("Next standalone output contains no pnpm runtime packages.");

  for (const [name, source] of packages) {
    const destination = path.join(modulesDirectory, name);
    await fs.rm(destination, { recursive: true, force: true });
    await fs.mkdir(path.dirname(destination), { recursive: true });
    await fs.cp(source, destination, { recursive: true, dereference: true });
  }
  console.log(`Materialized ${packages.size} standalone runtime packages.`);
}

await main();
