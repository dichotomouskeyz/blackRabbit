# ARC deterministic batch release contract

Approved release-contract regeneration, 2026-10-13. This contract replaces the
prototype baseline/proxy behavior in arc-processor.md where inconsistent.

- B-001: `run_arc_post_session(conn, session_id, sponsor_id, *, site_id, config_path=None)`
  requires nonempty tenant IDs, canonical session identity, status closed, and a
  watermark_verified audit event. A failed/missing gate performs no artifact writes.
  Capture closure never invokes this entry point implicitly. ARC holds the shared
  session-key transaction advisory lock used by capture/backfill for the full run.
- B-002: Every raw/metadata/baseline read carries session, sponsor and site scope.
  Raw ECHO/APEX records remain immutable. Derived quality findings live in the
  analysis artifact; no application writes to audit_events.
- B-003: Feature extraction uses complete fixed-duration epochs shared by baseline
  and response windows. EEG computes channel-wise one-sided Hann periodogram band
  power averaged across channels, retaining the captured voltage unit squared.
  Bands: theta [4,8), alpha [8,13), beta [13,30). HRV epoch RMSSD and sample SDNN
  are in ms, heart rate is mean 60000/RR in beats/min. EDA mean is in uS.
  Respiration amplitude is mean processed amplitude in metadata units; rate uses
  only supplied breaths_per_min, never amplitude inversion. Unsupported components
  raise a config error; absent derived respiration rate is explicitly unavailable.
- B-004: Flagged/nonfinite and nonpositive RR samples are excluded. A feature epoch
  with > configured degraded fraction or insufficient/irregular EEG samples is
  unavailable. Valid samples must span at least 80% of the epoch, with at least
  80% expected samples when metadata supplies a rate; every expected EEG channel
  must be present. Nonfinite timestamps are excluded and counted. No
  filtering/decomposition/clinical validation is implied. Baseline
  mean and sample standard deviation summarize at least two valid feature epochs.
  Metadata plus samples determine active modalities. Configured absent modalities
  are recorded as unavailable, provided min_modalities_required is met.
- B-005: Baseline is first configured N seconds from earliest stored APEX timestamp.
  Baselines persist units, extractor version, full config hash/version and input
  hash. Changed provenance cannot silently reuse old values. First-N is the MVP
  baseline mode; marker-selected baselines are deferred.
- B-006: Only successive TOML windows drive analysis: W1 [0,30), W2 [30,120),
  W3 [120,300), relative to each canonical ECHO timestamp. Only wholly enclosed
  epochs enter windows. Incomplete recording windows are explicitly unavailable.
  Historical centered helper functions remain compatibility utilities only.
- B-007: Dimensionless deviation is (response epoch mean - baseline epoch mean)
  divided by max(baseline sample SD, abs(mean)*1e-6, 1e-9). Participation requires
  abs(deviation) >= configured threshold. Convergence density is participating
  modalities / available modalities, requiring the configured minimum modalities.
  Window score is density times mean modality strength; modality strength is the
  maximum absolute component deviation capped at 10. The same pure statistics
  function computes observed and null scores; correlated components do not increase
  modality weight.
- B-008: The null independently circular-shifts each modality's feature timeline,
  retaining within-modality component relationships and temporal ordering. A
  fixed NumPy PCG64 seed, input ordering and config produce identical results.
  Event statistic is maximum window score over eligible W1/W2/W3. Its empirical p is
  (1 + valid null scores >= observed)/(valid draws + 1). Surrogates must have the
  same observed component support in every tested window. Invalid draws are
  excluded and counted; fewer than max(100, requested/2) usable draws makes the
  event untestable with p=1. BH adjusts across all canonical
  session anchors, including untestable p=1 anchors. The stationarity assumption
  and descriptive/exploratory nature are included in every report.
- B-009: All events and exclusion reasons are persisted in a content-addressed
  analysis artifact. Only FDR-passing events are projected into ECP rows. An
  identical replay reuses the same analysis ID and leaves one artifact/ECP set.
  Persistence is atomic inside the caller's transaction. CLI commits only success.
- B-010: Deterministic interpretation reads the finished metrics, cites each claim
  by echo_event_id/window/component, and includes existing safety alerts with
  algorithm provenance. It does not diagnose, create intervention thresholds,
  or use an LLM. An analysis_runs insert trigger writes arc_batch_complete and
  arc_interpretation_complete audit events, including zero-passing-event runs.

Numerical references:
- https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.periodogram.html
- https://numpy.org/doc/stable/reference/generated/numpy.fft.rfft.html
- https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.false_discovery_control.html

Verification: analytic sinusoid power and RR sequences, SQI/missing samples,
successive half-open bounds, BH reference vectors, seeded null reproducibility,
wrong-tenant/no-watermark refusal, changed provenance, and DB replay persistence.

- B-011: Post-session quality review counts stored flags and invalid values/times.
  Configured absolute epoch-deviation excursions are reported with signal, time,
  value, units and algorithm provenance, skipping unavailable epochs. These are
  descriptive data-review findings, not cardiac diagnoses or safety alerts.
  Clinical safety thresholds and alert generation remain deferred because no
  validated clinical threshold contract exists for this local research release.
