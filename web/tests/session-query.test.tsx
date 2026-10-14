import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, within, waitFor, fireEvent } from "@testing-library/react";
import Home from "@/app/page";
import { createApiClient, sessionFilterQuery, type Transport } from "@/lib/api-client";
import { createDispatcher } from "@/lib/dispatcher";
import { validateToolArgs } from "@/lib/tool-registry";
import { EMPTY_FILTER_FORM, toApiFilters } from "@/lib/session-filter-form";
import type { CapabilityState } from "@/lib/capabilities";

// session-query SQ-005 (client and agent tool) and SQ-006 (list filters).

afterEach(() => vi.unstubAllGlobals());

const PID = "3c1e9a52-4d6c-4e1f-9b7a-2c3d4e5f6a77";

function recording(calls: string[]): Transport {
  return async (path) => {
    calls.push(path);
    return new Response(JSON.stringify({ sessions: [] }), { status: 200, headers: { "content-type": "application/json" } });
  };
}

describe("SQ-005: client and tool send only validated filters", () => {
  it("encodes set filters and omits empty ones", () => {
    expect(sessionFilterQuery(undefined)).toBe("");
    expect(sessionFilterQuery({ status: "", session_id: "  " })).toBe("");
    const q = new URLSearchParams(sessionFilterQuery({ status: "closed", participant_id: PID, limit: 5 }).slice(1));
    expect(Object.fromEntries(q)).toEqual({ status: "closed", participant_id: PID, limit: "5" });
  });

  it("listSessions sends filters as query parameters", async () => {
    const calls: string[] = [];
    await createApiClient({ transport: recording(calls) }).listSessions({ compound: "mdma" });
    expect(calls).toEqual(["/sessions?compound=mdma"]);
  });

  it("list_sessions accepts the filters and rejects malformed ones", () => {
    expect(validateToolArgs("list_sessions", {}).ok).toBe(true);
    expect(validateToolArgs("list_sessions", { session_id: "9b2e", status: "closed", participant_id: PID, limit: 20 }).ok).toBe(true);
    expect(validateToolArgs("list_sessions", { participant_id: "3c1e9a52" }).ok).toBe(false);
    expect(validateToolArgs("list_sessions", { status: "deleted" }).ok).toBe(false);
    expect(validateToolArgs("list_sessions", { session_id: "9b2e%" }).ok).toBe(false);
    expect(validateToolArgs("list_sessions", { limit: 1000 }).ok).toBe(false);
    expect(validateToolArgs("list_sessions", { sql: "select 1" }).ok).toBe(false);
  });

  it("the dispatcher appends list filters to the fixed path; path-parameter tools are unchanged", async () => {
    const calls: string[] = [];
    const caps: CapabilityState = { loaded: true, rows: [] };
    const dispatcher = createDispatcher(createApiClient({ transport: recording(calls) }), caps);
    await dispatcher.execute("list_sessions", { status: "closed", session_id: "9b2e" });
    await dispatcher.execute("session_status", { session_id: PID });
    expect(calls[0].startsWith("/sessions?")).toBe(true);
    expect(Object.fromEntries(new URLSearchParams(calls[0].split("?")[1]))).toEqual({ status: "closed", session_id: "9b2e" });
    expect(calls[1]).toBe(`/sessions/${PID}/status`);
  });
});

describe("SQ-006: filter form", () => {
  it("turns local calendar days into an inclusive start and exclusive end", () => {
    const { filters, problems } = toApiFilters({ ...EMPTY_FILTER_FORM, from: "2026-10-13", to: "2026-10-14" });
    expect(problems).toEqual({});
    expect(filters.created_from).toBe(new Date(2026, 9, 13).toISOString());
    expect(filters.created_before).toBe(new Date(2026, 9, 15).toISOString());
  });

  it("holds back partial or contradictory input instead of sending it", () => {
    const partial = toApiFilters({ ...EMPTY_FILTER_FORM, participantId: "3c1e9a52", sessionId: "9b2e" });
    expect(partial.filters).toEqual({ session_id: "9b2e" });
    expect(partial.problems.participantId).toBeDefined();
    const backwards = toApiFilters({ ...EMPTY_FILTER_FORM, from: "2026-10-14", to: "2026-10-01" });
    expect(backwards.problems.to).toBeDefined();
  });

  it("changing a filter re-queries the session list", async () => {
    const urls: string[] = [];
    const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        urls.push(url);
        if (url.startsWith("/backend/sessions")) return json({ sessions: [] });
        if (url === "/backend/capabilities") return json([]);
        if (url === "/backend/vocab") return json({ compounds: ["psilocybin", "mdma"], dose_units: ["mg"] });
        if (url === "/backend/health") return json({ status: "ok", version: "0", contract_version: "0" });
        return json({ available: true });
      }),
    );

    render(<Home />);
    const list = screen.getByTestId("session-list");
    fireEvent.click(within(list).getByRole("button", { name: "Filter sessions" }));
    await waitFor(() => expect(within(list).getByRole("option", { name: "mdma" })).toBeInTheDocument());
    fireEvent.change(within(list).getByLabelText("Status"), { target: { value: "closed" } });
    fireEvent.change(within(list).getByLabelText("Substance"), { target: { value: "mdma" } });

    await waitFor(() =>
      expect(urls.some((u) => u.includes("/backend/sessions?") && u.includes("status=closed") && u.includes("compound=mdma"))).toBe(true),
    );
    expect(within(list).getByText("No sessions match these filters.")).toBeInTheDocument();
  });
});
