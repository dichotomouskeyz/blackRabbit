# Phase 3b Baseline Playbook

Use for local research baseline-in-batch work. Release authority is
`.correctless/specs/arc-batch-release.md`, approved through the release-contract
corrections on 2026-10-13. See the corresponding decision in `docs/decisions.md`.

## Goal

Compute reproducible baseline distributions from verified captured samples, using
exactly the feature extraction employed by response windows.

## Build Rules

- Require canonical session/sponsor/site identity, closed status, verified
  watermark and the session lock before batch input reads.
- Preserve all raw APEX and ECHO rows. Derived quality findings belong in the
  analysis artifact, never in a raw-row update.
- Use complete fixed-duration feature epochs with valid-sample and channel
  coverage checks. Record component units and extraction/config/input provenance.
- Determine usable modalities from metadata, samples and baseline coverage.
  Represent missing components explicitly; respect configured modality minimums.
- Use settings/TOML for configuration and owning Alembic files for schema changes.

## Release Gate Criteria

- Baseline and response features share `batch/arc/features.py`; analytic sinusoid
  and RR tests prove the named feature calculations and units.
- First-N-seconds baseline selection works with at least two valid feature epochs.
- Every persisted baseline includes analysis ID, source/config hashes, extractor
  version, unit, raw sample count and valid epoch count.
- A rerun with identical inputs/config yields identical artifacts; changed
  provenance preserves a separate run instead of overwriting baseline rows.
- Derived quality exclusions handle flags, invalid values/timestamps, inadequate
  epoch coverage and missing EEG channels. No raw samples are modified.
- A configured data-excursion review records signal/time/value/unit/deviation and
  algorithm provenance, skips unavailable epochs, and makes no clinical claim.
- DB-backed checks use `@pytest.mark.integration` plus isolated TEST_DATABASE_URL.

## Explicitly Deferred Gates

The previous playbook required writing raw `sqi_flag` fields and producing cardiac
safety alerts. Those requirements are superseded for the local research release:
raw data remains immutable, quality findings are derived, and clinical safety
assessment is not performed. No validated clinical threshold contract exists here.
Existing safety alerts are preserved in analysis reports. Marker-selected baseline
windows, live SQI/safety semantics and participant intervention remain deferred.
