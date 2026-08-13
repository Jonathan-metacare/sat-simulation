import fs from "node:fs";
import path from "node:path";

function rootEnvValue(name) {
  const rootEnvPath = path.resolve(process.cwd(), "../.env");
  if (!fs.existsSync(rootEnvPath)) return undefined;
  const match = fs.readFileSync(rootEnvPath, "utf8").match(new RegExp(`^${name}=(.*)$`, "m"));
  return match?.[1]?.trim().replace(/^['\"]|['\"]$/g, "") || undefined;
}

// The backend's root .env is the standard local configuration file for this
// repository. Next only loads env files under web/, so pass this public token
// through explicitly when the dashboard is started from web/ or Electron.
const cesiumIonToken = process.env.NEXT_PUBLIC_CESIUM_ION_ACCESS_TOKEN
  ?? rootEnvValue("NEXT_PUBLIC_CESIUM_ION_ACCESS_TOKEN");

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  // Keep development and production artifacts separate. Running `next build`
  // while the local dashboard is open must not invalidate the dev server's
  // module manifest.
  distDir: process.env.NODE_ENV === "development" ? ".next-dev" : ".next",
  env: {
    NEXT_PUBLIC_CESIUM_BASE_URL: "/cesium/",
    ...(cesiumIonToken ? { NEXT_PUBLIC_CESIUM_ION_ACCESS_TOKEN: cesiumIonToken } : {}),
  }
};

export default nextConfig;
