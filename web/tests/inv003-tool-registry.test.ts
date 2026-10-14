import { describe, it, expect } from "vitest";
import {
  TOOL_REGISTRY,
  PINNED_TOOL_NAMES,
  BANNED_ARG_KEYS,
  validateToolArgs,
  MAX_FREETEXT_LEN,
} from "@/lib/tool-registry";

// INV-003: The agent tool registry is a fixed, closed set with typed, bounded args.
// Test approach: unit (per spec). PRH-002 composes here.

const VALID_UUID = "11111111-1111-4111-8111-111111111111";

describe("INV-003 [unit]: registry is a fixed closed set", () => {
  it("Object.keys(registry) equals the pinned list (closed/non-dynamic)", () => {
    // Tests INV-003: registry keys must equal the pinned enumerated set, in any order.
    expect(Object.keys(TOOL_REGISTRY).sort()).toEqual([...PINNED_TOOL_NAMES].sort());
  });

  it("BANNED_ARG_KEYS contains exactly the spec's nine keys", () => {
    // Tests INV-003: the banned set is the spec's pinned set.
    expect([...BANNED_ARG_KEYS].sort()).toEqual(
      ["cmd", "endpoint", "path", "query", "shell", "site_id", "sponsor_id", "sql", "url"].sort(),
    );
  });
});

describe("INV-003 [unit]: each tool endpoint is a compile-time constant string", () => {
  it("every tool has a constant method+endpoint not derived from args", () => {
    // Tests INV-003: endpoint is a constant, never model-supplied.
    for (const name of PINNED_TOOL_NAMES) {
      const def = TOOL_REGISTRY[name];
      expect(def, `missing tool ${name}`).toBeDefined();
      expect(typeof def.endpoint).toBe("string");
      expect(def.endpoint.length).toBeGreaterThan(0);
      expect(typeof def.method).toBe("string");
      // A constant endpoint must not contain a template/interpolation marker for a
      // free arg beyond the fixed {id}/{session_id} path param.
      expect(def.endpoint).not.toMatch(/\$\{/);
    }
  });
});

describe("INV-003 [unit]: schemas reject banned keys", () => {
  for (const banned of BANNED_ARG_KEYS) {
    it(`every tool schema rejects banned key '${banned}'`, () => {
      // Tests INV-003: no tool accepts any BANNED_ARG_KEYS entry (.strict()).
      for (const name of PINNED_TOOL_NAMES) {
        const args: Record<string, unknown> = { session_id: VALID_UUID, [banned]: "x" };
        const result = validateToolArgs(name, args);
        expect(result.ok, `tool ${name} accepted banned key ${banned}`).toBe(false);
      }
    });
  }
});

describe("INV-003 [unit]: session_id must be a UUID", () => {
  it("rejects a non-UUID session_id", () => {
    // Tests INV-003: session_id is a UUID.
    const result = validateToolArgs("session_status", { session_id: "not-a-uuid" });
    expect(result.ok).toBe(false);
  });

  it("accepts a well-formed UUID session_id", () => {
    // Tests INV-003: valid args pass.
    const result = validateToolArgs("session_status", { session_id: VALID_UUID });
    expect(result.ok).toBe(true);
  });
});

describe("INV-003 [unit]: free-text fields are length-bounded", () => {
  it("rejects an over-length protocol_arm on create_session", () => {
    // Tests INV-003: free-text fields carry a max-length bound (RS-010).
    const overLong = "a".repeat(MAX_FREETEXT_LEN + 1);
    const result = validateToolArgs("create_session", {
      compound: "saline",
      capture_source: "lsl",
      participant_id: VALID_UUID,
      protocol_arm: overLong,
    });
    expect(result.ok).toBe(false);
  });

  it("create_session rejects unknown/extra keys (.strict / allow-list)", () => {
    // Tests INV-003: create_session accepts only the operator-ui allow-list fields.
    const result = validateToolArgs("create_session", {
      compound: "saline",
      capture_source: "lsl",
      participant_id: VALID_UUID,
      not_an_allowed_field: "x",
    });
    expect(result.ok).toBe(false);
  });
});
