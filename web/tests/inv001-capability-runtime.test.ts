import { describe, it, expect } from "vitest";
import {
  isCapabilityEnabled,
  statusFor,
  loadCapabilityState,
  COLD_START_STATE,
  type CapabilityState,
} from "@/lib/capabilities";
import { createApiClient } from "@/lib/api-client";
import type { CapabilityRow, Transport } from "@/lib/api-client";

// INV-001: Capability state is sourced at runtime, never hardcoded. Cold start
// fails closed (all disabled). Test approach: integration.

const MATRIX_ENABLED: CapabilityRow[] = [
  { capability: "create_session", endpoint: "POST /sessions", status: "implemented", blocked_reason: null, gate: null },
  { capability: "close_session", endpoint: "POST /sessions/{id}/close", status: "blocked", blocked_reason: "session close not enabled until auth lands", gate: "OQ-001" },
];

const MATRIX_FLIPPED: CapabilityRow[] = [
  // create_session flipped to blocked at runtime — control must follow the matrix.
  { capability: "create_session", endpoint: "POST /sessions", status: "blocked", blocked_reason: "down for maintenance", gate: "OQ-001" },
  { capability: "close_session", endpoint: "POST /sessions/{id}/close", status: "blocked", blocked_reason: "x", gate: "OQ-001" },
];

function loaded(rows: CapabilityRow[]): CapabilityState {
  return { loaded: true, rows };
}

describe("INV-001 [integration]: enabled state derives from the runtime matrix", () => {
  it("an implemented capability renders enabled", () => {
    // Tests INV-001: enabled follows /capabilities, not a hardcoded constant.
    expect(isCapabilityEnabled(loaded(MATRIX_ENABLED), "create_session")).toBe(true);
  });

  it("a blocked capability renders disabled with server status", () => {
    // Tests INV-001: blocked control disabled.
    expect(isCapabilityEnabled(loaded(MATRIX_ENABLED), "close_session")).toBe(false);
    expect(statusFor(loaded(MATRIX_ENABLED), "close_session")).toBe("blocked");
  });

  it("flipping the matrix flips the control (state change is runtime-sourced)", () => {
    // Tests INV-001: same capability, flipped status → enabled state changes.
    expect(isCapabilityEnabled(loaded(MATRIX_ENABLED), "create_session")).toBe(true);
    expect(isCapabilityEnabled(loaded(MATRIX_FLIPPED), "create_session")).toBe(false);
  });
});

describe("INV-001 [integration]: cold start / unreachable fails closed", () => {
  it("before the matrix loads, all capabilities render disabled (never fail-open)", () => {
    // Tests INV-001 cold-start: unloaded matrix → disabled.
    expect(isCapabilityEnabled(COLD_START_STATE, "create_session")).toBe(false);
    expect(isCapabilityEnabled(COLD_START_STATE, "list_sessions")).toBe(false);
  });

  it("an unreachable /capabilities leaves the state unloaded → all disabled", async () => {
    // Tests INV-001: transport rejects → client surfaces a not-loaded state, not enabled.
    const client = createApiClient({
      transport: async () => {
        throw new Error("ECONNREFUSED");
      },
    });
    const result = await client.getCapabilities();
    expect(result.ok).toBe(false);
    // The derived state from a failed fetch must be the cold-start (fail-closed) state.
    const state: CapabilityState = result.ok ? { loaded: true, rows: result.data } : COLD_START_STATE;
    expect(isCapabilityEnabled(state, "create_session")).toBe(false);
  });
});

// B5: drive the /capabilities fetch THROUGH the provider (the real fetch→derive
// path), stubbing only the HTTP transport. The provider — not the test — derives
// the CapabilityState. A lazy impl that leaves loadCapabilityState dead while the
// pure isCapabilityEnabled works would pass the supplements above yet FAIL here.
function transportReturning(rows: CapabilityRow[], status = 200): Transport {
  return async (path: string): Promise<Response> => {
    if (path.includes("/capabilities")) {
      return new Response(JSON.stringify({ capabilities: rows }), {
        status,
        headers: { "content-type": "application/json" },
      });
    }
    return new Response("{}", { status: 200, headers: { "content-type": "application/json" } });
  };
}

describe("INV-001 [integration]: provider derives state from a stubbed /capabilities (wired fetch→derive)", () => {
  it("flipped /capabilities status flows through the provider into the derived state", async () => {
    // Tests INV-001: a runtime-flipped status changes the derived enabled state —
    // proving state is sourced from the fetch, not hardcoded.
    const enabledClient = createApiClient({ transport: transportReturning(MATRIX_ENABLED) });
    const enabledState = await loadCapabilityState(enabledClient);
    expect(enabledState.loaded).toBe(true);
    expect(isCapabilityEnabled(enabledState, "create_session")).toBe(true);

    const flippedClient = createApiClient({ transport: transportReturning(MATRIX_FLIPPED) });
    const flippedState = await loadCapabilityState(flippedClient);
    expect(isCapabilityEnabled(flippedState, "create_session")).toBe(false);
    expect(statusFor(flippedState, "create_session")).toBe("blocked");
  });

  it("cold start: /capabilities unreachable → the PROVIDER derives all-disabled (fail closed)", async () => {
    // Tests INV-001 cold-start: the provider (not the test) returns COLD_START_STATE
    // when the fetch fails — never fail-open to enabled.
    const client = createApiClient({
      transport: async () => {
        throw new Error("ECONNREFUSED");
      },
    });
    const state = await loadCapabilityState(client);
    expect(state.loaded).toBe(false);
    expect(isCapabilityEnabled(state, "create_session")).toBe(false);
    expect(isCapabilityEnabled(state, "list_sessions")).toBe(false);
  });
});

describe("INV-001 [integration]: no hardcoded matrix in source (grep backstop)", () => {
  it("capabilities.ts does not inline an implemented/blocked matrix literal", async () => {
    // Tests INV-001: the client must not hardcode the matrix.
    const fs = await import("node:fs/promises");
    const path = await import("node:path");
    const src = await fs.readFile(path.resolve(__dirname, "../src/lib/capabilities.ts"), "utf8");
    // A hardcoded matrix would contain status string literals for specific capabilities.
    expect(src).not.toMatch(/capability:\s*["']create_session["']/);
  });
});
