# Spec: ARC Windows

## Metadata
- **Task**: arc-windows
- **Intensity**: standard
- **Recommended-intensity**: standard
- **Intensity reason**: no security keywords, no TB-xxx overlap, no antipattern history
- **Override**: none

## What

`batch/arc/windows.py` computes absolute LSL-time bounds for ARC event-locked temporal windows. A window is centered on an ECHO anchor timestamp; its half-width is `width_s / 2`. The three canonical windows are W1 (30 s narrow), W2 (120 s medium), and W3 (300 s wide). `ARCWindowBounds` is a pure frozen dataclass. All public functions (`centered_arc_window`, `centered_arc_windows`, `centered_w1/w2/w3`) are pure — no DB, no I/O.

## Rules

### `ARCWindowBounds` validation — unit tests

- **R-001** [unit]: `ARCWindowBounds` raises `ValueError` when any of `center_lsl_timestamp`, `start_lsl_timestamp`, or `end_lsl_timestamp` is not finite.

- **R-002** [unit]: `ARCWindowBounds` raises `ValueError` when `end_lsl_timestamp <= start_lsl_timestamp`.

- **R-003** [unit]: `ARCWindowBounds` raises `ValueError` when `center_lsl_timestamp` is not in `[start_lsl_timestamp, end_lsl_timestamp]`.

- **R-004** [unit]: `ARCWindowBounds.width_s` returns `end_lsl_timestamp - start_lsl_timestamp`.

### `contains` — unit tests

- **R-005** [unit]: `ARCWindowBounds.contains(ts)` (default `include_end=False`) returns `True` for `ts` in `[start, end)` and `False` for `ts == end`.

- **R-006** [unit]: `ARCWindowBounds.contains(ts, include_end=True)` returns `True` for `ts == end`.

- **R-007** [unit]: `ARCWindowBounds.as_sql_params()` returns `(start_lsl_timestamp, end_lsl_timestamp)` for use as `>= start AND < end` query params.

### `centered_arc_window` — unit tests

- **R-008** [unit]: `centered_arc_window` raises `ValueError` when `echo_lsl_timestamp` is not finite.

- **R-009** [unit]: `centered_arc_window` raises `ValueError` when `width_s` is not finite or `<= 0`.

- **R-010** [unit]: `centered_arc_window` returns a window where `center_lsl_timestamp == echo_lsl_timestamp`, `start == echo - width/2`, and `end == echo + width/2`.

### `centered_arc_windows` — unit tests

- **R-011** [unit]: `centered_arc_windows` raises `ValueError` when the `widths_s` dict is missing any of `"w1"`, `"w2"`, `"w3"`.

- **R-012** [unit]: `centered_arc_windows` returns a tuple of exactly 3 `ARCWindowBounds` in the order `(w1, w2, w3)`.

### Canonical window widths — unit tests

- **R-013** [unit]: `centered_w1` produces a window with `width_s == 30.0`.

- **R-014** [unit]: `centered_w2` produces a window with `width_s == 120.0`.

- **R-015** [unit]: `centered_w3` produces a window with `width_s == 300.0`.

## Won't Do

- Test that custom `widths_s` override canonical defaults — any valid dict passing all three keys is accepted.
- Test `label` defaults when `label=None` is passed — it falls back to `CANONICAL_CENTERED_WINDOW_LABELS[name]`, which is a constant lookup.

## Risks

- **Floating-point arithmetic for half-width** — `start = echo - width/2` and `end = echo + width/2` may not sum to exactly `width` due to float64 precision. For the canonical widths (30, 120, 300 s), this error is sub-nanosecond and inconsequential.

## Open Questions

- _(none)_
