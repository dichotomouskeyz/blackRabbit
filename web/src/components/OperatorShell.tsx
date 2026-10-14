// The operator shell: an agent-first layout with the session list and
// capability matrix in the left rail, the chat in the centre, and a context panel
// (manual create form or the selected session) on the right.
//
// INV-007: when the agent route is unavailable, the chat input is disabled and
// shows the sub-case message (not_configured / unreachable / stalled), while the
// session list, create form, and capability matrix STILL render and stay
// interactive — the model degrading must not disable the non-chat surfaces.

"use client";

import { useEffect, useRef, useState } from "react";
import type { JSX, KeyboardEvent } from "react";
import type { CapabilityState } from "@/lib/capabilities";
import type { AgentUnavailable } from "@/lib/agent-core";
import type { ApiClient, ApiResult, SessionSummary } from "@/lib/api-client";
import { createApiClient } from "@/lib/api-client";
import { SessionText } from "@/components/SessionText";
import { CreateSessionForm } from "@/components/CreateSessionForm";
import { CapabilityControl } from "@/components/CapabilityControl";
import { OutcomeMessage } from "@/components/OutcomeMessage";
import { InFlight } from "@/components/InFlight";
import { ToolResultCard, type ChatItem } from "@/components/ToolResultCard";

export interface ChatTurn {
  id: number;
  role: "operator" | "agent";
  // Operator text, or nothing for an agent turn.
  text?: string;
  // The agent's rendered items for this turn.
  items?: ChatItem[];
  // Local wall-clock time, HH:MM.
  at?: string;
}

export interface OperatorShellProps {
  // The capability matrix state (drives the capability controls).
  capabilities: CapabilityState;
  // The sessions to render in the durable session list.
  sessions: SessionSummary[];
  // The typed API client driving real create-session submissions (QA-004). The
  // shell NEVER fabricates a success — handleCreate returns the client's actual
  // ApiResult, so a 422/409/503 from the transport surfaces as the real outcome.
  // Optional only so existing call sites compile; when omitted a default client
  // (real fetch transport) is used — still never a synthetic success.
  apiClient?: ApiClient;
  // When set, the agent route is unavailable: chat input disabled with the
  // sub-case message; non-chat surfaces remain interactive.
  agentUnavailable?: AgentUnavailable | null;
  // Optional observer for created bodies (telemetry/tests); never substitutes for
  // the real transport call.
  onCreateSession?: (body: Record<string, unknown>) => void;

  // --- Supplied by OperatorApp; all optional so the shell renders standalone. ---
  turns?: ChatTurn[];
  // An agent turn is in flight (INV-016).
  pending?: boolean;
  onSend?: (text: string) => void;
  onRetryAgent?: () => void;
  // A failed GET /sessions, rendered in place of the list (INV-006).
  sessionsError?: ApiResult<unknown> | null;
  vocab?: { compounds: string[]; dose_units: string[] };
  health?: { version: string; contract_version: string } | null;
  // Contract-version mismatch banner text (INV-018).
  banner?: string | null;
  // Called after a manual create succeeds, so the app can refresh the list.
  onSessionCreated?: (sessionId: string) => void;
  // A session to open in the context panel, e.g. one the agent just created.
  focusSessionId?: string | null;
}

// Matrix rows that describe the API itself rather than an operator action.
const INFRA_CAPABILITIES = new Set(["health", "vocab", "capabilities"]);

// Prompts a live capability row places in the composer.
const CAPABILITY_PROMPTS: Record<string, string> = {
  list_sessions: "List sessions",
  session_status: "Status of session ",
  arc_review: "Is ARC review available for ",
};

const SUGGESTIONS = ["List sessions", "Create a session", "What is blocked in this build and why"];

function shortId(id: string): string {
  return id.length > 8 ? id.slice(0, 8) : id;
}

