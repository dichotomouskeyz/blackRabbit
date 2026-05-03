"""025 declarative partitioning on audit_events

Revision ID: 025_audit_partitioning
Revises: 024_encryption_columns
Create Date: 2026-05-03

WHY PARTITIONING:
  audit_events is deceptively high-volume. The lightweight trigger fires
  on every biosignal sample insert. A 4-hour EEG session at 256 Hz
  across 16 channels produces ~14.7 million audit rows from EEG alone.
  Add HRV, EDA, and respiration and a single session approaches 20M rows.

  Without partitioning, even indexed queries do a full index scan across
  the entire table lifetime. With monthly RANGE partitions, Postgres
  prunes irrelevant partitions before touching any index — a query for
  session X in May only scans the May partition. This is called
  "partition pruning" and it is automatic; no query changes are needed.

WHY PARTITION BY db_insert_time AND NOT event_timestamp:
  db_insert_time is always set to NOW() at write time (trigger-controlled,
  no application override). It is monotonically increasing and guaranteed
  non-null. event_timestamp can be backdated (e.g., reconstructed from an
  LSL clock) and is nullable on some rows. Partitioning on a column that
  can be null or out-of-order defeats partition pruning.

WHY THE PRIMARY KEY CHANGES:
  Postgres declarative partitioning requires that the partition key column
  (db_insert_time) appear in every UNIQUE constraint and PRIMARY KEY on
  the parent table. The original single-column PK (id) is replaced with
  a composite PK (id, db_insert_time). Since id is GENERATED ALWAYS AS
  IDENTITY (a monotone sequence), (id, db_insert_time) is still globally
  unique. Nothing in the schema references audit_events.id as a foreign
  key, so no other tables are affected.

WHY GENERATED ALWAYS AS IDENTITY INSTEAD OF BIGSERIAL:
  BIGSERIAL is syntactic sugar for a sequence + DEFAULT. With declarative
  partitioning, GENERATED ALWAYS AS IDENTITY is the cleaner and more
  explicit equivalent. Both produce the same sequence behavior, but
  IDENTITY columns make the auto-generation intent explicit and are the
  SQL standard approach. The sequence is owned by the parent table and
  shared across all partitions.

PARTITION LAYOUT:
  Monthly partitions: 2026-01 through 2027-12 (24 partitions).
  A DEFAULT partition (audit_events_overflow) catches any row outside
  this range. Without a DEFAULT partition, an INSERT with a db_insert_time
  beyond the defined ranges would raise a constraint violation error.

  In 1b, audit_events is replaced entirely by AWS QLDB. This partition
  strategy is 1a-only and does not need to extend beyond 2027.

APPEND-ONLY ENFORCEMENT:
  REVOKE UPDATE, DELETE is applied to the parent table and to each
  partition individually. Partition tables in Postgres do not inherit
  privileges from the parent — each partition is its own object with
  its own ACL. Revoking only on the parent leaves direct partition
  access unprotected.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "025_audit_partitioning"
down_revision: Union[str, None] = "024_encryption_columns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Monthly partitions to pre-create. 1a sessions will not extend past 2027.
PARTITION_YEARS = [2026, 2027]


def _partition_bounds(year: int, month: int) -> tuple[str, str]:
    """Return (start, end) date strings for a monthly partition."""
    if month < 12:
        return f"{year:04d}-{month:02d}-01", f"{year:04d}-{month + 1:02d}-01"
    return f"{year:04d}-12-01", f"{year + 1:04d}-01-01"


def upgrade() -> None:
    # Drop the original unpartitioned table. Must be empty at this point —
    # this migration must run before any real session data is written.
    op.execute("DROP TABLE IF EXISTS audit_events CASCADE;")

    # Parent partitioned table.
    # PRIMARY KEY must include db_insert_time (the partition key).
    op.execute("""
        CREATE TABLE audit_events (
            id              BIGINT      GENERATED ALWAYS AS IDENTITY,
            session_id      TEXT,
            event_type      TEXT        NOT NULL,
            table_name      TEXT,
            record_id       TEXT,
            actor_id        TEXT,
            payload         JSONB       NOT NULL DEFAULT '{}'::jsonb,
            event_timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            db_insert_time  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (id, db_insert_time)
        ) PARTITION BY RANGE (db_insert_time);
    """)

    # Append-only: revoke on the parent (covers access through the parent table).
    op.execute("REVOKE UPDATE, DELETE ON audit_events FROM PUBLIC;")

    # Recreate the session-time index dropped with the old table.
    # Creating on the parent propagates to all existing and future partitions.
    op.execute("""
        CREATE INDEX idx_audit_events_session_time
        ON audit_events (session_id, event_timestamp DESC);
    """)

    # Monthly partitions for the 1a operating window.
    for year in PARTITION_YEARS:
        for month in range(1, 13):
            start, end = _partition_bounds(year, month)
            name = f"audit_events_{year:04d}_{month:02d}"
            op.execute(f"""
                CREATE TABLE {name}
                PARTITION OF audit_events
                FOR VALUES FROM ('{start}') TO ('{end}');
            """)
            op.execute(f"REVOKE UPDATE, DELETE ON {name} FROM PUBLIC;")

    # Default partition: catches any row outside the pre-created monthly range.
    op.execute("""
        CREATE TABLE audit_events_overflow
        PARTITION OF audit_events DEFAULT;
    """)
    op.execute("REVOKE UPDATE, DELETE ON audit_events_overflow FROM PUBLIC;")


def downgrade() -> None:
    # DROP CASCADE removes the parent, all 24 monthly partitions, the
    # overflow partition, and the identity sequence in one statement.
    op.execute("DROP TABLE IF EXISTS audit_events CASCADE;")

    # Restore original unpartitioned table with single-column BIGSERIAL PK.
    op.execute("""
        CREATE TABLE audit_events (
            id              BIGSERIAL   PRIMARY KEY,
            session_id      TEXT,
            event_type      TEXT        NOT NULL,
            table_name      TEXT,
            record_id       TEXT,
            actor_id        TEXT,
            payload         JSONB       NOT NULL DEFAULT '{}'::jsonb,
            event_timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            db_insert_time  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)
    op.execute("REVOKE UPDATE, DELETE ON audit_events FROM PUBLIC;")
    op.execute("""
        CREATE INDEX idx_audit_events_session_time
        ON audit_events (session_id, event_timestamp DESC);
    """)
