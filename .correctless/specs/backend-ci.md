# Backend release CI contract

- CI-001: Backend CI uses Python3.12, uv's frozen lock, and pinned
  timescale/timescaledb:2.27.1-pg16 with a disposable blackrabbit_ci_test database.
  It applies Alembic, provisions a SELECT-only API role, runs Ruff/Pyright, the
  full Python suite with at least60% coverage, and offline capture/ARC replay.
  It has no frontend package install/build dependency.
- CI-005: Install the optional agent extra for agent tests, include investigation
  in type checking and coverage, and run the scripted headless investigation
  against the synthetic capture receipt. No provider credentials or live model
  calls are used. Verify cited evidence and unchanged saved analysis hashes.
- CI-002: Provisioning requires identical DATABASE_URL/TEST_DATABASE_URL, an
  underscore-delimited test/audit database name, and an API URL for the same
  host/port/database. It refuses invalid configuration before database access.
- CI-003: The API role must be a distinct blackrabbit_ identifier with a password.
  Existing elevated, inherited or write-enabled roles are rejected. Provisioning
  grants only CONNECT/USAGE/SELECT, never deletes data or resets existing passwords.
- CI-004: Provisioning checks the actual connected database and current migration
  head, then verifies the actual API credentials can read and cannot insert.
  CI service credentials are disposable local fixtures, not deployment secrets.

References: https://github.com/astral-sh/setup-uv and
https://docs.github.com/en/actions/tutorials/use-containerized-services/create-postgresql-service-containers
