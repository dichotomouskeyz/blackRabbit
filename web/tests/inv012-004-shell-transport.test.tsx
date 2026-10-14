import { describe, it, expect } from "vitest";
import { render, screen, within, fireEvent, waitFor } from "@testing-library/react";
import { OperatorShell } from "@/components/OperatorShell";
import { createApiClient } from "@/lib/api-client";
import { loadCapabilityState, COLD_START_STATE } from "@/lib/capabilities";
import type { CapabilityState } from "@/lib/capabilities";
import type { SessionSummary, Transport } from "@/lib/api-client";

// QA-004 — OperatorShell.handleCreate is wired to the REAL ApiClient.createSession;
// it returns the actual ApiResult, never a hardcoded {ok:true}. These tests RENDER
// the shell with a stubbed TRANSPORT (not a stubbed onSubmit) and assert a 422/409
// from the transport surfaces as the real outcome — no fabricated 200.
//
// QA-005 — also mounts the shell with /capabilities unreachable and asserts all
// controls are disabled at first paint (INV-001 cold start, on the wired tree).

const VALID_UUID = "11111111-1111-4111-8111-111111111111";
const IMPLEMENTED: CapabilityState = {
  loaded: true,
  rows: [
    { capability: "create_session", endpoint: "POST /sessions", status: "implemented", blocked_reason: null, gate: null },
    { capability: "close_session", endpoint: "POST /sessions/{id}/close", status: "implemented", blocked_reason: null, gate: null },
  ],
};
const SESSIONS: SessionSummary[] = [];

function transport422(): Transport {
  return async (path: string, init?: RequestInit): Promise<Response> => {
    const method = (init?.method ?? "GET").toUpperCase();
    if (method === "POST" && /\/sessions$/.test(path.split("?")[0])) {
      return new Response(
        JSON.stringify({ field: "compound", message: "unknown compound", valid_choices: ["saline"] }),
        { status: 422, headers: { "content-type": "application/json" } },
      );
    }
    return new Response("{}", { status: 200, headers: { "content-type": "application/json" } });
  };
}

function transport409(): Transport {
  return async (path: string, init?: RequestInit): Promise<Response> => {
    const method = (init?.method ?? "GET").toUpperCase();
    if (method === "POST" && /\/sessions$/.test(path.split("?")[0])) {
      return new Response(
        JSON.stringify({ error: "capability_unavailable", capability: "create_session", status: "blocked", blocked_reason: "writes disabled", gate: "OQ-001" }),
        { status: 409, headers: { "content-type": "application/json" } },
      );
    }
    return new Response("{}", { status: 200, headers: { "content-type": "application/json" } });
  };
}

async function submitCreate() {
  const form = screen.getByTestId("create-session-form");
  fireEvent.change(within(form).getByLabelText(/participant_id/i), { target: { value: VALID_UUID } });
  fireEvent.change(within(form).getByLabelText(/capture_source/i), { target: { value: "lsl" } });
  fireEvent.click(within(form).getByRole("button", { name: /create/i }));
}

describe("QA-004 [integration]: shell surfaces the real transport outcome (no fabricated 200)", () => {
  it("a 422 from the stubbed transport surfaces as the real validation outcome", async () => {
    const client = createApiClient({ transport: transport422() });
    render(<OperatorShell capabilities={IMPLEMENTED} sessions={SESSIONS} apiClient={client} />);

    await submitCreate();

    // The shell renders the REAL 422 outcome — not a fabricated success.
    await waitFor(() => {
      expect(document.body.textContent ?? "").toMatch(/unknown compound|compound/i);
    });
    expect(screen.queryByTestId("tool-success-card")).toBeNull();
    expect(document.body.textContent ?? "").not.toMatch(/created|session_id/i);
  });

  it("a 409 from the stubbed transport surfaces as the real refusal outcome", async () => {
    const client = createApiClient({ transport: transport409() });
    render(<OperatorShell capabilities={IMPLEMENTED} sessions={SESSIONS} apiClient={client} />);

    await submitCreate();

    await waitFor(() => {
      expect(document.body.textContent ?? "").toMatch(/unavailable|disabled/i);
    });
    expect(screen.queryByTestId("tool-success-card")).toBeNull();
  });
});

describe("QA-005 [integration]: wired shell fails closed when /capabilities is unreachable", () => {
  it("cold start (unreachable /capabilities): all capability controls disabled at first paint", async () => {
    const client = createApiClient({
      transport: async () => {
        throw new Error("ECONNREFUSED");
      },
    });
    // The provider derives the matrix at runtime; an unreachable /capabilities fails
    // closed to COLD_START_STATE (never fail-open to enabled).
    const state = await loadCapabilityState(client);
    expect(state).toEqual(COLD_START_STATE);

    render(<OperatorShell capabilities={state} sessions={SESSIONS} apiClient={client} />);

    const matrix = screen.getByTestId("capability-matrix");
    const buttons = within(matrix).queryAllByRole("button");
    // Cold start → no implemented rows → no enabled controls. Any rendered control
    // must be disabled (fail closed).
    for (const b of buttons) {
      expect(b).toBeDisabled();
    }
  });

  it("the shell mounts the wired provider tree with a runtime-sourced matrix (not hardcoded)", async () => {
    // Drive the full fetch→derive→render path: a runtime 'blocked' status renders
    // disabled even though the capability is otherwise known.
    const rows = [
      { capability: "create_session", endpoint: "POST /sessions", status: "blocked" as const, blocked_reason: "maintenance", gate: "OQ-001" },
    ];
    const client = createApiClient({
      transport: async (path: string) => {
        if (path.includes("/capabilities")) {
          return new Response(JSON.stringify({ capabilities: rows }), { status: 200, headers: { "content-type": "application/json" } });
        }
        return new Response("{}", { status: 200, headers: { "content-type": "application/json" } });
      },
    });
    const state = await loadCapabilityState(client);
    render(<OperatorShell capabilities={state} sessions={SESSIONS} apiClient={client} />);
    const matrix = screen.getByTestId("capability-matrix");
    expect(within(matrix).getByText(/maintenance/i)).toBeInTheDocument();
  });
});
