// INV-009 / PRH-005 sentinel build (frontend-shell audit B2).
//
// Runs `next build` with the AGENT_* env set to known sentinel literals, then
// writes web/.next/SENTINEL_BUILD with SENTINEL_BUILD_OK as evidence the
// sentinel-injected build ran. The Vitest gate (tests/inv009-010-env-bundle.ts)
// and the Playwright spec (tests/e2e/inv009-bundle-scan.spec.ts) then scan
// web/.next/static/**/*.js to prove NONE of the sentinels leaked into the client
// bundle — AGENT_* are server-route-only and must never reach the browser.
//
// If the bundle were to leak any AGENT_* value, the sentinel literal would appear
// in a static chunk and the scan would fail. By using sentinels (not the real
// values) the scan is deterministic and self-evidencing.

import { spawnSync } from "node:child_process";
import { mkdirSync, writeFileSync, readdirSync, statSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join, resolve } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const webRoot = resolve(__dirname, "..");

// The exact sentinel values the gate scans for (must match the test constants).
const sentinelEnv = {
  ...process.env,
  AGENT_BASE_URL: "http://127.0.0.1:65111/__SENTINEL_BASE__",
  AGENT_MODEL: "__SENTINEL_MODEL__",
  AGENT_API_KEY: "__SENTINEL_KEY__", // pragma: allowlist secret (test sentinel, not a key)
  // Keep the client API URL benign; it is allowed in the bundle.
  NEXT_PUBLIC_API_URL: "http://localhost:8000",
};

// Newest mtime among build inputs (source + build config). Used to skip the
// (expensive) `next build` when an existing sentinel bundle is already current —
// this script runs as a `pretest` hook before every Vitest run, so an
// unconditional build would dominate the gate's runtime.
function newestMtime(dir, exts) {
  let newest = 0;
  let entries;
  try {
    entries = readdirSync(dir, { withFileTypes: true });
  } catch {
    return newest;
  }
  for (const ent of entries) {
    const full = join(dir, ent.name);
    if (ent.isDirectory()) {
      newest = Math.max(newest, newestMtime(full, exts));
    } else if (exts.some((e) => ent.name.endsWith(e))) {
      newest = Math.max(newest, statSync(full).mtimeMs);
    }
  }
  return newest;
}

const evidencePath = join(webRoot, ".next", "SENTINEL_BUILD");
const staticDir = join(webRoot, ".next", "static");

function bundleIsCurrent() {
  if (!existsSync(evidencePath) || !existsSync(staticDir)) return false;
  const builtAt = statSync(evidencePath).mtimeMs;
  const srcNewest = Math.max(
    newestMtime(join(webRoot, "src"), [".ts", ".tsx", ".css"]),
    newestMtime(join(webRoot, "scripts"), [".mjs"]),
  );
  let configNewest = 0;
  for (const f of ["next.config.mjs", "package.json", "tsconfig.json"]) {
    const p = join(webRoot, f);
    if (existsSync(p)) configNewest = Math.max(configNewest, statSync(p).mtimeMs);
  }
  return builtAt >= Math.max(srcNewest, configNewest);
}

if (bundleIsCurrent()) {
  console.log("[sentinel-build] existing sentinel bundle is current — skipping next build");
} else {
  const result = spawnSync("npx", ["next", "build"], {
    cwd: webRoot,
    env: sentinelEnv,
    stdio: "inherit",
    shell: process.platform === "win32",
  });
  if (result.status !== 0) {
    console.error(`[sentinel-build] next build failed with code ${result.status}`);
    process.exit(result.status ?? 1);
  }
}

// Confirm the static bundle exists before writing evidence — a vacuous pass would
// let a leak ship undetected.
let jsCount = 0;
function walk(dir) {
  let entries;
  try {
    entries = readdirSync(dir, { withFileTypes: true });
  } catch {
    return;
  }
  for (const ent of entries) {
    if (ent.isDirectory()) walk(join(dir, ent.name));
    else if (ent.name.endsWith(".js")) jsCount += 1;
  }
}
walk(staticDir);

if (jsCount === 0) {
  console.error("[sentinel-build] no built JS bundle found under .next/static");
  process.exit(1);
}

mkdirSync(dirname(evidencePath), { recursive: true });
writeFileSync(
  evidencePath,
  `SENTINEL_BUILD_OK\nbuilt ${jsCount} static JS chunks at ${new Date().toISOString()}\n`,
  "utf8",
);
console.log(`[sentinel-build] SENTINEL_BUILD_OK written (${jsCount} JS chunks scanned by the gate)`);
