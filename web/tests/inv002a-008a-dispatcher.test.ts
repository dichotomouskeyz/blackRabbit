import { describe, it, expect } from "vitest";
import { createApiClient } from "@/lib/api-client";
import { createDispatcher } from "@/lib/dispatcher";
import { TOOL_REGISTRY } from "@/lib/tool-registry";
import type { CapabilityState } from "@/lib/capabilities";
import type { CapabilityRow } from "@/lib/api-client";

// INV-002a: Gated invocation reaches the server and surfaces the 409 (no
// client-fabricated success). INV-008a: live execution only for `implemented`.
// Test approach: integration (dispatcher seam + real client path; model stubbed).

const MATRIX: CapabilityRow[] = [
  { capability: "list_sessions", endpoint: "GET /sessions", status: "implemented", blocked_reason: null, gate: null },
  { capability: "session_status", endpoint: "GET /sessions/{id}/status", status: "implemented", blocked_reason: null, gate: null },
  { capability: "create_session", endpoint: "POST /sessions", status: "implemented", blocked_reason: null, gate: null },
  { capability: "close_session", endpoint: "POST /sessions/{id}/close", status: "blocked", blocked_reason: "session close not enabled until auth lands", gate: "OQ-001" },
];

const capState: CapabilityState = { loaded: true, rows: MATRIX };
const VALID_UUID = "11111111-1111-4111-8111-111111111111";

// The exact 409 capability-status body from api/capabilities.py.
const CLOSE_409 = {
  error: "capability_unavailable",
  capability: "close_session",
  status: "blocked",
  blocked_reason: "session close not enabled until auth lands",
  gate: "OQ-001",
};

