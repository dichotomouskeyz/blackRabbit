// Researcher-legible message mapping for every API outcome (frontend-shell INV-006 / INV-018).
// STUB:TDD — the mapping is the contract; bodies are filled in GREEN.

import type { ApiResult } from "@/lib/api-client";

export interface OperatorMessage {
  // Plain-language, researcher-facing text. Never a raw stack/JSON dump.
  text: string;
  // Optional severity for rendering.
  severity?: "info" | "warning" | "error";
  // For 422: the field-level detail, preserving form context.
  field?: string;
  validChoices?: string[];
  // Distinguishes a zero-state ("no sessions yet") from an error.
  kind?:
    | "capability_unavailable"
    | "backend_unavailable"
    | "agent_unavailable"
    | "tenancy_not_configured"
    | "validation"
    | "not_found"
    | "empty"
    | "version_mismatch"
    | "ok";
}

function bodyOf(result: ApiResult<unknown>): Record<string, unknown> {
  if (result.ok) return {};
  const b = (result as { body: unknown }).body;
  return b !== null && typeof b === "object" ? (b as Record<string, unknown>) : {};
}

function asString(v: unknown): string | null {
  return typeof v === "string" && v.length > 0 ? v : null;
}

// Map a 409 capability_unavailable body to plain-language operator copy. The raw
// gate id (e.g. OQ-004) is never shown verbatim; blocked_reason/gate may be null
// and must render without "(null)" or a crash (INV-006).
function capabilityUnavailableText(body: Record<string, unknown>): string {
  const capability = asString(body.capability);
  const reason = asString(body.blocked_reason);
  const subject = capability ? capability.replace(/_/g, " ") : "this action";
  if (reason) {
    return `This action (${subject}) is currently unavailable: ${reason}.`;
  }
  return `This action (${subject}) is currently unavailable in this build.`;
}

// 409 bodies about the session's own state rather than a gated capability.
const SESSION_CONFLICTS = new Set(["already_voided", "session_not_voidable", "session_busy", "session_voided"]);

// Map any API result to an operator-facing message.
export function messageForResult(result: ApiResult<unknown>): OperatorMessage {
  if (result.ok) {
    return { text: "Done.", severity: "info", kind: "ok" };
  }

  const body = bodyOf(result);
  const errorCode = asString(body.error);

  switch (result.status) {
    case 409:
      // Session-state conflicts carry their own operator copy (session-void).
      if (errorCode && SESSION_CONFLICTS.has(errorCode)) {
        return {
          text: asString(body.message) ?? "The session is not in a state that allows this.",
          severity: "warning",
          kind: "capability_unavailable",
        };
      }
      return {
        text: capabilityUnavailableText(body),
        severity: "warning",
        kind: "capability_unavailable",
      };
    case 422:
      return {
        text: asString(body.message) ?? "A field needs attention before this can be submitted.",
        field: asString(body.field) ?? undefined,
        validChoices: Array.isArray(body.valid_choices)
          ? (body.valid_choices as unknown[]).map((c) => String(c))
          : undefined,
        severity: "error",
        kind: "validation",
      };
    case 503:
      if (errorCode === "tenancy_not_configured") {
        return {
          text:
            "The backend is running but tenancy is not configured. Set API_SPONSOR_ID " +
            "and API_SITE_ID in your .env file (see .env.example for example values) " +
            "and the docs/ui-integration.md tenancy section.",
          severity: "error",
          kind: "tenancy_not_configured",
        };
      }
      // QA-008: a model-down 503 from the agent route must NOT be conflated with a
      // backend-API outage (INV-007). The copy states the MODEL (chat assistant) is
      // affected — not the backend or the operator's session data — and never says
      // "backend unavailable". The route already supplies a model-specific message;
      // if present we surface it, else a model-specific fallback.
      if (errorCode === "agent_unavailable") {
        return {
          text:
            asString(body.message) ??
            "The chat assistant's local model is unavailable. Your sessions, data, and the rest of the app are unaffected.",
          severity: "warning",
          kind: "agent_unavailable",
        };
      }
      return {
        text: "Backend unavailable, retry.",
        severity: "error",
        kind: "backend_unavailable",
      };
    case 404:
      return { text: "Not found.", severity: "warning", kind: "not_found" };
    default:
      return {
        text: "Something went wrong. Please retry.",
        severity: "error",
      };
  }
}

// The empty-sessions zero-state message (distinct from an error).
export function emptySessionsMessage(): OperatorMessage {
  return {
    text: "No sessions yet. Create one to get started.",
    severity: "info",
    kind: "empty",
  };
}

// contract_version skew banner (INV-018). Returns null when versions match.
export function contractVersionBanner(
  backendVersion: string,
  builtAgainst: string,
): OperatorMessage | null {
  if (backendVersion === builtAgainst) return null;
  return {
    text:
      `Backend/frontend version mismatch: the backend reports contract version ` +
      `${backendVersion} but this shell was built against ${builtAgainst}. ` +
      `Capability behavior may be inaccurate until they are aligned.`,
    severity: "warning",
    kind: "version_mismatch",
  };
}

// The version the shell was built against (pinned constant).
// Matches CONTRACT_VERSION in api/app.py.
export const BUILT_AGAINST_CONTRACT_VERSION = "0";
