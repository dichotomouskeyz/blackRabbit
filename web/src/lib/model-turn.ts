// One operator turn against an OpenAI-compatible chat-completions endpoint (a
// LiteLLM proxy, Ollama's /v1, vLLM, llama.cpp server) with tool calling
// (frontend-shell TB-006).
//
// The turn runs through runAgentLoop, so the per-turn cap (INV-014) and the
// malformed/unknown-tool handling (INV-015) apply to the calls that actually hit
// the API (QA-011). Each model response is checked for a 2xx status before it is
// trusted (QA-012). Tool results return to the model inside the untrusted-data
// fence (INV-005b) and render as API-backed cards (INV-012).

import { zodSchema } from "ai";
import {
  MAX_TOOL_CALLS_PER_TURN,
  fenceSessionData,
  runAgentLoop,
  type LoopOutcome,
  type ModelEmission,
} from "@/lib/agent-core";
import { correctContradictingProse, STEP_LIMIT_TEXT } from "@/lib/chat-items";
import type { Dispatcher } from "@/lib/dispatcher";
import { TOOL_REGISTRY } from "@/lib/tool-registry";
import type { ChatItem } from "@/components/ToolResultCard";

// What each tool does, as the model sees it. Kept beside the registry rather
// than in it so the pinned registry shape (INV-003) stays unchanged.
const TOOL_DESCRIPTIONS: Record<string, string> = {
  list_sessions:
    "List recording sessions with their status and timestamps. Optional filters: session_id (UUID prefix), participant_id (full UUID), status, compound, created_from and created_before (ISO 8601 dates or datetimes with a UTC offset), limit.",
  session_status: "Get the status and watermark state of one session.",
  create_session:
    "Create a recording session. participant_id must be a pseudonymous UUID. compound and capture_source are required.",
  view_live_signals: "Check whether the live signal view is available in this build.",
  view_arc: "Check whether ARC review is available in this build.",
  start_capture: "Start biosignal capture for a session.",
  stop_capture: "Stop biosignal capture for a session.",
  log_marker: "Log an ECHO zone or marker event on a session.",
  close_session: "Close a session, reconciling XDF and database sample counts.",
  run_arc: "Run ARC post-session convergence analysis on a closed session.",
};

// OpenAI tool definitions generated from the registry's strict zod schemas, so
// the model sees exactly the arguments the dispatcher will accept.
export function openAiTools(): unknown[] {
  return Object.values(TOOL_REGISTRY).map((def) => ({
    type: "function",
    function: {
      name: def.name,
      description: TOOL_DESCRIPTIONS[def.name] ?? def.name,
      parameters: zodSchema(def.schema).jsonSchema,
    },
  }));
}

// Operating rules appended to the pinned system prompt for the live model.
export const TOOL_POLICY =
  "Required fields such as participant_id, compound, and capture_source come from the " +
  "operator. If any are missing, ask for them; never invent a participant_id or other " +
  "identifier. When a tool returns a 409, explain in plain language that the capability " +
  "is not available in this build and give the reason it returned. Keep replies short.";

export interface HistoryMessage {
  role: "user" | "assistant";
  content: string;
}

// Bounds on what the browser may send as history.
const MAX_HISTORY_MESSAGES = 20;
const MAX_MESSAGE_CHARS = 4000;

// Parse the browser's history into plain user/assistant text messages. Anything
// else (system/tool roles, non-string content) is dropped, so operator text can
// never inject a system message or a fake tool result (BND-004).
export function sanitizeHistory(raw: unknown): HistoryMessage[] {
  if (!Array.isArray(raw)) return [];
  const out: HistoryMessage[] = [];
  for (const m of raw) {
    if (m === null || typeof m !== "object") continue;
    const { role, content } = m as { role?: unknown; content?: unknown };
    if ((role !== "user" && role !== "assistant") || typeof content !== "string") continue;
    if (content.trim() === "") continue;
    out.push({ role, content: content.slice(0, MAX_MESSAGE_CHARS) });
  }
  return out.slice(-MAX_HISTORY_MESSAGES);
}

interface OpenAiToolCall {
  id?: string;
  function?: { name?: string; arguments?: string };
}

interface OpenAiMessage {
  content?: string | null;
  tool_calls?: OpenAiToolCall[];
}

// Some local models wrap reasoning in <think> tags; it is not operator-facing.
function visibleText(content: string | null | undefined): string {
  return (content ?? "").replace(/<think>[\s\S]*?<\/think>/g, "").trim();
}

export class ModelHttpError extends Error {
  constructor(readonly status: number) {
    super(`model endpoint returned HTTP ${status}`);
  }
}

export interface ModelTurnResult {
  items: ChatItem[];
  loop: LoopOutcome["outcome"];
}

