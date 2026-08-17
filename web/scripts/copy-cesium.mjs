import { cp, mkdir, rm } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
// Do not put Cesium in Next's module graph: its minified build can embed its
// WebAssembly payload in a production chunk, which caused invalid octal escape
// syntax in Electron.  The unminified distribution is a browser-ready classic
// script with no bare `@cesium/*` module imports, so it remains fully local.
const source = join(root, "node_modules", "cesium", "Build", "CesiumUnminified");
const destination = join(root, "public", "cesium");

await mkdir(join(root, "public"), { recursive: true });
await rm(destination, { recursive: true, force: true });
await cp(source, destination, { recursive: true });
