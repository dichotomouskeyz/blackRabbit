# blackRabbit release contract corrections

Prepared and approved 2026-10-13. Jahlon approved the contract corrections and
affected test regeneration, then limited implementation to the backend. The
frontend remains separate work. See the release audit for completed validation.

## Why approval is needed

`AGENTS.md` requires implementation to follow `.correctless/specs/` and says:
"fix the implementation to the spec, or upgrade the spec first and regenerate
the test (user-gated)." Several specifications currently encode behaviors
that conflict with the repository's capture-integrity requirements or with
the external XDF format. Changing implementation alone would preserve neither
the contract nor a meaningful test gate.

## Proposed contract changes

| Contract | Current rule | Proposed release rule and verification |
| --- | --- | --- |
| `xdf-writer` R-002, R-003, R-006, R-007 and reconciliation R-009 | Two-byte variable integers, an extra wall-clock field, and bare timestamps | Follow XDF 1.0: variable integer widths 1/4/8, stream ID followed by sample count, timestamp length byte followed by timestamp. Prove independent `pyxdf` parsing for all four signals and ECHO; internal round trips alone are insufficient. |
| `xdf-writer` failure/lifecycle rules | Disk failures are swallowed; writes after close silently disappear | Reject malformed shape/count/timestamps before writing. A failed write or finalization must prevent successful continuation of capture. Preserve recoverable artifacts and expose a fatal outcome. |
| `session-close` R-018/R-019 and ARC orchestration | Run ARC before capture watermark; analysis failure marks raw capture failed | Reconcile and persist closed/failed capture first. Invoke analysis separately and require a verified watermark plus canonical tenant identity. Failed reconciliation must never run analysis. Analysis failure preserves verified raw capture. |
| `forwarder` and `watchdog` | Some startup failures return from individual workers; placeholder watchdog coverage | Every required stream startup or runtime failure stops capture and causes a nonzero result. Verify canonical participant/site/sponsor identity before writing. Test restart, shutdown, and terminal-state persistence with the actual collaborator interfaces. |
| `arc-processor`, `arc-preflight`, `arc-windows` | Proxy features under physiological names, inconsistent filters and window definitions | Use shared defined feature extraction; preserve units and extraction/config provenance. Apply identical anchor filters throughout alignment. Adopt one window definition consistently before convergence implementation. |
| Existing fixture debt | Ten fixtures documented as stale in `docs/2R/backlog.md` | Regenerate only fixtures that contradict the approved contracts. Keep assertions that expose real defects; replace four watchdog placeholders with behavior tests. Re-run the complete suite against an isolated migrated test database. |

The XDF format reference is the [official XDF specification](https://github.com/sccn/xdf/wiki/Specifications).
Existing recordings must not be overwritten. Any legacy-format compatibility
must be explicit and tested separately from newly written standards-compliant
recordings.

## Completion order

1. Correct the contracts and regenerate affected tests.
2. Stabilize XDF durability, required streams, canonical identity, closeout,
   restart/reconciliation, and terminal states.
3. Complete deterministic features and baseline persistence with provenance.
4. Implement convergence, null/FDR analysis, and reproducible artifacts.
5. Complete the local operator review/export backend and document its API for
   the separately developed frontend.
6. Run isolated database integration, independent XDF validation, simulated
   end-to-end replay, and a clean-clone quickstart.
7. Review publication contents and history, add MIT licensing per the release
   playbook, then publish the approved release.

## Scope preserved

This is the local research-tool MVP. Clinical use, live intervention, cloud
deployment, new hardware integrations, and broad service infrastructure remain
deferred. The audit does not establish that the product is finished, validate
physiological interpretation, or authorize changing GitHub visibility.
