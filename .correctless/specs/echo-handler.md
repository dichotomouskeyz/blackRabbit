# Spec: ECHO Handler

## Metadata
- **Task**: echo-handler
- **Intensity**: standard
- **Recommended-intensity**: standard
- **Intensity reason**: no security keywords, no TB-xxx overlap beyond data-integrity (covered by rules), no antipattern history
- **Override**: none

## What

`capture/echo_handler` listens on the LSL marker stream for `ECHO|`-prefixed pipe-delimited strings, parses and validates them, writes the raw marker to XDF backup first, then inserts a structured row into `echo_events`. Events that fail parsing are silently dropped after a warning log. On DB connection loss, rows are buffered (up to `BUFFER_MAX = 100`) and replayed on reconnect. If the marker stream is not found at startup the thread exits cleanly — biosignal capture is unaffected. `source` is always hardcoded to `'manual_logging'` (hardware proximity is deferred).

## Rules

### Parser — unit tests

- **R-001** [unit]: `parse_echo_marker` returns `None` for any string that does not start with `"ECHO|"`.

- **R-002** [unit]: `parse_echo_marker` returns `None` when the marker does not split into exactly 5 fields on `"|"`.

- **R-003** [unit]: `parse_echo_marker` returns `None` when `event_type` is not in `VALID_EVENT_TYPES` (`zone_enter`, `zone_exit`, `manual_marker`).

- **R-004** [unit]: `parse_echo_marker` returns `None` when `actor_role` is not in `VALID_ACTOR_ROLES` (`therapist`, `facilitator`, `coordinator`, `observer`).

- **R-005** [unit]: `parse_echo_marker` returns `None` for a `manual_marker` event whose `zone_label` is not in `VALID_MANUAL_LABELS`.

- **R-006** [unit]: `parse_echo_marker` returns `None` for a `zone_enter` or `zone_exit` event whose `zone_label` is not in `VALID_ZONE_LABELS`.

- **R-007** [unit]: `parse_echo_marker` returns a dict with keys `event_type`, `actor_id`, `actor_role`, `zone_label` for a fully valid marker string.

- **R-008** [unit]: `parse_echo_marker` sets `actor_id = None` when the `actor_id` field in the marker is an empty string or whitespace only.

### Row helpers — unit tests

- **R-009** [unit]: `raw_marker_from_sample` returns `None` when called with `None`.

- **R-010** [unit]: `raw_marker_from_sample` returns the first element when called with a list.

- **R-011** [unit]: `raw_marker_from_sample` returns `None` when the extracted value is not a string.

- **R-012** [unit]: `build_echo_row` returns a dict containing `session_id`, `participant_id`, `site_id`, `sponsor_id` from `cfg` and `lsl_timestamp` from the passed-in float, merged with all fields from `parsed`.

### ECHOWriter — unit tests

- **R-013** [unit]: `ECHOWriter.buffer_row` appends the row to the buffer when it is not full.

- **R-014** [unit]: `ECHOWriter.buffer_row` still appends (dropping the oldest via deque overflow) and logs an error at ERROR level when the buffer is already at `BUFFER_MAX`.

- **R-015** [unit]: `ECHOWriter.flush_buffer` removes each row from the buffer only after a successful write, and stops flushing if the connection drops mid-flush.

### Integration tests

- **R-016** [integration]: After a valid marker is processed, exactly one row appears in `echo_events` with the correct `event_type`, `actor_role`, `zone_label`, `actor_id`, `lsl_timestamp`, `session_id`, `site_id`, and `sponsor_id`.

- **R-017** [integration]: The `source` column in `echo_events` is always `'manual_logging'` — never derived from the marker string.

- **R-018** [integration]: XDF write (`xdf.write_marker`) is called before the DB write for the same marker event (same ordering invariant as biosignal streams).

- **R-019** [integration]: An unrecognised marker (fails `parse_echo_marker`) produces no DB row and no XDF write — only a WARNING log.

- **R-020** [integration]: On `psycopg2.OperationalError` during `write_row`, the event is buffered and the connection is set to `None`. On reconnect, buffered events are flushed to the DB before new events are written.

## Won't Do

- Test LSL inlet resolution against real hardware — use a `pylsl` stub.
- Test `source = 'hardware_proximity'` — proximity hardware is deferred from MVP.
- Test that biosignal threads are unaffected when ECHO thread exits early — that belongs in an end-to-end integration test, not the ECHO handler spec.

## Risks

- **Marker stream absent at startup** — accepted; thread exits with a WARNING; session continues without ECHO events.
- **Buffer overflow loses oldest events** when `BUFFER_MAX = 100` is exceeded during extended DB outage — accepted; same design decision as biosignal forwarder.
- **Non-operational DB error permanently drops event** (`psycopg2.Error` that is not `OperationalError`) — accepted; logged at ERROR with event fields; ECHO events are contextual annotations, not primary data.

## Open Questions

- _(none)_
