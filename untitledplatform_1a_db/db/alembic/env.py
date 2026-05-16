"""Alembic environment configuration for untitledplatform_1a.

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

# Load .env from project root (three levels up from untitledplatform_1a_db/db/alembic/)
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".env"))

# Alembic Config object — gives access to values in alembic.ini
config = context.config

# Allow -x db_url=... to override for test database
# Otherwise fall back to DATABASE_URL from .env
database_url = context.get_x_argument(as_dictionary=True).get("db_url")
if not database_url:
    database_url = os.getenv("DATABASE_URL")
if not database_url:
    raise RuntimeError("DATABASE_URL not set. Copy .env.example to .env and fill in your values.")
config.set_main_option("sqlalchemy.url", database_url)

# Set up Python logging from alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def run_migrations_offline() -> None:
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
    connectable = create_engine(
        config.get_main_option("sqlalchemy.url"),
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
