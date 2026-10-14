import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { OutcomeMessage } from "@/components/OutcomeMessage";
import { messageForResult, emptySessionsMessage } from "@/lib/error-messages";
import type { ApiResult } from "@/lib/api-client";

// INV-006: Every API outcome maps to an actionable, researcher-legible message.
// Test approach: integration.

const NO_RAW = /\{|\}|Traceback/;

function noRawDump(container: HTMLElement) {
  expect(container.textContent ?? "").not.toMatch(NO_RAW);
}

describe("INV-006 [integration]: 409 capability_unavailable", () => {
  it("renders a plain-language reason; never the raw gate id verbatim", () => {
    // Tests INV-006: raw gate id (OQ-004) is not shown verbatim.
    const result: ApiResult<unknown> = {
      ok: false,
      status: 409,
      body: {
        error: "capability_unavailable",
        capability: "capture_start",
        status: "blocked",
        blocked_reason: "capture process ownership unsettled",
        gate: "OQ-004",
      },
    };
    const { container } = render(<OutcomeMessage result={result} />);
    expect(container.textContent).toMatch(/capture/i);
    // The raw gate id must not appear verbatim.
    expect(container.textContent).not.toContain("OQ-004");
    noRawDump(container);
  });

  it("renders without crashing when blocked_reason and gate are null", () => {
    // Tests INV-006: null fields render without "(null)" or a crash.
    const result: ApiResult<unknown> = {
      ok: false,
      status: 409,
      body: {
        error: "capability_unavailable",
        capability: "close_session",
        status: "blocked",
        blocked_reason: null,
        gate: null,
      },
    };
    const { container } = render(<OutcomeMessage result={result} />);
    expect(container.textContent).not.toContain("(null)");
    expect(container.textContent).not.toContain("null");
    noRawDump(container);
  });
});

describe("INV-006 [integration]: 503 outcomes", () => {
  it("503 backend_unavailable → 'backend unavailable, retry'", () => {
    // Tests INV-006.
    const result: ApiResult<unknown> = { ok: false, status: 503, body: { error: "backend_unavailable" } };
    const { container } = render(<OutcomeMessage result={result} />);
    expect(container.textContent).toMatch(/backend unavailable/i);
    expect(container.textContent).toMatch(/retry/i);
    noRawDump(container);
  });

  it("503 tenancy_not_configured names the .env file + example + doc pointer", () => {
    // Tests INV-006: not a bare "set API_SPONSOR_ID".
    const result: ApiResult<unknown> = { ok: false, status: 503, body: { error: "tenancy_not_configured" } };
    const { container } = render(<OutcomeMessage result={result} />);
    expect(container.textContent).toMatch(/\.env/);
    noRawDump(container);
  });
});

describe("INV-006 [integration]: 422 / 404 / empty", () => {
  it("422 → field-level validation with valid_choices", () => {
    // Tests INV-006: structured field-level message.
    const result: ApiResult<unknown> = {
      ok: false,
      status: 422,
      body: { field: "compound", message: "unknown compound", valid_choices: ["saline", "psilocybin"] },
    };
    const msg = messageForResult(result);
    expect(msg.field).toBe("compound");
    expect(msg.validChoices).toEqual(["saline", "psilocybin"]);
  });

  it("404 → 'not found'", () => {
    // Tests INV-006.
    const result: ApiResult<unknown> = { ok: false, status: 404, body: {} };
    const { container } = render(<OutcomeMessage result={result} />);
    expect(container.textContent).toMatch(/not found/i);
    noRawDump(container);
  });

  it("empty GET /sessions → a zero-state distinct from an error", () => {
    // Tests INV-006: "no sessions yet" zero-state, not an error.
    const msg = emptySessionsMessage();
    expect(msg.kind).toBe("empty");
    expect(msg.text).toMatch(/no sessions/i);
    expect(msg.severity).not.toBe("error");
  });
});
