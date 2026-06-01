# Module Inventory

Full module list with DB tables written and modality mappings.
Use this to confirm names before generating tests.

---

## Capture Layer (Phase 2)

| Module | Tables written | Modalities | Notes |
|--------|---------------|------------|-------|
| `capture/session_init.py` | `sessions`, `session_signal_metadata` | all 4 | creates session row + one metadata row per modality |
| `capture/session_close.py` | `sessions` | — | transitions session status, triggers watermark check |
| `capture/lsl_forwarder.py` | `eeg_samples`, `hrv_samples`, `eda_samples`, `respiration_samples` | eeg, hrv, eda, respiration | reads LSL inlets, writes to TimescaleDB + XDF |
| `capture/xdf/writer.py` | XDF file (not DB) | all 4 | writes XDF backup |
| `capture/echo_handler/` | `echo_events` | — | receives ECHO marker events from LSL stream |
| `capture/logger.py` | — | — | structured logging helper, no DB writes |

Test location: `tests/capture_tests/<domain>/test_<module>.py`

---

## ARC Package — Batch Chain (Phase 3b / Phase 5b)

| Module | Tables written | Modalities | Notes |
|--------|---------------|------------|-------|
| `batch/arc/processor.py` | `session_baselines`, `event_composite_profiles` | eeg, hrv, eda, respiration | statistical core; reads ECHO + APEX; writes ECPs |
| `batch/arc/models.py` | — (in-memory only) | eeg, hrv, eda, respiration | `EchoAnchorEvent`, `APEXResponse`, `ConvergenceEvent` dataclasses |
| `batch/arc/windows.py` | — (in-memory only) | — | W1/W2/W3 temporal window helpers |
| `batch/arc/preflight.py` | — | — | preflight session validation checks |
| `batch/eeg_batch.py` | `eeg_samples` (reads) | eeg | per-modality batch feature extraction |
| `batch/hrv_batch.py` | `hrv_samples` (reads) | hrv | per-modality batch feature extraction |
| `batch/eda_batch.py` | `eda_samples` (reads) | eda | per-modality batch feature extraction |
| `batch/respiration_batch.py` | `respiration_samples` (reads) | respiration | per-modality batch feature extraction |
| `batch/reconciliation/db.py` | — | — | DB queries for reconciliation |
| `batch/reconciliation/backfill.py` | modality sample tables | all 4 | gap backfill from XDF |
| `batch/reconciliation/xdf.py` | — | — | XDF read helpers for reconciliation |
| `batch/utils.py` | — | — | shared batch utilities |

**Phase 3b new module (to be created):**

| Module | Tables written | Modalities | Notes |
|--------|---------------|------------|-------|
| `batch/arc/baseline.py` | `session_baselines` | eeg, hrv, eda, respiration | post-session baseline computation; reads validated APEX records |

Test location: `tests/capture_tests/arc/test_<module>.py`

---

## Operator Surface (Phase 4b)

| Module | Tables written | Notes |
|--------|---------------|-------|
| CLI / notebook trigger | none directly | thin surface over batch chain; test trigger path and response format |

---

## Shared Tables Reference

| Table | Written by | Audited by trigger |
|-------|-----------|-------------------|
| `sessions` | `session_init`, `session_close` | yes |
| `session_signal_metadata` | `session_init` | yes |
| `eeg_samples` | `lsl_forwarder` | yes |
| `hrv_samples` | `lsl_forwarder` | yes |
| `eda_samples` | `lsl_forwarder` | yes |
| `respiration_samples` | `lsl_forwarder` | yes |
| `echo_events` | `echo_handler` | yes |
| `session_baselines` | `arc/baseline.py` (Phase 3b) | yes |
| `event_composite_profiles` | `arc/processor.py` (Phase 5b) | yes |
| `alert_events` | `arc/safety.py` (deferred) | yes |
| `audit_events` | **DB triggers only** | — |

---

## Signal Components by Modality

Used in `session_baselines` and `event_composite_profiles` `signal_component` field.

| Modality | Signal components |
|----------|------------------|
| `eeg` | `eeg_alpha_power` |
| `hrv` | `hrv_rmssd` |
| `eda` | `eda_mean` |
| `respiration` | `respiration_rate` |

These are defined in the ARC watchdog TOML config under `[signal_components]`.

---

## ARC Window Names

| Name | Label | Default range |
|------|-------|---------------|
| `w1` | immediate | 0–30 s post-anchor |
| `w2` | near_response | 30–120 s post-anchor |
| `w3` | sustained_response | 120–300 s post-anchor |

Defined in `config/arc_watchdog_config.toml` under `[windows.*]`.
