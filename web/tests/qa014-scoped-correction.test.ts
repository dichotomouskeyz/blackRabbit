import { describe, it, expect } from "vitest";
import { correctContradictingProse } from "@/lib/chat-items";
import type { ChatItem } from "@/components/ToolResultCard";

// QA-014: correction is keyed to the failed action, not to any claim verb.

const ok = (toolName: string): ChatItem => ({
  kind: "tool_result",
  toolResult: { toolName, ok: true, status: 200, body: {}, apiBacked: true },
});
const refused = (toolName: string): ChatItem => ({
  kind: "tool_result",
  toolResult: { toolName, ok: false, status: 409, body: {}, apiBacked: true },
});

describe("QA-014 [unit]: correction in a mixed turn", () => {
  it("a claim only about the succeeded tool is not corrected", () => {
    const prose: ChatItem = { kind: "prose", text: "I created the session for participant 3c1e." };
    const out = correctContradictingProse([ok("create_session"), refused("close_session"), prose]);
    expect(out[2]).toEqual(prose);
  });

  it("a claim about the failed tool is corrected", () => {
    const out = correctContradictingProse([
      ok("create_session"),
      refused("close_session"),
      { kind: "prose", text: "The session is now closed." },
    ]);
    expect(out[2].kind).toBe("correction");
    expect(out[2].toolName).toBe("close_session");
  });

  it("a sentence that reports the failure is not a success claim", () => {
    const prose: ChatItem = { kind: "prose", text: "I tried both. Neither ran." };
    const out = correctContradictingProse([refused("close_session"), refused("run_arc"), prose]);
    expect(out[2]).toEqual(prose);
  });

  it("an affirmative sentence next to a negated one is still corrected", () => {
    const out = correctContradictingProse([
      refused("close_session"),
      { kind: "prose", text: "Capture was not started. The session is closed." },
    ]);
    expect(out[1].kind).toBe("correction");
  });

  it("a generic completion claim is corrected only when nothing in the turn succeeded", () => {
    const done: ChatItem = { kind: "prose", text: "Done." };
    expect(correctContradictingProse([refused("run_arc"), done])[1].kind).toBe("correction");
    expect(correctContradictingProse([ok("list_sessions"), refused("run_arc"), done])[2]).toEqual(done);
  });
});
