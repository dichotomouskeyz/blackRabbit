import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ToolResultCard } from "@/components/ToolResultCard";
import { createApiClient } from "@/lib/api-client";
import { createDispatcher } from "@/lib/dispatcher";
import { chatItemsFromTurn } from "@/lib/chat-items";
import type { CapabilityState } from "@/lib/capabilities";
import type { CapabilityRow } from "@/lib/api-client";
import type { ModelEmission } from "@/lib/agent-core";

// QA-003 — when a same-turn tool result is a failure/409, the contradicting success
// PROSE TEXT must be absent or visibly CORRECTED, not merely "no success card".
// These tests assert the literal "now closed" claim does NOT survive uncorrected.

const VALID_UUID = "11111111-1111-4111-8111-111111111111";
const MATRIX: CapabilityRow[] = [
  { capability: "close_session", endpoint: "POST /sessions/{id}/close", status: "blocked", blocked_reason: "session close not enabled until auth lands", gate: "OQ-001" },
];
const capState: CapabilityState = { loaded: true, rows: MATRIX };

const CLOSE_409 = {
  error: "capability_unavailable",
  capability: "close_session",
  status: "blocked",
  blocked_reason: "session close not enabled until auth lands",
  gate: "OQ-001",
};

function transport(calls: { method: string; path: string }[]) {
  return async (path: string, init?: RequestInit): Promise<Response> => {
    calls.push({ method: (init?.method ?? "GET").toUpperCase(), path });
    if (path.includes("/close")) {
      return new Response(JSON.stringify(CLOSE_409), { status: 409, headers: { "content-type": "application/json" } });
    }
    return new Response(JSON.stringify({ sessions: [] }), { status: 200, headers: { "content-type": "application/json" } });
  };
}

async function renderTurn(emissions: ModelEmission[]) {
  const calls: { method: string; path: string }[] = [];
  const client = createApiClient({ transport: transport(calls) });
  const dispatcher = createDispatcher(client, capState);
  const items = await chatItemsFromTurn({ emissions, dispatcher });
  render(
    <>
      {items.map((item, i) => (
        <ToolResultCard key={i} item={item} />
      ))}
    </>,
  );
  return { items, calls };
}

describe("QA-003 [integration]: contradicting success prose is corrected, not echoed", () => {
  it("409 close_session THEN prose 'session is now closed' → the false claim text is suppressed/corrected", async () => {
    const { items } = await renderTurn([
      { kind: "tool_call", toolName: "close_session", args: { session_id: VALID_UUID } },
      { kind: "prose", text: "Great news — the session is now closed." },
    ]);

    // The contradicting success claim must NOT render verbatim.
    expect(document.body.textContent ?? "").not.toMatch(/session is now closed/i);
    // A correction is rendered in its place, naming that the action did not complete.
    expect(document.body.textContent ?? "").toMatch(/did not complete|claimed/i);
    // No fabricated success affordance.
    expect(screen.queryByTestId("tool-success-card")).toBeNull();
    // The refusal (409) still surfaces.
    expect(document.body.textContent ?? "").toMatch(/not enabled|unavailable|blocked/i);
    // A correction ChatItem replaced the prose.
    expect(items.some((it) => it.kind === "correction")).toBe(true);
  });

  it("prose claiming success BEFORE the 409 is also corrected (order-independent)", async () => {
    const { items } = await renderTurn([
      { kind: "prose", text: "I have closed the session for you." },
      { kind: "tool_call", toolName: "close_session", args: { session_id: VALID_UUID } },
    ]);
    expect(document.body.textContent ?? "").not.toMatch(/closed the session for you/i);
    expect(document.body.textContent ?? "").toMatch(/did not complete|claimed/i);
    expect(items.some((it) => it.kind === "correction")).toBe(true);
  });

  it("a SUCCESSFUL tool result leaves benign prose intact (no over-correction)", async () => {
    // list_sessions succeeds; surrounding prose is NOT contradicted, so it stays.
    const { items } = await renderTurn([
      { kind: "tool_call", toolName: "list_sessions", args: {} },
      { kind: "prose", text: "I listed the sessions and everything completed fine." },
    ]);
    // No failed result → no correction; the prose stands.
    expect(items.some((it) => it.kind === "correction")).toBe(false);
    expect(document.body.textContent ?? "").toMatch(/listed the sessions/i);
  });
});
