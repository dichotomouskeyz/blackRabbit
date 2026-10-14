import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, within, waitFor } from "@testing-library/react";
import Home from "@/app/page";

// QA-013: the product entry point mounts the operator shell, wired to the
// runtime capability provider and the real ApiClient.

afterEach(() => vi.unstubAllGlobals());

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

describe("QA-013 [integration]: page.tsx renders the wired OperatorShell", () => {
  it("cold start: the shell renders with every capability disabled before /capabilities answers", () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(() => {})));
    render(<Home />);
    expect(document.querySelector("[data-operator-shell]")).not.toBeNull();
    expect(screen.getByTestId("chat-region")).toBeInTheDocument();
    for (const b of within(screen.getByTestId("capability-matrix")).queryAllByRole("button")) {
      expect(b).toBeDisabled();
    }
  });

  it("loads the matrix and sessions through /backend and shows them", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/backend/capabilities") {
        return json(200, [
          { capability: "list_sessions", endpoint: "GET /sessions", status: "implemented", blocked_reason: null, gate: null },
          {
            capability: "close_session",
            endpoint: "POST /sessions/{id}/close",
            status: "blocked",
            blocked_reason: "XDF reconciliation is not released",
            gate: "OQ-002",
          },
        ]);
      }
      if (url === "/backend/sessions") {
        return json(200, {
          sessions: [
            { id: "33333333-3333-4333-8333-333333333333", status: "active", compound: "saline", started_at: null, closed_at: null, created_at: null },
          ],
        });
      }
      if (url === "/backend/health") return json(200, { status: "ok", version: "0.1.0", contract_version: "0" });
      if (url === "/backend/vocab") return json(200, { compounds: ["saline"], dose_units: ["mg"] });
      if (url === "/api/agent") return json(200, { available: true });
      return json(404, {});
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<Home />);
    const list = screen.getByTestId("session-list");
    await waitFor(() =>
      expect(within(list).getByText("33333333-3333-4333-8333-333333333333")).toBeInTheDocument(),
    );
    const matrix = screen.getByTestId("capability-matrix");
    await waitFor(() => expect(within(matrix).getByRole("button", { name: "list_sessions" })).not.toBeDisabled());
    expect(within(matrix).getByRole("button", { name: "close_session" })).toBeDisabled();
    expect(within(matrix).getByText(/XDF reconciliation is not released/)).toBeInTheDocument();
    // Contract versions match, so no mismatch banner.
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
