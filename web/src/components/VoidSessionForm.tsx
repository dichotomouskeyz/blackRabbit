// Void a closed or failed session after a confirmed reason (session-void
// SV-007). Voiding keeps all data and the audit trail; the session leaves
// normal views. This is a human action only: the agent has no void tool.

"use client";

import { useState } from "react";
import type { FormEvent, JSX } from "react";
import type { ApiResult } from "@/lib/api-client";
import { OutcomeMessage } from "@/components/OutcomeMessage";

const MIN_REASON = 3;
const MAX_REASON = 500;

export interface VoidSessionFormProps {
  onSubmit: (reason: string) => Promise<ApiResult<unknown>>;
  onVoided: () => void;
}

export function VoidSessionForm({ onSubmit, onVoided }: VoidSessionFormProps): JSX.Element {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<ApiResult<unknown> | null>(null);
  const trimmed = reason.trim();
  const valid = trimmed.length >= MIN_REASON && trimmed.length <= MAX_REASON;

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!valid) return;
    setSubmitting(true);
    try {
      const res = await onSubmit(trimmed);
      setResult(res);
      if (res.ok) onVoided();
    } finally {
      setSubmitting(false);
    }
  }

  if (!open) {
    return (
      <div className="void">
        <button type="button" className="btn btn-ghost btn-sm" onClick={() => setOpen(true)}>
          Void session
        </button>
      </div>
    );
  }

  return (
    <form className="void void-open" data-testid="void-session-form" onSubmit={handleSubmit}>
      <p className="void-note">
        Voiding hides this session from normal views and from analysis. Its samples, markers, XDF
        file and audit history are kept.
      </p>
      <div className="field">
        <label htmlFor="void_reason">Reason</label>
        <textarea
          id="void_reason"
          className="input"
          rows={3}
          maxLength={MAX_REASON}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
        />
        <p className="field-hint">Do not include names or other identifying details.</p>
      </div>
      <div className="confirm-actions">
        <button type="submit" className="btn btn-danger btn-sm" disabled={!valid || submitting}>
          Confirm void
        </button>
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          onClick={() => {
            setOpen(false);
            setReason("");
            setResult(null);
          }}
        >
          Cancel
        </button>
      </div>
      {result && !result.ok ? <OutcomeMessage result={result} /> : null}
    </form>
  );
}