function transportFor(calls: { method: string; path: string }[]) {
  return async (path: string, init?: RequestInit): Promise<Response> => {
    const method = (init?.method ?? "GET").toUpperCase();
    calls.push({ method, path });
    if (method === "POST" && path.includes("/sessions/") && path.includes("/close")) {
      return new Response(JSON.stringify(CLOSE_409), {
        status: 409,
        headers: { "content-type": "application/json" },
      });
    }
    if (method === "POST" && /\/sessions$/.test(path.split("?")[0])) {
      return new Response(JSON.stringify({ session_id: VALID_UUID }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }
    return new Response(JSON.stringify({ sessions: [] }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };
}

describe("INV-002a [integration]: gated invocation surfaces the 409, never a fake success", () => {
  it("close_session issues exactly one request to its fixed path and returns the 409 body", async () => {
    // Tests INV-002a: real HTTP request to the mapped fixed endpoint; status is blocked.
    const calls: { method: string; path: string }[] = [];
    const client = createApiClient({ transport: transportFor(calls) });
    const dispatcher = createDispatcher(client, capState);

    const result = await dispatcher.execute("close_session", { session_id: VALID_UUID });

    const closeCalls = calls.filter((c) => c.path.includes("/close"));
    expect(closeCalls.length).toBe(1);
    expect(result.ok).toBe(false);
    expect(result.status).toBe(409);
    expect((result.body as typeof CLOSE_409).status).toBe("blocked");
    // No fabricated success.
    expect((result.body as { success?: boolean }).success).not.toBe(true);
    expect(result.apiBacked).toBe(true);
  });
});

// B6 / A3: pin the EXACT registry-mapped method+path, derived from TOOL_REGISTRY —
// not a path merely "containing /close" — and assert no model-supplied endpoint/url
// is used for routing. A lazy impl that routes on a substring or trusts a model
// `endpoint` arg would pass the loose assertions above yet FAIL these.
describe("INV-002a/008a [integration] (B6): dispatcher hits the EXACT registry-derived endpoint", () => {
  it("close_session resolves to the registry method+path with the id substituted, not a substring match", () => {
    // Tests INV-003/002a: the endpoint is the compile-time constant, not arbitrary.
    const def = TOOL_REGISTRY["close_session"];
    expect(def.method).toBe("POST");
    expect(def.endpoint).toBe("/sessions/{session_id}/close");
  });

  it("issues exactly one request whose method+path EQUAL the registry mapping (id substituted)", async () => {
    // Tests B6: assert the full resolved path equals the expected concrete path,
    // not merely that it includes '/close'.
    const calls: { method: string; path: string }[] = [];
    const client = createApiClient({ transport: transportFor(calls) });
    const dispatcher = createDispatcher(client, capState);

    await dispatcher.execute("close_session", { session_id: VALID_UUID });

    const def = TOOL_REGISTRY["close_session"];
    const expectedPath = def.endpoint.replace("{session_id}", VALID_UUID);
    // Compare against the concrete derived path, ignoring query string.
    const matched = calls.filter(
      (c) => c.method === def.method && c.path.split("?")[0] === expectedPath,
    );
    expect(matched.length).toBe(1);
    // And nothing routed to some other /close-ish path.
    expect(calls.every((c) => !c.path.includes("/close") || c.path.split("?")[0] === expectedPath)).toBe(true);
  });

  it("A3/PRH-002: a model-supplied endpoint/url/path arg is NOT used to route the request", async () => {
    // Tests A3: even if the model emits an endpoint/url/path arg, the dispatcher
    // routes by the fixed registry endpoint only — the malicious target is never hit.
    const calls: { method: string; path: string }[] = [];
    const client = createApiClient({ transport: transportFor(calls) });
    const dispatcher = createDispatcher(client, capState);

    await dispatcher.execute("close_session", {
      session_id: VALID_UUID,
      endpoint: "/evil/exfiltrate",
      url: "http://169.254.169.254/latest/meta-data",
      path: "/etc/passwd",
    });

    const def = TOOL_REGISTRY["close_session"];
    const expectedPath = def.endpoint.replace("{session_id}", VALID_UUID);
    // The only outbound path is the registry-derived one.
    for (const c of calls) {
      expect(c.path.split("?")[0]).toBe(expectedPath);
    }
    expect(calls.some((c) => c.path.includes("evil") || c.path.includes("169.254") || c.path.includes("passwd"))).toBe(false);
  });
});

describe("INV-008a [integration]: live execution only for implemented capabilities", () => {
  it("create_session issues a live POST /sessions and returns the real session_id", async () => {
    // Tests INV-008a(a): real POST for an implemented write capability.
    const calls: { method: string; path: string }[] = [];
    const client = createApiClient({ transport: transportFor(calls) });
    const dispatcher = createDispatcher(client, capState);

    const result = await dispatcher.execute("create_session", {
      compound: "saline",
      capture_source: "lsl",
      participant_id: VALID_UUID,
    });

    const postCalls = calls.filter((c) => c.method === "POST" && /\/sessions$/.test(c.path.split("?")[0]));
    expect(postCalls.length).toBe(1);
    expect(result.ok).toBe(true);
    expect((result.body as { session_id: string }).session_id).toBe(VALID_UUID);
    expect(result.apiBacked).toBe(true);
  });

  it("close_session returns the structured 409 without synthesizing success", async () => {
    // Tests INV-008a(b): gated tool returns 409, never synthesized success.
    const calls: { method: string; path: string }[] = [];
    const client = createApiClient({ transport: transportFor(calls) });
    const dispatcher = createDispatcher(client, capState);
    const result = await dispatcher.execute("close_session", { session_id: VALID_UUID });
    expect(result.status).toBe(409);
    expect((result.body as { success?: boolean }).success).not.toBe(true);
  });

  it("implemented tools are not gated off when /capabilities reports them implemented", async () => {
    // Tests INV-008a(c): list_sessions stays enabled/executable.
    const calls: { method: string; path: string }[] = [];
    const client = createApiClient({ transport: transportFor(calls) });
    const dispatcher = createDispatcher(client, capState);
    const result = await dispatcher.execute("list_sessions", {});
    expect(result.ok).toBe(true);
    expect(calls.filter((c) => c.path.includes("/sessions")).length).toBeGreaterThan(0);
  });
});
