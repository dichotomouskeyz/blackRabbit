// Server-side agent route → local LiteLLM model (frontend-shell TB-006).
// App Router route handler. no-store/dynamic per INV-011; the wired turn-driving
// logic lives in agent-core.ts (QA-001/002 GREEN fix): the POST calls the wired
// handler with REAL deps (real ApiClient + a runtime capability matrix), so the
// agent-loop helpers (runAgentLoop, chatItemsFromTurn, buildAgentRequest,
// createDispatcher) all sit on the live product path, not just under tests.

import {
  agentConfigStatus,
  handleAgentRequest,
  getRouteDeps,
  type RouteDeps,
} from "@/lib/agent-core";
import { createApiClient } from "@/lib/api-client";
import { loadCapabilityState, COLD_START_STATE } from "@/lib/capabilities";

// INV-011: the agent route is dynamic / no-store (no Next.js Data Cache / RSC
// caching of session-derived responses).
export const dynamic = "force-dynamic";
export const fetchCache = "force-no-store";

// Build the REAL route deps the product uses (QA-001): a typed ApiClient over the
// FastAPI surface plus the runtime-sourced capability matrix. The dispatcher the
// wired handler builds from these is the live model→tool→API path. AGENT_* env is
// read inside handleAgentRequest (server-only); tenancy is never attached (INV-004).
async function realRouteDeps(): Promise<RouteDeps> {
  const apiBaseUrl = process.env.API_BASE_URL ?? "";
  const client = createApiClient({ baseUrl: apiBaseUrl });
  // Runtime capability matrix; fail closed to cold-start if /capabilities is down.
  let capabilities = COLD_START_STATE;
  try {
    capabilities = await loadCapabilityState(client);
  } catch {
    capabilities = COLD_START_STATE;
  }
  return { client, capabilities };
}

// INV-007: the POST handler delegates to the wired core handler. Tests inject route
// deps (model-completion seam, client, matrix) via setRouteDeps; in production we
// supply the real client + matrix. The real env read (AGENT_BASE_URL) and the
// bounded-timeout-wrapped model completion live behind handleAgentRequest.
export async function POST(req: Request): Promise<Response> {
  const injected = getRouteDeps();
  const deps = injected ?? (await realRouteDeps());
  return handleAgentRequest(req, deps);
}

// GET reports whether the agent route is configured, without calling the model
// and without echoing AGENT_BASE_URL (INV-009). The browser uses it to disable
// chat up front for the not_configured / egress_refused cases.
export async function GET(): Promise<Response> {
  const injected = getRouteDeps();
  const baseUrl = injected && "baseUrl" in injected ? injected.baseUrl : process.env.AGENT_BASE_URL;
  const status = agentConfigStatus(baseUrl);
  return new Response(JSON.stringify(status ?? { available: true }), {
    status: 200,
    headers: { "content-type": "application/json", "cache-control": "no-store" },
  });
}
