# Spec: XDF Writer

## Metadata
- **Task**: xdf-writer
- **Intensity**: standard
- **Recommended-intensity**: standard
- **Intensity reason**: no security keywords, no TB-xxx overlap, no antipattern history
- **Override**: none

## What

`capture/xdf` writes standard XDF 1.0 before the TimescaleDB write path. One `XDFWriter` instance owns one capture segment. Its lock serializes writes and finalization. Every successful write is flushed and fsynced before returning. Invalid payloads raise `ValueError` before writing; I/O failures raise `XDFWriteError`, a `RuntimeError`, and permanently invalidate the writer. Failed artifacts are preserved. Finalization reports success only after all footers are durable. These release corrections were approved on 2026-10-13 through `docs/release-contract-proposal.md`.

## Rules

### Binary encoding — unit tests

- **R-001** [unit]: `_encode_varlen(n)` returns a 2-byte sequence (`b"\x01"` prefix + 1 data byte) for `0 <= n <= 255`.

- **R-002** [unit]: `_encode_varlen(n)` returns a 5-byte sequence (`b"\x04"` prefix + 4 data bytes, little-endian) for `256 <= n <= 65535`. XDF does not permit width 2.

- **R-003** [unit]: `_encode_varlen(n)` returns a 5-byte sequence (`b"\x04"` prefix + 4 data bytes, little-endian) for `65536 <= n <= 4294967295`.

- **R-004** [unit]: `_write_chunk` writes `_encode_varlen(len(tag_bytes + payload))` followed by the 2-byte little-endian tag, followed by the payload bytes — in that exact order.

### Payload builders — unit tests

- **R-005** [unit]: `_build_biosignal_payload` encodes `stream_id` as the first 4 bytes (little-endian `<I`).

- **R-006** [unit]: `_build_biosignal_payload` encodes `len(timestamps)` as a varlen sample count immediately after the 4-byte stream ID, with no extra wall-clock field.

- **R-007** [unit]: Each sample starts with timestamp-width byte 8, then an 8-byte little-endian timestamp and float32 channels. ECHO uses the same timestamp prefix followed by a UTF-8 varlen string.

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

- **R-019** [unit]: Disk write, flush, or fsync failure raises `XDFWriteError`; counts do not increment, subsequent writes fail, and `close` cannot report success.

- **R-020** [unit]: `write_marker` increments `sample_counts["ECHO"]` by exactly 1 on each successful call.

- **R-021** [unit]: Writes after successful close raise `XDFWriteError` without changing bytes or counts.

- **R-022** [unit]: `close()` writes exactly 5 stream footer chunks — one per stream in `STREAM_IDS`.

- **R-023** [unit]: `close()` is idempotent — calling it a second time is a no-op; footers are written exactly once.

- **R-024** [unit]: `is_closed` returns `False` before `close()` and `True` after.

- **R-025** [unit]: `sample_counts` returns a copy of the counts dict — mutating the returned dict does not affect the writer's internal state.

### Thread safety — unit test

- **R-026** [unit]: Concurrent `write_samples` calls from multiple threads produce non-interleaved chunks — each chunk's bytes appear contiguously in the output file without mixing with bytes from another concurrent write.

- **R-027** [unit]: Samples and timestamps must have equal lengths; every sample has the stream header's exact channel count; timestamps and float32 signal values are finite. Invalid input writes no bytes and does not increment counts. Empty paired lists remain a no-op for an open writer.
- **R-028** [unit]: Finalization failures raise `XDFWriteError`, release the file handle, leave `is_closed=False`, and remain failures on subsequent close calls.
- **R-029** [unit]: Two writers for the same session cannot overwrite each other's files, even when created at the same instant.
- **R-030** [external]: Independent `pyxdf` reads all four signal streams and ECHO with correct counts, values, timestamps, and identity metadata. Run with clock synchronization/dejitter disabled to compare raw timestamps.
- **R-031** [unit]: Variable integers reject negatives, non-integers, and values above uint64. Values above uint32 use width 8. Short writes are fatal.
- **R-032** [unit]: New headers identify standard format and persist canonical EEG channel names and device ID when supplied. Existing files are never rewritten.

## Won't Do

- No hardware acquisition is required for the independent XDF compatibility fixture.
- Test the exact byte layout of the XDF file header chunk — it is a hardcoded literal; trust the constant.
- Test `OSError` propagation from `__init__` — that is filesystem behavior, not business logic.
- Test per-stream channel counts or sample rates against hardware — those belong in `settings` spec.

## Risks

- **Biosignal values encoded as `float32` (lossy)** — the XDF standard uses float32 for biosignal streams. DB stores the original float64 precision. The XDF backup may not round-trip exactly. Accepted by design; the DB is the precision source, XDF is the continuity safety net.
- A failing storage device can leave an incomplete artifact. It must never be accepted as successful capture merely because part of the file exists.
- **`_stream_footer_xml` uses f-string interpolation for float values** — `{first_ts}`, `{last_ts}` may produce scientific notation for very small/large timestamps. XDF readers that expect decimal notation may fail to parse. Accepted for MVP; timestamps are LSL floats with ~10 significant digits and won't hit scientific notation in practice.

## Open Questions

- _(none)_
