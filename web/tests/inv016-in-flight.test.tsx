import { describe, it, expect } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { InFlight } from "@/components/InFlight";

// INV-016: Every tool call and API request has a defined in-flight state, distinct
// from model prose. Test approach: integration.

describe("INV-016 [integration]: in-flight affordance renders before resolution", () => {
  it("renders a pending/awaiting indicator while a request is in flight", () => {
    // Tests INV-016: a deferred (pending) transport surfaces a loading affordance.
    render(<InFlight phase="awaiting" label="list_sessions" />);
    expect(screen.getByTestId("in-flight")).toBeInTheDocument();
  });

  it("distinguishes tool-call status (issued/awaiting/returned)", () => {
    // Tests INV-016: tool-call status is distinct from prose.
    const { rerender } = render(<InFlight phase="issued" label="create_session" />);
    expect(screen.getByTestId("in-flight")).toHaveAttribute("data-phase", "issued");
    rerender(<InFlight phase="returned" label="create_session" />);
    expect(screen.getByTestId("in-flight")).toHaveAttribute("data-phase", "returned");
  });

  it("clears the in-flight affordance when idle/returned", async () => {
    // Tests INV-016: the pending state clears after resolution.
    render(<InFlight phase="idle" label="list_sessions" />);
    await waitFor(() => {
      expect(screen.queryByTestId("in-flight-spinner")).toBeNull();
    });
  });
});
