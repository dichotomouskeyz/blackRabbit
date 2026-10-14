// Turn a model turn (emissions + dispatched tool results) into rendered ChatItems
// (frontend-shell INV-012 / PRH-004). This is the model→render seam: prose alone
// must become a prose ChatItem (never a success card); a tool intent with no
// completed result becomes a tool_intent item; a tool call becomes a tool_result
// item carrying the REAL dispatcher result (e.g. a 409), never a synthesized
// success even if streamed prose claims otherwise. Tests drive emissions through
// this (via the dispatcher) into ToolResultCard, not by hand-building ChatItems.
//
// QA-003: when a same-turn tool result is a failure/409, prose that CLAIMS the
// contradicted action completed is visibly corrected rather than rendered verbatim
// as a success-sounding statement next to the refusal.
//
// QA-011: the per-turn tool-call cap (INV-014) is enforced HERE, at the real
// dispatch, not in a parallel accounting-only loop.
//
// QA-014: correction is keyed to the failed action. Prose about a tool that
// succeeded in the same turn is left alone.

import type { ModelEmission } from "@/lib/agent-core";
import type { Dispatcher, ToolResult } from "@/lib/dispatcher";
import type { ChatItem } from "@/components/ToolResultCard";
import { validateToolArgs } from "@/lib/tool-registry";

// Default per-turn tool-call cap. Kept equal to agent-core's
// MAX_TOOL_CALLS_PER_TURN (not imported, to avoid a module cycle).
const DEFAULT_MAX_TOOL_CALLS = 5;

export const STEP_LIMIT_TEXT =
  "Step limit reached: the assistant made too many tool calls in one turn. The remaining calls were not run.";

// Verbs that claim a specific state-changing action completed, per tool (QA-014).
const CLAIM_BY_TOOL: Record<string, RegExp> = {
  close_session: /\bclos(ed|ing)\b/i,
  create_session: /\bcreated\b/i,
  start_capture: /\b(started|recording|capturing)\b/i,
  stop_capture: /\bstopped\b/i,
  log_marker: /\b(logged|published|marked)\b/i,
  run_arc: /\b(ran|analy[sz]ed)\b/i,
};

// Generic completion claims ("done", "completed") that name no action. They are
// corrected only when nothing in the turn succeeded, since they cannot be tied to
// one action.
const GENERIC_CLAIM_RE = /\b(done|completed|succeeded|successfully)\b/i;

// Any completed-action verb, used for tools without a specific entry.
const ANY_CLAIM_RE =
  /\b(closed|created|started|stopped|ran|completed|logged|published|done)\b/i;

function claimReFor(toolName: string): RegExp {
  return CLAIM_BY_TOOL[toolName] ?? ANY_CLAIM_RE;
}

// A sentence that negates the action ("Neither ran", "it was not closed") reports
// the failure honestly and is not a success claim.
const NEGATION_RE =
  /\b(not|no|neither|nor|never|cannot|unable|failed|blocked|unavailable)\b|n't\b/i;

// Whether any sentence of `text` asserts a completed action matching `re`.
function claims(text: string, re: RegExp): boolean {
  return text
    .split(/(?<=[.!?])\s+|\n+/)
    .some((sentence) => re.test(sentence) && !NEGATION_RE.test(sentence));
}

// Build the correction text for prose that contradicts a failed tool result.
function correctionFor(toolName: string | undefined): string {
  const action = toolName ? toolName.replace(/_/g, " ") : "the requested action";
  return `The assistant claimed ${action} succeeded, but the action did not complete.`;
}

// Replace success-claiming prose that a failed tool result in the same turn
// contradicts. Applies to prose before or after the failed result (QA-003), and
// only to claims about the failed action (QA-014).
export function correctContradictingProse(items: ChatItem[]): ChatItem[] {
  const failed: string[] = [];
  let anySucceeded = false;
  for (const it of items) {
    if (it.kind !== "tool_result" || !it.toolResult) continue;
    if (it.toolResult.ok) anySucceeded = true;
    else failed.push(it.toolResult.toolName);
  }
  if (failed.length === 0) return items;

  return items.map((it) => {
    if (it.kind !== "prose") return it;
    const text = it.text ?? "";
    const hit = failed.find((tool) => claims(text, claimReFor(tool)));
    if (hit) {
      return { kind: "correction", text: correctionFor(hit), toolName: hit };
    }
    if (!anySucceeded && claims(text, GENERIC_CLAIM_RE)) {
      return { kind: "correction", text: correctionFor(failed[0]), toolName: failed[0] };
    }
    return it;
  });
}

// Drive a sequence of model emissions through the dispatcher into ChatItems.
// Prose emissions never produce a tool_result/success; a tool_call emission is
// dispatched for real and its result (success OR 409 refusal) is what renders.
// At most `maxToolCalls` calls are dispatched; a request beyond the cap is not
// sent and a step-limit notice is rendered instead (INV-014 / QA-011).
export async function chatItemsFromTurn(opts: {
  emissions: ModelEmission[];
  dispatcher: Dispatcher;
  maxToolCalls?: number;
}): Promise<ChatItem[]> {
  const cap = opts.maxToolCalls ?? DEFAULT_MAX_TOOL_CALLS;
  const items: ChatItem[] = [];
  let dispatched = 0;

  for (const emission of opts.emissions) {
    if (emission.kind === "prose") {
      items.push({ kind: "prose", text: emission.text ?? "" });
      continue;
    }

    if (emission.kind === "tool_call") {
      const toolName = emission.toolName ?? "";
      // Validate against the closed schema before forwarding (BND-002).
      const validation = validateToolArgs(toolName, emission.args ?? {});
      if (!validation.ok) {
        // A narrated tool intent we could not complete (no API-backed result).
        items.push({ kind: "tool_intent", toolName });
        continue;
      }
      if (dispatched >= cap) {
        items.push({ kind: "notice", text: STEP_LIMIT_TEXT });
        break;
      }
      const toolResult: ToolResult = await opts.dispatcher.execute(
        toolName,
        emission.args ?? {},
      );
      dispatched += 1;
      items.push({ kind: "tool_result", toolResult });
      continue;
    }

    // malformed / none / unknown → no forwarded call; nothing renders as success.
  }

  return correctContradictingProse(items);
}

export type { ToolResult };
