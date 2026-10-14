// Runtime capability provider (frontend-shell INV-001 / PAT-014).
// STUB:TDD — runtime-sourced capability state, fail-closed on cold start.

import type { ApiClient, CapabilityRow, CapabilityStatus } from "@/lib/api-client";

export interface CapabilityState {
  // True only once /capabilities has loaded successfully.
  loaded: boolean;
  rows: CapabilityRow[];
}

// Cold-start / fail-closed: before the matrix loads, everything is disabled.
export const COLD_START_STATE: CapabilityState = {
  loaded: false,
  rows: [],
};

// Derive whether a capability's control is enabled. Fail closed: disabled unless
// the matrix loaded AND the named capability is `implemented`.
export function isCapabilityEnabled(
  state: CapabilityState,
  capability: string,
): boolean {
  if (!state.loaded) return false;
  const row = rowFor(state, capability);
  return row?.status === "implemented";
}

export function statusFor(
  state: CapabilityState,
  capability: string,
): CapabilityStatus | "unknown" {
  const row = rowFor(state, capability);
  return row ? row.status : "unknown";
}

export function rowFor(
  state: CapabilityState,
  capability: string,
): CapabilityRow | undefined {
  return state.rows.find((r) => r.capability === capability);
}

// The runtime capability provider's load seam (INV-001 / PAT-014). Fetches
// GET /capabilities through the real client and DERIVES the CapabilityState:
// on success → { loaded:true, rows }; on any failure (unreachable cold start) →
// COLD_START_STATE (fail closed, never fail open to enabled). The PROVIDER, not
// the test, performs the fetch→derive — tests only stub the HTTP transport.
export async function loadCapabilityState(client: ApiClient): Promise<CapabilityState> {
  try {
    const result = await client.getCapabilities();
    if (result.ok) {
      return { loaded: true, rows: result.data };
    }
  } catch {
    // fall through to fail closed
  }
  // Any failure (unreachable cold start, non-ok) → fail closed, never fail open.
  return COLD_START_STATE;
}
