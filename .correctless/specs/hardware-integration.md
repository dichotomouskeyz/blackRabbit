# Spec: Hardware integration

## What

A local, headless Python process publishes explicitly mapped BrainFlow source
signals through LSL. It neither records sessions nor starts the existing capture
API. Profiles are portable; connection parameters and pseudonymous source IDs
are local bindings. All public JSON documents carry schema_version 1.

## Rules

- **HW-001 [unit]**: Strict versioned JSON profiles contain an ID, version,
  BrainFlow board ID, one or more presets, source rates, timestamp origins,
  signal mappings and evidence references. Unknown fields/versions, malformed
  values, nonfinite conversions, duplicate presets/signals/channels, overlapping
  assignments and reserved timestamp/package rows are rejected before acquisition.
  BrainFlow descriptors verify layout/rate, not physical wiring or live settings.
- **HW-002 [unit]**: A signal declares its type, source rows, labels, source/output
  units, quantity and optional documented affine conversion. HRV is restricted to
  one device-provided beat-interval channel in milliseconds. ECG/PPG remain their
  own source types. No filtering, resampling, beat detection or derived HRV occurs.
- **HW-003 [unit]**: Bindings use unique pseudonymous source IDs and a closed set
  of typed BrainFlow connection parameters. Multiple devices and presets are
  supported. Duplicate physical connection identities are rejected. No arbitrary
  driver commands, plugins or executable content are accepted in profiles.
- **HW-004 [unit]**: Inspection loads model metadata without preparing hardware;
  it returns unresolved channel alternatives, units, wiring and timestamp origin
  rather than inventing them. Only the synthetic executable profile ships in v1.
  Documentation, simulated verification and physical tests have distinct evidence
  labels. Synthetic data is always identified as simulated.
- **HW-005 [unit]**: Discovery enumerates USB serial endpoints and BLE adverts,
  never pairs, opens serial ports, installs drivers or calls prepare/start.
  Results distinguish ok (possibly empty), missing_dependency, unavailable,
  permission_denied and failed. Name/VID:PID/service matches are provisional,
  may match several profiles, and never prove a physical device identity.
- **HW-006 [unit]**: Serial and BLE backends are optional imports. BLE defaults
  to five seconds. Manual connection works independently of discovery. Runtime
  defaults and hardware-only validation reside in config/settings.py; neither
  inspecting, validating nor running the bridge requires a database URL.
- **HW-007 [unit/native]**: Each signal gets a separate float64 LSL outlet at its
  preset rate. Default names are blackRabbit.<source_id>.<signal_id>, distinct
  from recorder defaults. LSL source_id includes a new run UUID on each explicit
  run, avoiding implicit reconnection across runs. Metadata includes profile
  version/hash/content, effective mapping, BrainFlow version, source kind,
  declared evidence and timestamp conversion; it excludes connection addresses.
- **HW-008 [unit/native]**: Measure epoch-to-LSL offset using bracketed startup
  clock reads; retain the narrowest of five measurements and its uncertainty.
  Convert every sample with that fixed offset. Reject nonfinite, nonpositive,
  duplicate or backward source timestamps. Converted zero timestamps are rejected
  because LSL uses zero to mean "now". A wall/LSL clock offset change over the
  configured threshold (default 50 ms) fails the group. Never clamp or
  silently repair timestamps. This conversion does not certify device latency.
- **HW-009 [unit]**: BrainFlow owns bounded native buffers (default ten seconds
  at the highest configured rate); polling is nonblocking and round-robin across
  devices and presets. Reaching capacity is fatal; no unbounded application queue
  exists. Empty reads are normal until the configured no-data deadline (10 s).
  Invalid shape/nonfinite signal values and invalid beat intervals fail the group.
- **HW-010 [unit/native]**: prepare -> start -> read -> stop -> release is owned
  by one coordinator. Every created adapter/publisher is registered for cleanup
  before setup. Partial prepare/start/outlet failures, cancellation, KeyboardInterrupt
  and acquisition errors all stop/release every resource. Cleanup continues after
  individual cleanup errors and reports failure. No automatic reconnect occurs.
- **HW-011 [unit]**: Python functions and CLI expose inspection, discovery,
  validation and running. JSON events/results/errors use schema_version 1. Logging
  uses the shared structured logger, without raw connection parameters. CLI
  cancellation handles SIGINT and SIGTERM through a stop event.
- **HW-012 [regression]**: Existing capture, XDF/DB order, analysis, HTTP capability
  gates and existing tests are unchanged. Native LSL smoke tests are opt-in and
  do not require a database. Installation includes packaged profiles/examples.

## Evidence and exclusions

The installed BrainFlow 5.22.0 synthetic descriptor has sixteen overlapping
EEG/ECG/EMG/EOG rows, one EDA row and two PPG rows at 250 Hz. The bundled profile
assigns the shared EXG rows once, as EEG; it does not invent respiration or RR.
Unknown synthetic EDA/PPG units remain unknown. Generic board metadata is not a
live interrogation or physical-validation receipt.

USB serial enumeration is not general USB HID detection; BLE is not Bluetooth
Classic discovery. Already-paired Classic serial ports remain manually selectable.
Firmware commands, physical profiles, study configuration, frontend work, raw
cardiac recording and downstream HRV derivation are deferred. The existing
recorder still expects all four modalities and one configured stream per modality.
Bridge publication alone does not establish recorder compatibility or lossless
delivery to an LSL consumer.

## Acceptance

Focused tests exercise HW-001..011; a native synthetic -> bridge -> LSL inlet test
verifies values, metadata, timestamps and teardown. Run settings/forwarder
regression tests, Ruff and Pyright. Report Windows simulated evidence separately
from unavailable physical-device and other-OS evidence.
