# Spec: ARC Models

## Metadata
- **Task**: arc-models
- **Intensity**: standard
- **Recommended-intensity**: standard
- **Intensity reason**: no security keywords, no TB-xxx overlap, no antipattern history
- **Override**: none

## What

`batch/arc/models.py` defines the in-memory contract for ARC convergence events. It contains three frozen dataclasses — `APEXResponse`, `ARCWindowResponse`, and `ARCConvergenceEvent` — each with `__post_init__` validation. These classes are pure value objects: they validate at construction time and serialize to the `event_composite_profiles` row shape. They perform no signal processing and open no DB connections.

## Rules

### `APEXResponse` validation — unit tests

- **R-001** [unit]: `APEXResponse` raises `ValueError` when `baseline_std < 0`.

- **R-002** [unit]: `APEXResponse` raises `ValueError` when `sample_count <= 0`.

- **R-003** [unit]: `APEXResponse` raises `ValueError` when `p_value` is outside `[0.0, 1.0]`.

- **R-004** [unit]: `APEXResponse.arc_signal_id` returns `f"{modality}.{signal_component}"`.

- **R-005** [unit]: `APEXResponse.to_deviation_metric()` returns a dict containing all nine core fields: `modality`, `signal_component`, `baseline_mean`, `baseline_std`, `observed_value`, `sample_count`, `z_score`, `p_value`, `effect_direction`.

- **R-006** [unit]: `APEXResponse.to_deviation_metric()` includes a `metadata` key only when `self.metadata` is non-empty.

### `ARCWindowResponse` validation — unit tests

- **R-007** [unit]: `ARCWindowResponse` raises `ValueError` when `start_s < 0`.

- **R-008** [unit]: `ARCWindowResponse` raises `ValueError` when `end_s <= start_s`.

- **R-009** [unit]: `ARCWindowResponse` raises `ValueError` when `convergence_density < 0.0`.

- **R-010** [unit]: `ARCWindowResponse` raises `ValueError` when any `APEXResponse` in `responses` has a `.window` value that does not equal the `ARCWindowResponse.name`.

- **R-011** [unit]: `ARCWindowResponse.participating_signals` returns a sorted tuple of unique `arc_signal_id` values from all responses — duplicates are deduplicated.

### `ARCConvergenceEvent` validation — unit tests

- **R-012** [unit]: `ARCConvergenceEvent` raises `ValueError` when the three windows are not ordered as `("w1", "w2", "w3")`.

- **R-013** [unit]: `ARCConvergenceEvent` raises `ValueError` when `null_threshold` is outside `[0.0, 1.0]`.

- **R-014** [unit]: `ARCConvergenceEvent` raises `ValueError` when `fdr_q_value` is outside `[0.0, 1.0]`.

- **R-015** [unit]: `ARCConvergenceEvent` raises `ValueError` when `passed_fdr` is not `True` — only FDR-passing events may be serialized.

- **R-016** [unit]: `ARCConvergenceEvent` raises `ValueError` when `temporal_alignment_score` is not `None` and is outside `[0.0, 1.0]`.

- **R-017** [unit]: `ARCConvergenceEvent` raises `ValueError` when `arc_config_version` is empty.

- **R-018** [unit]: `ARCConvergenceEvent` raises `ValueError` when `arc_config_sha256` is not exactly 64 characters.

### Serialization — unit tests

- **R-019** [unit]: `ARCConvergenceEvent.to_event_composite_profile_row()` includes `echo_event_id`, `deviation_metrics`, `null_threshold`, `fdr_q_value`, `passed_fdr`, `temporal_alignment_score`, `sap_available_signals`, `sap_participating_signals`, `arc_config_version`, and `arc_config_sha256`.

- **R-020** [unit]: `to_event_composite_profile_row()` includes exactly the three convergence-density columns (`w1_convergence_density`, `w2_convergence_density`, `w3_convergence_density`) and three participating-signals columns (`w1_participating_signals`, `w2_participating_signals`, `w3_participating_signals`) — one pair per window.

- **R-021** [unit]: `to_event_composite_profile_row()` carries tenancy fields `session_id`, `participant_id`, `site_id`, `sponsor_id` from `self.echo`.

## Won't Do

- Test `EchoAnchorEvent` construction — it is a plain frozen dataclass with no validation logic; its shape is tested as part of `ARCConvergenceEvent` serialization.
- Test that `metadata` is stored as `MappingProxyType` internally — that is an immutability implementation detail, not a behavioral requirement.

## Risks

- **`ARCConvergenceEvent` enforces `passed_fdr is True`** — only passing events can be constructed. There is no model type for a failing-FDR convergence event. If the codebase ever needs to store failing events in `event_composite_profiles`, the model must be extended or a separate dataclass added.

## Open Questions

- _(none)_
