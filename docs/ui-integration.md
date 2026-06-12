# UI ↔ Backend Integration

Living document. Anything concerning connecting the future researcher UI
(Phase 4b operator surface and beyond) to this backend lives here: which code
is the contract surface, what was deliberately deferred until the UI exists,
and what must be added or changed when it lands. Companion to
[decisions.md](decisions.md) ("Real-Time Delivery": any API wraps existing
contracts instead of replacing them).

## 1. The de-facto backend API (what a UI calls today)

These are the boundaries a UI/API layer wraps. They are spec-pinned and
tested — do not redesign them for the UI; wrap them.

| Capability | Contract | Notes for UI |
|---|---|---|
| Create session | `capture.session_init.workflow.create_session(compound=…, site_id=…, sponsor_id=…, participant_id=…, capture_source=…, …electrode kwargs)` → session UUID | Validates inputs (ValueError) **before** any DB connect — safe to surface errors directly as form feedback. Valid choice sets exported as `VALID_COMPOUNDS` / `VALID_DOSE_UNITS`; CLI argparse choices in `capture/session_init/cli.py` are the same sets a UI dropdown should use. |
| Run capture | `capture.watchdog` (supervised) / `capture.lsl_forwarder` (direct), launched as a process | UI starts/stops the watchdog process; SIGTERM is the clean-stop signal. Watchdog sets session status (`closing` / `failed`). |
| Log context events | LSL marker stream consumed by `capture.echo_handler` | UI marker buttons should publish to the LSL marker outlet (like `capture/marker_simulator.py` does) — **not** write `echo_events` directly. |
| Close session | `capture.session_close.workflow.run(session_id, sponsor_id, xdf_path)` → exit code 0/1/2 | Accepts `str` or `Path` for `xdf_path` — coercion added specifically for non-CLI callers. |
| ARC post-session | `batch.arc.processor.run_arc_post_session(conn, session_id, sponsor_id, config_path)`; preflight gate `batch.arc.preflight.assert_arc_temporal_alignment(conn, session_id, sponsor_id, …)` | Selected ARC entry points accept sponsor scope. The complete ARC lifecycle and tenancy sweep remain unfinished; do not expose ARC as a trusted UI workflow yet. |
| Session status / progress | `sessions.status` + watermark events in `audit_events` (`watermark_verified` / `watermark_failed`) | UI polls these reads; never writes `audit_events` (trigger-owned). |

## 2. Deferred until the UI exists (deliberate, June 2026)

Deferred because both ends of the session-init chain are spec-pinned kwargs
contracts today — these abstractions need a real second consumer to be
designed against, not speculation:

- **`SessionRequest` dataclass** — typed request object with `__post_init__`
  validation. Design it against the actual UI/API request shape when that
  spec is written; today's validation already lives at the top of
  `create_session`.
- **`SessionRepository`** — persistence layer behind session init. One CLI
  workflow with one transaction doesn't justify it; an API server with
  concurrent handlers will.
- **Connection pooling** — revisit when the API layer creates concurrent
  handlers (db-health §1.2 threshold note).
- **Aborted-session state** — clinically significant terminal state with its
  own watermark path (db-health §3.2, rollup #1, Phase 5b).

## 3. Integration principles (binding)

1. The API layer **wraps** the contracts in §1 — it never duplicates their
   logic or reaches past them into SQL.
2. UI never writes to the DB directly. Reads preserve tenancy boundaries
   (`site_id`, `sponsor_id` in every query).
3. Pseudonymous participant IDs only — the UI must not collect or display PII.
4. Context markers go through LSL (so XDF stays the recovery source of
   truth), not through DB inserts.
5. Runtime config stays in `config/settings.py` + `.env`; the UI does not
   introduce its own config store for backend behavior.

## 4. When the UI lands — work checklist

- [ ] Write the UI/API spec (`.correctless/specs/`) before code; it pins the
      request/response shapes and is when `SessionRequest` gets designed.
- [ ] Thin FastAPI (or equivalent) app exposing §1 contracts; no broad app
      (decisions.md "Real-Time Delivery").
- [ ] Process management story for watchdog/forwarder start-stop from the UI
      (the `ForwarderEngine` lifecycle is the intended hook).
- [ ] Status endpoint over `sessions.status` + watermark audit events.
- [ ] Marker-entry component publishing to the LSL marker stream.
- [ ] Dedicated test database split (`TEST_DATABASE_URL` ≠ `DATABASE_URL`)
      before API tests land.
- [ ] Revisit deferred items in §2.
