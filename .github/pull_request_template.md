## What

<!-- One sentence: what does this PR change? -->

## Why

<!-- Why is this change needed? Link to spec or issue if applicable. -->

## How

<!-- Brief notes on approach. Skip if the diff is self-explanatory. -->

## Checklist

- [ ] Tests cover the new behavior (`uv run pytest -m "not integration"` passes)
- [ ] No direct writes to `audit_events`
- [ ] `lsl_timestamp` and `db_insert_time` kept separate
- [ ] Schema changes go through the repository's Alembic policy
- [ ] No PII in logs (pseudonymous `participant_id` only)
- [ ] `uv run ruff check .` passes
