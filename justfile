set dotenv-load := true

# ── Dev defaults — override with SESSION_ID=xxx just <recipe> ─────────────────
session_id     := env_var_or_default("SESSION_ID",     "11111111-1111-1111-1111-111111111111")
participant_id := env_var_or_default("PARTICIPANT_ID", "22222222-2222-2222-2222-222222222222")
site_id        := env_var_or_default("SITE_ID",        "33333333-3333-3333-3333-333333333333")
sponsor_id     := env_var_or_default("SPONSOR_ID",     "44444444-4444-4444-4444-444444444444")
xdf_path       := env_var_or_default("XDF_PATH", "data/xdf_backups/session_" + session_id + ".xdf")

# ── Full simulation: APEX + ECHO + ARC/monitors + supervised Timescale forwarder
sim:
    #!/usr/bin/env bash
    set -euo pipefail

    SESSION_ID="${SESSION_ID:-}"
    if [[ -z "$SESSION_ID" ]]; then
        SESSION_ID="$(SIMULATION_MODE=true uv run python -m capture.session_init \
            --compound psilocybin \
            --site-id "{{site_id}}" \
            --sponsor-id "{{sponsor_id}}" \
            --participant-id "{{participant_id}}")"
    fi
    export SESSION_ID
    echo "simulation session: $SESSION_ID"

    PIDS=()

    terminate_tree() {
        local pid="$1"
        local child

        for child in $(pgrep -P "$pid" 2>/dev/null || true); do
            terminate_tree "$child"
        done

        kill -TERM "$pid" 2>/dev/null || true
    }

    kill_tree() {
        local pid="$1"
        local child

        for child in $(pgrep -P "$pid" 2>/dev/null || true); do
            kill_tree "$child"
        done

        kill -KILL "$pid" 2>/dev/null || true
    }

    terminate_harness_modules() {
        local pattern

        for pattern in \
            "python -m capture.synthetic_board" \
            "python -m capture.marker_simulator" \
            "python -m capture.lsl_forwarder" \
            "python -m capture.watchdog" \
            "python -m ingestion.safety" \
            "python -m ingestion.sqi"; do
            pkill -TERM -f "$pattern" 2>/dev/null || true
        done
    }

    kill_harness_modules() {
        local pattern

        for pattern in \
            "python -m capture.synthetic_board" \
            "python -m capture.marker_simulator" \
            "python -m capture.lsl_forwarder" \
            "python -m capture.watchdog" \
            "python -m ingestion.safety" \
            "python -m ingestion.sqi"; do
            pkill -KILL -f "$pattern" 2>/dev/null || true
        done
    }

    cleanup() {
        trap - EXIT INT TERM
        for pid in "${PIDS[@]:-}"; do
            terminate_tree "$pid"
        done
        terminate_harness_modules
        sleep 2
        for pid in "${PIDS[@]:-}"; do
            kill_tree "$pid"
        done
        kill_harness_modules
        wait 2>/dev/null || true
    }
    trap cleanup EXIT INT TERM

    SIMULATION_MODE=true uv run python -m capture.synthetic_board &
    PIDS+=($!)

    sleep 2

    SIMULATION_MODE=true uv run python -m capture.marker_simulator \
        --min-interval "${MARKER_MIN_INTERVAL:-1}" \
        --max-interval "${MARKER_MAX_INTERVAL:-3}" &
    PIDS+=($!)

    SIMULATION_MODE=true uv run python -m capture.watchdog \
        --session-id     "$SESSION_ID" \
        --participant-id "{{participant_id}}" \
        --site-id        "{{site_id}}" \
        --sponsor-id     "{{sponsor_id}}" &
    PIDS+=($!)

    SIMULATION_MODE=true uv run python -m ingestion.safety &
    PIDS+=($!)
    SIMULATION_MODE=true uv run python -m ingestion.sqi &
    PIDS+=($!)

    if [[ -n "${SIM_DURATION:-}" ]]; then
        sleep "$SIM_DURATION"
        cleanup
    else
        wait
    fi

# ── Standalone ECHO marker stream ──────────────────────────────────────────────
markers:
    SIMULATION_MODE=true uv run python -m capture.marker_simulator

# ── LSL forwarder + process watchdog ──────────────────────────────────────────
capture:
    #!/usr/bin/env bash
    set -euo pipefail
    SIMULATION_MODE=true uv run python -m capture.lsl_forwarder \
        --session-id     {{session_id}} \
        --participant-id {{participant_id}} \
        --site-id        {{site_id}} \
        --sponsor-id     {{sponsor_id}} &
    FWD_PID=$!
    SIMULATION_MODE=true uv run python -m capture.watchdog \
        --session-id     {{session_id}} \
        --participant-id {{participant_id}} \
        --site-id        {{site_id}} \
        --sponsor-id     {{sponsor_id}} &
    WD_PID=$!
    wait $FWD_PID $WD_PID

# ── Safety monitor + SQI monitor ──────────────────────────────────────────────
monitor:
    #!/usr/bin/env bash
    set -euo pipefail
    uv run python -m ingestion.safety &
    uv run python -m ingestion.sqi &
    wait

# ── Docker compose stack ───────────────────────────────────────────────────────
stack:
    docker-compose up

# ── Alembic migrations (main + test DB) ───────────────────────────────────────
migrate:
    uv run python -m alembic upgrade head
    uv run python -m alembic -x db_url=${TEST_DATABASE_URL:-} upgrade head

# ── Test suite ─────────────────────────────────────────────────────────────────
test:
    uv run pytest tests/

# ── Test suite with coverage report ───────────────────────────────────────────
coverage:
    uv run pytest tests/ --cov --cov-report=term-missing

# ── Schema tests only ──────────────────────────────────────────────────────────
test-schema:
    uv run pytest tests/test_schema.py -v

# ── Lint: ruff check + format check + pyright ─────────────────────────────────
lint:
    uv run ruff check .
    uv run ruff format --check .
    uv run pyright

# ── Auto-fix: ruff fix + format ───────────────────────────────────────────────
fix:
    uv run ruff check --fix .
    uv run ruff format .

# ── Phase gate: ARC config validation → full test suite ───────────────────────
gate:
    uv run python -c "from config.arc_watchdog import load_arc_watchdog_config; c=load_arc_watchdog_config('config/arc_watchdog_config.toml'); print(f'ARC config OK  ({c.version_label}  sha256={c.content_sha256[:12]}…)')"
    just test

# ── Close session and gate post-session batch ─────────────────────────────────
close:
    uv run python -m capture.session_close \
        --session-id {{session_id}} \
        --xdf-path   {{xdf_path}}

# ── Tear down stack + wipe and remigrate test DB ──────────────────────────────
reset:
    #!/usr/bin/env bash
    set -euo pipefail
    docker-compose down
    if [[ -n "${TEST_DATABASE_URL:-}" ]]; then
        psql "$TEST_DATABASE_URL" \
            -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;" \
            && echo "test DB schema wiped"
        uv run python -m alembic -x "db_url=${TEST_DATABASE_URL}" upgrade head \
            && echo "test DB remigrated"
    fi

# ── Full simulated session: compatibility alias for `just sim` ────────────────
session:
    just sim
