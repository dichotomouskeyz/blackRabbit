# Testing Rules

- Run focused tests for the changed subsystem.
- Run `uv run pytest` before merging behavior changes.
- Mark DB-dependent tests with `@pytest.mark.integration`.
- Do not require local hardware for the default test suite.
- Keep test fixtures pseudonymous and synthetic.
