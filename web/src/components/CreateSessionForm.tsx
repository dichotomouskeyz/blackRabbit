// Create-session form (frontend-shell INV-004 / INV-006 422-preserve / INV-011 / INV-019).
// Exposes NO tenancy inputs and NO PII fields; rejects non-UUID participant_id
// before submission; preserves other entered values on a 422. Field names match
// api/app.py CreateSessionRequest.

"use client";

import { useState } from "react";
import type { FormEvent, JSX } from "react";
import type { ApiResult } from "@/lib/api-client";
import { UUID_RE } from "@/lib/tool-registry";
import { OutcomeMessage } from "@/components/OutcomeMessage";

export interface CreateSessionFormProps {
  // Called with the validated allow-list body (no tenancy keys).
  onSubmit: (body: Record<string, unknown>) => Promise<ApiResult<{ session_id: string }>>;
  vocab?: { compounds: string[]; dose_units: string[] };
}

export function CreateSessionForm({ onSubmit, vocab }: CreateSessionFormProps): JSX.Element {
  const compounds = vocab?.compounds ?? [];
  const doseUnits = vocab?.dose_units ?? [];

  const [participantId, setParticipantId] = useState("");
  const [compound, setCompound] = useState(compounds[0] ?? "");
  const [captureSource, setCaptureSource] = useState("lsl");
  const [dose, setDose] = useState("");
  const [doseUnit, setDoseUnit] = useState(doseUnits[0] ?? "");
  const [protocolArm, setProtocolArm] = useState("");
  const [roomId, setRoomId] = useState("");
  const [pidError, setPidError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  // The last API outcome (e.g. a 422) — rendered without wiping entered values.
  const [result, setResult] = useState<ApiResult<{ session_id: string }> | null>(null);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    // INV-011: reject a non-UUID participant_id before any submission.
    if (!UUID_RE.test(participantId.trim())) {
      setPidError("participant_id must be a valid UUID");
      return;
    }
    setPidError(null);

    // Tenancy is server-injected — the form never collects or sends it (INV-004).
    const body: Record<string, unknown> = {
      participant_id: participantId.trim(),
      compound,
      capture_source: captureSource,
    };
    const doseNumber = Number.parseFloat(dose);
    if (dose.trim() !== "" && Number.isFinite(doseNumber)) {
      body.compound_dose = doseNumber;
      if (doseUnit) body.compound_dose_unit = doseUnit;
    }
    if (protocolArm) body.protocol_arm = protocolArm;
    if (roomId) body.room_id = roomId;

    setSubmitting(true);
    try {
      setResult(await onSubmit(body));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className="form" data-testid="create-session-form" onSubmit={handleSubmit}>
      <div className="field">
        <label htmlFor="participant_id">
          Participant <code>participant_id</code>
        </label>
        <input
          id="participant_id"
          name="participant_id"
          className="input mono"
          placeholder="UUID"
          autoComplete="off"
          spellCheck={false}
          value={participantId}
          onChange={(e) => setParticipantId(e.target.value)}
        />
        {pidError ? (
          <p className="field-error" data-pid-error>
            {pidError}
          </p>
        ) : null}
      </div>

      <div className="field">
        <label htmlFor="compound">Substance</label>
        <select id="compound" name="compound" className="input" value={compound} onChange={(e) => setCompound(e.target.value)}>
          {compounds.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
      </div>

      <div className="field-row">
        <div className="field">
          <label htmlFor="compound_dose">Dose</label>
          <input
            id="compound_dose"
            name="compound_dose"
            className="input mono"
            inputMode="decimal"
            value={dose}
            onChange={(e) => setDose(e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="compound_dose_unit">Unit</label>
          <select
            id="compound_dose_unit"
            name="compound_dose_unit"
            className="input"
            value={doseUnit}
            onChange={(e) => setDoseUnit(e.target.value)}
          >
            {doseUnits.map((u) => (
              <option key={u} value={u}>
                {u}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="field">
        <label htmlFor="capture_source">
          Capture source <code>capture_source</code>
        </label>
        <input
          id="capture_source"
          name="capture_source"
          className="input mono"
          value={captureSource}
          onChange={(e) => setCaptureSource(e.target.value)}
        />
      </div>

      <div className="field-row">
        <div className="field">
          <label htmlFor="protocol_arm">Protocol arm</label>
          <input
            id="protocol_arm"
            name="protocol_arm"
            className="input"
            value={protocolArm}
            onChange={(e) => setProtocolArm(e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="room_id">Room</label>
          <input id="room_id" name="room_id" className="input" value={roomId} onChange={(e) => setRoomId(e.target.value)} />
        </div>
      </div>

      <button type="submit" className="btn btn-primary" disabled={submitting}>
        Create session
      </button>

      {result && !result.ok ? <OutcomeMessage result={result} /> : null}
    </form>
  );
}