export async function runModelTurn(opts: {
  baseUrl: string;
  model: string;
  apiKey?: string;
  systemPrompt: string;
  history: HistoryMessage[];
  dispatcher: Dispatcher;
  signal: AbortSignal;
  maxToolCalls?: number;
  fetchImpl?: typeof fetch;
}): Promise<ModelTurnResult> {
  const doFetch = opts.fetchImpl ?? fetch;
  const endpoint = `${opts.baseUrl.replace(/\/$/, "")}/chat/completions`;
  const tools = openAiTools();
  const messages: unknown[] = [
    { role: "system", content: `${opts.systemPrompt}

${TOOL_POLICY}` },
    ...opts.history,
  ];
  const items: ChatItem[] = [];

  // Tool calls from the latest model response that have not been run yet, and
  // the id of the one being dispatched (its result is sent back under that id).
  const queue: { emission: ModelEmission; callId: string }[] = [];
  let currentCallId = "";
  let modelCalls = 0;
  let lastEmission: ModelEmission | undefined;

  async function complete(): Promise<OpenAiMessage> {
    modelCalls += 1;
    const headers: Record<string, string> = { "content-type": "application/json" };
    if (opts.apiKey) headers.authorization = `Bearer ${opts.apiKey}`;
    const res = await doFetch(endpoint, {
      method: "POST",
      headers,
      body: JSON.stringify({ model: opts.model, messages, tools, tool_choice: "auto", stream: false }),
      signal: opts.signal,
    });
    // QA-012: a 4xx/5xx from the model proxy is a failed inference, not an
    // empty successful turn.
    if (!res.ok) throw new ModelHttpError(res.status);
    const body = (await res.json()) as { choices?: { message?: OpenAiMessage }[] };
    return body.choices?.[0]?.message ?? {};
  }

  async function nextEmission(): Promise<ModelEmission> {
    if (queue.length === 0) {
      const message = await complete();
      const text = visibleText(message.content);
      const calls = message.tool_calls ?? [];
      messages.push({
        role: "assistant",
        content: message.content ?? "",
        ...(calls.length > 0 ? { tool_calls: calls } : {}),
      });
      if (calls.length === 0) {
        return text ? { kind: "prose", text } : { kind: "none" };
      }
      // Narration that accompanies tool calls renders as plain prose.
      if (text) items.push({ kind: "prose", text });
      for (const [i, call] of calls.entries()) {
        const callId = call.id ?? `call_${modelCalls}_${i}`;
        const name = call.function?.name ?? "";
        let args: unknown;
        try {
          args = JSON.parse(call.function?.arguments || "{}");
        } catch {
          queue.push({ emission: { kind: "malformed", toolName: name, rawJson: call.function?.arguments }, callId });
          continue;
        }
        queue.push({ emission: { kind: "tool_call", toolName: name, args }, callId });
      }
    }
    const next = queue.shift()!;
    currentCallId = next.callId;
    if (next.emission.kind !== "tool_call") {
      items.push({ kind: "tool_intent", toolName: next.emission.toolName });
    }
    return next.emission;
  }

  let loop: LoopOutcome;
  try {
    loop = await runAgentLoop({
      nextEmission: async () => {
        const emission = await nextEmission();
        lastEmission = emission;
        if (emission.kind === "prose") items.push({ kind: "prose", text: emission.text ?? "" });
        return emission;
      },
      dispatch: async (toolName, args) => {
        const result = await opts.dispatcher.execute(toolName, args);
        items.push({ kind: "tool_result", toolResult: result });
        messages.push({
          role: "tool",
          tool_call_id: currentCallId,
          content: fenceSessionData(JSON.stringify({ status: result.status, body: result.body })),
        });
        return result;
      },
      maxToolCalls: opts.maxToolCalls ?? MAX_TOOL_CALLS_PER_TURN,
    });
  } catch (err) {
    // A failure on the first model call means the model is unavailable; the
    // caller maps it to agent_unavailable. A failure after tools already ran
    // must not hide those results, so the turn ends with what happened.
    if (modelCalls <= 1 && items.length === 0) throw err;
    items.push({
      kind: "notice",
      text: opts.signal.aborted
        ? "The local model stopped responding before the turn finished. The results above are the actions that ran."
        : "The local model returned an error before the turn finished. The results above are the actions that ran.",
    });
    return { items: correctContradictingProse(items), loop: "could_not_complete" };
  }

  if (loop.outcome === "step_limit") {
    items.push({ kind: "notice", text: STEP_LIMIT_TEXT });
  } else if (loop.outcome === "could_not_complete") {
    // An unknown tool or args that fail the schema: nothing was sent (INV-015).
    if (lastEmission?.kind === "tool_call") {
      items.push({ kind: "tool_intent", toolName: lastEmission.toolName });
    }
    items.push({ kind: "notice", text: loop.message });
  }
  return { items: correctContradictingProse(items), loop: loop.outcome };
}
