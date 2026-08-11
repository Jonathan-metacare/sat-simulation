/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  // Keep development and production artifacts separate. Running `next build`
  // while the local dashboard is open must not invalidate the dev server's
  // module manifest.
  distDir: process.env.NODE_ENV === "development" ? ".next-dev" : ".next",
  env: { NEXT_PUBLIC_CESIUM_BASE_URL: "/cesium/" }
};

export default nextConfig;
