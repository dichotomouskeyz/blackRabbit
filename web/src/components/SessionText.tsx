// Inert renderer for session-derived text (frontend-shell INV-005a / PRH-003).
// React renders string children as escaped text nodes — never markup. We never
// use any raw-HTML injection sink, so any markup in `value` is DOM-inert.

import type { JSX } from "react";

export interface SessionTextProps {
  value: string | null | undefined;
}

export function SessionText({ value }: SessionTextProps): JSX.Element {
  // Rendering the string as a child escapes it; no element is created from markup.
  return <span data-session-text>{value ?? ""}</span>;
}
