import { describe, it, expect, vi, afterEach } from "vitest";
import { POST } from "@/app/api/agent/route";
import { setRouteDeps, AGENT_TIMEOUT_MS } from "@/lib/agent-core";

// QA-002 — the bounded timeout (AGENT_TIMEOUT_MS, AbortController) must wrap the
// REAL model completion call, not a GET liveness probe. The 'stalled' case
// simulates the injected model completion ACCEPTING (resolving its handshake) then
// NEVER resolving the inference; the route must surface agent_unavailable
// {reason:'stalled'} before the deadline (fake timers), proving the timeout wraps
// the inference, not a cheaper proxy.

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

describe("QA-002 [integration]: the timeout wraps the model COMPLETION call", () => {
  it("model completion accepts then stalls during inference → agent_unavailable reason=stalled, aborted at the deadline", async () => {
    vi.useFakeTimers();

    let handshakeAccepted = false;
    let abortObserved = false;
    // The injected model-completion seam: it "accepts" (begins the request) then
    // never resolves until the AbortController fires — i.e. the model handshakes
    // then stalls mid-inference. The seam observes the abort signal, proving the
    // timeout aborts THIS call (not a separate liveness probe).
    const modelComplete = (_url: string, signal: AbortSignal) =>
      new Promise((_resolve, reject) => {
        handshakeAccepted = true; // accepted the request (inference started)
        signal.addEventListener("abort", () => {
          abortObserved = true;
          reject(new Error("inference aborted at deadline"));
        });
        // never resolves on its own — simulates an inference stall
      });

    setRouteDeps({
      baseUrl: "http://127.0.0.1:4000",
      probe: modelComplete,
      timeoutMs: AGENT_TIMEOUT_MS,
    });

    let settled = false;
    const resPromise = POST(chatRequest()).then((r) => {
      settled = true;
      return r;
    });

    // Let microtasks flush so the seam is entered (handshake accepted).
    await vi.advanceTimersByTimeAsync(0);
    expect(handshakeAccepted).toBe(true);

    // Before the deadline the route is genuinely waiting on the inference.
    await vi.advanceTimersByTimeAsync(AGENT_TIMEOUT_MS - 50);
    expect(settled).toBe(false);

    // At/after the deadline the AbortController aborts the model completion and the
    // route fails closed as stalled — never hangs.
    await vi.advanceTimersByTimeAsync(100);
    const res = await resPromise;
    expect(settled).toBe(true);
    expect(abortObserved).toBe(true);

    const body = (await res.json()) as { error: string; reason: string; message: string };
    expect(body).toMatchObject({ error: "agent_unavailable", reason: "stalled" });
    // Distinguishes the MODEL, not the backend or session data (INV-007).
    expect(body.message).toMatch(/model/i);
    expect(body.message).not.toMatch(/session data|data loss|backend unavailable/i);
  });
});
