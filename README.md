<h1 align="center">blackRabbit</h1>

<p align="center">
  <img src="docs/assets/blackrabbit-overview.gif" width="840"
       alt="blackRabbit records EEG, interbeat intervals, EDA and respiration over LSL with ECHO markers, writes XDF before TimescaleDB, reconciles the two, and runs ARC response-window analysis.">
</p>

<p align="center">
  <a href="LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-ece8e1?style=flat-square&labelColor=0e0f11"></a>
  <img alt="Python 3.12+" src="https://img.shields.io/badge/python-3.12%2B-ece8e1?style=flat-square&labelColor=0e0f11">
  <img alt="Lab Streaming Layer" src="https://img.shields.io/badge/LSL-XDF%201.0-ff5a1f?style=flat-square&labelColor=0e0f11">
  <img alt="TimescaleDB" src="https://img.shields.io/badge/TimescaleDB-Postgres-ece8e1?style=flat-square&labelColor=0e0f11">
  <img alt="Next.js 15" src="https://img.shields.io/badge/operator%20UI-Next.js%2015-ece8e1?style=flat-square&labelColor=0e0f11">
</p>

<p align="center">
  Local research infrastructure for synchronized physiological recording and
  reproducible post-session analysis.
</p>

blackRabbit records EEG, interbeat intervals, electrodermal activity, respiration,
and manual contextual markers through Lab Streaming Layer (LSL). It writes
standard XDF recordings before database rows, verifies capture completeness,
and computes exploratory responses around recorded events.

## Backend workflows

- **APEX capture:** four physiological streams with canonical pseudonymous
  session identity, per-worker failure propagation, and durable XDF backups.
- **ECHO markers:** manual contextual events recorded on the same LSL clock.
- **Recovery and closeout:** tenant-scoped XDF validation, missing-sample replay,
  complete EEG channel checks, and database watermarks.
- **ARC analysis:** shared feature extraction, versioned baselines, successive
  response windows, seeded circular-shift null tests, Benjamini-Hochberg FDR,
  metric-cited summaries, and reproducible JSON artifacts.
- **Operator API:** local session creation, tenant-scoped reads, capability
  discovery, and completed analysis retrieval. Capture/analysis execution uses
  the CLI while API process ownership and authentication remain deferred.
- **Recording investigator:** optional PydanticAI backend with six typed,
  read-only tools, cited findings, quality limitations, and signal-window data.
  A headless synthetic demonstration runs without model credentials.
- **Operator console (`web/`):** an agent-first Next.js app. A local
  OpenAI-compatible model (LiteLLM, Ollama) lists, inspects, and creates sessions
  through the API; capability-gated actions return the server's reason instead
  of running. Live signal and ARC review screens are not built yet.

This is an exploratory research tool; it does not
perform clinical safety assessment or establish causation from marker responses.
Quality exclusions and data excursions are included in analysis artifacts.

## Quickstart

