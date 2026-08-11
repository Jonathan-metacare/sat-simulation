import { cp, mkdir, rm } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const source = join(root, "node_modules", "cesium", "Build", "Cesium");
const destination = join(root, "public", "cesium");

await mkdir(join(root, "public"), { recursive: true });
await rm(destination, { recursive: true, force: true });
await cp(source, destination, { recursive: true });

