// Session list filter controls (session-query SQ-006). Holds no state of its
// own; the app owns the form and decides when to query.

"use client";

import type { JSX } from "react";
import { SESSION_STATUSES } from "@/lib/tool-registry";
import { EMPTY_FILTER_FORM, type FilterProblems, type SessionFilterForm } from "@/lib/session-filter-form";

export interface SessionFilterPanelProps {
  form: SessionFilterForm;
  problems: FilterProblems;
  compounds: string[];
  onChange: (form: SessionFilterForm) => void;
}

export function SessionFilterPanel({ form, problems, compounds, onChange }: SessionFilterPanelProps): JSX.Element {
  function set<K extends keyof SessionFilterForm>(key: K, value: SessionFilterForm[K]) {
    onChange({ ...form, [key]: value });
  }

  return (
    <div className="filters" role="search" aria-label="Filter sessions">
      <div className="field">
        <label htmlFor="filter-session">Session ID</label>
        <input
          id="filter-session"
          className="input mono"
          placeholder="Prefix"
          autoComplete="off"
          spellCheck={false}
          value={form.sessionId}
          onChange={(e) => set("sessionId", e.target.value)}
        />
        {problems.sessionId ? <p className="field-error">{problems.sessionId}</p> : null}
      </div>
      <div className="field">
        <label htmlFor="filter-participant">Participant ID</label>
        <input
          id="filter-participant"
          className="input mono"
          placeholder="Full UUID"
          autoComplete="off"
          spellCheck={false}
          value={form.participantId}
          onChange={(e) => set("participantId", e.target.value)}
        />
        {problems.participantId ? <p className="field-error">{problems.participantId}</p> : null}
      </div>
      <div className="field-row">
        <div className="field">
          <label htmlFor="filter-from">From</label>
          <input id="filter-from" type="date" className="input" value={form.from} onChange={(e) => set("from", e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="filter-to">To</label>
          <input id="filter-to" type="date" className="input" value={form.to} onChange={(e) => set("to", e.target.value)} />
        </div>
      </div>
      {problems.from || problems.to ? <p className="field-error">{problems.from ?? problems.to}</p> : null}
      <div className="field-row">
        <div className="field">
          <label htmlFor="filter-status">Status</label>
          <select id="filter-status" className="input" value={form.status} onChange={(e) => set("status", e.target.value)}>
            <option value="">Any</option>
            {SESSION_STATUSES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="filter-compound">Substance</label>
          <select id="filter-compound" className="input" value={form.compound} onChange={(e) => set("compound", e.target.value)}>
            <option value="">Any</option>
            {compounds.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </div>
      </div>
      <button type="button" className="btn btn-ghost btn-sm" onClick={() => onChange(EMPTY_FILTER_FORM)}>
        Clear filters
      </button>
    </div>
  );
}
