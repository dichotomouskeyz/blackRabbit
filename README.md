# Untitled Biometric Platform 1a

Local research infrastructure for synchronized physiological capture and
post-session convergence analysis.

The MVP captures EEG, HRV, EDA, and respiration through Lab Streaming Layer
(LSL), records manual contextual ECHO markers, writes XDF before database rows,
and runs ARC batch analysis after session close. It is not a therapy app,
wellness product, clinical trial management system, or regulated medical device.

## Setup

Prerequisites:

- Docker Desktop
- Python 3.12+
- `uv`
- WSL2 on Windows

```bash
uv sync
cp .env.example .env
docker compose up -d
alembic upgrade head
```

## Running Capture

Real hardware and simulated streams use the same LSL stream names. Runtime
configuration belongs in `config/settings.py` and `.env`.

For real hardware:

```bash
python -m capture.forwarder
```

For simulated development sessions:

```bash
python -m capture.synthetic_board
python -m capture.forwarder
```

The simulator publishes:

| Stream | Channels | Rate | Signal |
| --- | ---: | ---: | --- |
| EEG | 8 | 250 Hz | BrainFlow synthetic EEG channels |
| HRV | 1 | ~1 Hz | ECG-derived RR intervals with fallback |
| EDA | 1 | 4 Hz | Board EDA channel or synthetic fallback |
| Respiration | 1 | 4 Hz | Accel proxy or synthetic fallback |

## Database And Tests

Alembic migrations are the schema source of truth. Do not change schema outside
a migration.

```bash
alembic upgrade head
alembic current
uv run pytest
```

Integration tests require `TEST_DATABASE_URL` in `.env` pointing at a database
with migrations applied.

## ARC

ARC means Agentic Response Convergence. It runs after capture over complete
APEX and ECHO records. ARC configuration lives in
`config/arc_watchdog_config.toml`; generated artifacts store config version and
SHA-256 provenance so results can be reproduced.

See `docs/arc.md` for the ARC event contract and window semantics.

## Operator API (M0)

A thin, capability-gated FastAPI surface (`api/`) for the staged operator UI.
Milestone 0 is read/create only: health, capability discovery, vocab, session
list/status, and session create (wrapping `capture.session_init`). Write/exec
capabilities (capture start/stop, markers, close, ARC run) are present but
**blocked** — they return a structured `409 Capability unavailable` before any
DB call, and the live-stream WebSocket refuses the upgrade. `GET /capabilities`
returns the full matrix.

```bash
uv run uvicorn api.app:app --host 127.0.0.1 --port 8000
uv run pytest tests/api_tests          # API test suite
```

The API's direct SQL runs on a `GRANT SELECT`-only role via
`API_READONLY_DATABASE_URL`; all UI env vars are optional and the capture/ARC
paths validate unchanged without them (see `.env.example`). M0 is
localhost-bound with no authentication — tenancy is server-injected
(`API_SPONSOR_ID`/`API_SITE_ID`), and localhost tenancy is not authentication.
Contract authority: `.correctless/specs/operator-ui.md`; integration notes:
`docs/ui-integration.md` §0. The Next.js chat shell is deferred
(`docs/2R/backlog.md`, "Operator UI — Deferred / Skipped Register").

## Local Model Experiments

Local coding-agent experiments are agent-neutral for now. The expected local
model shape is:

```text
LM Studio OpenAI-compatible API: http://localhost:1234/v1
```

Existing user-level configs may reference this endpoint, including:

- `C:\Users\jahlo\.continue\config.yaml`
- `C:\Users\jahlo\.claude\litellm\config.yaml`

Those files are outside this repo and are not required for the project to run.

## Logs

Processes write structured JSON logs to stdout and `logs/<process_name>.log`.
Logs, data artifacts, caches, `.env`, and XDF files should not be committed.
