// Renders a mapped operator message for an API outcome (frontend-shell INV-006).
// Researcher-legible copy only; never a raw stack/JSON dump. All text is rendered
// as escaped React children (INV-005a) — no raw-HTML injection sink.

import type { JSX } from "react";
import type { ApiResult } from "@/lib/api-client";
import { messageForResult } from "@/lib/error-messages";
import { SessionText } from "@/components/SessionText";

export interface OutcomeMessageProps {
  result: ApiResult<unknown>;
}

export function OutcomeMessage({ result }: OutcomeMessageProps): JSX.Element {
  const msg = messageForResult(result);
  return (
    <div className="outcome" role="status" data-outcome={msg.kind} data-severity={msg.severity}>
      <p data-field={msg.field ?? undefined}>
        <SessionText value={msg.text} />
      </p>
      {msg.validChoices && msg.validChoices.length > 0 ? (
        <p className="outcome-choices">
          Valid choices: <SessionText value={msg.validChoices.join(", ")} />
        </p>
      ) : null}
    </div>
  );
}
