import { describe, it, expect } from "vitest";

// INV-009 / PRH-005: Frontend AGENT_* vars stay server-only — no NEXT_PUBLIC_AGENT*
// var exists; no AGENT_* literal reaches the browser bundle. INV-010 (mostly
// Python/CI-side) gets the natural JS-side assertion: no NEXT_PUBLIC_AGENT in source.
//
// NOTE: the authoritative INV-009 control is the post-`next build` sentinel scan of
// web/.next/static/**/*.js (see web/tests/e2e/inv009-bundle-scan.spec.ts — not run to
// confirm RED). This file covers the source-grep backstop that runs in the Vitest gate.

async function readAllSource(): Promise<{ file: string; text: string }[]> {
  const fs = await import("node:fs/promises");
  const path = await import("node:path");
  const root = path.resolve(__dirname, "../src");
  const out: { file: string; text: string }[] = [];
  async function walk(dir: string) {
    for (const entry of await fs.readdir(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) await walk(full);
      else if (/\.(ts|tsx)$/.test(entry.name)) {
        out.push({ file: full, text: await fs.readFile(full, "utf8") });
      }
    }
  }
  await walk(root);
  return out;
}

describe("INV-009 [integration]: no NEXT_PUBLIC_AGENT* var anywhere in source", () => {
  it("no source file references NEXT_PUBLIC_AGENT", async () => {
    // Tests INV-009 / PRH-005: AGENT_* carry no NEXT_PUBLIC_ prefix.
    const files = await readAllSource();
    for (const { file, text } of files) {
      expect(text, `${file} exposes a NEXT_PUBLIC_AGENT var`).not.toMatch(/NEXT_PUBLIC_AGENT/);
    }
  });

  it("AGENT_* env reads occur only under app/api (server route), never in components", async () => {
    // Tests INV-009: AGENT_* must not be read in client components (would risk bundle leak).
    const files = await readAllSource();
    for (const { file, text } of files) {
      if (file.includes("components")) {
        expect(text, `${file} reads an AGENT_* var in a component`).not.toMatch(
          /process\.env\.AGENT_/,
        );
      }
    }
  });
});

describe("INV-010 [integration]: JS-side env-hygiene assertion", () => {
  it(".env.example documents AGENT_* as server-only (no NEXT_PUBLIC_ prefix)", async () => {
    // Tests INV-010 (JS half): the env template keeps AGENT_* server-only.
    const fs = await import("node:fs/promises");
    const path = await import("node:path");
    const env = await fs.readFile(path.resolve(__dirname, "../.env.example"), "utf8");
    expect(env).not.toMatch(/NEXT_PUBLIC_AGENT/);
    expect(env).toMatch(/AGENT_BASE_URL/);
  });
});

// B2: the authoritative INV-009 control belongs IN the Vitest gate, not only in a
// Playwright spec that the gate never runs. Two checks here:
//  (1) the agent route module is the ONLY place AGENT_* is read; client components
//      (and any module reachable from a client export) read no AGENT_* value.
//  (2) the built bundle is scanned for the sentinel values — and the test FAILS
//      (does not vacuously pass) if there is no evidence a sentinel build was run.
const AGENT_SENTINELS = ["__SENTINEL_BASE__", "__SENTINEL_MODEL__", "__SENTINEL_KEY__"];

describe("INV-009 [integration] (B2): AGENT_* is read only server-side (route module)", () => {
  it("the agent route module imports cleanly and exposes only server handlers (no AGENT_* value on its exports)", async () => {
    // Tests INV-009/PRH-005: importing the route must not surface any AGENT_*
    // literal on its public exports (which could be serialized to the client).
    const mod = await import("@/app/api/agent/route");
    const exportedNames = Object.keys(mod);
    // The route exposes server-only handlers/config, never an AGENT_* value.
    for (const name of exportedNames) {
      expect(name).not.toMatch(/AGENT_/);
      const val = (mod as Record<string, unknown>)[name];
      if (typeof val === "string") {
        for (const s of AGENT_SENTINELS) expect(val).not.toContain(s);
        expect(val).not.toMatch(/__AGENT_BASE__|AGENT_API_KEY/);
      }
    }
    // It exposes the no-store/dynamic config (server route) and a POST handler.
    expect(typeof (mod as { POST?: unknown }).POST).toBe("function");
  });

  it("no client component reads an AGENT_* env var (would risk a bundle leak)", async () => {
    // Tests INV-009: 'use client' modules must not read AGENT_* (only the server
    // route may). The source-grep above is a backstop; this targets client modules.
    const files = await readAllSource();
    for (const { file, text } of files) {
      const isClient = /^\s*["']use client["']/m.test(text);
      const inApiRoute = file.replace(/\\/g, "/").includes("/app/api/");
      if (isClient || (file.includes("components") && !inApiRoute)) {
        expect(text, `${file} reads AGENT_* in a client-reachable module`).not.toMatch(
          /process\.env\.AGENT_/,
        );
      }
    }
  });
});

describe("INV-009 [integration] (B2): built-bundle sentinel scan runs in the gate", () => {
  it("the built client bundle contains no AGENT_* sentinel AND a sentinel build was actually run", async () => {
    // Tests INV-009 authoritative half: scan web/.next/static for the sentinels.
    // This FAILS (does not skip) when there is no evidence a sentinel-injected
    // build ran — a vacuous pass would let a leak ship undetected.
    const fs = await import("node:fs/promises");
    const path = await import("node:path");
    const staticDir = path.resolve(__dirname, "../.next/static");

    const jsFiles: string[] = [];
    async function walk(dir: string): Promise<void> {
      let entries: import("node:fs").Dirent[];
      try {
        entries = await fs.readdir(dir, { withFileTypes: true });
      } catch {
        return;
      }
      for (const e of entries) {
        const full = path.join(dir, e.name);
        if (e.isDirectory()) await walk(full);
        else if (e.name.endsWith(".js")) jsFiles.push(full);
      }
    }
    await walk(staticDir);

    // Evidence requirement: a sentinel build must have produced bundle output, and
    // a sentinel-evidence marker file must record the build used the sentinel env.
    let evidence = "";
    try {
      evidence = await fs.readFile(
        path.resolve(__dirname, "../.next/SENTINEL_BUILD"),
        "utf8",
      );
    } catch {
      evidence = "";
    }
    expect(
      jsFiles.length > 0 && evidence.includes("SENTINEL_BUILD_OK"),
      "no evidence of a sentinel-injected `next build` — run the build with " +
        "AGENT_BASE_URL/AGENT_MODEL/AGENT_API_KEY set to the sentinel values and " +
        "write web/.next/SENTINEL_BUILD with SENTINEL_BUILD_OK before this gate.",
    ).toBe(true);

    for (const f of jsFiles) {
      const text = await fs.readFile(f, "utf8");
      for (const s of AGENT_SENTINELS) {
        expect(text, `${f} leaks AGENT_* sentinel ${s}`).not.toContain(s);
      }
    }
  });
});
