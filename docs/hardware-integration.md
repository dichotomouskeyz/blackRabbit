# Hardware bridge and frontend handoff

The bridge publishes source signals through LSL. It does not create a research
session, record XDF, write database rows, run ARC, or enable API capture controls.
The only bundled executable device profile is BrainFlow's synthetic board.

## Local commands

Run from the repository root, using the existing Python environment:

```powershell
uv run python -m capture.hardware inspect --board-id -1
uv run python -m capture.hardware validate --config capture/hardware/examples/synthetic.json
uv run python -m capture.hardware run --config capture/hardware/examples/synthetic.json --duration 10
```

Omit `--duration` to run until Ctrl+C or a termination request. The installed
entrypoint is `blackrabbit-hardware`, with the same subcommands. stdout contains
JSON documents; run emits newline-delimited lifecycle events. Logs use the shared
JSON logger on stderr and in the configured log directory. The bridge disables
BrainFlow's native logger before preparation because its INFO logs include
connection parameters; use the bridge as a dedicated acquisition process.

Discovery requires optional dependencies. Include any other extras your local
installation uses when syncing:

```powershell
uv sync --extra hardware --group dev
uv run python -m capture.hardware discover --backend usb_serial
uv run python -m capture.hardware discover --backend ble
```

Discovery only enumerates USB serial endpoints or BLE advertisements. It does
not pair, install drivers or start acquisition. A generic USB adapter is not a
confirmed biosensor. Bluetooth Classic is not covered by BLE scans; an existing
paired serial endpoint can still be supplied manually to BrainFlow. Native USB
devices that do not expose serial ports are outside this discovery backend.

Both the bridge and discovery work without DATABASE_URL. Runtime defaults live
in `config/settings.py`: five-second BLE scan, ten-second native/outlet buffers,
20 ms polling, ten-second no-data deadline, and 50 ms host-clock jump threshold.
The existing capture validator still requires its normal database configuration.

## Profiles and local bindings

`capture/hardware/profiles/synthetic.json` is the complete portable schema
example. `capture/hardware/examples/synthetic.json` is the matching binding file.
Profiles include `schema_version`, `id`, semantic `version`, `board_id`, `presets`,
`evidence`, and optional `discovery_hints`. Each preset supplies its BrainFlow
preset number, model sampling rate, timestamp origin and signals. Signals
declare source rows, labels, source/output units, type and quantity. A nonidentity
scale/offset or unit change requires a `conversion_reference`.

The initial profile exposes sixteen EEG channels and one EDA plus two PPG
channels, all at 250 Hz. EDA/PPG units are explicitly unknown. The EXG inputs are
assigned once as EEG even though BrainFlow also advertises ECG/EMG/EOG aliases.
The profile does not manufacture respiration or RR intervals.

A local binding file has `schema_version: 1` and a `bindings` array. Each item
contains a pseudonymous `source_id`, a profile filename (relative to the binding
file) or `builtin:synthetic`, and optional `parameters`. Multiple bindings and
multiple presets within a device profile are supported. Use pseudonymous source
aliases, not participant names. The same physical endpoint must not be configured
twice; native resources have one owner.

Supported connection keys are `serial_port`, `mac_address`, `ip_address`,
`ip_address_aux`, `ip_address_anc`, `serial_number`, `other_info`, `ip_port`,
`ip_port_aux`, `ip_port_anc`, `ip_protocol`, and `timeout`. Text and integer types
are checked; protocol values are BrainFlow's 0/1/2 enum. Driver preparation
defaults to a ten-second timeout. Profiles cannot contain executable driver
commands. Runtime firmware configuration is outside v1.

`inspect` returns model metadata, alternative channel interpretations and
unresolved fields. It does not return a ready-to-run physical profile or query
the connected device. Review device documentation and wiring before filling
those fields. Model metadata rate checks do not establish a device's current
firmware settings. Unsupported profile versions fail before preparation.

Evidence entries distinguish `documentation`, `simulated_verification` and
`physical_test`. These are declarations with references and notes, not evidence
automatically certified by the loader. Discovery hints match a `transport`,
`field` and `value`: USB uses `name`/`vid_pid`, BLE uses `name`/`service_uuid`.
Matching is case-insensitive and provisional; several profiles may match one
candidate. Pass profiles to discovery with repeated `--profile` arguments.

## Programmatic interface for Claude

Public imports come from `capture.hardware`:

| Operation | Input | Result / effect |
|---|---|---|
| `inspect_board` | BrainFlow integer board ID | Schema-1 draft with model descriptors, ambiguous rows and unresolved fields; no connection |
| `load_profile` / `synthetic_profile` | JSON path / no argument | Validated `DeviceProfile` |
| `load_config` | Binding JSON path | `BridgeConfig` containing `DeviceBinding` values |
| `validate_config` | `BridgeConfig` | Schema-1 report with profile hashes and `connection_verified: false`; no preparation |
| `await discover` | Backend tuple and optional profile tuple | Independent backend statuses and candidates |
| `run_bridge` | Config, optional stop event, duration and event callback | Blocking run with structured events; returns sample counters after teardown |

