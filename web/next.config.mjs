/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  env: { NEXT_PUBLIC_CESIUM_BASE_URL: "/cesium/" }
};

export default nextConfig;