Requires Python 3.12+, [uv](https://docs.astral.sh/uv/), and PostgreSQL 16 with
TimescaleDB and pgvector. The supplied Docker Compose database image includes
both extensions. Docker Desktop or a working Linux Docker engine is sufficient;
WSL is an optional Windows route.

```sh
uv sync --frozen
cp .env.example .env
```

On PowerShell, use `Copy-Item .env.example .env` instead of `cp`. Set `DB_PASSWORD`
in the new file; `DATABASE_URL` interpolates the database fields. Use a
URL-compatible password or set an explicitly URL-encoded connection string.
Then start only the database and apply migrations:

```sh
docker compose up -d timescaledb
uv run python -m alembic upgrade head
uv run python -m alembic current
```

This release updates pre-release owning migrations. Use a fresh database for
this schema. Existing recordings and databases are not automatically rebuilt.

### Reproducible backend demonstration

Create and migrate a dedicated database whose name contains `test` or `audit`.
Set both `DATABASE_URL` and `TEST_DATABASE_URL` to its connection string in the
shell before running this command. The script intentionally refuses other
database names and retains its fictional sessions for inspection:

```sh
uv run python -m scripts.backend_smoke --output data/backend_smoke/demo
```

The script generates fictional signals and exercises the real capture writers,
XDF recovery, closeout, analysis CLI, and deterministic replay. It intentionally
omits a database chunk, proves recovery from XDF, rejects analysis before the
watermark, and checks foreign-tenant rejection. It writes a JSON receipt and
analysis artifacts without requiring sensors or a model service.

For an actual short LSL/process smoke test, see:

```sh
uv run python -m scripts.lsl_smoke --help
```

### Headless investigation demo

After the backend demonstration, configure `API_READONLY_DATABASE_URL` with a
SELECT-only role on the same test database, then run:

```sh
uv sync --frozen --extra agent
uv run --frozen --extra agent python -m scripts.investigation_smoke --receipt data/backend_smoke/demo/receipt.json --output data/investigation_demo
```

This scripted SDK tool loop produces a cited report, tool trace, and downsampled
signal windows. It verifies stored evidence and unchanged analysis hashes without
a live model request. See [Recording investigation](docs/recording-investigation.md)
for outputs, optional hosted providers, and the future streaming API connection.

### Recording and analysis

Use `--help` on each command for required identity and configuration arguments:

```sh
uv run python -m capture.session_init --help
uv run python -m capture.synthetic_board
uv run python -m capture.marker_simulator
uv run python -m capture.watchdog --help
uv run python -m capture.session_close --help
uv run python -m batch.arc --help
```

Start capture with the initialized session's exact participant, site, and sponsor
identifiers. Stop the forwarder before closeout. Closeout accepts the XDF file
and sponsor ID; it does not start analysis. Run `batch.arc` explicitly with the
session, sponsor, and site IDs and `--output` for a reproducible JSON export.

The default analysis config is `config/arc_watchdog_config.toml`. Its baseline
and response windows require a sufficiently long recording. Short or missing
windows are excluded explicitly. Failed capture is not automatically resumed;
a new recording needs a new session so sample indices cannot be silently reused.
Older blackRabbit custom-format recordings require explicit `--legacy-xdf`
recovery; new files are standard XDF 1.0.

### Operator console

Requires Node.js 20+ and the operator API running locally. Set `AGENT_BASE_URL`
and `AGENT_MODEL` in `.env.local` to a loopback or private OpenAI-compatible
endpoint with tool calling, such as `http://localhost:11434/v1` for Ollama.

```sh
cd web
corepack pnpm@9.15.9 install --frozen-lockfile
cp .env.example .env.local
corepack pnpm@9.15.9 dev
```

Without a model, the console still lists and creates sessions; the chat shows
why it is unavailable.

## Verification

```sh
uv run python -m ruff check .
uv run python -m pyright capture batch api
uv run python -m pytest -m "not integration"
corepack pnpm@9.15.9 -C web test
```

The complete suite requires an isolated migrated database. Set `DATABASE_URL`
and `TEST_DATABASE_URL` to that same database, `API_READONLY_DATABASE_URL` to a
SELECT-only role on it, and `PYTHON_DOTENV_DISABLED=1` to prevent local settings
from leaking into the test run. Do not point integration tests at real recordings.
Then run `uv run python -m pytest`. The backend CI workflow provisions these roles.

Tests include independent `pyxdf` parsing, numerical feature fixtures, an
independent SciPy FDR comparison, missing-data gates, tenant isolation, failure
propagation, persisted analysis replay, and actual database permissions.

## Integration and scope

See [backend handoff](docs/backend-handoff.md),
[release audit](docs/release-audit-2026-10-13.md), and the active contracts in
[.correctless/specs](.correctless/specs). Historical `docs/2R` audits describe the
previous implementation, not the current release state.

The API must remain bound to localhost until authenticated tenant authorization
and capture-process ownership are implemented. Live clinical monitoring,
intervention, cloud deployment, and hardware-specific validation remain outside
this backend release. Legacy Python package/database identifiers are retained
for compatibility; the product name is blackRabbit.

## Data handling and compliance

blackRabbit stores pseudonymous UUIDs, never names or other direct identifiers,
but it is research software provided as is under the MIT license. It is not
certified or validated for HIPAA, GDPR, 21 CFR Part 11 or any other regulatory
regime. The lab or institution that deploys it decides which rules apply and is
responsible for meeting them: access control, encryption, retention, consent,
IRB or ethics approval, and agreements with any model provider it enables.
[Data handling](docs/data-handling.md) lists what the software stores, where
identifying information can still appear, and what a deploying team must cover.

## License

[MIT](LICENSE), copyright 2026 Jahlon Burruss. Third-party dependencies retain
their own licenses. Do not commit `.env`, real participant data, logs, or recordings.
