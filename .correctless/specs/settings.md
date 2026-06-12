# Spec: Settings

## Metadata
- **Task**: settings
- **Intensity**: standard
- **Recommended-intensity**: standard
- **Intensity reason**: no security keywords, no TB-xxx overlap, no antipattern history
- **Override**: none

## What

`config/settings.py` loads all runtime configuration from environment variables (`.env` at repo root). Module-level assignments load values immediately on import; defaults are provided for all optional values. `PAYLOAD_SCHEMA_VERSION` identifies the forwarder payload/log schema and defaults to `"1.0"`. `validate()` performs a single-pass check of all required and range-bound settings, collects every failure, and raises one `RuntimeError` containing all messages — never one error at a time. No setting is ever hardcoded elsewhere in the codebase.

## Rules

### `_require` — unit tests

- **R-001** [unit]: `_require(key)` raises `RuntimeError` when the environment variable is not set.

- **R-002** [unit]: `_require(key)` raises `RuntimeError` when the environment variable is set to an empty string.

- **R-003** [unit]: `_require(key)` returns the string value when the environment variable is set to a non-empty string.

### `_get_optional` and `_get_optional_csv` — unit tests

- **R-004** [unit]: `_get_optional(key)` returns `None` when the environment variable is not set.

- **R-005** [unit]: `_get_optional(key)` returns `None` when the environment variable is set to an empty string.

- **R-006** [unit]: `_get_optional_csv(key)` returns `None` when the environment variable is not set or is an empty string.

- **R-007** [unit]: `_get_optional_csv(key)` returns `None` when the value contains only whitespace or whitespace-only comma-separated fields.

- **R-008** [unit]: `_get_optional_csv(key)` returns a tuple of stripped, non-empty strings when the value is a valid comma-separated list.

### `validate()` — unit tests

- **R-009** [unit]: `validate()` raises `RuntimeError` when `DATABASE_URL` is empty or not set.

- **R-010** [unit]: `validate()` raises `RuntimeError` when any numeric setting is outside its valid range (e.g. `SAMPLE_RATE_EEG < 1` or `SAMPLE_RATE_EEG > 10000`).

- **R-011** [unit]: `validate()` raises `RuntimeError` when `DEVICE_ID` is not a valid UUID string.

- **R-012** [unit]: `validate()` raises `RuntimeError` for invalid `HRV_SIGNAL_SOURCE` (not in `("ecg", "pcg", "ppg")`).

- **R-013** [unit]: `validate()` raises `RuntimeError` for invalid `EDA_SIGNAL_SOURCE` (not in `("combined", "scl", "scr")`).

- **R-014** [unit]: `validate()` raises `RuntimeError` for invalid `RESPIRATION_SOURCE` (not in `("belt_direct", "rsa_derived")`).

- **R-015** [unit]: `validate()` raises `RuntimeError` for invalid `CAPTURE_SOURCE` (not in `("simulated", "hardware")`).

- **R-016** [unit]: `validate()` raises `RuntimeError` when `EEG_CHANNEL_NAMES` is set and its length does not match `EEG_CHANNEL_COUNT`.

- **R-017** [unit]: When multiple settings fail, `validate()` raises a single `RuntimeError` containing ALL failure messages — not just the first.

- **R-018** [unit]: `validate()` does not raise when all settings are valid.

### Derived values — unit tests

- **R-019** [unit]: `SIMULATION_MODE` is `True` when `CAPTURE_SOURCE == "simulated"` and `False` when `CAPTURE_SOURCE == "hardware"`.

- **R-020** [unit]: When neither `CAPTURE_SOURCE` nor `SIMULATION_MODE` is set in the environment, `CAPTURE_SOURCE` defaults to `"simulated"`.

- **R-021** [unit]: When `SIMULATION_MODE=false` is set and `CAPTURE_SOURCE` is unset, `CAPTURE_SOURCE` defaults to `"hardware"`.

- **R-022** [unit]: `PAYLOAD_SCHEMA_VERSION` defaults to `"1.0"` when the environment variable is unset.

## Won't Do

- Test that `.env` file loading works end-to-end — that is `python-dotenv` behavior.
- Test all 30+ individual setting defaults — only test the ones that interact with validation logic.
- Test that settings are imported once at startup — module import caching is a Python runtime guarantee.

## Risks

- **Settings are module-level globals** — tests that manipulate environment variables must patch `config.settings` attributes directly (or use `importlib.reload`) rather than setting `os.environ`, since `os.environ` changes after import do not update the module-level values. Mitigation: tests use `monkeypatch.setattr(settings, "DATABASE_URL", ...)` or reload the module within the test.
- **`DATABASE_URL` defaults to `""` instead of raising on import** — this allows the module to be imported without a database connection (useful in tests and CLI --help invocations). The `validate()` call at each script's `main()` entry point is the enforcement point.

## Open Questions

- _(none)_
