// The mounted operator app (QA-013): loads the runtime capability matrix, the
// session list, vocab, and health through the real ApiClient, and drives chat
// turns through the server-side agent route. All state is React state only; no
// session-derived content is persisted anywhere (INV-011).

"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { JSX } from "react";
import { createApiClient, type ApiResult, type SessionSummary } from "@/lib/api-client";
import { COLD_START_STATE, loadCapabilityState, type CapabilityState } from "@/lib/capabilities";
import { BUILT_AGAINST_CONTRACT_VERSION, contractVersionBanner } from "@/lib/error-messages";
import type { AgentUnavailable } from "@/lib/agent-core";
import { OperatorShell, type ChatTurn } from "@/components/OperatorShell";
import type { ChatItem } from "@/components/ToolResultCard";
import {
  EMPTY_FILTER_FORM,
  toApiFilters,
  type SessionFilterForm,
} from "@/lib/session-filter-form";

// Browser requests go to the Next.js server, which rewrites /backend/* to
// API_BASE_URL (next.config.mjs), so the FastAPI surface needs no CORS policy.
const BACKEND_PREFIX = "/backend";

function now(): string {
  return new Date().toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

function isUnavailable(body: unknown): body is AgentUnavailable {
  return (
    body !== null &&
    typeof body === "object" &&
    (body as { error?: unknown }).error === "agent_unavailable" &&
    typeof (body as { message?: unknown }).message === "string"
  );
}

// The history sent with each turn: operator text, and for agent turns the prose
// plus which tools ran and their status codes. Tool bodies are not resent.
function historyOf(turns: ChatTurn[]): { role: "user" | "assistant"; content: string }[] {
  return turns.map((t) => {
    if (t.role === "operator") return { role: "user" as const, content: t.text ?? "" };
    const lines = (t.items ?? []).map((it) => {
      if (it.kind === "tool_result" && it.toolResult) {
        return `[${it.toolResult.toolName} returned ${it.toolResult.status}]`;
      }
      return it.text ?? "";
    });
    return { role: "assistant" as const, content: lines.filter(Boolean).join("\n") };
  });
}

export function OperatorApp(): JSX.Element {
  const client = useMemo(() => createApiClient({ baseUrl: BACKEND_PREFIX }), []);
  const [capabilities, setCapabilities] = useState<CapabilityState>(COLD_START_STATE);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [sessionsError, setSessionsError] = useState<ApiResult<unknown> | null>(null);
  const [vocab, setVocab] = useState<{ compounds: string[]; dose_units: string[] } | undefined>();
  const [health, setHealth] = useState<{ version: string; contract_version: string } | null>(null);
  const [agentUnavailable, setAgentUnavailable] = useState<AgentUnavailable | null>(null);
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [pending, setPending] = useState(false);
  const [focusSessionId, setFocusSessionId] = useState<string | null>(null);
  const [filterForm, setFilterForm] = useState<SessionFilterForm>(EMPTY_FILTER_FORM);
  // The filters the list was last requested with; refreshes reuse them.
  const filtersRef = useRef(toApiFilters(EMPTY_FILTER_FORM).filters);
  const { problems: filterProblems } = toApiFilters(filterForm);

  const refreshSessions = useCallback(async () => {
    const res = await client.listSessions(filtersRef.current);
    if (res.ok) {
      setSessions(res.data.sessions ?? []);
      setSessionsError(null);
    } else {
      setSessionsError(res);
    }
  }, [client]);

  const checkAgent = useCallback(async () => {
    try {
      const res = await fetch("/api/agent", { cache: "no-store" });
      const body: unknown = await res.json();
      setAgentUnavailable(isUnavailable(body) ? body : null);
    } catch {
      setAgentUnavailable(null);
    }
  }, []);

  useEffect(() => {
    void loadCapabilityState(client).then(setCapabilities);
    void refreshSessions();
    void client.getVocab().then((res) => {
      if (res.ok) setVocab(res.data);
    });
    void client.getHealth().then((res) => {
      if (res.ok) setHealth(res.data);
    });
    void checkAgent();
  }, [client, refreshSessions, checkAgent]);

  // Re-query when the filters change (SQ-006), after typing pauses, and only
  // once every filter is complete and valid.
  const firstFilterRun = useRef(true);
  useEffect(() => {
    if (firstFilterRun.current) {
      firstFilterRun.current = false;
      return;
    }
    const { filters, problems } = toApiFilters(filterForm);
    if (Object.keys(problems).length > 0) return;
    const timer = setTimeout(() => {
      filtersRef.current = filters;
      void refreshSessions();
    }, 250);
    return () => clearTimeout(timer);
  }, [filterForm, refreshSessions]);

  async function send(text: string) {
    const operatorTurn: ChatTurn = { id: Date.now(), role: "operator", text, at: now() };
    const next = [...turns, operatorTurn];
    setTurns(next);
    setPending(true);

    let items: ChatItem[];
    try {
      const res = await fetch("/api/agent", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ messages: historyOf(next) }),
        cache: "no-store",
      });
      const body: unknown = await res.json();
      if (isUnavailable(body)) {
        setAgentUnavailable(body);
        items = [{ kind: "notice", text: body.message }];
      } else {
        items = Array.isArray((body as { items?: unknown }).items)
          ? ((body as { items: ChatItem[] }).items)
          : [{ kind: "notice", text: "The agent route returned a response this console could not read." }];
      }
    } catch {
      items = [{ kind: "notice", text: "The agent route did not respond. Check that the Next.js server is running." }];
    }

    setTurns((prev) => [...prev, { id: Date.now() + 1, role: "agent", items, at: now() }]);
    setPending(false);

    // INV-011: a created session also lands in the durable session list, and
    // opens in the context panel.
    const created = items.find(
      (it) => it.kind === "tool_result" && it.toolResult?.ok && it.toolResult.toolName === "create_session",
    );
    if (created) {
      void refreshSessions();
      const sid = (created.toolResult?.body as { session_id?: unknown } | undefined)?.session_id;
      if (typeof sid === "string") setFocusSessionId(sid);
    }
  }

  const banner = health ? contractVersionBanner(health.contract_version, BUILT_AGAINST_CONTRACT_VERSION) : null;

  return (
    <OperatorShell
      capabilities={capabilities}
      sessions={sessions}
      apiClient={client}
      agentUnavailable={agentUnavailable}
      turns={turns}
      pending={pending}
      onSend={(text) => void send(text)}
      onRetryAgent={() => void checkAgent()}
      sessionsError={sessionsError}
      vocab={vocab}
      health={health}
      banner={banner?.text ?? null}
      onSessionCreated={() => void refreshSessions()}
      focusSessionId={focusSessionId}
      filterForm={filterForm}
      filterProblems={filterProblems}
      onFilterFormChange={setFilterForm}
      onSessionsChanged={() => void refreshSessions()}
    />
  );
}
