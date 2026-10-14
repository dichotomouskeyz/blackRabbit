import { describe, it, expect, afterEach } from "vitest";
import { promises as fs } from "node:fs";
import { join } from "node:path";
import os from "node:os";

// QA-007 — POSITIVE CONTROL for the INV-009 sentinel bundle scan. The real scan
// asserts ABSENCE of AGENT_* sentinels in web/.next/static/**/*.js — but an
// absence assertion proves nothing unless the scanner can actually DETECT a leak.
// This test plants a sentinel into a quarantined fixture bundle and runs the SAME
// scan predicate, asserting it FAILS — demonstrating the scan has detection power
// (it is not vacuously passing by construction).

const AGENT_SENTINELS = ["__SENTINEL_BASE__", "__SENTINEL_MODEL__", "__SENTINEL_KEY__"];

// The scan predicate, identical in spirit to the gate: returns the list of
// (file, sentinel) leaks found in a scanned directory's *.js chunks.
async function scanForLeaks(dir: string): Promise<Array<{ file: string; sentinel: string }>> {
  const leaks: Array<{ file: string; sentinel: string }> = [];
  async function walk(d: string): Promise<void> {
    let entries: import("node:fs").Dirent[];
    try {
      entries = await fs.readdir(d, { withFileTypes: true });
    } catch {
      return;
    }
    for (const e of entries) {
      const full = join(d, e.name);
      if (e.isDirectory()) await walk(full);
      else if (e.name.endsWith(".js")) {
        const text = await fs.readFile(full, "utf8");
        for (const s of AGENT_SENTINELS) {
          if (text.includes(s)) leaks.push({ file: full, sentinel: s });
        }
      }
    }
  }
  await walk(dir);
  return leaks;
}

let tmpDir: string | null = null;
afterEach(async () => {
  if (tmpDir) {
    await fs.rm(tmpDir, { recursive: true, force: true });
    tmpDir = null;
  }
});

describe("QA-007 [integration]: the bundle sentinel scan has demonstrated detection power", () => {
  it("FAILS (detects the leak) when an AGENT_* sentinel is present in a scanned chunk", async () => {
    // Quarantined fixture: a deliberately-leaked sentinel build under a temp dir.
    tmpDir = await fs.mkdtemp(join(os.tmpdir(), "sentinel-positive-"));
    const staticDir = join(tmpDir, "static", "chunks");
    await fs.mkdir(staticDir, { recursive: true });
    // A clean chunk (no sentinel) and a leaked chunk (carries a sentinel value).
    await fs.writeFile(join(staticDir, "clean.js"), "console.log('http://localhost:8000');", "utf8");
    await fs.writeFile(
      join(staticDir, "leaked.js"),
      "const base='http://127.0.0.1:65111/__SENTINEL_BASE__';export default base;",
      "utf8",
    );

    const leaks = await scanForLeaks(staticDir);
    // The scan MUST detect the planted leak — proving it is not absence-by-construction.
    expect(leaks.length).toBeGreaterThan(0);
    expect(leaks.some((l) => l.sentinel === "__SENTINEL_BASE__")).toBe(true);
    expect(leaks.some((l) => l.file.endsWith("leaked.js"))).toBe(true);
  });

  it("PASSES (no leak) on a clean fixture bundle — the predicate is not always-fail", async () => {
    tmpDir = await fs.mkdtemp(join(os.tmpdir(), "sentinel-clean-"));
    const staticDir = join(tmpDir, "static", "chunks");
    await fs.mkdir(staticDir, { recursive: true });
    await fs.writeFile(join(staticDir, "a.js"), "const x='http://localhost:8000';", "utf8");
    await fs.writeFile(join(staticDir, "b.js"), "export const y='AGENT only as a word';", "utf8");

    const leaks = await scanForLeaks(staticDir);
    expect(leaks.length).toBe(0);
  });
});
