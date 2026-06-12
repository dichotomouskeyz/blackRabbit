# Branch 2R Backlog

**Branch:** `2R`
**As of:** 2026-06-11
**Purpose:** Canonical list of unresolved, deferred, conditional, and
user-gated work
**Current branch state:** [state.md](state.md)
**Deep database context:** [db-health.md](db-health.md)

This file replaces the overlapping open-item lists formerly spread across the
capture state audit, database rollup, test findings, and burn-down tracker.
Completed work is recorded in [state.md](state.md), not repeated here.

## Capture Phase-Exit Work

| ID | Priority | Open work | Deep reference |
|---|---|---|---|
| CAP-01 | High | Close and emit `watermark_verified` before ARC; move ARC to a separately gated batch entry point. | [state CAP-01](state.md#cap-01---arc-runs-before-watermark_verified), [DB §3.2](db-health.md#32-watermark-gating--) |
| CAP-02 | High | Treat missing required inlets, failed initial stream startup, and unexpected stream exceptions as fatal forwarder failures. | [state CAP-02](state.md#cap-02---required-stream-failure-can-be-invisible), [DB §2.2](db-health.md#22-threading-model-in-this-pipeline--) |
| CAP-03 | High | Validate XDF payload shape and propagate XDF write/finalization failures before DB continuation. | [state CAP-03](state.md#cap-03---xdf-failure-does-not-stop-the-db-path), [DB §3.4](db-health.md#34-xdf--db-reconciliation-parity--) |
| CAP-04 | High | Load or verify canonical forwarder identity and finish sponsor scoping on reconciliation reads. | [state CAP-04](state.md#cap-04---canonical-session-identity-is-not-fully-enforced), [DB §3.5](db-health.md#35-tenancy-enforcement-sponsor_id--site_id--) |
| CAP-05 | Medium | Ensure reconciliation/watchdog failures produce an observable, queryable terminal state. | [state CAP-05](state.md#cap-05---terminal-lifecycle-persistence-is-not-guaranteed), [DB §5.6](db-health.md#56-failure-recovery-procedures--) |
| CAP-06 | Medium | Repair ten user-gated test fixtures, replace four watchdog-loop placeholders, and run the simulated end-to-end close workflow. | [state CAP-06](state.md#cap-06---critical-test-harness-work-remains) |

## User-Gated Test Work

The original regenerated suite had 46 failures. Phase 2 implementation changes
resolved 36. Ten fixture-level failures remain:

| Area | Tests | Required change |
|---|---:|---|
| ECHO writer | 5 | Construct buffer-only `ECHOWriter()` without passing session config; exercise processing through the owning thread/runtime contract. |
| ARC config fixture | 4 | Replace the `SimpleNamespace` placeholder with the real `ARCWatchdogConfig`/loader contract. |
| Session close cleanup | 1 | Install the fixture's `_tracking_run` wrapper so connection closure can actually be observed. |

Separate from those failures, four watchdog-loop tests are placeholders and
must be wired to `WatchdogState`, subprocess collaborators, restart accounting,
and terminal-state calls.

## Database and Operational Work

Items below are filtered from the former 33-item database rollup. Resolved
items are intentionally absent.

| Former # | Area | Status / trigger | Deep reference |
|---:|---|---|---|
| 1 | Aborted-session watermark path | Deferred to the batch/lifecycle phase. | [DB §3.2](db-health.md#32-watermark-gating--) |
| 4 | Optional-governance migration activation collision | Conditional: re-chain before enabling that migration tree. | [DB §1.7](db-health.md#17-migrations--schema-chain--) |
| 9 | Deadlock/serialization retry classification | Distinguish transient DB failures from permanent constraint failures. | [DB §2.3](db-health.md#23-deadlock--serialization-retry--) |
| 10 | Cursor cleanup on exceptional paths | Replace remaining raw cursor lifecycle sites with context managers. | [DB §2.4](db-health.md#24-cursor-leak-on-exception--) |
| 12 | Live `audit_trigger_smart_func` verification | Deployment-side verification. | [DB §3.1](db-health.md#31-audit-trail-triggers-only-writes--) |
| 13 | Future PII columns and `row_to_json` exclusion | Conditional if real-identity fields are ever introduced. | [DB §3.6](db-health.md#36-pseudonymous-ids--) |
| 14 | Compression/backfill operating procedure | Document before compressed historical backfill is operationalized. | [DB §4.2](db-health.md#42-compression-policy--) |
| 15 | Shutdown buffer-flush time budget | Prevent unbounded close time under a large buffered backlog. | [DB §5.6](db-health.md#56-failure-recovery-procedures--) |
| 16 | Interruptible watchdog restart delay | Replace or wrap blocking sleep so shutdown is prompt. | [DB §5.6](db-health.md#56-failure-recovery-procedures--) |
| 17 | `echo_events` natural-key uniqueness | Add when idempotent marker replay becomes mandatory. | [DB §1.5](db-health.md#15-constraints-pk--fk--unique--check--not-null--) |
| 18 | Reconciliation-log uniqueness | Add a natural uniqueness rule for idempotent reruns. | [DB §1.5](db-health.md#15-constraints-pk--fk--unique--check--not-null--) |
| 19 | `EXPLAIN ANALYZE` on representative data | Run when real-volume session data is available. | [DB §1.6](db-health.md#16-indexes--) |
| 20 | Retention policy | Deferred for the local MVP; required for a managed deployment. | [DB §4.4](db-health.md#44-retention-policy--) |
| 21 | DB roles and least privilege | Required before external/research-site deployment. | [DB §5.1](db-health.md#51-db-roles--privileges--) |
| 22 | TLS policy | Require an explicit remote `sslmode` deployment contract. | [DB §5.2](db-health.md#52-tls-in-transit--) |
| 23 | Automated backup and disaster recovery | Deferred to deployment work. | [DB §5.4](db-health.md#54-backup--disaster-recovery--) |
| 24 | Disk-capacity monitoring | Add before sustained multi-session operation. | [DB §5.5](db-health.md#55-disk-capacity--data-growth--) |
| 25 | Failure-recovery runbooks | Required before research-site deployment. | [DB §5.6](db-health.md#56-failure-recovery-procedures--) |
| 27 | Runtime Alembic compatibility check | Refuse startup when the live DB revision is incompatible. | [DB §5.8](db-health.md#58-schema-version-visibility--) |
| 28 | Continuous aggregates | Evaluate only if ARC/batch query latency requires them. | [DB §4.3](db-health.md#43-continuous-aggregates--) |
| 29 | Secret rotation / vault integration | Deferred to deployment infrastructure. | [DB §5.3](db-health.md#53-secrets-management-for-database_url--) |
| 32 | Computed reconciliation properties | Optional model cleanup; not a phase blocker. | [DB §6.3](db-health.md#63-streamresult--reconciliationreport-computed-vs-stored-fields--) |
| 33 | ARC windows empty-dict contract | Update the spec or implementation so the fallback behavior is explicit. | [DB §6.4](db-health.md#64-centered_arc_window-empty-dict-fallback--) |

## Capture Metadata and Test Infrastructure

| ID | Priority | Open work | Source |
|---|---|---|---|
| META-01 | Phase 3b prerequisite | Wire `eeg_skin_prep` through settings/CLI/workflow/metadata/SQL or explicitly remove the unused schema field. | Historical test findings §5 |
| META-02 | Phase 3b prerequisite | Add EDA electrode settings defaults and metadata fallback symmetry. | Historical test findings §5 |
| TEST-01 | Medium | Use a dedicated `TEST_DATABASE_URL` database instead of the development database. | Historical test findings §7 |
| HYGIENE-01 | Low | Remove legacy empty test-directory husks and stale caches. | Former burn-down 3.3 |
| HYGIENE-02 | Low | Decide whether `.correctless` and `.coverage` belong in `.gitignore`. | Former burn-down 3.4 |
| OBS-01 | Low | Attach `CAPTURE_SOURCE` to all capture logs through logging context rather than per-call fields. | Archived forwarder proposal |

## Explicitly Deferred Design Work

These are not active Phase 2 tasks:

- `SessionRequest` and `SessionRepository` wait for a real UI/API request
  boundary.
- A modality registry or `StreamFactory` waits until another modality is
  actually added.
- Generic primary/backup sink abstractions remain out of scope.
- Broad live safety/SQI behavior remains deferred; only Phase 3b prerequisites
  should be addressed now.

## Historical Records

The source audits, run logs, burn-down tracker, and refactor proposals are
preserved under [`docs/_archive/phase-2-reviews/`](../_archive/phase-2-reviews/).
They are evidence of how the branch evolved, not current task trackers.

## Source Disposition

This map verifies that the former trackers were consolidated without dropping
an item:

- Former DB rollup items **1, 4, 9, 10, 12-25, 27-29, 32, and 33** remain in
  the Database and Operational Work table.
- Former DB rollup items **2, 3, and 7** are consolidated into CAP-05, CAP-04,
  and CAP-03 respectively.
- Former DB rollup items **5, 6, 8, 11, 26, 30, and 31** are resolved and
  recorded in the Completed Phase 2 Work section of
  [state.md](state.md#completed-phase-2-work).
- Burn-down Phases 0, 1, and 2 are summarized as completed branch state.
- The original 14 user-gated tests are accounted for: four forwarder tests are
  resolved and the remaining ten are listed above.
- Burn-down items 3.1 and 3.2 are complete; 3.3 and 3.4 remain as HYGIENE-01
  and HYGIENE-02.
- Open metadata and test-infrastructure findings from the historical test
  audit remain as META-01, META-02, and TEST-01.
- Unimplemented refactor-proposal work is either OBS-01 or explicitly deferred
  under Explicitly Deferred Design Work.
