import { describe, it, expect, vi } from "vitest";
import {
  runAgentLoop,
  MAX_TOOL_CALLS_PER_TURN,
  type ModelEmission,
} from "@/lib/agent-core";

// INV-014: The agent route caps tool-calls per turn / loop iterations.
// INV-015: Malformed/absent model tool emission handled without crashing.

describe("INV-014 [unit]: per-turn tool-call / loop cap", () => {
  it("halts at the configured cap when the model emits a tool call every step", async () => {
    // Tests INV-014: a model that emits a tool call every step is bounded; the loop
    // stops at MAX_TOOL_CALLS_PER_TURN and surfaces a step-limit message.
    const dispatch = vi.fn(async () => ({ ok: true }));
    const nextEmission = (_step: number): ModelEmission => ({
      kind: "tool_call",
      toolName: "list_sessions",
      args: {},
    });

    const outcome = await runAgentLoop({ nextEmission, dispatch });

    expect(outcome.outcome).toBe("step_limit");
    expect(outcome.message).toMatch(/step limit|limit reached/i);
    expect(outcome.toolCallCount).toBeLessThanOrEqual(MAX_TOOL_CALLS_PER_TURN);
    expect(dispatch.mock.calls.length).toBeLessThanOrEqual(MAX_TOOL_CALLS_PER_TURN);
  });
});

describe("INV-015 [integration]: malformed/absent emissions handled without crashing", () => {
  it("malformed tool-call JSON → could_not_complete, no forwarded dispatch", async () => {
    // Tests INV-015: malformed emission does not throw / forward an invalid call.
    const dispatch = vi.fn(async () => ({ ok: true }));
    const nextEmission = (_step: number): ModelEmission => ({
      kind: "malformed",
      rawJson: '{"toolName": "list_sessions", "args": {',
    });
    const outcome = await runAgentLoop({ nextEmission, dispatch });
    expect(outcome.outcome).toBe("could_not_complete");
    expect(dispatch).not.toHaveBeenCalled();
  });

  it("a tool name not in the registry → could_not_complete, no forwarded dispatch", async () => {
    // Tests INV-015: out-of-registry tool name rejected.
    const dispatch = vi.fn(async () => ({ ok: true }));
    const nextEmission = (_step: number): ModelEmission => ({
      kind: "tool_call",
      toolName: "rm_rf_root",
      args: {},
    });
    const outcome = await runAgentLoop({ nextEmission, dispatch });
    expect(outcome.outcome).toBe("could_not_complete");
    expect(dispatch).not.toHaveBeenCalled();
  });

  it("no tool call at all (prose only) → completed without forwarding a call", async () => {
    // Tests INV-015: absent emission is handled (distinct from agent_unavailable).
    const dispatch = vi.fn(async () => ({ ok: true }));
    const nextEmission = (_step: number): ModelEmission => ({
      kind: "none",
    });
    const outcome = await runAgentLoop({ nextEmission, dispatch });
    expect(["completed", "could_not_complete"]).toContain(outcome.outcome);
    expect(dispatch).not.toHaveBeenCalled();
  });

  it("wrong-typed args → could_not_complete, no forwarded dispatch", async () => {
    // Tests INV-015: wrong-typed args rejected against the closed schema before forward.
    const dispatch = vi.fn(async () => ({ ok: true }));
    const nextEmission = (_step: number): ModelEmission => ({
      kind: "tool_call",
      toolName: "session_status",
      args: { session_id: 12345 }, // not a UUID string
    });
    const outcome = await runAgentLoop({ nextEmission, dispatch });
    expect(outcome.outcome).toBe("could_not_complete");
    expect(dispatch).not.toHaveBeenCalled();
  });
});
