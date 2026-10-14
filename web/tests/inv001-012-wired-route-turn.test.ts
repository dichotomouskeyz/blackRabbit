import { describe, it, expect, afterEach, vi } from "vitest";
import { POST } from "@/app/api/agent/route";
import { setRouteDeps, type ModelEmission } from "@/lib/agent-core";
import { createApiClient } from "@/lib/api-client";
import { loadCapabilityState, type CapabilityState } from "@/lib/capabilities";
import type { CapabilityRow } from "@/lib/api-client";

// QA-001 (instance proof) — the agent ROUTE POST drives a REAL turn through the
// wired handler: injected model emissions → buildAgentRequest (fence) →
// runAgentLoop (cap) → createDispatcher (live tool→API) → chatItemsFromTurn
// (INV-012). These assert the route's RESPONSE reflects the dispatched tool result,
// not a {ok:true} stub. A re-stubbed handler that returns {ok:true} early would
// fail these because no tool result / refusal would appear in the response.

afterEach(() => {
  setRouteDeps(undefined);
  vi.restoreAllMocks();
});

const VALID_UUID = "11111111-1111-4111-8111-111111111111";
const MATRIX: CapabilityRow[] = [
  { capability: "list_sessions", endpoint: "GET /sessions", status: "implemented", blocked_reason: null, gate: null },
  { capability: "close_session", endpoint: "POST /sessions/{id}/close", status: "blocked", blocked_reason: "session close not enabled until auth lands", gate: "OQ-001" },
];

const CLOSE_409 = {
  error: "capability_unavailable",
  capability: "close_session",
  status: "blocked",
  blocked_reason: "session close not enabled until auth lands",
  gate: "OQ-001",
};

function transport(calls: { method: string; path: string }[]) {
  return async (path: string, init?: RequestInit): Promise<Response> => {
    const method = (init?.method ?? "GET").toUpperCase();
    calls.push({ method, path });
    if (path.includes("/close")) {
      return new Response(JSON.stringify(CLOSE_409), { status: 409, headers: { "content-type": "application/json" } });
    }
    return new Response(JSON.stringify({ sessions: [] }), { status: 200, headers: { "content-type": "application/json" } });
  };
}

function chatRequest(): Request {
  return new Request("http://localhost/api/agent", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ messages: [{ role: "user", content: "close the session" }] }),
  });
}

async function wiredState(calls: { method: string; path: string }[]): Promise<{ client: ReturnType<typeof createApiClient>; capabilities: CapabilityState }> {
  const client = createApiClient({ transport: transport(calls) });
  // The capability matrix is sourced at runtime via the real provider (INV-001).
  const capabilities = await loadCapabilityState({
    ...client,
    getCapabilities: async () => ({ ok: true, status: 200, data: MATRIX }),
  });
  return { client, capabilities };
}

describe("QA-001 [integration]: the wired route drives a real model→tool→API turn", () => {
  it("a model tool_call for a gated capability dispatches a REAL request and the response carries the 409 refusal (not a {ok:true} stub)", async () => {
    const calls: { method: string; path: string }[] = [];
    const { client, capabilities } = await wiredState(calls);

    const emissions: ModelEmission[] = [
      { kind: "tool_call", toolName: "close_session", args: { session_id: VALID_UUID } },
      { kind: "prose", text: "Great news — the session is now closed." },
    ];

    // The injected model-completion seam ACCEPTS then RETURNS the emissions: the
    // bounded timeout wraps THIS call (QA-002); on success the wired turn runs.
    setRouteDeps({
      baseUrl: "http://127.0.0.1:4000",
      probe: async () => emissions,
      client,
      capabilities,
    });

    const res = await POST(chatRequest());
    expect(res.status).toBe(200);
    const body = (await res.json()) as { ok: boolean; items: unknown[] };

    // A REAL request to the fixed close path was issued by the wired dispatcher.
    expect(calls.filter((c) => c.path.includes("/close")).length).toBe(1);

    // The response carries the dispatched tool result (the 409 refusal) AND a
    // CORRECTION of the contradicting success-prose — never a fabricated success.
    const serialized = JSON.stringify(body.items);
    expect(serialized).toMatch(/tool_result/);
    expect(serialized).toMatch(/409|capability_unavailable|not enabled/);
    // The contradicting "now closed" success claim must be corrected/suppressed.
    expect(serialized).not.toMatch(/session is now closed/);
  });

  it("a reachable model that emits ONLY prose returns prose items, no tool call dispatched", async () => {
    const calls: { method: string; path: string }[] = [];
    const { client, capabilities } = await wiredState(calls);

    setRouteDeps({
      baseUrl: "http://127.0.0.1:4000",
      probe: async () => [{ kind: "prose", text: "Here is some information." } as ModelEmission],
      client,
      capabilities,
    });

    const res = await POST(chatRequest());
    const body = (await res.json()) as { items: unknown[] };
    expect(calls.length).toBe(0);
    expect(JSON.stringify(body.items)).toMatch(/prose/);
  });
});
