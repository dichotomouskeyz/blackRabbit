// In-flight indicator for tool calls / API requests (frontend-shell INV-016).
// STUB:TDD — distinguishes working / hung / completed; tool-call status (issued /
// awaiting / returned) distinct from model prose.

import type { JSX } from "react";

export type RequestPhase = "issued" | "awaiting" | "returned" | "idle";

export interface InFlightProps {
  phase: RequestPhase;
  label?: string;
}

const PHASE_TEXT: Record<RequestPhase, string> = {
  issued: "issued",
  awaiting: "awaiting response…",
  returned: "returned",
  idle: "",
};

// Renders a defined in-flight affordance distinct from model prose (INV-016).
// The pending spinner only appears while a request is genuinely in flight
// (issued/awaiting); idle/returned clear it.
export function InFlight({ phase, label }: InFlightProps): JSX.Element | null {
  if (phase === "idle") {
    // No in-flight affordance when idle — the pending state is cleared.
    return null;
  }
  const pending = phase === "issued" || phase === "awaiting";
  return (
    <span className="in-flight" data-testid="in-flight" data-phase={phase} role="status" aria-live="polite">
      {pending ? <span className="spinner" data-testid="in-flight-spinner" aria-hidden="true" /> : null}
      <span>
        {label ? `${label}: ` : ""}
        {PHASE_TEXT[phase]}
      </span>
    </span>
  );
}
