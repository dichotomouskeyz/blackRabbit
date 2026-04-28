"""013 create indexes across all tables

Revision ID: 013_indexes
Revises: 012_audit_triggers
Create Date: 2026-04-26

WHY INDEXES MATTER:
  Without indexes, every query does a "sequential scan" — Postgres
  reads every single row in the table to find matches. For a
  biosignal table with 29 million rows (4-hour EEG session), that
  means scanning 29M rows to answer "show me channel Fz for the
  last 5 minutes."

  An index is like a book's index: instead of reading every page
  to find "photosynthesis," you look it up in the index and go
  directly to page 342. Postgres B-tree indexes work the same way.

WHY THESE SPECIFIC INDEXES:
  Three query patterns drive the index choices:

  1. DATA TENANCY (every query): WHERE site_id = ? AND sponsor_id = ?
     Every API query filters by site and sponsor. Without an index,
     this filter scans the entire table.

  2. SESSION LOOKUP (most queries): WHERE session_id = ?
     Almost every query is scoped to a single session. This is the
     most selective filter after time range.

  3. TIME-ORDERED RETRIEVAL: ORDER BY lsl_timestamp DESC
     "Show me the last 5 minutes of data" needs lsl_timestamp indexed.
     For EEG, the composite (session_id, channel_name, lsl_timestamp)
     index serves the most common query in a single index lookup.

WHY COMPOSITE INDEXES:
  A composite index on (session_id, lsl_timestamp DESC) is NOT the
  same as two separate indexes on session_id and lsl_timestamp.
  The composite index can answer "rows for session X ordered by time"
  in a single lookup. Two separate indexes would need Postgres to
  merge results from both — slower and more memory-intensive.

  Column order in composite indexes matters: put the equality filter
  first (session_id = ?), then the range/sort column (lsl_timestamp).
"""

from typing import Sequence, Union

from alembic import op

revision: str = "013_indexes"
down_revision: Union[str, None] = "012_audit_triggers"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Biosignal hypertables — high-volume, time-series queries
BIOSIGNAL_TABLES = [
    "eeg_samples",
    "hrv_samples",
    "eda_samples",
    "respiration_samples",
]

# Event/metadata tables — lower-volume, relational queries
EVENT_TABLES = [
    "alert_events",
    "humen_events",
    "voice_segments",
    "session_feature_vectors",
    "session_notes",
]


def upgrade() -> None:
    # --- Biosignal tables ---
    for table in BIOSIGNAL_TABLES:
        # Primary query pattern: "data for this session, ordered by time"
        op.execute(f"""
            CREATE INDEX idx_{table}_session_time
            ON {table} (session_id, lsl_timestamp DESC);
        """)

        # Data tenancy: "all data for this site/sponsor"
        op.execute(f"""
            CREATE INDEX idx_{table}_tenancy
            ON {table} (site_id, sponsor_id);
        """)

    # EEG-specific: per-channel queries are the most common
    # "Show me channel Fz for session X in the last 5 minutes"
    op.execute("""
        CREATE INDEX idx_eeg_session_channel_time
        ON eeg_samples (session_id, channel_name, lsl_timestamp DESC);
    """)

    # --- Sessions table ---
    op.execute("""
        CREATE INDEX idx_sessions_tenancy
        ON sessions (site_id, sponsor_id);
    """)
    op.execute("""
        CREATE INDEX idx_sessions_status
        ON sessions (status);
    """)
    op.execute("""
        CREATE INDEX idx_sessions_compound
        ON sessions (compound);
    """)

    # --- Event tables ---
    for table in EVENT_TABLES:
        op.execute(f"""
            CREATE INDEX idx_{table}_session
            ON {table} (session_id);
        """)
        op.execute(f"""
            CREATE INDEX idx_{table}_tenancy
            ON {table} (site_id, sponsor_id);
        """)

    # Alert-specific: query by severity and type
    op.execute("""
        CREATE INDEX idx_alert_events_severity
        ON alert_events (session_id, severity);
    """)
    op.execute("""
        CREATE INDEX idx_alert_events_unacknowledged
        ON alert_events (session_id)
        WHERE acknowledged_at IS NULL;
    """)

    # Audit events: query by session and event type
    op.execute("""
        CREATE INDEX idx_audit_events_session
        ON audit_events (session_id, db_insert_time DESC);
    """)
    op.execute("""
        CREATE INDEX idx_audit_events_table
        ON audit_events (table_name, db_insert_time DESC);
    """)

    # HUMeN: time-ordered events per session for timeline reconstruction
    op.execute("""
        CREATE INDEX idx_humen_events_session_time
        ON humen_events (session_id, lsl_timestamp);
    """)


def downgrade() -> None:
    # Drop all indexes created above
    # (Tables themselves are not affected — just the indexes)

    for table in BIOSIGNAL_TABLES:
        op.execute(f"DROP INDEX IF EXISTS idx_{table}_session_time;")
        op.execute(f"DROP INDEX IF EXISTS idx_{table}_tenancy;")

    op.execute("DROP INDEX IF EXISTS idx_eeg_session_channel_time;")

    op.execute("DROP INDEX IF EXISTS idx_sessions_tenancy;")
    op.execute("DROP INDEX IF EXISTS idx_sessions_status;")
    op.execute("DROP INDEX IF EXISTS idx_sessions_compound;")

    for table in EVENT_TABLES:
        op.execute(f"DROP INDEX IF EXISTS idx_{table}_session;")
        op.execute(f"DROP INDEX IF EXISTS idx_{table}_tenancy;")

    op.execute("DROP INDEX IF EXISTS idx_alert_events_severity;")
    op.execute("DROP INDEX IF EXISTS idx_alert_events_unacknowledged;")
    op.execute("DROP INDEX IF EXISTS idx_audit_events_session;")
    op.execute("DROP INDEX IF EXISTS idx_audit_events_table;")
    op.execute("DROP INDEX IF EXISTS idx_humen_events_session_time;")
