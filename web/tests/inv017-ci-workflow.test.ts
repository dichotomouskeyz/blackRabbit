import { describe, it, expect } from "vitest";
import { promises as fs } from "node:fs";
import { resolve } from "node:path";

// QA-009 — strengthen INV-017: the "gate is wired and required-green" claim must be
// enforced against the ACTUAL CI workflow YAML, not just workflow-config keys (which
// a post-merge revert of the branch-scoped commands.test swap can disable). Assert
// .github/workflows/ci.yml has a job that runs pnpm install + lint + test + build
// for web/, so an un-wiring of the frontend gate fails this meta-test.

const CI_PATH = resolve(__dirname, "../../.github/workflows/ci.yml");

async function ciText(): Promise<string> {
  return fs.readFile(CI_PATH, "utf8");
}

describe("QA-009 [integration]: CI workflow runs the web/ gate (install+lint+test+build)", () => {
  it("ci.yml defines a frontend job scoped to web/", async () => {
    const yml = await ciText();
    // A job with working-directory web (PAT-013 foreign-toolchain subtree).
    expect(yml).toMatch(/working-directory:\s*web/);
  });

  it("the frontend job invokes pnpm install, lint, test, and build for web/", async () => {
    const yml = await ciText();
    // install (frozen lockfile), lint, test, build — each present as a run step.
    expect(yml, "pnpm install missing").toMatch(/corepack pnpm@?[\d.]*\s+install/);
    expect(yml, "pnpm lint missing").toMatch(/corepack pnpm@?[\d.]*\s+lint/);
    expect(yml, "pnpm test missing").toMatch(/corepack pnpm@?[\d.]*\s+test\b/);
    expect(yml, "pnpm build missing").toMatch(/corepack pnpm@?[\d.]*\s+build/);
  });

  it("the frontend gate is on the PR-required path (pull_request trigger present)", async () => {
    const yml = await ciText();
    // The workflow runs on pull_request → it is a required-green gate before merge.
    expect(yml).toMatch(/pull_request/);
  });
});
