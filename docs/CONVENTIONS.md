# Conventions

## Code

- Use Python 3.12+ and `uv`.
- Keep SQL parameterized.
- Keep runtime configuration in `config/settings.py`.
- Keep module changes scoped to the subsystem being changed.
- Prefer explicit dataclasses and small functions over broad service objects.

## Data

- Never write directly to `audit_events`; triggers own audit writes.
- Keep `lsl_timestamp` and `db_insert_time` separate.
- Keep EEG, HRV, EDA, and respiration tables separate.
- Use pseudonymous IDs only.
- Keep XDF write-before-DB-write behavior intact.

## Tests

- Unit tests should avoid a DB unless behavior requires one.
- DB-backed tests use `@pytest.mark.integration`.
- Use `TEST_DATABASE_URL` for integration tests.

## Git

- Do not commit `.env`, logs, data artifacts, caches, or XDF files.
- Prefer small logical commits with prefixes such as `docs:`, `fix:`,
  `refactor:`, `feat:`, and `test:`.
