# Phase 5b ARC Batch Playbook

Use for local research Agentic Response Convergence batch work. Release authority
is `.correctless/specs/arc-batch-release.md`, approved through the 2026-10-13
release-contract corrections and recorded in `docs/decisions.md`.

## Goal

Turn verified ECHO/APEX recordings into deterministic event association artifacts
and an interpretation consisting of cited numerical findings.

## Build Rules

- Run explicitly after capture closes and its watermark verifies. Require both
  tenant identifiers and use the shared session lock throughout the transaction.
- Preserve raw records; compute from shared feature epochs and baseline values
  that are persisted with the same run's complete provenance.
- Use successive TOML response intervals W1 [0,30), W2 [30,120), W3 [120,300).
  Historical centered-window utilities are compatibility helpers, not analysis.
- Record incomplete windows, missing signals, and insufficient null support.
- Keep numerical definitions in pure functions. The null shifts modalities
  independently while preserving component relationships within each modality.
- Persist all tested/nonpassing/excluded anchors in the analysis artifact; project
  only FDR-passing events into ECP rows. Interpretation must cite stored metrics.

## Release Gate Criteria

- Analytic feature tests, BH agreement with SciPy, seeded-null reproducibility,
  injected-convergence detection and noise rejection pass.
- A mostly missing recording cannot acquire significance from unsupported null
  draws. Unusable draws are counted; insufficient support yields p=1/untestable.
- Invalid tenant/lifecycle gates perform no artifact writes. Analysis errors do
  not alter previously verified capture state.
- Identical replay produces the same analysis ID, artifact and ECP set. Different
  provenance retains a separate run.
- Baselines and ECPs persist atomically. An analysis_runs database trigger emits
  arc_batch_complete and arc_interpretation_complete, including zero-passing runs;
  application code never directly writes audit_events.
- Deterministic interpretation reads FDR-passing metrics only, cites event/window/
  component/value, and reproduces existing safety alerts with provenance.
- Isolated-DB simulated capture/reconciliation/analysis/export works end to end.
  Performance for 1000 shifts and about 50 anchors is measured independently.

## Explicitly Deferred Gates

Clinical safety assessment and intervention thresholds are not performed. The
local report contains derived quality/excursion review and existing safety alerts,
with an explicit statement of that limit. LLM narrative generation remains
optional and is not needed for metric-cited interpretation. Live convergence,
cloud deployment, broad API/UI expansion and heavyweight physiology stacks remain
outside this release.
