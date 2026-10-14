// Renders one assistant chat item (frontend-shell INV-012). A success card only
// renders for an API-backed ok result; prose alone never renders as a completed
// action. All session-derived text goes through SessionText (INV-005a).

import type { JSX } from "react";
import type { ToolResult } from "@/lib/dispatcher";
import type { ApiResult } from "@/lib/api-client";
import { OutcomeMessage } from "@/components/OutcomeMessage";
import { SessionText } from "@/components/SessionText";

export interface ChatItem {
  // An assistant message is prose, a tool result, a tool intent, a CORRECTION
  // of success-claiming prose that a same-turn failed tool result contradicts
  // (QA-003 / PRH-004), or a NOTICE about how the turn ended (step limit,
  // model error mid-turn).
  kind: "prose" | "tool_result" | "tool_intent" | "correction" | "notice";
  text?: string;
  toolResult?: ToolResult;
  toolName?: string;
}

export interface ToolResultCardProps {
  item: ChatItem;
}

const FAILURE_LABEL: Record<number, string> = {
  0: "not sent",
  404: "not found",
  409: "not available",
  422: "invalid",
  503: "unavailable",
};

export function ToolResultCard({ item }: ToolResultCardProps): JSX.Element {
  if (item.kind === "prose") {
    return (
      <div className="msg-prose" data-chat-item="prose">
        <SessionText value={item.text ?? ""} />
      </div>
    );
  }

  if (item.kind === "correction") {
    // The original false claim is NOT rendered (QA-003).
    return (
      <div className="msg-alert" data-chat-item="correction" data-tool={item.toolName}>
        <AlertIcon />
        <p>
          <SessionText value={item.text ?? "The action did not complete."} />
        </p>
      </div>
    );
  }

  if (item.kind === "tool_intent") {
    return (
      <div className="msg-alert" data-chat-item="tool-intent" data-tool={item.toolName}>
        <AlertIcon />
        <p>
          The assistant intended to run <code>{item.toolName ?? "an action"}</code>, but the action did not complete.
        </p>
      </div>
    );
  }

  if (item.kind === "notice") {
    return (
      <div className="msg-alert" data-chat-item="notice">
        <AlertIcon />
        <p>
          <SessionText value={item.text ?? ""} />
        </p>
      </div>
    );
  }

  const result = item.toolResult;
  if (!result) {
    return (
      <div className="msg-alert" data-chat-item="tool-result">
        <AlertIcon />
        <p>The action did not complete.</p>
      </div>
    );
  }

  // A success card requires an actual API-backed ok result (INV-012).
  if (result.apiBacked && result.ok) {
    const verb = result.toolName === "create_session" ? "created" : "completed";
    return (
      <div className="tool-card" data-testid="tool-success-card" data-chat-item="tool-result" data-tool={result.toolName}>
        <div className="tool-card-head">
          <span className="tool-name">
            <span className="tool-prompt">&gt;_</span> <SessionText value={result.toolName} />
          </span>
          <span className="badge badge-ok">
            {result.status} · {verb}
          </span>
        </div>
        <ResultBody body={result.body} />
      </div>
    );
  }

  // A failed / 409 tool result renders the refusal, never success.
  const apiResult: ApiResult<unknown> = { ok: false, status: result.status, body: result.body };
  return (
    <div className="tool-card tool-card-refused" data-chat-item="tool-result-refusal" data-tool={result.toolName}>
      <div className="tool-card-head">
        <span className="tool-name">
          <span className="tool-prompt">&gt;_</span> <SessionText value={result.toolName} />
        </span>
        <span className="badge badge-refused">
          {result.status > 0 ? `${result.status} · ` : ""}
          {FAILURE_LABEL[result.status] ?? "failed"}
        </span>
      </div>
      <div className="tool-card-body">
        <OutcomeMessage result={apiResult} />
      </div>
    </div>
  );
}

type Primitive = string | number | boolean | null;

function isPrimitive(v: unknown): v is Primitive {
  return v === null || ["string", "number", "boolean"].includes(typeof v);
}

function show(v: Primitive): string {
  return v === null ? "—" : String(v);
}

// Render an API success body as a key/value list or a row table. Values are
// session-derived, so every one goes through SessionText.
function ResultBody({ body }: { body: unknown }): JSX.Element | null {
  const rows = Array.isArray(body)
    ? body
    : body !== null && typeof body === "object"
      ? Object.values(body as Record<string, unknown>).find(Array.isArray)
      : undefined;

  if (rows) {
    const records = rows.filter(
      (r): r is Record<string, unknown> => r !== null && typeof r === "object" && !Array.isArray(r),
    );
    if (records.length === 0) {
      return <p className="tool-card-empty">No rows returned.</p>;
    }
    const columns = Object.keys(records[0]).filter((k) => isPrimitive(records[0][k])).slice(0, 4);
    const shown = records.slice(0, 10);
    return (
      <div className="tool-card-body">
        <table className="kv-table">
          <thead>
            <tr>
              {columns.map((c) => (
                <th key={c}>{c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {shown.map((r, i) => (
              <tr key={i}>
                {columns.map((c) => (
                  <td key={c}>
                    <SessionText value={isPrimitive(r[c]) ? show(r[c] as Primitive) : "…"} />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {records.length > shown.length ? (
          <p className="tool-card-more">{records.length - shown.length} more not shown</p>
        ) : null}
      </div>
    );
  }

  if (body !== null && typeof body === "object") {
    const entries = Object.entries(body as Record<string, unknown>).filter(([, v]) => isPrimitive(v));
    if (entries.length === 0) return null;
    return (
      <dl className="tool-card-body kv">
        {entries.map(([k, v]) => (
          <div key={k} className="kv-row">
            <dt>{k}</dt>
            <dd>
              <SessionText value={show(v as Primitive)} />
            </dd>
          </div>
        ))}
      </dl>
    );
  }

  return null;
}

function AlertIcon(): JSX.Element {
  return (
    <svg className="alert-icon" viewBox="0 0 20 20" aria-hidden="true">
      <circle cx="10" cy="10" r="8.25" fill="none" stroke="currentColor" strokeWidth="1.5" />
      <path d="M10 5.5v5.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      <circle cx="10" cy="14" r="1" fill="currentColor" />
    </svg>
  );
}
