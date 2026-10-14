import { fileURLToPath } from "node:url";
import { dirname } from "node:path";

const webRoot = dirname(fileURLToPath(import.meta.url));

// Where the Next.js server reaches the FastAPI api/ surface. Read on the server
// only; the browser calls /backend/* on this origin and Next forwards it.
const apiBaseUrl = (process.env.API_BASE_URL ?? "http://localhost:8000").replace(/\/$/, "");

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Pin the workspace root to web/ so Next never infers the Python repo root
  // as the workspace. Keeps the Node tree self-contained (PAT-013 / INV-010).
  outputFileTracingRoot: webRoot,
  // The operator UI is a local research tool; no telemetry.
  experimental: {},
  async rewrites() {
    return [{ source: "/backend/:path*", destination: `${apiBaseUrl}/:path*` }];
  },
};

export default nextConfig;
