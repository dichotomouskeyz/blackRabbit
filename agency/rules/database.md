# Database Rules

- Alembic migrations are the schema source of truth.
- Do not hand-edit live schema outside migrations.
- Use parameterized SQL for values.
- Literal table names in dynamic SQL must come from closed internal mappings.
- Keep tenant fields present on session-scoped tables.
