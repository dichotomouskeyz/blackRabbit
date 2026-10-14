import { describe, it, expect } from "vitest";
import { promises as fs } from "node:fs";
import { resolve, join } from "node:path";

// QA-001 (class fix) — meta-test: every agent-loop helper the invariants frame as
// the ROUTE's behavior must have at least one NON-TEST caller in web/src/. If a
// future refactor un-wires the route/shell (leaving these helpers dead, callable
// only from tests), this grep-based check fails — closing the canonical mock-gap
// the QA round found (handler stub + zero-caller helpers passing helper-only tests).
//
// QA-004 (class fix) — also bans hardcoded `{ ok: true }` / synthetic-success
// returns in non-test web/src/ source (the OperatorShell stub fabricated success).

const SRC = resolve(__dirname, "../src");

async function srcFiles(): Promise<{ file: string; text: string }[]> {
  const out: { file: string; text: string }[] = [];
  async function walk(dir: string): Promise<void> {
    for (const entry of await fs.readdir(dir, { withFileTypes: true })) {
      const full = join(dir, entry.name);
      if (entry.isDirectory()) await walk(full);
      else if (/\.(ts|tsx)$/.test(entry.name)) {
        out.push({ file: full, text: await fs.readFile(full, "utf8") });
      }
    }
  }
  await walk(SRC);
  return out;
}

// The agent-loop helpers named in the invariants (INV-005b/008a/012/014/015).
const WIRED_HELPERS = [
  "runAgentLoop",
  "chatItemsFromTurn",
  "buildAgentRequest",
  "createDispatcher",
];

describe("QA-001 [meta]: agent-loop helpers have a non-test caller in web/src/", () => {
  it("each invariant-named helper is referenced from a non-definition src module", async () => {
    const files = await srcFiles();
    for (const helper of WIRED_HELPERS) {
      // A non-test caller is any src file that references the helper by name but is
      // not the module that DEFINES it (no `export function <helper>` /
      // `export const <helper>` / `export ... function <helper>`).
      const definitionRe = new RegExp(
        `export\\s+(?:async\\s+)?(?:function|const)\\s+${helper}\\b`,
      );
      const callers = files.filter(({ text }) => {
        if (definitionRe.test(text)) return false; // the definition site
        // A reference that is the helper's own name as an identifier (call/import).
        return new RegExp(`\\b${helper}\\b`).test(text);
      });
      expect(
        callers.length,
        `${helper} has ZERO non-test callers in web/src/ — it is dead/un-wired ` +
          `(QA-001). Wire it into the route/shell product path.`,
      ).toBeGreaterThan(0);
    }
  });

  it("the agent route module wires the handler through to the loop helpers", async () => {
    // The route POST must reach the wired handler (handleAgentRequest), which in
    // turn composes the loop helpers — not a stub that returns {ok:true} early.
    const routeText = await fs.readFile(
      resolve(SRC, "app/api/agent/route.ts"),
      "utf8",
    );
    expect(routeText).toMatch(/handleAgentRequest/);
    const coreText = await fs.readFile(resolve(SRC, "lib/agent-core.ts"), "utf8");
    // handleAgentRequest composes the dispatcher + chat-items + loop (the wired path).
    expect(coreText).toMatch(/createDispatcher/);
    expect(coreText).toMatch(/chatItemsFromTurn/);
    expect(coreText).toMatch(/runAgentLoop/);
    expect(coreText).toMatch(/buildAgentRequest/);
  });
});

describe("QA-004 [meta]: no hardcoded synthetic-success returns in non-test src/", () => {
  it("no src module returns a hardcoded { ok: true, status: <literal> } success", async () => {
    const files = await srcFiles();
    // Ban a synthetic success: `return { ok: true, status: <NUMERIC LITERAL> ... }`.
    // The OperatorShell stub did `return { ok: true, status: 200, data: {...} }`.
    // A REAL ApiResult success uses `status: res.status` (a variable) and
    // `data: parsed` — never a hardcoded numeric status — so this rule flags only
    // the fabricated-success shape (QA-004 / PRH-004), not the transport's result.
    const synthRe = /return\s*\{\s*ok\s*:\s*true\s*,\s*status\s*:\s*\d+/;
    for (const { file, text } of files) {
      expect(
        synthRe.test(text),
        `${file} returns a hardcoded { ok: true, status: <literal> } success ` +
          `(QA-004 / PRH-004). Return the real ApiResult from the transport instead.`,
      ).toBe(false);
    }
  });
});
