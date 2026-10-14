// Tool dispatcher seam (frontend-shell INV-002a / INV-008a / INV-012).
// STUB:TDD — runs execute(toolName, args) against the mapped fixed endpoint via
// the real client; never synthesizes success for a gated capability.

import type { ApiClient } from "@/lib/api-client";
import type { CapabilityState } from "@/lib/capabilities";
import { TOOL_REGISTRY, BANNED_ARG_KEYS } from "@/lib/tool-registry";

export interface ToolResult {
  toolName: string;
  // The structured outcome carried back to the chat. For a gated capability this
  // is the server 409 body; for create_session it is the real {session_id}.
  ok: boolean;
  status: number;
  // The raw server body (409 capability body, 422 body, or success payload).
  body: unknown;
  // True only when an API tool-result backs the claim (INV-012). Never synthesized.
  apiBacked: boolean;
}

export interface Dispatcher {
  execute(toolName: string, args: unknown): Promise<ToolResult>;
}

function asRecord(args: unknown): Record<string, unknown> {
  if (args !== null && typeof args === "object" && !Array.isArray(args)) {
    return args as Record<string, unknown>;
  }
  return {};
}

// Build the outbound body: drop banned keys (incl. a model-supplied endpoint/url/
// path) and the path-param session_id. The endpoint is the fixed registry constant
// — never derived from an arg (INV-002a/003/008a, PRH-002).
function sanitizeBody(args: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  const banned = new Set<string>([...(BANNED_ARG_KEYS as readonly string[]), "session_id"]);
  for (const [k, v] of Object.entries(args)) {
    if (banned.has(k)) continue;
    out[k] = v;
  }
  return out;
}

export function createDispatcher(
  client: ApiClient,
  _capabilities: CapabilityState,
): Dispatcher {
  return {
    async execute(toolName: string, args: unknown): Promise<ToolResult> {
      const def = TOOL_REGISTRY[toolName];
      if (!def) {
        // Out-of-registry tool: refuse without any outbound call (fail closed).
        return {
          toolName,
          ok: false,
          status: 0,
          body: { error: "unknown_tool", toolName },
          apiBacked: false,
        };
      }

      const record = asRecord(args);
      // Resolve the path strictly from the registry constant, substituting only
      // the fixed {session_id} path param — never a model-supplied endpoint/url.
      const sessionId = typeof record.session_id === "string" ? record.session_id : "";
      const path = def.endpoint.replace("{session_id}", encodeURIComponent(sessionId));

      const result =
        def.method.toUpperCase() === "GET"
          ? await client.call(def.method, path)
          : await client.call(def.method, path, sanitizeBody(record));

      return {
        toolName,
        ok: result.ok,
        status: result.status,
        body: result.ok ? (result as { data: unknown }).data : (result as { body: unknown }).body,
        apiBacked: true,
      };
    },
  };
}