function formatTime(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function OperatorShell({
  capabilities,
  sessions,
  apiClient,
  agentUnavailable,
  onCreateSession,
  turns = [],
  pending = false,
  onSend,
  onRetryAgent,
  sessionsError,
  vocab,
  health,
  banner,
  onSessionCreated,
  focusSessionId,
}: OperatorShellProps): JSX.Element {
  const chatDisabled = Boolean(agentUnavailable);
  const [client] = useState<ApiClient>(() => apiClient ?? createApiClient());
  const [draft, setDraft] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<ApiResult<unknown> | null>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const threadEnd = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (focusSessionId) setSelected(focusSessionId);
  }, [focusSessionId]);

  // The composer moves from the empty state to the thread footer after the
  // first turn; keep focus on it once each reply lands.
  useEffect(() => {
    if (!pending && turns.length > 0) inputRef.current?.focus();
  }, [pending, turns.length]);

  useEffect(() => {
    threadEnd.current?.scrollIntoView?.({ block: "end" });
  }, [turns.length, pending]);

  useEffect(() => {
    if (!selected) {
      setDetail(null);
      return;
    }
    let live = true;
    setDetail(null);
    void client.getSessionStatus(selected).then((res) => {
      if (live) setDetail(res);
    });
    return () => {
      live = false;
    };
  }, [selected, client]);

  async function handleCreate(
    body: Record<string, unknown>,
  ): Promise<ApiResult<{ session_id: string }>> {
    onCreateSession?.(body);
    // QA-004: drive the REAL ApiClient.createSession and return its actual result.
    // A 422/409/503 from the transport is surfaced verbatim — never a hardcoded
    // synthetic success (PRH-004).
    const res = await client.createSession(body);
    if (res.ok && typeof res.data?.session_id === "string") {
      onSessionCreated?.(res.data.session_id);
      setSelected(res.data.session_id);
    }
    return res;
  }

  function send(text: string) {
    const trimmed = text.trim();
    if (!trimmed || chatDisabled || pending) return;
    onSend?.(trimmed);
    setDraft("");
  }

  function handleKey(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send(draft);
    }
  }

  function prefill(capability: string) {
    if (capability === "create_session") {
      setSelected(null);
      return;
    }
    const prompt = CAPABILITY_PROMPTS[capability];
    if (prompt) {
      setDraft(prompt);
      inputRef.current?.focus();
    }
  }

  const composer = (
    <div className="composer">
      <textarea
        ref={inputRef}
        data-testid="chat-input"
        className="composer-input"
        rows={1}
        placeholder="Ask the operator agent"
        aria-label="Message the operator agent"
        disabled={chatDisabled}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={handleKey}
      />
      <button
        type="button"
        className="send"
        aria-label="Send"
        disabled={chatDisabled || pending || draft.trim() === ""}
        onClick={() => send(draft)}
      >
        <svg viewBox="0 0 20 20" aria-hidden="true">
          <path d="M3 10h12M11 5l5 5-5 5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
    </div>
  );

  const unavailableNotice = agentUnavailable ? (
    <div className="agent-unavailable" data-agent-unavailable={agentUnavailable.reason}>
      <p>
        <SessionText value={agentUnavailable.message} />
      </p>
      {onRetryAgent ? (
        <button type="button" className="btn btn-ghost btn-sm" onClick={onRetryAgent}>
          Retry
        </button>
      ) : null}
    </div>
  ) : null;

  const visibleCaps = capabilities.rows.filter((r) => !INFRA_CAPABILITIES.has(r.capability));

  return (
    <div className="app" data-operator-shell>
      <aside className="rail">
        <div className="brand">
          <span className="wordmark">
            black<strong>Rabbit</strong>
          </span>
        </div>

        {/* Durable session list — unaffected by an unavailable model. */}
        <section className="rail-section rail-sessions" data-testid="session-list" aria-label="sessions">
          <header className="rail-head">
            <h2>Sessions</h2>
            <span className="count">{sessions.length}</span>
            <button type="button" className="icon-btn" aria-label="New session" onClick={() => setSelected(null)}>
              <svg viewBox="0 0 20 20" aria-hidden="true">
                <path d="M10 4v12M4 10h12" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
              </svg>
            </button>
          </header>
          {sessionsError ? (
            <div className="rail-note">
              <OutcomeMessage result={sessionsError} />
            </div>
          ) : sessions.length === 0 ? (
            <p className="rail-note">No sessions yet. Create one to get started.</p>
          ) : (
            <ul className="session-list">
              {sessions.map((s) => (
                <li key={s.id}>
                  <button
                    type="button"
                    className={`session-row${selected === s.id ? " is-selected" : ""}`}
                    aria-current={selected === s.id ? "true" : undefined}
                    onClick={() => setSelected(s.id)}
                  >
                    <span className="session-id mono">
                      <SessionText value={s.id} />
                    </span>
                    <span className={`status status-${s.status === "active" ? "active" : "other"}`}>
                      <span className="dot" aria-hidden="true" />
                      <SessionText value={s.status} />
                    </span>
                    <span className="session-meta">
                      {s.compound ? <SessionText value={s.compound} /> : null}
                      {s.created_at ? <span>{formatTime(s.created_at)}</span> : null}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>

        {/* Capability matrix — runtime-sourced (INV-001); interactive regardless. */}
        <section className="rail-section" data-testid="capability-matrix" aria-label="capabilities">
          <header className="rail-head">
            <h2>Capabilities</h2>
          </header>
          {!capabilities.loaded ? <p className="rail-note">Capability matrix not loaded. Every action stays disabled until it loads.</p> : null}
          <ul className="cap-list">
            {visibleCaps.map((row) => (
              <li key={row.capability}>
                <CapabilityControl
                  capability={row.capability}
                  state={capabilities}
                  onInvoke={() => prefill(row.capability)}
                  label={row.capability}
                />
              </li>
            ))}
          </ul>
        </section>

        <footer className="rail-foot mono">
          {health ? (
            <span>
              API <SessionText value={health.version} /> · contract <SessionText value={health.contract_version} />
            </span>
          ) : (
            <span>API not connected</span>
          )}
        </footer>
      </aside>

      <main className="main">
        {banner ? (
          <div className="banner" role="alert">
            <SessionText value={banner} />
          </div>
        ) : null}

        {/* Chat surface — degrades INDEPENDENTLY of the rest of the shell (INV-007). */}
        <section className="chat" data-testid="chat-region" aria-label="assistant chat">
          <h2 className="sr-only">Assistant</h2>
          {turns.length === 0 && !pending ? (
            <div className="chat-empty">
              {agentUnavailable ? null : <p className="chat-status mono">Local model · {chatDisabled ? "unavailable" : "ready"}</p>}
              {unavailableNotice}
              {composer}
              <div className="suggestions">
                {SUGGESTIONS.map((s) => (
                  <button key={s} type="button" className="chip" disabled={chatDisabled || !onSend} onClick={() => send(s)}>
                    {s}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <>
              <div className="thread">
                {turns.map((t) =>
                  t.role === "operator" ? (
                    <div key={t.id} className="turn turn-operator">
                      <div className="bubble">
                        <span className="turn-meta">
                          <span className="who who-operator">Operator</span>
                          {t.at ? <span>{t.at}</span> : null}
                        </span>
                        <p>
                          <SessionText value={t.text ?? ""} />
                        </p>
                      </div>
                    </div>
                  ) : (
                    <div key={t.id} className="turn turn-agent">
                      <span className="avatar" aria-hidden="true">
                        bR
                      </span>
                      <div className="turn-body">
                        <span className="turn-meta">
                          <span className="who">blackRabbit</span>
                          {t.at ? <span>{t.at}</span> : null}
                        </span>
                        {(t.items ?? []).map((item, i) => (
                          <ToolResultCard key={i} item={item} />
                        ))}
                      </div>
                    </div>
                  ),
                )}
                {pending ? (
                  <div className="turn turn-agent">
                    <span className="avatar" aria-hidden="true">
                      bR
                    </span>
                    <div className="turn-body">
                      <InFlight phase="awaiting" label="agent" />
                    </div>
                  </div>
                ) : null}
                <div ref={threadEnd} />
              </div>
              <div className="chat-foot">
                {unavailableNotice}
                {composer}
              </div>
            </>
          )}
        </section>
      </main>

      <aside className="context">
        {selected ? (
          <section className="panel" aria-label="session detail">
            <header className="panel-head">
              <h2 className="mono">Session {shortId(selected)}</h2>
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => setSelected(null)}>
                New session
              </button>
            </header>
            {detail === null ? (
              <InFlight phase="awaiting" label="session_status" />
            ) : detail.ok ? (
              <SessionDetail body={detail.data} />
            ) : (
              <OutcomeMessage result={detail} />
            )}
          </section>
        ) : (
          /* Create form — interactive regardless of model availability. */
          <section className="panel" aria-label="create session">
            <header className="panel-head">
              <h2>New session</h2>
            </header>
            <CreateSessionForm key={vocab ? "vocab" : "no-vocab"} onSubmit={handleCreate} vocab={vocab} />
          </section>
        )}
      </aside>
    </div>
  );
}

const DETAIL_LABELS: Record<string, string> = {
  id: "Session ID",
  status: "Status",
  started_at: "Started",
  closed_at: "Closed",
  watermark_state: "Watermark",
};

function SessionDetail({ body }: { body: unknown }): JSX.Element {
  const record = body !== null && typeof body === "object" ? (body as Record<string, unknown>) : {};
  return (
    <dl className="kv detail">
      {Object.keys(DETAIL_LABELS).map((key) => (
        <div key={key} className="kv-row">
          <dt>{DETAIL_LABELS[key]}</dt>
          <dd className="mono">
            <SessionText value={record[key] == null ? "—" : String(record[key])} />
          </dd>
        </div>
      ))}
    </dl>
  );
}