Discovery backend statuses are `ok`, `missing_dependency`, `unavailable`,
`permission_denied`, and `failed`. `ok` with zero candidates is a successful empty
scan. Candidate fields are `transport`, `address`, `name`, `identifiers`,
`possible_profiles`, and `identity_confirmed` (always false for discovery).
Addresses are opaque platform identifiers; a BLE identifier is not necessarily
a MAC address and may require manual resolution for a specific BrainFlow driver.

The run callback receives `preparing`, `streaming`, and `stopped` or `cancelled`
events with a run ID. On failure the Python API raises `HardwareError` with a
stable `code`, chains the original exception, and cleans up first. The CLI emits
an `error` document and exits 1. Successful commands and clean cancellation exit
0. Discovery with any unsuccessful requested backend exits 1 while retaining
all results. Invalid command-line syntax follows argparse's exit 2 behavior.

Failure codes include `invalid_configuration`, `buffer_capacity_reached`,
`source_timeout`, `invalid_batch`, `invalid_signal`, `invalid_timestamp`,
`invalid_clock`, `clock_discontinuity`, `acquisition_failed`, and `cleanup_failed`.
Lifecycle and cleanup diagnostics are also in the shared structured log. A
failed run requires an explicit new start. In-process callers cancel with a
`threading.Event`; native preparation may take its driver timeout to return.

Frontend code should invoke this through a future local host integration.
There are no new HTTP routes in this increment. A scan result, validated config,
connected source, and physically tested device must remain separate UI states.

## Streams, timestamps and existing recorder compatibility

Outlets use `blackRabbit.<source_id>.<signal_id>` names. Every explicit run adds
a new UUID to the LSL source identifier. Samples are float64, carry individual
timestamps, and retain their source rate. XML channel metadata includes labels,
types and units. The `blackrabbit` XML field contains JSON with the profile
version, SHA-256 content hash and effective profile, signal mapping, BrainFlow
version, source kind, run identity and timestamp conversion. Connection addresses
are excluded.

Five bracketed wall/LSL clock measurements establish a fixed epoch-to-LSL offset;
the narrowest bracket supplies its uncertainty. The mapping is included in stream
metadata, so original source timestamps can be reconstructed. Each preset's
timestamps must be positive, finite and strictly increasing across chunks.
Clock discontinuities fail the complete group. Neither this conversion nor LSL
clock synchronization measures the hardware's sampling/transport latency.

The native buffers are bounded. Reaching capacity fails the group; there is no
unbounded application queue. The publisher does not guarantee consumer delivery
or quantify packet loss occurring before BrainFlow. No filtering, resampling,
beat detection, reconnection or hidden signal substitution occurs.

Existing capture is deliberately unchanged: it expects all four configured
modalities, one stream per modality, a global DEVICE_ID, and EEG channel count
matching its configuration. Its EDA rows assume microsiemens; its HRV rows expect
device-provided beat intervals in milliseconds. **Do not point those inputs at
unknown-unit EDA, raw ECG, or raw PPG.** The shipped synthetic bridge alone cannot
satisfy that recorder's four-modality contract. The pre-existing complete demo
simulator remains available for that workflow.

An explicitly compatible input can be wired by matching the recorder's stream
name, units, channel count and sample-rate settings. This increment does not
certify end-to-end multi-device recording or persist per-device identities into
the existing tables. Raw ECG/PPG recording, beat detection, HRV derivation and
study-specific modality selection are future work.

## Verification evidence

| Capability | Evidence | Limit |
|---|---|---|
| Profile parsing, mapping and lifecycle | Spec-derived unit tests | Simulated inputs and injected failures |
| USB serial and BLE discovery | Mocked enumeration, errors and ambiguity tests | No physical scan/connection claim |
| BrainFlow -> bridge -> LSL | Native synthetic board and local inlet on Windows, BrainFlow 5.22.0 / pylsl 1.18.2 | Source simulation; no physical sensor validation |
| Physical profiles | No bundled physical profile | Device, firmware, OS and driver combination still needs verification |
| Other operating systems | Not exercised in this task | Cross-platform library availability is not an execution receipt |

Run the ordinary suite and opt-in native test separately:

```powershell
uv run python -m pytest tests/capture_tests/hardware -m "not lsl_smoke"
uv run python -m pytest tests/capture_tests/hardware/test_native.py -m lsl_smoke
```

The smoke test compares received values against BrainFlow samples before
publication, checks source metadata/timestamps, cancels acquisition and verifies
teardown. It requires native BrainFlow/LSL libraries and working local sockets,
but no database or physical device. Network-restricted Windows sandboxes can
prevent Python event-loop creation or LSL discovery before application code runs.

### Verification receipt: 2026-10-13

Windows, Python 3.12.10, BrainFlow 5.22.0, pylsl 1.18.2, Bleak 3.0.2 and
pySerial 3.5:

- 66 hardware contract tests passed, including the optional Bleak reason cases.
- Three native smoke tests passed: sample/metadata/timestamp agreement with an
  LSL inlet, two simultaneous devices followed by explicit restart, and multiple
  presets within one device.
- 64 focused settings/capture/control/API regressions passed; one test skipped
  and four database integration tests deselected.
- Ruff, formatting and Pyright checks passed for the changed Python code.
- The installed `blackrabbit-hardware validate` command returned a successful
  JSON report without database configuration.

These runs used simulated sources only. No physical-device scan or acquisition
was performed. Native/event-loop tests ran outside the restricted Windows
sandbox after its local-socket creation stalled before application execution.
