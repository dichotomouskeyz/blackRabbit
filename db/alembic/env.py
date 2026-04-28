"""Alembic environment configuration for Consensai 1a.

This file runs every time you execute an Alembic command
(upgrade, downgrade, current, etc.). Its job:
  1. Load DATABASE_URL from .env (not hardcoded)
  2. Connect to the database
  3. Run whatever migration(s) Alembic needs to apply

You should rarely need to edit this file.
"""

import os
from logging.config import fileConfig

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import create_engine

# Load .env from project root (two levels up from db/alembic/)
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

# Alembic Config object — gives access to values in alembic.ini
config = context.config

# Override the placeholder URL in alembic.ini with the real one from .env
database_url = os.getenv("DATABASE_URL")
if not database_url:
    raise RuntimeError(
        "DATABASE_URL not set. Copy .env.example to .env and fill in your values."
    )
config.set_main_option("sqlalchemy.url", database_url)

# Set up Python logging from alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This generates SQL scripts without connecting to the database.
    Useful for reviewing what a migration WOULD do before running it.

    Usage: alembic upgrade head --sql
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=None,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    This connects to the database and applies migrations directly.
    This is the normal mode — what happens when you run:
        alembic upgrade head
    """
    connectable = create_engine(
        config.get_main_option("sqlalchemy.url"),
        # Pool pre-ping checks if the connection is alive before using it.
        # Prevents "connection closed" errors if the DB restarted.
        pool_pre_ping=True,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=None,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
