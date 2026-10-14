import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CapabilityControl } from "@/components/CapabilityControl";
import type { CapabilityState } from "@/lib/capabilities";
import type { CapabilityRow } from "@/lib/api-client";

// INV-019: Newly-enabled write/exec capabilities require first-use confirmation.
// Test approach: integration.

const NEWLY_IMPLEMENTED: CapabilityRow[] = [
  { capability: "close_session", endpoint: "POST /sessions/{id}/close", status: "implemented", blocked_reason: null, gate: null },
];
const state: CapabilityState = { loaded: true, rows: NEWLY_IMPLEMENTED };

describe("INV-019 [integration]: first-use confirmation for newly-enabled write/exec", () => {
  it("a newly-implemented close_session prompts confirmation before issuing the request", async () => {
    // Tests INV-019: the first invocation of a write/exec capability requires explicit
    // confirmation — not a silently flipped flag triggerable by reflex.
    const user = userEvent.setup();
    const onInvoke = vi.fn();
    render(
      <CapabilityControl
        capability="close_session"
        state={state}
        previouslyImplemented={false}
        onInvoke={onInvoke}
        label="Close session"
      />,
    );

    await user.click(screen.getByRole("button", { name: /close session/i }));
    // A confirmation affordance must appear and onInvoke must NOT have fired yet.
    expect(onInvoke).not.toHaveBeenCalled();
    expect(screen.getByTestId("first-use-confirm")).toBeInTheDocument();

    // Confirming then issues the request.
    await user.click(screen.getByRole("button", { name: /confirm/i }));
    expect(onInvoke).toHaveBeenCalledTimes(1);
  });

  it("a read capability does not require first-use confirmation", async () => {
    // Tests INV-019: only write/exec capabilities gate on confirmation.
    const user = userEvent.setup();
    const onInvoke = vi.fn();
    const readState: CapabilityState = {
      loaded: true,
      rows: [{ capability: "list_sessions", endpoint: "GET /sessions", status: "implemented", blocked_reason: null, gate: null }],
    };
    render(
      <CapabilityControl
        capability="list_sessions"
        state={readState}
        previouslyImplemented={false}
        onInvoke={onInvoke}
        label="List sessions"
      />,
    );
    await user.click(screen.getByRole("button", { name: /list sessions/i }));
    expect(onInvoke).toHaveBeenCalledTimes(1);
  });
});
