# Spec: Void a session

## Metadata
- **Created**: 2026-10-14
- **Status**: draft
- **Impacts**: operator-ui (new `POST /sessions/{id}/void` route and capability row; the documented route set grows by one), session-query (voided sessions are hidden by default), schema (`sessions` gains a `voided` status and a void record, edited in migration 002 pre-go-live)
- **Branch**: feat/sessions-void
- **Intensity**: high (state-changing write; audit trail)

## Context

Operators need to remove a mistaken or unusable session from normal views
without destroying evidence. Voiding is that action. It never deletes rows,
samples, XDF files or analysis artifacts, and the existing audit triggers record
it. Permanent removal of data (for example for participant withdrawal) is out of
scope and remains the deploying team's procedure (see `docs/data-handling.md`).

## Requirements

### SV-001: Voided is a terminal status with a void record [integration]
`session_status` gains `voided`. A voided session carries `voided_at`, a
non-blank `void_reason` and `voided_from` (the status it replaced). A database
check keeps the three set exactly when the status is `voided`.

### SV-002: Only closed or failed sessions can be voided [integration]
Voiding moves a `closed` or `failed` session to `voided`. Any other status
returns 409 `session_not_voidable` with the current status; capture must end
first. An already voided session returns 409 `already_voided`.

### SV-003: Voiding respects session ownership and tenancy [integration]
The void runs in one transaction under the shared per-session advisory lock. If
capture, closeout, recovery or ARC holds it, the request returns 409
`session_busy`. A session outside the server's sponsor and site scope returns
404, exactly like a missing one.

### SV-004: Input is validated before the database [unit]
`POST /sessions/{id}/void` takes `{"reason": string}`. A non-UUID path or a
reason that is blank, shorter than 3 or longer than 500 characters after
trimming returns the structured 422 before any connection is opened. Extra
body fields are rejected.

### SV-005: Nothing is deleted and the change is audited [integration]
Voiding changes only the session row's status and void record. Samples, ECHO
events, XDF files and analysis rows are untouched. The existing status
transition trigger writes a `session_status_transition` audit event with the old
and new status. Application code writes no audit rows (house rule).

### SV-006: Voided sessions leave normal views and analysis [integration]
`GET /sessions` excludes voided sessions unless `status=voided` is requested.
Status reads still return a voided session, with `status: "voided"` and the
watermark state of the lifecycle it replaced. ARC reads and runs refuse voided
sessions because they require `closed`.

### SV-007: Console void is a confirmed human action [integration]
The console offers Void only for closed or failed sessions, only while the
`void_session` capability is implemented, and only after the operator enters a
reason in a confirmation step that warns against identifying details. The agent
tool registry has no void tool.
