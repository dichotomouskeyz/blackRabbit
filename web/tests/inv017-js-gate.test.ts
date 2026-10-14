import { describe, it, expect } from "vitest";

// INV-017: The frontend test gate is wired and required-green. A JS lane is
// registered in .correctless/config/workflow-config.json (non-empty build/JS test
// command). Test approach: integration (meta-test over the config).

describe("INV-017 [integration]: JS lane registered in workflow-config", () => {
  it("workflow-config commands include a pnpm-based frontend test + build + lint", async () => {
    // Tests INV-017: the JS lane is the frontend gate of record.
    const fs = await import("node:fs/promises");
    const path = await import("node:path");
    const cfgPath = path.resolve(__dirname, "../../.correctless/config/workflow-config.json");
    const cfg = JSON.parse(await fs.readFile(cfgPath, "utf8"));

    expect(cfg.commands.build, "build command must be non-empty").toMatch(/pnpm.*-C web build/);
    expect(cfg.commands.test_frontend ?? cfg.commands.test).toMatch(/pnpm.*-C web test/);
    expect(cfg.commands.lint_frontend ?? cfg.commands.lint).toMatch(/pnpm.*-C web lint/);
  });

  it("the JS test_file pattern covers web/tests/**", async () => {
    // Tests INV-017: web/ invariants cannot ship with zero JS assertions executed.
    const fs = await import("node:fs/promises");
    const path = await import("node:path");
    const cfgPath = path.resolve(__dirname, "../../.correctless/config/workflow-config.json");
    const cfg = JSON.parse(await fs.readFile(cfgPath, "utf8"));
    expect(cfg.patterns.test_file).toMatch(/web\/tests/);
  });
});
