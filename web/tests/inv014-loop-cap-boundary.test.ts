import { describe, it, expect, vi } from "vitest";
import { runAgentLoop, MAX_TOOL_CALLS_PER_TURN, type ModelEmission } from "@/lib/agent-core";

// QA-010 — pin the EXACT dispatch count and the boundary between "completed at the
// cap" and "exceeded the cap". A turn that legitimately stops at exactly the cap is
// NOT a limit breach; step_limit is surfaced ONLY when the model requests work
// BEYOND the cap (checked before the (cap+1)-th dispatch).

describe("QA-010 [unit]: loop-cap boundary is exact, not eager", () => {
  it("a model that stops at EXACTLY the cap completes — NOT step_limit", async () => {
    const dispatch = vi.fn(async () => ({ ok: true }));
    // Emit a tool call for the first `cap` steps, then stop (prose/none).
    const nextEmission = (step: number): ModelEmission =>
      step < MAX_TOOL_CALLS_PER_TURN
        ? { kind: "tool_call", toolName: "list_sessions", args: {} }
        : { kind: "none" };

    const outcome = await runAgentLoop({ nextEmission, dispatch });

    // Completed-at-cap: exactly `cap` dispatches, and the outcome is 'completed'.
    expect(dispatch).toHaveBeenCalledTimes(MAX_TOOL_CALLS_PER_TURN);
    expect(outcome.toolCallCount).toBe(MAX_TOOL_CALLS_PER_TURN);
    expect(outcome.outcome).toBe("completed");
  });

  it("a model that requests work BEYOND the cap hits step_limit at exactly cap dispatches", async () => {
    const dispatch = vi.fn(async () => ({ ok: true }));
    // Emit a tool call every step (never stops) → exceeds the cap.
    const nextEmission = (_step: number): ModelEmission => ({
      kind: "tool_call",
      toolName: "list_sessions",
      args: {},
    });

    const outcome = await runAgentLoop({ nextEmission, dispatch });

    // Exceeded-cap: step_limit, and dispatch ran EXACTLY `cap` times — the (cap+1)-th
    // requested call is refused before dispatch, never executed.
    expect(outcome.outcome).toBe("step_limit");
    expect(dispatch).toHaveBeenCalledTimes(MAX_TOOL_CALLS_PER_TURN);
    expect(outcome.toolCallCount).toBe(MAX_TOOL_CALLS_PER_TURN);
  });

  it("a model that stops at cap-1 completes with cap-1 dispatches", async () => {
    const dispatch = vi.fn(async () => ({ ok: true }));
    const stopAt = MAX_TOOL_CALLS_PER_TURN - 1;
    const nextEmission = (step: number): ModelEmission =>
      step < stopAt ? { kind: "tool_call", toolName: "list_sessions", args: {} } : { kind: "none" };

    const outcome = await runAgentLoop({ nextEmission, dispatch });
    expect(dispatch).toHaveBeenCalledTimes(stopAt);
    expect(outcome.outcome).toBe("completed");
  });
});
