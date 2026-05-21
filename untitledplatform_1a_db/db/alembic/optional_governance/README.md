# Optional Governance Migrations

These migrations are reference material for deployments that need regulated-study
governance tables such as consent logs, electronic signatures, investigational
product accountability, and formal adverse-event designations.

They are intentionally outside the default Alembic `versions/` chain. The open-source
1a core focuses on local capture, replayability, ECHO/APEX/ARC data integrity, and
computational provenance. A deployment that needs these tables should copy or adapt
them into its own migration chain and add the matching application workflows.
