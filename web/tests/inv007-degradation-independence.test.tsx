import { describe, it, expect } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { OperatorShell } from "@/components/OperatorShell";
import type { CapabilityState } from "@/lib/capabilities";
import type { AgentUnavailable } from "@/lib/agent-core";
import type { SessionSummary } from "@/lib/api-client";
import type { CapabilityRow } from "@/lib/api-client";

// INV-007 [integration] (B3): when the agent route is unavailable, the chat input
// is disabled with the sub-case message, BUT the session list, create form, and
// capability matrix STILL render and stay interactive. Driving this through the
// rendered shell (not a helper) is the wired-path control the audit asked for.

const MATRIX: CapabilityRow[] = [
  { capability: "create_session", endpoint: "POST /sessions", status: "implemented", blocked_reason: null, gate: null },
  { capability: "list_sessions", endpoint: "GET /sessions", status: "implemented", blocked_reason: null, gate: null },
];
const capState: CapabilityState = { loaded: true, rows: MATRIX };

const SESSIONS: SessionSummary[] = [
  { id: "11111111-1111-4111-8111-111111111111", status: "active", compound: "saline", started_at: null, closed_at: null, created_at: null },
];

const UNAVAILABLE: AgentUnavailable = {
  error: "agent_unavailable",
  reason: "stalled",
  message: "The local model stopped responding. Your sessions and data are unaffected.",
};

describe("INV-007 [integration]: chat degrades independently of the rest of the shell", () => {
  it("chat input is disabled and shows the stalled sub-case message", () => {
    // Tests INV-007: the chat surface fails closed with the right sub-case copy.
    render(
      <OperatorShell capabilities={capState} sessions={SESSIONS} agentUnavailable={UNAVAILABLE} />,
    );
    const chat = screen.getByTestId("chat-input") as HTMLInputElement | HTMLTextAreaElement;
    expect(chat).toBeDisabled();
    // The sub-case message renders and does not imply session-data loss.
    const chatRegion = screen.getByTestId("chat-region");
    expect(within(chatRegion).getByText(/model/i)).toBeInTheDocument();
    expect(chatRegion.textContent ?? "").not.toMatch(/session data|data loss/i);
  });

  it("session list, create form, and capability matrix still render and are interactive", () => {
    // Tests INV-007: non-chat surfaces are NOT disabled by an unavailable model.
    render(
      <OperatorShell capabilities={capState} sessions={SESSIONS} agentUnavailable={UNAVAILABLE} />,
    );
    // Session list renders the seeded session.
    const list = screen.getByTestId("session-list");
    expect(within(list).getByText(/11111111-1111-4111-8111-111111111111/)).toBeInTheDocument();

    // The create form is present and its submit affordance is NOT disabled.
    const form = screen.getByTestId("create-session-form");
    const submit = within(form).getByRole("button", { name: /create/i });
    expect(submit).not.toBeDisabled();

    // The capability matrix renders an enabled implemented control.
    const matrix = screen.getByTestId("capability-matrix");
    expect(within(matrix).getByText(/create_session/)).toBeInTheDocument();
  });
});
