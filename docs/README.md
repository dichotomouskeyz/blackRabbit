# untitledplatform_1a

Regulatory-grade neuro-behavioral data infrastructure for psychedelic clinical trials.

Captures EEG, HRV, EDA, and respiration via Lab Streaming Layer (LSL), writes to TimescaleDB with a tamper-evident audit trail, and produces a simultaneous XDF backup for reconciliation. Designed for 21 CFR Part 11 compliance.

---

## Prerequisites

- Docker Desktop (runs TimescaleDB + pgAdmin)
- Python 3.11+
- Poetry (dependency management)
- WSL2 (Windows only)

---

## Setup

```bash
# 1. Clone and install dependencies
git clone <repo>
cd untitledplatform_1a
uv sync

# 2. Copy env template and fill in your values
cp .env.example .env

# 3. Start the database
docker compose up -d

# 4. Run migrations
alembic upgrade head
```

---

## Running with real hardware

Start the forwarder. It resolves LSL streams by name — whatever is publishing
`EEG`, `HRV`, `EDA`, and `Respiration` streams on the network will be captured.

```bash
# In .env:  SIMULATION_MODE=false

python -m capture.lsl_forwarder
```

---

## Running with the simulator (development / testing)

The simulator publishes synthetic biosignal streams on the local network using
the same stream names as real hardware. The forwarder cannot tell the difference.

```bash
# In .env:  SIMULATION_MODE=true

# Terminal 1 — start streams (BrainFlow synthetic board by default)
python -m capture.synthetic_board
# or with real hardware:
python -m capture.synthetic_board --board ganglion --serial-port /dev/cu.usbserial-...

# Terminal 2 — start forwarder (same command as real hardware)
python -m capture.lsl_forwarder
```

The synthetic board outputs:

| Stream      | Channels | Rate    | Signal                                         |
|-------------|----------|---------|------------------------------------------------|
| EEG         | 8        | 250 Hz  | BrainFlow SYNTHETIC_BOARD EEG channels         |
| HRV         | 1        | ~1 Hz   | ECG-derived RR intervals; RSA+Mayer fallback   |
| EDA         | 1        | 4 Hz    | Board EDA channel if available; tonic/SCR fallback |
| Respiration | 1        | 4 Hz    | Accel Z-axis proxy; ~0.3 Hz sine fallback      |

`SIMULATION_MODE=true` is logged at forwarder startup so audit records clearly
distinguish simulated sessions from sessions with real devices.

---

## Verifying streams are visible

```bash
python - <<'EOF'
import pylsl
streams = pylsl.resolve_streams(wait_time=3.0)
for s in streams:
    print(s.name(), s.type(), s.channel_count(), int(s.nominal_srate()), 'Hz')
EOF
```

---

## Running tests

```bash
pytest tests/
```

Tests require `TEST_DATABASE_URL` in `.env` pointing at a running Postgres instance
with all migrations applied (`alembic upgrade head`).

---

## Database migrations

```bash
# Apply all migrations
alembic upgrade head

# Check current revision
alembic current

# Roll back one step
alembic downgrade -1
```

Migrations live in `db/alembic/versions/`. Never modify schema outside a migration file.

---

## ARC watchdog config

ARC demo parameters live in `config/arc_watchdog_config.toml`. The loader in
`config/arc_watchdog.py` validates the three ARC windows, FDR method, baseline
requirements, null model, and signal availability profile.

`arc_config_version` values should use the loader's `version_label`, for example
`arc_watchdog_config.toml@demo-001`, so every Event Composite Profile points back
to the exact config version that produced it.

---

## Logs

Each process writes structured JSON to `logs/<process_name>.log` and stdout.
Files rotate at 10 MB, keeping 5 backups.

```json
{"timestamp": "2026-05-05T14:32:01Z", "process_name": "lsl_forwarder", "level": "INFO", "session_id": "abc-123", "message": "EEG stream connected", "rate_hz": 256}
```
