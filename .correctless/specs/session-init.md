# Spec: Session Init

## Metadata
- **Task**: session-init
- **Intensity**: standard
- **Recommended-intensity**: standard
- **Intensity reason**: no security keywords, no TB-xxx overlap, no antipattern history
- **Override**: none

## What

`capture/session_init` creates a new research session in a single atomic DB transaction. It generates a UUID session ID, inserts one `sessions` anchor row (status transitions `initializing` → `active` within the same transaction), inserts four `session_signal_metadata` rows (one per modality: EEG, HRV, EDA, respiration), and inserts one `schema_version_log` row recording the exact software environment at capture time. It returns the session UUID to the caller. The module also exports `VALID_COMPOUNDS` and `VALID_DOSE_UNITS` for use by callers at their validation boundary.

## Rules

- **R-001** [unit]: `create_session` returns a string that is a valid UUID v4.

- **R-002** [unit]: `create_session` validates `compound` against `VALID_COMPOUNDS` before opening a DB connection — raises `ValueError` if the value is not in the set.

- **R-003** [unit]: `create_session` validates `participant_id` as a well-formed UUID before opening a DB connection — raises `ValueError` if the format is invalid.

- **R-004** [unit]: `create_session` validates `compound_dose_unit`, when provided, against `VALID_DOSE_UNITS` — raises `ValueError` if the value is not in the set.

- **R-005** [unit]: `_build_metadata_rows` returns exactly 4 dicts — one for each modality: `eeg`, `hrv`, `eda`, `respiration`. No more, no fewer.

- **R-006** [unit]: Every dict returned by `_build_metadata_rows` carries `session_id`, `site_id`, `sponsor_id`, and `participant_id` with the values passed in — none are altered, dropped, or defaulted.

- **R-007** [unit]: The EDA metadata row sets `electrode_placement`, `electrode_type`, and `skin_prep` from the values passed to `_build_metadata_rows`. When those values are `None`, the row carries `None` (not a default string).

- **R-008** [unit]: The respiration metadata row sets `is_derived = True` when `settings.RESPIRATION_SOURCE` is `"rsa_derived"`, and `False` otherwise.

- **R-009** [unit]: `_build_schema_version_row` includes `alembic_version`, `app_version`, `python_version`, `postgres_version`, `timescaledb_version`, and `pgvector_version`. None of these fields are omitted or aliased.

- **R-010** [integration]: After `create_session` returns, exactly one row exists in `sessions` with the returned `session_id` and `status = 'active'`.

- **R-011** [integration]: After `create_session` returns, exactly 4 rows exist in `session_signal_metadata` with the returned `session_id` — one per modality (`eeg`, `hrv`, `eda`, `respiration`).

- **R-012** [integration]: After `create_session` returns, exactly 1 row exists in `schema_version_log` with the returned `session_id`.

- **R-013** [integration]: If the DB raises any exception during the transaction, `create_session` rolls back completely — no partial rows remain in `sessions`, `session_signal_metadata`, or `schema_version_log`.

- **R-014** [integration]: `audit_events` is never written directly by `create_session` — the row (if any) is written by the DB trigger on `sessions`, not by application code.

- **R-015** [integration]: Every `session_signal_metadata` row carries the same `site_id` and `sponsor_id` as the `sessions` row for the same session.

## Won't Do

- Validate that `site_id` or `sponsor_id` exist in any reference table — that is the DB constraint's job.
- Validate that `participant_id` belongs to a known participant — session init is pseudonymous; no participant registry exists in the MVP.
- Accept or store PII in any column — `participant_id` is always an opaque UUID.
- Write to `audit_events` directly.

## Risks

- **`compound` passed as free text reaches the DB without validation** — mitigated by R-002 (ValueError before DB open).
- **`participant_id` type mismatch causes opaque psycopg2 error** — mitigated by R-003 (UUID validation before DB open).
- **Partial session state if process is killed mid-transaction** — accepted; PostgreSQL rolls back uncommitted transactions on disconnect. No additional mitigation in MVP.
- **Schema version log captures `None` for optional extension versions** (pgvector, timescaledb) when extensions are not installed — accepted; `None` is a valid sentinel meaning "not present."

## Open Questions

- _(none — scope is fully defined by existing implementation + confirmed decisions above)_
