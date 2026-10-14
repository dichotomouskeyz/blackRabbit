import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { CapabilityControl } from "@/components/CapabilityControl";
import { loadCapabilityState } from "@/lib/capabilities";
import { createApiClient } from "@/lib/api-client";
import type { CapabilityRow, Transport } from "@/lib/api-client";

// INV-001 [integration] (B5): the rendered CapabilityControl reflects the state the
// PROVIDER derived from a stubbed /capabilities response — the full fetch→derive→
// render path, not a hand-built CapabilityState.

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

describe("INV-001 [integration]: rendered control reflects provider-derived state", () => {
  it("an implemented capability from /capabilities renders an enabled control", async () => {
    // Tests INV-001: fetch→derive→render leaves an implemented control enabled.
    const rows: CapabilityRow[] = [
      { capability: "create_session", endpoint: "POST /sessions", status: "implemented", blocked_reason: null, gate: null },
    ];
    const client = createApiClient({ transport: transportReturning(rows) });
    const state = await loadCapabilityState(client);

    render(
      <CapabilityControl capability="create_session" state={state} onInvoke={() => {}} label="Create session" />,
    );
    expect(screen.getByRole("button", { name: /create session/i })).not.toBeDisabled();
  });

  it("a blocked capability from /capabilities renders a disabled control with the server reason", async () => {
    // Tests INV-001: a runtime-blocked status renders disabled + server blocked_reason.
    const rows: CapabilityRow[] = [
      { capability: "create_session", endpoint: "POST /sessions", status: "blocked", blocked_reason: "down for maintenance", gate: "OQ-001" },
    ];
    const client = createApiClient({ transport: transportReturning(rows) });
    const state = await loadCapabilityState(client);

    render(
      <CapabilityControl capability="create_session" state={state} onInvoke={() => {}} label="Create session" />,
    );
    expect(screen.getByRole("button", { name: /create session/i })).toBeDisabled();
    expect(document.body.textContent ?? "").toMatch(/maintenance/i);
  });

  it("cold start (unreachable /capabilities): the rendered control is disabled (fail closed)", async () => {
    // Tests INV-001 cold-start: provider derives all-disabled → control disabled.
    const client = createApiClient({
      transport: async () => {
        throw new Error("ECONNREFUSED");
      },
    });
    const state = await loadCapabilityState(client);

    render(
      <CapabilityControl capability="create_session" state={state} onInvoke={() => {}} label="Create session" />,
    );
    expect(screen.getByRole("button", { name: /create session/i })).toBeDisabled();
  });
});
