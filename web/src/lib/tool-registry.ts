// Pinned, closed agent tool registry with typed, bounded args (frontend-shell INV-003 / PRH-002).
// STUB:TDD — the registry shape, the banned-key list, and the pinned tool names
// are load-bearing; bodies/schemas are filled in GREEN.

import { z } from "zod";

// Defense-in-depth: no tool arg schema may admit any of these keys (INV-003).
export const BANNED_ARG_KEYS = [
  "sponsor_id",
  "site_id",
  "sql",
  "query",
  "url",
  "endpoint",
  "path",
  "cmd",
  "shell",
] as const;

// The pinned, closed set of tool names. Object.keys(TOOL_REGISTRY) must equal this.
export const PINNED_TOOL_NAMES = [
  "list_sessions",
  "session_status",
  "create_session",
  "view_live_signals",
  "view_arc",
  "start_capture",
  "stop_capture",
  "log_marker",
  "close_session",
  "run_arc",
] as const;

// Max length bound on free-text fields (defense-in-depth against stored-injection).
export const MAX_FREETEXT_LEN = 256;

export interface ToolDef {
  name: string;
  // Compile-time constant endpoint: "METHOD /path" — never derived from an arg.
  method: string;
  endpoint: string;
  // The capability this tool maps to (for capability gating).
  capability: string;
  // Strict zod schema (.strict()) over the tool's args.
  schema: z.ZodTypeAny;
}

// UUID validation for session_id / participant_id args (any UUID version; INV-003).
// Exported as the single source of truth so the create form (INV-011) validates
// participant_id with the same pattern the agent tools use.
export const UUID_RE =
  /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/;

const sessionIdSchema = z.string().regex(UUID_RE, "session_id must be a UUID");

// A length-bounded free-text field (defense-in-depth against stored-injection).
const freeText = () => z.string().max(MAX_FREETEXT_LEN);

// create_session accepts only the operator-ui allow-list fields (.strict()), named
// exactly as api/app.py CreateSessionRequest names them (that model is
// extra="forbid", so any other key is a 422). Tenancy keys are excluded by
// construction (INV-004) and are also in the global BANNED_ARG_KEYS guard.
const createSessionSchema = z
  .object({
    compound: freeText(),
    capture_source: freeText(),
    participant_id: sessionIdSchema,
    compound_dose: z.number().optional(),
    compound_dose_unit: freeText().optional(),
    protocol_arm: freeText().optional(),
    room_id: freeText().optional(),
    eeg_sensor_form: freeText().optional(),
    eeg_electrode_system: freeText().optional(),
    eeg_electrode_type: freeText().optional(),
    hrv_electrode_placement: freeText().optional(),
    hrv_electrode_type: freeText().optional(),
    eda_electrode_placement: freeText().optional(),
    eda_electrode_type: freeText().optional(),
    eda_skin_prep: freeText().optional(),
  })
  .strict();

const sessionIdOnlySchema = z.object({ session_id: sessionIdSchema }).strict();

const emptySchema = z.object({}).strict();

// The session_status enum (migration 002).
export const SESSION_STATUSES = ["initializing", "active", "closing", "closed", "failed", "voided"] as const;

// list_sessions filters (session-query SQ-005). session_id here is a prefix
// filter, not a path parameter; participant_id must be a full UUID.
const listSessionsSchema = z
  .object({
    session_id: z.string().regex(/^[0-9a-fA-F-]{1,36}$/, "session_id must be a UUID prefix").optional(),
    participant_id: sessionIdSchema.optional(),
    status: z.enum(SESSION_STATUSES).optional(),
    compound: freeText().optional(),
    created_from: z.string().max(40).optional(),
    created_before: z.string().max(40).optional(),
    limit: z.number().int().min(1).max(500).optional(),
  })
  .strict();

const logMarkerSchema = z
  .object({
    session_id: sessionIdSchema,
    zone_label: freeText().optional(),
    marker_label: freeText().optional(),
  })
  .strict();

export const TOOL_REGISTRY: Record<string, ToolDef> = {
  list_sessions: { name: "list_sessions", method: "GET", endpoint: "/sessions", capability: "list_sessions", schema: listSessionsSchema },
  session_status: { name: "session_status", method: "GET", endpoint: "/sessions/{session_id}/status", capability: "session_status", schema: sessionIdOnlySchema },
  create_session: { name: "create_session", method: "POST", endpoint: "/sessions", capability: "create_session", schema: createSessionSchema },
  view_live_signals: { name: "view_live_signals", method: "GET", endpoint: "/capabilities", capability: "live_signals", schema: emptySchema },
  view_arc: { name: "view_arc", method: "GET", endpoint: "/capabilities", capability: "arc_review", schema: emptySchema },
  start_capture: { name: "start_capture", method: "POST", endpoint: "/sessions/{session_id}/capture:start", capability: "capture_start", schema: sessionIdOnlySchema },
  stop_capture: { name: "stop_capture", method: "POST", endpoint: "/sessions/{session_id}/capture:stop", capability: "capture_stop", schema: sessionIdOnlySchema },
  log_marker: { name: "log_marker", method: "POST", endpoint: "/sessions/{session_id}/markers", capability: "log_marker", schema: logMarkerSchema },
  close_session: { name: "close_session", method: "POST", endpoint: "/sessions/{session_id}/close", capability: "close_session", schema: sessionIdOnlySchema },
  run_arc: { name: "run_arc", method: "POST", endpoint: "/sessions/{session_id}/arc:run", capability: "arc_run", schema: sessionIdOnlySchema },
};

// Helper exposed for tests: validate args for a named tool. Fails closed:
//  - unknown tool name → reject
//  - any BANNED_ARG_KEYS key present → reject (defense-in-depth, INV-003/PRH-002)
//  - otherwise validate against the tool's strict schema
export function validateToolArgs(
  toolName: string,
  args: unknown,
): { ok: true; value: unknown } | { ok: false; error: string } {
  const def = TOOL_REGISTRY[toolName];
  if (!def) {
    return { ok: false, error: `unknown tool: ${toolName}` };
  }
  if (args !== null && typeof args === "object" && !Array.isArray(args)) {
    for (const key of Object.keys(args as Record<string, unknown>)) {
      if ((BANNED_ARG_KEYS as readonly string[]).includes(key)) {
        return { ok: false, error: `banned argument key: ${key}` };
      }
    }
  }
  const parsed = def.schema.safeParse(args);
  if (!parsed.success) {
    return { ok: false, error: parsed.error.message };
  }
  return { ok: true, value: parsed.data };
}
