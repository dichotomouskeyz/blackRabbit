import { describe, it, expect, vi } from "vitest";
import { render, screen, within, waitFor, fireEvent } from "@testing-library/react";
import { OperatorShell } from "@/components/OperatorShell";
import { createApiClient, type Transport } from "@/lib/api-client";
import { messageForResult } from "@/lib/error-messages";
import { PINNED_TOOL_NAMES } from "@/lib/tool-registry";
import type { CapabilityState } from "@/lib/capabilities";
import type { SessionSummary } from "@/lib/api-client";

// session-void SV-007: void is a confirmed human action in the console.

const SID = "9b2e41d0-7c3f-4a12-b8e6-1f2d9c0a6e11";
const SESSIONS: SessionSummary[] = [
  { id: SID, status: "closed", compound: "psilocybin", started_at: null, closed_at: null, created_at: null },
];
const CAN_VOID: CapabilityState = {
  loaded: true,
  rows: [{ capability: "void_session", endpoint: "POST /sessions/{id}/void", status: "implemented", blocked_reason: null, gate: null }],
};
const NO_VOID: CapabilityState = { loaded: true, rows: [] };

type Call = { method: string; path: string; body?: unknown };

function backend(calls: Call[], status: { current: string }): Transport {
  return async (path, init) => {
    const method = (init?.method ?? "GET").toUpperCase();
    calls.push({ method, path, body: init?.body ? JSON.parse(String(init.body)) : undefined });
    const json = (code: number, body: unknown) =>
      new Response(JSON.stringify(body), { status: code, headers: { "content-type": "application/json" } });
    if (method === "POST" && path.endsWith("/void")) {
      status.current = "voided";
      return json(200, { session_id: SID, status: "voided", voided_at: "2026-10-14T05:00:00+00:00" });
    }
    return json(200, { id: SID, status: status.current, started_at: null, closed_at: null, watermark_state: "verified" });
  };
}

async function openSession() {
  fireEvent.click(within(screen.getByTestId("session-list")).getByText(SID));
  await screen.findByText("Session ID");
}

describe("SV-007: console void", () => {
  it("voids a closed session only after a reason is confirmed, then refreshes", async () => {
    const calls: Call[] = [];
    const status = { current: "closed" };
    const onSessionsChanged = vi.fn();
    render(
      <OperatorShell
        capabilities={CAN_VOID}
        sessions={SESSIONS}
        apiClient={createApiClient({ transport: backend(calls, status) })}
        onSessionsChanged={onSessionsChanged}
      />,
    );
    await openSession();
    fireEvent.click(await screen.findByRole("button", { name: "Void session" }));

    const form = screen.getByTestId("void-session-form");
    const confirm = within(form).getByRole("button", { name: "Confirm void" });
    expect(confirm).toBeDisabled();
    fireEvent.change(within(form).getByLabelText("Reason"), { target: { value: "  ab " } });
    expect(confirm).toBeDisabled();
    fireEvent.change(within(form).getByLabelText("Reason"), { target: { value: "  Leads detached  " } });
    fireEvent.click(confirm);

    await waitFor(() => expect(onSessionsChanged).toHaveBeenCalledTimes(1));
    expect(calls.find((c) => c.method === "POST")).toEqual({
      method: "POST",
      path: `/sessions/${SID}/void`,
      body: { reason: "Leads detached" },
    });
    // The refreshed status is voided, so the action disappears.
    await waitFor(() => expect(screen.queryByRole("button", { name: "Void session" })).toBeNull());
  });

  it("offers no void for an active session or when the capability is not implemented", async () => {
    const status = { current: "active" };
    const { unmount } = render(
      <OperatorShell capabilities={CAN_VOID} sessions={SESSIONS} apiClient={createApiClient({ transport: backend([], status) })} />,
    );
    await openSession();
    expect(screen.queryByRole("button", { name: "Void session" })).toBeNull();
    unmount();

    render(
      <OperatorShell capabilities={NO_VOID} sessions={SESSIONS} apiClient={createApiClient({ transport: backend([], { current: "closed" }) })} />,
    );
    await openSession();
    expect(screen.queryByRole("button", { name: "Void session" })).toBeNull();
  });

  it("session-state conflicts show the server's message, not capability copy", () => {
    const msg = messageForResult({
      ok: false,
      status: 409,
      body: { error: "session_not_voidable", message: "only closed or failed sessions can be voided; end capture first", status: "active" },
    });
    expect(msg.text).toBe("only closed or failed sessions can be voided; end capture first");
  });

  it("the agent has no void tool", () => {
    expect(PINNED_TOOL_NAMES.some((n) => n.includes("void"))).toBe(false);
  });
});
