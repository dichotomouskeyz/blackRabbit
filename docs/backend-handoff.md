# blackRabbit backend handoff

The backend is a local research tool. Frontend implementation remains separate.
The optional headless recording investigator is documented in
`docs/recording-investigation.md`; its scripted synthetic demo requires no model credentials.
Read `docs/release-audit-2026-10-13.md` for verification evidence and remaining
release gates.

## Data flow

`session_init` creates canonical pseudonymous identity and recording metadata.
The forwarder acquires a per-session database advisory lock, verifies identity,
and captures EEG, HRV, EDA, respiration, and optional ECHO markers. Every accepted
chunk is written and flushed to a standard XDF file before database insertion.
Capture failure is visible; the MVP does not restart a failed recording with
reset sample indices.

After capture stops, `session_close` validates complete XDF structure and
identity, repairs recoverable database gaps, writes a reconciliation report,
and transitions the session to `closed` or `failed`. Only verified closed
sessions can enter ARC. Raw capture validity is independent of analysis outcome.

`batch.arc` computes shared feature epochs, persisted baselines, successive
response windows, a seeded null model and false-discovery correction. Exported
JSON records source/configuration/algorithm provenance, missing data, excluded
windows, and metric-linked descriptions. These are exploratory associations
with recorded markers, not causal or clinical conclusions.

## Commands

Run from the repository root after installing with `uv sync --frozen`:

```text
uv run python -m capture.session_init --help
uv run python -m capture.forwarder --help
uv run python -m capture.watchdog --help
uv run python -m capture.session_close --help
uv run python -m batch.reconcile --help
uv run python -m batch.arc --help
```

Closeout requires `--session-id`, `--sponsor-id`, and `--xdf-path`. ARC requires
`--session-id`, `--sponsor-id`, and `--site-id`; `--config` selects a TOML analysis
configuration, and `--output` writes the reproducible JSON artifact. Recordings
from the former custom XDF dialect require explicit `--legacy-xdf` recovery.

## HTTP contract

Start locally with:

```text
uv run python -m uvicorn api.app:app --host 127.0.0.1 --port 8000
```

Use `/openapi.json` for request/response schemas and `/capabilities` for current
availability. The frontend must use the returned capability state; it must not
infer readiness from the presence of a route.

| Route | Current behavior |
| --- | --- |
| `GET /health` | Service and contract version |
| `GET /capabilities` | Full capability matrix including blocked reasons |
| `GET /vocab` | Supported compounds and dose units |
| `GET /sessions` | Tenant-scoped session list |
| `GET /sessions/{session_id}/status` | Tenant-scoped capture status and watermark |
| `POST /sessions` | Validated creation through the capture backend |
| `GET /sessions/{session_id}/arc` | Latest completed persisted analysis for a verified, closed session |
| `POST /agent/chat` | Optional Python investigation agent, SDK 7 streaming, server-owned conversations |
| Capture start/stop, marker publish, close, ARC run, live WebSocket | Blocked pending process ownership and authenticated authorization |

Session creation uses `compound_dose` and `compound_dose_unit`, not `dose` or
`dose_unit`. Capture execution paths use `capture:start`, `capture:stop`, and
`arc:run` with colons. Tenant identifiers are server-injected with
`API_SPONSOR_ID`/`API_SITE_ID`; callers cannot override them. Direct reads require
`API_READONLY_DATABASE_URL`; missing configuration returns a structured 503.

Analysis reads return `session_id`, `analysis_id`, `created_at`, `provenance`
(algorithm version plus configuration, input and artifact SHA-256 hashes), and
the stored `artifact`. Foreign sponsor/site sessions return 404; sessions without
verified capture return 409; a verified session without analysis returns 404.

The current HTTP surface has no user authentication and must stay bound to
localhost. Developing the frontend in a cloud workspace does not make this a
public backend. External access needs an authenticated tenant-authorized gateway
and a defined capture-process owner before execution routes can be enabled.

## Schema and records

Alembic is the schema authority. This pre-release work updates the owning
migrations for baseline/analysis provenance, consistent with `AGENTS.md`.
Use a fresh development/test database when validating this schema. Do not run
an automatic destructive reset against existing recordings.

The old `docs/2R` documents retain historical audits. Legacy Python package and
database names are intentional; the product name is blackRabbit.
