import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Static export so FastAPI can serve the ops UI from the same Coolify PORT.
  output: "export",
  images: { unoptimized: true },
  trailingSlash: true,
};

export default nextConfig;
