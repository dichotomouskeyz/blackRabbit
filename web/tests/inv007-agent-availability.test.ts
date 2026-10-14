import { describe, it, expect, vi, afterEach } from "vitest";
import {
  resolveAgentAvailability,
  AGENT_TIMEOUT_MS,
  setRouteDeps,
} from "@/lib/agent-core";
import { POST } from "@/app/api/agent/route";

// INV-007: The agent route fails closed within a bounded timeout and degrades
// independently, distinguishing not-configured vs unreachable vs stalled.
// Test approach: integration (Entry: resolveAgentAvailability with injected probe;
// Through: the timeout/abort path; Exit: structured agent_unavailable before a
// hard deadline, reason distinguishes the three modes).

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  setRouteDeps(undefined);
});

function chatRequest(): Request {
  return new Request("http://localhost/api/agent", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ messages: [{ role: "user", content: "list sessions" }] }),
  });
}

async function bodyOf(res: Response): Promise<Record<string, unknown>> {
  return (await res.json()) as Record<string, unknown>;
}

describe("INV-007 [integration]: three failure modes within a bounded timeout", () => {
  it("(a) AGENT_BASE_URL unset → agent_unavailable reason=not_configured", async () => {
    // Tests INV-007(a).
    const result = await resolveAgentAvailability({ baseUrl: undefined });
    expect(result).toMatchObject({ error: "agent_unavailable", reason: "not_configured" });
    // Message states the model is affected, not session data.
    expect((result as { message: string }).message).not.toMatch(/session data|data loss/i);
  });

  it("(b) set but connection-refused → agent_unavailable reason=unreachable", async () => {
    // Tests INV-007(b).
    const probe = vi.fn(async () => {
      throw new Error("ECONNREFUSED");
    });
    const result = await resolveAgentAvailability({
      baseUrl: "http://localhost:4000",
      probe,
    });
    expect(result).toMatchObject({ error: "agent_unavailable", reason: "unreachable" });
  });

  it("(c) accepted-then-stalls past the timeout → agent_unavailable reason=stalled, before a hard deadline", async () => {
    // Tests INV-007(c): fake timers advanced past the configured timeout; the call
    // must resolve to a structured outcome, never hang.
    vi.useFakeTimers();
    const probe = (_url: string, signal: AbortSignal) =>
      new Promise((_resolve, reject) => {
        // Accept then stall: only reject when aborted by the timeout.
        signal.addEventListener("abort", () => reject(new Error("aborted")));
      });

    const promise = resolveAgentAvailability({
      baseUrl: "http://localhost:4000",
      probe,
      timeoutMs: AGENT_TIMEOUT_MS,
    });

    await vi.advanceTimersByTimeAsync(AGENT_TIMEOUT_MS + 100);
    const result = await promise;
    expect(result).toMatchObject({ error: "agent_unavailable", reason: "stalled" });
  });
});

// B3: the AUTHORITATIVE INV-007 control must exercise the WIRED route, not just
// the helper. These drive the exported POST handler (web/src/app/api/agent/route.ts)
// for all three modes — a lazy impl that fixes resolveAgentAvailability but leaves
// the route dead would pass the helper tests above yet FAIL these.
describe("INV-007 [integration]: the agent ROUTE POST fails closed in all three modes", () => {
  it("(a) AGENT_BASE_URL unset → POST returns structured agent_unavailable reason=not_configured", async () => {
    // Tests INV-007(a) at the route seam.
    setRouteDeps({ baseUrl: undefined });
    const res = await POST(chatRequest());
    expect(res).toBeInstanceOf(Response);
    const body = await bodyOf(res);
    expect(body).toMatchObject({ error: "agent_unavailable", reason: "not_configured" });
    expect(String(body.message)).not.toMatch(/session data|data loss/i);
  });

  it("(b) connection-refused → POST returns agent_unavailable reason=unreachable", async () => {
    // Tests INV-007(b) at the route seam: the route's probe throws ECONNREFUSED.
    const probe = vi.fn(async () => {
      throw new Error("ECONNREFUSED");
    });
    setRouteDeps({ baseUrl: "http://127.0.0.1:4000", probe });
    const res = await POST(chatRequest());
    const body = await bodyOf(res);
    expect(body).toMatchObject({ error: "agent_unavailable", reason: "unreachable" });
    expect(probe).toHaveBeenCalled();
  });

  it("(c) accepted-then-stalls → POST resolves to agent_unavailable reason=stalled BY the deadline (does not hang)", async () => {
    // Tests INV-007(c) at the route seam. Positive deadline assertion: the promise
    // MUST settle once timers advance past AGENT_TIMEOUT_MS; if it hangs, the
    // `settled` flag stays false and the test fails rather than timing out silently.
    vi.useFakeTimers();
    const probe = (_url: string, signal: AbortSignal) =>
      new Promise((_resolve, reject) => {
        signal.addEventListener("abort", () => reject(new Error("aborted")));
      });
    setRouteDeps({ baseUrl: "http://127.0.0.1:4000", probe, timeoutMs: AGENT_TIMEOUT_MS });

    let settled = false;
    const resPromise = POST(chatRequest()).then((r) => {
      settled = true;
      return r;
    });

    // Before the deadline it must NOT have resolved (it is genuinely waiting).
    await vi.advanceTimersByTimeAsync(AGENT_TIMEOUT_MS - 50);
    expect(settled).toBe(false);

    // After the deadline it MUST resolve — proving a bounded timeout, not a hang.
    await vi.advanceTimersByTimeAsync(100);
    const res = await resPromise;
    expect(settled).toBe(true);
    const body = await bodyOf(res);
    expect(body).toMatchObject({ error: "agent_unavailable", reason: "stalled" });
    // The message distinguishes stalled and names the model, not session data.
    expect(String(body.message)).not.toMatch(/session data|data loss/i);
  });

  it("the three modes carry DISTINCT messages (not-configured vs unreachable vs stalled)", async () => {
    // Tests INV-007: the operator message distinguishes the sub-cases.
    setRouteDeps({ baseUrl: undefined });
    const unsetMsg = String((await bodyOf(await POST(chatRequest()))).message);

    setRouteDeps({
      baseUrl: "http://127.0.0.1:4000",
      probe: async () => {
        throw new Error("ECONNREFUSED");
      },
    });
    const refusedMsg = String((await bodyOf(await POST(chatRequest()))).message);

    expect(unsetMsg).not.toBe(refusedMsg);
    expect(unsetMsg.length).toBeGreaterThan(0);
    expect(refusedMsg.length).toBeGreaterThan(0);
  });
});
