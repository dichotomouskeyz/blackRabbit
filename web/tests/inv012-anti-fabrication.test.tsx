import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ToolResultCard, type ChatItem } from "@/components/ToolResultCard";
import { createApiClient } from "@/lib/api-client";
import { createDispatcher } from "@/lib/dispatcher";
import { chatItemsFromTurn } from "@/lib/chat-items";
import type { CapabilityState, } from "@/lib/capabilities";
import type { CapabilityRow } from "@/lib/api-client";
import type { ModelEmission } from "@/lib/agent-core";

// INV-012 / PRH-004: Every state-change claim is backed by a rendered API-sourced
// tool-result; prose alone never renders as a completed action. Test approach:
// integration.

describe("INV-012 [integration]: prose-only claims do not render success", () => {
  it("assistant prose claiming 'session closed' renders no success card", () => {
    // Tests INV-012: prose alone never renders a completed-action affordance.
    const item: ChatItem = {
      kind: "prose",
      text: "I have closed the session successfully.",
    };
    render(<ToolResultCard item={item} />);
    expect(screen.queryByTestId("tool-success-card")).toBeNull();
  });

  it("a narrated tool intent with no result renders 'action did not complete'", () => {
    // Tests INV-012: intent with no completed/failed result → visible not-complete state.
    const item: ChatItem = { kind: "tool_intent", toolName: "close_session" };
    const { container } = render(<ToolResultCard item={item} />);
    expect(container.textContent).toMatch(/did not complete|not complete/i);
  });

  it("a close_session 409 tool-result renders the refusal, not success", () => {
    // Tests INV-012: a 409 tool-result renders as a refusal even if prose claims done.
    const item: ChatItem = {
      kind: "tool_result",
      toolResult: {
        toolName: "close_session",
        ok: false,
        status: 409,
        body: {
          error: "capability_unavailable",
          capability: "close_session",
          status: "blocked",
          blocked_reason: "session close not enabled until auth lands",
          gate: "OQ-001",
        },
        apiBacked: true,
      },
    };
    render(<ToolResultCard item={item} />);
    expect(screen.queryByTestId("tool-success-card")).toBeNull();
  });
});

// B4: drive the model→render PATH, not hand-built ChatItems. The model emits
// either prose-only or a tool call; emissions flow through the dispatcher (real
// client + stubbed transport) and chatItemsFromTurn into the rendered cards. A
// lazy impl that special-cases hand-built ChatItems but mis-handles the real
// loop output would pass the cases above yet FAIL here.
const VALID_UUID = "11111111-1111-4111-8111-111111111111";
const MATRIX: CapabilityRow[] = [
  { capability: "close_session", endpoint: "POST /sessions/{id}/close", status: "blocked", blocked_reason: "session close not enabled until auth lands", gate: "OQ-001" },
  { capability: "list_sessions", endpoint: "GET /sessions", status: "implemented", blocked_reason: null, gate: null },
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
    const method = (init?.method ?? "GET").toUpperCase();
    calls.push({ method, path });
    if (path.includes("/close")) {
      return new Response(JSON.stringify(CLOSE_409), {
        status: 409,
        headers: { "content-type": "application/json" },
      });
    }
    return new Response(JSON.stringify({ sessions: [] }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };
}

describe("INV-012 [integration]: model→render path (driven through dispatcher, not hand-built)", () => {
  it("(a) prose claiming a close with NO tool call renders prose only — no success card, no completed affordance", async () => {
    // Tests INV-012: the model emits ONLY prose; no tool call is dispatched, so
    // no completed-action affordance may render.
    const calls: { method: string; path: string }[] = [];
    const client = createApiClient({ transport: transport(calls) });
    const dispatcher = createDispatcher(client, capState);

    const emissions: ModelEmission[] = [
      { kind: "prose", text: "Done — I have closed the session successfully." },
    ];
    const items = await chatItemsFromTurn({ emissions, dispatcher });

    render(
      <>
        {items.map((item, i) => (
          <ToolResultCard key={i} item={item} />
        ))}
      </>,
    );
    // No tool call was issued at all.
    expect(calls.length).toBe(0);
    // The prose renders, but NO success/completed-action affordance.
    expect(screen.queryByTestId("tool-success-card")).toBeNull();
    expect(document.body.textContent ?? "").not.toMatch(/did not complete|not complete/i);
    // (prose is shown as prose, with no completed-action affordance)
    expect(document.body.textContent ?? "").toMatch(/closed the session/i);
  });

  it("(b) close_session tool call returns 409 then streamed prose claims success → rendered state is the REFUSAL, not success", async () => {
    // Tests INV-012: a tool call dispatched for real returns 409; later prose
    // contradicting it must NOT upgrade the render to success.
    const calls: { method: string; path: string }[] = [];
    const client = createApiClient({ transport: transport(calls) });
    const dispatcher = createDispatcher(client, capState);

    const emissions: ModelEmission[] = [
      { kind: "tool_call", toolName: "close_session", args: { session_id: VALID_UUID } },
      { kind: "prose", text: "Great news — the session is now closed." },
    ];
    const items = await chatItemsFromTurn({ emissions, dispatcher });

    render(
      <>
        {items.map((item, i) => (
          <ToolResultCard key={i} item={item} />
        ))}
      </>,
    );
    // Exactly one real request to the fixed close path.
    expect(calls.filter((c) => c.path.includes("/close")).length).toBe(1);
    // The refusal is what renders — never a fabricated success.
    expect(screen.queryByTestId("tool-success-card")).toBeNull();
    // The 409 reason text surfaces (refusal state), not "closed".
    expect(document.body.textContent ?? "").toMatch(/not enabled|unavailable|blocked/i);
  });
});

describe("INV-012 [integration]: a real API-backed success renders a card", () => {
  it("a create_session 200 tool-result renders a success card", () => {
    // Tests INV-012: a completed-action affordance requires a backing API result.
    const item: ChatItem = {
      kind: "tool_result",
      toolResult: {
        toolName: "create_session",
        ok: true,
        status: 200,
        body: { session_id: "11111111-1111-4111-8111-111111111111" },
        apiBacked: true,
      },
    };
    render(<ToolResultCard item={item} />);
    expect(screen.getByTestId("tool-success-card")).toBeInTheDocument();
  });
});
