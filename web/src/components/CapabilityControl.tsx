// A capability-gated control: enabled state sourced from runtime matrix (INV-001),
// first-use confirmation for newly-enabled write/exec (INV-019).

"use client";

import { useState } from "react";
import type { JSX } from "react";
import {
  isCapabilityEnabled,
  rowFor,
  type CapabilityState,
} from "@/lib/capabilities";
import { SessionText } from "@/components/SessionText";

// Write/exec capabilities that require first-use confirmation when newly enabled.
export const WRITE_EXEC_CAPABILITIES = [
  "capture_start",
  "capture_stop",
  "close_session",
  "arc_run",
  "log_marker",
] as const;

export interface CapabilityControlProps {
  capability: string;
  state: CapabilityState;
  // Whether this capability was already implemented on a previous matrix load.
  previouslyImplemented?: boolean;
  onInvoke: () => void;
  label: string;
}

function isWriteExec(capability: string): boolean {
  return (WRITE_EXEC_CAPABILITIES as readonly string[]).includes(capability);
}

export function CapabilityControl({
  capability,
  state,
  previouslyImplemented = true,
  onInvoke,
  label,
}: CapabilityControlProps): JSX.Element {
  const [confirming, setConfirming] = useState(false);

  const enabled = isCapabilityEnabled(state, capability);
  const row = rowFor(state, capability);

  // INV-019: a write/exec capability newly transitioned to implemented requires an
  // explicit first-use confirmation before issuing the request.
  const needsFirstUseConfirm =
    enabled && isWriteExec(capability) && previouslyImplemented === false;

  function handleClick() {
    if (needsFirstUseConfirm) {
      setConfirming(true);
      return;
    }
    onInvoke();
  }

  function handleConfirm() {
    setConfirming(false);
    onInvoke();
  }

  const status = row?.status ?? "unknown";
  return (
    <div className="cap" data-capability={capability} data-status={status}>
      <div className="cap-line">
        <button type="button" className="cap-btn" disabled={!enabled} onClick={handleClick}>
          {label}
        </button>
        <span className={enabled ? "tag tag-live" : "tag tag-off"}>{enabled ? "live" : state.loaded ? status : "unknown"}</span>
      </div>
      {!enabled && row && row.status !== "implemented" && row.blocked_reason ? (
        <p className="cap-reason" data-blocked-reason>
          <SessionText value={row.blocked_reason} />
        </p>
      ) : null}
      {confirming ? (
        <div className="confirm" data-testid="first-use-confirm" role="dialog">
          <p>This capability was just enabled. Confirm you want to run {label} for the first time.</p>
          <div className="confirm-actions">
            <button type="button" className="btn btn-primary btn-sm" onClick={handleConfirm}>
              Confirm
            </button>
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => setConfirming(false)}>
              Cancel
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
