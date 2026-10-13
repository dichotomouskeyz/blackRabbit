# Spec: Capture Control

## Metadata
- **Task**: capture-control
- **Intensity**: standard
- **Recommended-intensity**: standard
- **Intensity reason**: no security keywords, no TB-xxx overlap, no antipattern history
- **Override**: none

## What

`capture/control.py` implements a file-based stop-signal protocol for coordinating a clean shutdown between the watchdog and the forwarder subprocess. The watchdog calls `request_stop(session_id)` to write a sentinel file; the forwarder polls `stop_requested(session_id)` and exits when the file appears; the watchdog then calls `clear_stop_request(session_id)` to remove it. All paths are rooted under `settings.LOG_DIR / "control" /`.

**Note:** `capture/lsl_forwarder.py` is a 4-line entry point (`from capture.forwarder.cli import main; main()`) and is fully covered by the forwarder spec. `capture/metadata.py` is an empty stub file with no implementation — neither file requires an independent spec.

## Rules

### Path construction — unit test

- **R-001** [unit]: `stop_request_path(session_id)` returns a `Path` whose parent is `settings.LOG_DIR / "control"` and whose filename contains the session_id string.

### `request_stop` — unit tests (with tmp_path)

- **R-002** [unit]: `request_stop(session_id)` creates all parent directories if they do not already exist.

- **R-003** [unit]: `request_stop(session_id)` writes the text `"stop\n"` (UTF-8) to the signal file.

- **R-004** [unit]: `request_stop(session_id)` returns the `Path` of the created file.

### `clear_stop_request` — unit tests (with tmp_path)

- **R-005** [unit]: `clear_stop_request(session_id)` removes the signal file when it exists.

- **R-006** [unit]: `clear_stop_request(session_id)` is a no-op and does not raise when the file does not exist.

### `stop_requested` — unit tests (with tmp_path)

- **R-007** [unit]: `stop_requested(session_id)` returns `True` when the signal file exists.

- **R-008** [unit]: `stop_requested(session_id)` returns `False` when the signal file does not exist.

## Won't Do

- Test file permissions or concurrent access behavior — filesystem atomicity is OS-level.
- Test what happens when `settings.LOG_DIR` is not writable — that belongs in the settings spec.

## Risks

- **No locking around `stop_requested`/`clear_stop_request`** — file existence check followed by delete is not atomic. If the forwarder and watchdog race on the same file, the watchdog may call `clear_stop_request` while the forwarder is still reading it. Accepted for MVP; the timing window is narrow and the worst case is an extra stop-request poll cycle.
- **`stop_request_path` uses `session_id` directly in the filename** — if `session_id` contains path-separator characters, the path could escape the `control/` directory. Mitigated in practice because session IDs are UUIDs (only hex + hyphens), so no path traversal is possible.

## Open Questions

- _(none)_
