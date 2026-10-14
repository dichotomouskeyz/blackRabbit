import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { OutcomeMessage } from "@/components/OutcomeMessage";
import { messageForResult } from "@/lib/error-messages";
import type { ApiResult } from "@/lib/api-client";

// QA-008 — a model-down 503 {error:'agent_unavailable'} must render model-specific
// copy (states the MODEL is affected, not the backend or session data) and must
// NEVER say "backend unavailable". The tenancy/backend 503 must render its own
// distinct, domain-correct copy. Two failure domains share HTTP 503 → the mapper
// disambiguates on the error code (INV-006/007).

const NO_RAW = /\{|\}|Traceback/;

describe("QA-008 [integration]: 503 agent_unavailable vs backend/tenancy are distinct", () => {
  it("agent_unavailable 503 → model-specific copy, never 'backend unavailable'", () => {
    const result: ApiResult<unknown> = {
      ok: false,
      status: 503,
      body: {
        error: "agent_unavailable",
        reason: "unreachable",
        message: "The local model could not be reached. Your sessions and data are unaffected.",
      },
    };
    const msg = messageForResult(result);
    expect(msg.kind).toBe("agent_unavailable");
    expect(msg.text).toMatch(/model/i);
    expect(msg.text).not.toMatch(/backend unavailable/i);
    expect(msg.text).not.toMatch(/session data|data loss/i);

    const { container } = render(<OutcomeMessage result={result} />);
    expect(container.textContent).toMatch(/model/i);
    expect(container.textContent).not.toMatch(/backend unavailable/i);
    expect(container.textContent ?? "").not.toMatch(NO_RAW);
  });

  it("backend_unavailable 503 → 'backend unavailable, retry' (distinct from the model copy)", () => {
    const result: ApiResult<unknown> = { ok: false, status: 503, body: { error: "backend_unavailable" } };
    const msg = messageForResult(result);
    expect(msg.kind).toBe("backend_unavailable");
    expect(msg.text).toMatch(/backend unavailable/i);
    expect(msg.text).toMatch(/retry/i);
  });

  it("tenancy_not_configured 503 → names the .env file (distinct from both)", () => {
    const result: ApiResult<unknown> = { ok: false, status: 503, body: { error: "tenancy_not_configured" } };
    const msg = messageForResult(result);
    expect(msg.kind).toBe("tenancy_not_configured");
    expect(msg.text).toMatch(/\.env/);
    expect(msg.text).not.toMatch(/the local model/i);
  });

  it("the three 503 domains carry mutually-distinct copy", () => {
    const agent = messageForResult({ ok: false, status: 503, body: { error: "agent_unavailable", message: "model down" } }).text;
    const backend = messageForResult({ ok: false, status: 503, body: { error: "backend_unavailable" } }).text;
    const tenancy = messageForResult({ ok: false, status: 503, body: { error: "tenancy_not_configured" } }).text;
    expect(new Set([agent, backend, tenancy]).size).toBe(3);
  });
});
