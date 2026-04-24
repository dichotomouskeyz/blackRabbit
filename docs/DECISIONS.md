# Consensai 1a — Decisions Log

Decisions made during Phase 0. Not to be relitigated without good reason.

## Dependency Management
- **Decision:** Poetry (pyproject.toml + poetry.lock)
- **Rationale:** Clean separation of production vs dev dependencies, automatic virtual environment management, deterministic installs via lockfile. requirements.txt was too flat and error-prone.
- **Date:** April 2026

## Version Control
- **Decision:** main is always clean and working. All development on feature branches. Merge only when task is complete and tested.
- **Branch naming:** feature/[task-name] (e.g. feature/lsl-forwarder)
- **Date:** April 2026
