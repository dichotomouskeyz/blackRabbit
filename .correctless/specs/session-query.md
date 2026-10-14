# Spec: Session query filters

## Metadata
- **Created**: 2026-10-14
- **Status**: draft
- **Impacts**: operator-ui (`GET /sessions` gains optional query parameters; response unchanged), frontend-shell (`list_sessions` tool arguments, session list filters)
- **Branch**: feat/sessions-query
- **Intensity**: standard

## Context

Operators need to find sessions by date, session ID, participant ID, status and
substance. Sessions already carry all of these fields, so filtering adds no new
stored data. The list response keeps its closed field allowlist
(operator-ui INV-003/INV-005): `participant_id` is accepted as a filter but is
never returned.

## Scope

**Covers:** query parameters on `GET /sessions`, their validation, the read SQL,
the typed client and `list_sessions` agent tool arguments, and the filter
controls in the session list.

**Does not cover:** full-text search, pagination cursors, sorting options, or any
new response field.

## Requirements

### SQ-001: Optional filters on GET /sessions [integration]
`GET /sessions` accepts optional `session_id`, `participant_id`, `status`,
`compound`, `created_from`, `created_before` and `limit`. Absent filters do not
narrow the result. Present filters combine with AND, inside the existing
sponsor and site scope (operator-ui INV-001).
- `session_id`: case-insensitive prefix of the session UUID, 1 to 36 characters
  of `[0-9a-f-]`.
- `participant_id`: a complete UUID; exact match.
- `status`: one of the `session_status` enum values.
- `compound`: one of `VALID_COMPOUNDS`.
- `created_from` (inclusive) and `created_before` (exclusive): an ISO 8601 date
  (`YYYY-MM-DD`, read as UTC midnight) or a datetime with a UTC offset.
- `limit`: 1 to 500, default 200. Results stay ordered by `created_at`
  descending.

### SQ-002: Invalid filters fail closed before the database [unit]
Any invalid filter returns the structured 422 `{field, message, valid_choices?}`
without opening a database connection. This covers a malformed value, a naive
datetime, `created_from` not before `created_before`, or `limit` out of range.
`status` and `compound` errors include `valid_choices`.

### SQ-003: Read SQL stays a parameterized constant [unit]
The list query is a module-level constant that begins with `SELECT`, contains no
write token, and binds every filter as a `%(name)s` parameter with a typed
`IS NULL OR` guard. No SQL text is built from input.

### SQ-004: Response field allowlist is unchanged [integration]
Rows contain exactly `id, status, compound, started_at, closed_at, created_at`.
Filtering by `participant_id` never adds it to the response.

### SQ-005: Client and agent tool send only validated filters [unit]
The typed client encodes filters as query parameters and omits empty ones. The
`list_sessions` tool accepts the same optional filters under a strict schema,
and the dispatcher appends them as a query string to the fixed `/sessions`
path. Banned argument keys stay banned (frontend-shell INV-003).

### SQ-006: Session list filter controls [integration]
The session list offers session ID, participant ID, a date range, status and
substance filters, plus a clear action. Dates are local calendar days sent as
UTC instants (start of the first day, inclusive, to the start of the day after
the last, exclusive). A filtered empty result shows a no-matches message,
distinct from "no sessions yet".
