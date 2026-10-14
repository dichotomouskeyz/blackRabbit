// Session list filter form state and its translation to API filters
// (session-query SQ-006). Dates are local calendar days; the API receives UTC
// instants from the start of the first day (inclusive) to the start of the day
// after the last (exclusive).

import type { SessionFilters } from "@/lib/api-client";
import { UUID_RE } from "@/lib/tool-registry";

export interface SessionFilterForm {
  sessionId: string;
  participantId: string;
  from: string; // YYYY-MM-DD, local
  to: string; // YYYY-MM-DD, local, inclusive
  status: string;
  compound: string;
}

export const EMPTY_FILTER_FORM: SessionFilterForm = {
  sessionId: "",
  participantId: "",
  from: "",
  to: "",
  status: "",
  compound: "",
};

export type FilterProblems = Partial<Record<keyof SessionFilterForm, string>>;

const SESSION_PREFIX_RE = /^[0-9a-fA-F-]{1,36}$/;
const DAY_RE = /^(\d{4})-(\d{2})-(\d{2})$/;

export function activeFilterCount(form: SessionFilterForm): number {
  return Object.values(form).filter((v) => v.trim() !== "").length;
}

// Local midnight of a YYYY-MM-DD day, offset by `addDays`, as an ISO instant.
function localDayStart(day: string, addDays = 0): string | null {
  const m = DAY_RE.exec(day);
  if (!m) return null;
  const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]) + addDays);
  return Number.isNaN(d.getTime()) ? null : d.toISOString();
}

// API filters for a form, plus any problems that stop it being sent. Text that
// is still being typed (a partial participant UUID, for example) is reported
// as a problem rather than sent.
export function toApiFilters(form: SessionFilterForm): {
  filters: SessionFilters;
  problems: FilterProblems;
} {
  const filters: SessionFilters = {};
  const problems: FilterProblems = {};

  const sessionId = form.sessionId.trim();
  if (sessionId) {
    if (SESSION_PREFIX_RE.test(sessionId)) filters.session_id = sessionId.toLowerCase();
    else problems.sessionId = "Use hexadecimal characters and hyphens only.";
  }

  const participantId = form.participantId.trim();
  if (participantId) {
    if (UUID_RE.test(participantId)) filters.participant_id = participantId.toLowerCase();
    else problems.participantId = "Enter the full participant UUID.";
  }

  if (form.from) {
    const start = localDayStart(form.from);
    if (start) filters.created_from = start;
    else problems.from = "Not a valid date.";
  }
  if (form.to) {
    const end = localDayStart(form.to, 1);
    if (end) filters.created_before = end;
    else problems.to = "Not a valid date.";
  }
  if (filters.created_from && filters.created_before && filters.created_from >= filters.created_before) {
    problems.to = "The end date is before the start date.";
  }

  if (form.status) filters.status = form.status;
  if (form.compound) filters.compound = form.compound;

  return { filters, problems };
}
