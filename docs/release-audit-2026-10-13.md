# blackRabbit backend audit and completion

Audit date: 2026-10-13. Scope: local research backend. Frontend completion is
separate work at Jahlon's request. GitHub publication is a separate step.

## Original assessment

The existing implementation was a substantial prototype with useful boundaries:
separate capture/reconciliation/batch modules, schema migrations, structured
logging, pseudonymous identities, and capability-gated API routes. Initial
verification found 301 passing non-integration tests, four skipped watchdog
placeholders, a passing lint gate, and three API typing errors.

The architecture was stronger than end-to-end correctness. Some specifications
encoded incorrect behavior, so tests passing did not establish a complete
recording and analysis system. Jahlon approved correcting the specifications and
regenerating affected tests before implementation.

## Corrections

| Finding | Implemented correction |
| --- | --- |
| Nonstandard XDF layout accepted by its own reader | XDF 1.0 writer/reader, independent pyxdf tests, explicit legacy recovery |
| Storage failures swallowed before DB writes | Shape/finite validation, flush/fsync before DB continuation, fatal storage errors |
| Worker failure and unsafe restart could hide data loss | Shared failure propagation, no automatic segmented restart, fresh-session requirement |
| Caller-controlled identity or wrong XDF could reach recovery | Canonical identity checks, full file identity validation, session advisory locks |
| EEG channel loss or replay changed electrode identities | Complete-frame counting and per-channel recovery using persisted/header metadata |
| ARC ran before capture watermark | Independent closeout and analysis; verified capture required before batch |
| Proxy values mislabeled as physiological metrics | Shared epoch extraction with explicit units, supported features and missing-data handling |
| No convergence or reproducible analysis persistence | Seeded circular-shift null, BH FDR, durable analysis/baseline/ECP provenance, deterministic export |
| Missing API config returned raw errors | Structured 503 handling and validated server tenancy |
| Completed analysis was not available to the frontend | Persisted analysis read with provenance, sponsor/site isolation and watermark gate |
| Stale/placeholder tests hid integration behavior | Approved spec-derived regeneration, actual watchdog tests, restored settings isolation |
| Incomplete release setup | MIT license, backend handoff, explicit source package allowlist, pinned database image |

## Verification

The final source run passed **492 tests, zero skipped**, with **75.65%** coverage
across capture, batch, API and config. The complete source suite ran against an
isolated PostgreSQL/Timescale database and a dedicated SELECT-only API role.
Evidence is retained locally in `.pytest_tmp/backend-final.log`,
`.pytest_tmp/backend-final-results.xml` and `.pytest_tmp/backend-coverage.json`.

A clean Linux install extracted the backend source archive, installed its locked
dependencies with Python 3.12.3, migrated a fresh database and provisioned its API
role. Its final run passed **484 tests, zero skipped**, with **75.61%** coverage. The eight
excluded tests concern frontend toolchain isolation, which is absent from the
backend archive. Linux validation found two Windows-only signal typing accesses;
these were corrected with optional signal lookup. The affected Windows capture
and watchdog tests then passed (33 tests). Ruff and Pyright pass on both systems.
Linux logs and JUnit results are retained in `dist/backend-validation`.
The installed wheel also imports from an unrelated working directory and loads
its packaged analysis configuration and 26 migration files.

Independent XDF verification covers all four physiological streams plus ECHO,
raw timestamps, float32 values, and complete metadata/footer structure. Unit
tests exercise malformed data, wrong identities, storage failure and replay.

The first full backend smoke generated 900 seconds of fictional data through
real capture chunk writers and PostgreSQL: 90,000 EEG frames, 900 HRV samples,
3,600 EDA samples, 3,600 respiration samples and one contextual event. It
deliberately withheld 600 EDA database samples, recovered them from XDF, closed
capture with one verified watermark, and ran analysis twice with identical
exports and one persisted run. Premature analysis and foreign sponsor/site
access were rejected. Receipt: `data/backend_smoke/release-20261013-01/receipt.json`.
After final numerical changes, two fresh exports were byte-identical, with
SHA-256 `b3aef8b92133156958159fe34b4ee2927e2df6ae3947c91500c454799489b6ba`.
Receipt: `data/backend_smoke/release-20261013-01/final-replay-receipt.json`.

The same full offline workflow also passed on a freshly migrated pinned
TimescaleDB 2.27.1 / PostgreSQL 16 container. Receipt:
`data/backend_ci_fresh_smoke_20261013/receipt.json`.
The independently installed Linux source package passed this workflow too,
including deterministic replay and 600 recovered EDA rows in 89.95 seconds.
Receipt: `dist/backend-validation/smoke-receipt.json`.

A separate actual LSL test started the synthetic publisher, marker publisher,
and forwarder processes. After all streams connected, it recorded 12 seconds,
requested shutdown, verified exit code zero, and closed with matching XDF/DB
counts and one verified watermark. Receipt:
`.pytest_tmp/lsl-smoke-c758aa4d/receipt.json`.

These are synthetic-software checks. They do not validate real electrodes,
device calibration, physiological interpretation, or clinical effectiveness.

## Supported release and remaining scope

The release supports local capture, recoverable closeout, deterministic
post-session analysis, JSON export, and tenant-scoped operator reads. The
frontend is unfinished and excluded from the backend source archive.

Clinical safety assessment, cardiac alert generation, marker-selected baseline
windows, EDA phasic decomposition, LLM interpretation, safe segmented capture
resume, remote authentication and capture-process ownership remain deferred.
The derived quality/excursion report explicitly says clinical safety assessment
was not performed. This release does not silently satisfy the old clinical
safety phase gates.

The HTTP API remains localhost-only. Capture, close and analysis execution
remain explicit CLI operations until an authenticated process owner exists.

Owning pre-release migrations 027/028 changed. A clean migrated database is
required for this release; existing databases and recordings were not reset.

The private working repository contains historical agent/project context.
The source distribution uses an explicit backend allowlist and excludes that
history, recordings, credentials, caches, the frontend, and archived tests.
Making the existing private repository public requires a separate history and
publication-content decision; publishing the backend archive does not publish
the private repository history.

The publication scan reviewed 80 reachable commits and 916 unique historical
blobs, plus working-tree content. Across 1,204 unique UTF-8 text contents,
27 detect-secrets detectors produced no confirmed live credential findings after
context review. Fifteen binary/oversized contents were not scanned. This covers
reachable refs and selected working-tree source, not ignored local credentials,
unreachable objects or external/LFS payloads. The redacted local report is
`.pytest_tmp/release-audit/secret-history-report.json`.

The backend archive is built from an explicit file allowlist. Its contents were
checked for private context, caches, actual environment files and recordings.
Final archives and SHA-256 checksums are in `dist/backend-release`.

## Format reference

XDF encoding follows the [official XDF specification](https://github.com/sccn/xdf/wiki/Specifications).
The independent reader check is essential because matching custom writer and
reader implementations had concealed the original incompatibility.
