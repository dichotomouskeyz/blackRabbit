import { test, expect } from "@playwright/test";
import { promises as fs } from "node:fs";
import { join, resolve } from "node:path";

// INV-009 / PRH-005 (authoritative half): after `next build`, the literal sentinel
// values of AGENT_* set at build time must NOT appear in web/.next/static/**/*.js.
//
// This is a build-artifact scan, NOT a browser flow — but it belongs to the full
// build path so it lives under tests/e2e/ (Playwright command). It is NOT run to
// confirm RED (per the task); it fails today because the build step + sentinels are
// not yet wired. Run with: corepack pnpm@9.15.9 -C web test:e2e
//
// The build must be invoked with these sentinel env values for the scan to be valid:
//   AGENT_BASE_URL=http://127.0.0.1:65111/__SENTINEL_BASE__
//   AGENT_MODEL=__SENTINEL_MODEL__
//   AGENT_API_KEY=__SENTINEL_KEY__
const SENTINELS = ["__SENTINEL_BASE__", "__SENTINEL_MODEL__", "__SENTINEL_KEY__"];

async function jsFiles(dir: string): Promise<string[]> {
  const out: string[] = [];
  let entries: import("node:fs").Dirent[];
  try {
    entries = await fs.readdir(dir, { withFileTypes: true });
  } catch {
    return out; // .next/static not built yet → handled by the assertion below
  }
  for (const e of entries) {
    const full = join(dir, e.name);
    if (e.isDirectory()) out.push(...(await jsFiles(full)));
    else if (e.name.endsWith(".js")) out.push(full);
  }
  return out;
}

test("INV-009 [integration]: no AGENT_* sentinel value appears in the built client bundle", async () => {
  const staticDir = resolve(__dirname, "../../.next/static");
  const files = await jsFiles(staticDir);
  // The scan requires a built bundle; the GREEN phase wires the sentinel-injected build.
  expect(files.length, "no built bundle found — wire `next build` with sentinel env").toBeGreaterThan(0);
  for (const f of files) {
    const text = await fs.readFile(f, "utf8");
    for (const sentinel of SENTINELS) {
      expect(text, `${f} leaks AGENT_* sentinel ${sentinel}`).not.toContain(sentinel);
    }
  }
});
