# Spec: XDF Writer

## Metadata
- **Task**: xdf-writer
- **Intensity**: standard
- **Recommended-intensity**: standard
- **Intensity reason**: no security keywords, no TB-xxx overlap, no antipattern history
- **Override**: none

## What

`capture/xdf` writes a valid XDF (Extensible Data Format v1.0) file as a parallel backup to the TimescaleDB write path. One `XDFWriter` instance per session. All four biosignal threads call `write_samples()` concurrently; an internal lock serializes disk I/O. ECHO markers use `write_marker()`. The file is finalized with `close()` once, after all threads stop. If the file cannot be opened, `__init__` raises `OSError`. Subsequent write failures are logged and silently dropped — the DB write path is never affected. Sample counts, first/last timestamps, and the `is_closed` flag are read-only properties exposed for tests and the session reconciliation layer.

## Rules

### Binary encoding — unit tests

- **R-001** [unit]: `_encode_varlen(n)` returns a 2-byte sequence (`b"\x01"` prefix + 1 data byte) for `0 <= n <= 255`.

- **R-002** [unit]: `_encode_varlen(n)` returns a 3-byte sequence (`b"\x02"` prefix + 2 data bytes, little-endian) for `256 <= n <= 65535`.

- **R-003** [unit]: `_encode_varlen(n)` returns a 5-byte sequence (`b"\x04"` prefix + 4 data bytes, little-endian) for `65536 <= n <= 4294967295`.

- **R-004** [unit]: `_write_chunk` writes `_encode_varlen(len(tag_bytes + payload))` followed by the 2-byte little-endian tag, followed by the payload bytes — in that exact order.

### Payload builders — unit tests

- **R-005** [unit]: `_build_biosignal_payload` encodes `stream_id` as the first 4 bytes (little-endian `<I`).

- **R-006** [unit]: `_build_biosignal_payload` encodes `len(timestamps)` as a varlen sample count immediately after the 8-byte wall-clock field.

- **R-007** [unit]: `_build_biosignal_payload` encodes each timestamp as 8-byte little-endian float64 (`<d`) and each channel value as 4-byte little-endian float32 (`<f`).

- **R-008** [unit]: `_build_marker_payload` encodes varlen sample count of exactly `1` (one marker per call).

- **R-009** [unit]: `_build_marker_payload` encodes the marker string as UTF-8 bytes preceded by a varlen length prefix.

### Stream metadata — unit tests

- **R-010** [unit]: `_stream_header_xml` uses `html.escape()` for all user-supplied string values (`stream_name`, `session_id`, `participant_id`, `site_id`, `sponsor_id`) — special characters are entity-escaped.

- **R-011** [unit]: `_stream_header_xml` sets `channel_format` to `"string"` for the ECHO stream and `"float32"` for all biosignal streams.

- **R-012** [unit]: `_stream_header_xml` sets `nominal_srate` to `0.0` for the ECHO stream (irregular/event-driven).

- **R-013** [unit]: `_stream_footer_xml` returns a `bytes` object encoding `first_timestamp`, `last_timestamp`, and `sample_count` as XML.

### XDFWriter lifecycle — unit tests (with temp file)

- **R-014** [unit]: After `__init__`, the file begins with the XDF magic bytes (`b"XDF:"`).

- **R-015** [unit]: `__init__` writes exactly 5 stream header chunks — one per stream in `STREAM_IDS` (`EEG`, `HRV`, `EDA`, `Respiration`, `ECHO`) — before any `write_samples` call.

- **R-016** [unit]: `write_samples` is a no-op (no bytes written, counts unchanged) when `samples` is an empty list.

- **R-017** [unit]: After a successful `write_samples` call, `sample_counts[stream_name]` increases by `len(timestamps)`.

- **R-018** [unit]: `write_samples` sets `_first_ts[stream_name]` on the first successful write for that stream and `_last_ts[stream_name]` on every successful write.

- **R-019** [unit]: When `write_samples` raises an `OSError` during the disk write, `sample_counts` is NOT incremented — the count reflects only successfully written samples.

- **R-020** [unit]: `write_marker` increments `sample_counts["ECHO"]` by exactly 1 on each successful call.

- **R-021** [unit]: `write_samples` and `write_marker` are no-ops after `close()` has been called — they return immediately without writing bytes or changing counts.

- **R-022** [unit]: `close()` writes exactly 5 stream footer chunks — one per stream in `STREAM_IDS`.

- **R-023** [unit]: `close()` is idempotent — calling it a second time is a no-op; footers are written exactly once.

- **R-024** [unit]: `is_closed` returns `False` before `close()` and `True` after.

- **R-025** [unit]: `sample_counts` returns a copy of the counts dict — mutating the returned dict does not affect the writer's internal state.

### Thread safety — unit test

- **R-026** [unit]: Concurrent `write_samples` calls from multiple threads produce non-interleaved chunks — each chunk's bytes appear contiguously in the output file without mixing with bytes from another concurrent write.

## Won't Do

- Test that the output file can be parsed by an external XDF reader (e.g. `pyxdf`) — round-trip parsing is an end-to-end concern.
- Test the exact byte layout of the XDF file header chunk — it is a hardcoded literal; trust the constant.
- Test `OSError` propagation from `__init__` — that is filesystem behavior, not business logic.
- Test per-stream channel counts or sample rates against hardware — those belong in `settings` spec.

## Risks

- **Biosignal values encoded as `float32` (lossy)** — the XDF standard uses float32 for biosignal streams. DB stores the original float64 precision. The XDF backup may not round-trip exactly. Accepted by design; the DB is the precision source, XDF is the continuity safety net.
- **`write_samples` / `write_marker` `OSError` silently drops the chunk** — a disk-full or permissions error logs at ERROR but does not stop the session. The DB write path continues unaffected. Downstream reconciliation may detect the gap if XDF counts are lower than DB counts.
- **`_stream_footer_xml` uses f-string interpolation for float values** — `{first_ts}`, `{last_ts}` may produce scientific notation for very small/large timestamps. XDF readers that expect decimal notation may fail to parse. Accepted for MVP; timestamps are LSL floats with ~10 significant digits and won't hit scientific notation in practice.

## Open Questions

- _(none)_
