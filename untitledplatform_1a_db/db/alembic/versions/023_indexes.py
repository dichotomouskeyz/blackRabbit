"""023 create indexes across all tables

Revision ID: 023_indexes
Revises: 022_session_environment_log
Create Date: 2026-05-04

WHY INDEXES ARE THE LAST MIGRATION:
  Indexes must be created AFTER the tables they reference exist.
  Placing this migration last ensures every table in the 1a schema
  — including regulatory tables (014-019), correction and environment
  logs (021-022) — is present before any index is created. A single
  consolidated migration is also easier to audit: one file lists every
  index in the schema.

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

WHY idx_audit_events_session_time IS A STANDARD INDEX:
  In 1a, audit_events is a regular (non-partitioned) Postgres table.
  Declarative range partitioning of audit_events by db_insert_time is
  deferred to 1b when monthly data volumes justify the overhead.
  The index is created directly on the table here.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "023_indexes"
down_revision: Union[str, None] = "022_session_environment_log"
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
    "echo_events",
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
        ON eeg_samples (session_id, channel_id, lsl_timestamp DESC);
    """)

    # --- Sessions table ---
    op.execute("""
        CREATE INDEX idx_sessions_sponsor
        ON sessions (sponsor_id);
    """)
    op.execute("""
        CREATE INDEX idx_sessions_site
        ON sessions (site_id);
    """)
    op.execute("""
        CREATE INDEX idx_sessions_trial_arm
        ON sessions (protocol_arm);
    """)
    op.execute("""
        CREATE INDEX idx_sessions_sponsor_site
        ON sessions (sponsor_id, site_id);
    """)
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

    # ECHO: time-ordered events per session for timeline reconstruction
    op.execute("""
        CREATE INDEX idx_echo_events_session_time
        ON echo_events (session_id, lsl_timestamp);
    """)
    # ECHO: look up all events by a specific actor (therapist/coordinator)
    op.execute("""
        CREATE INDEX idx_echo_events_actor
        ON echo_events (actor_id);
    """)
    # ECHO: look up all events within a proximity zone
    op.execute("""
        CREATE INDEX idx_echo_events_zone_label
        ON echo_events (zone_label);
    """)

    # --- audit_events ---
    op.execute("""
        CREATE INDEX idx_audit_events_session_time
        ON audit_events (session_id, event_timestamp DESC);
    """)

    # --- schema_version_log ---
    op.execute("""
        CREATE INDEX idx_schema_version_session
        ON schema_version_log (session_id);
    """)
    op.execute("""
        CREATE INDEX idx_schema_version_alembic
        ON schema_version_log (alembic_version);
    """)
    op.execute("""
        CREATE INDEX idx_schema_version_recorded
        ON schema_version_log (recorded_at DESC);
    """)

    # --- electronic_signatures ---
    op.execute("""
        CREATE INDEX idx_esig_session
        ON electronic_signatures (session_id);
    """)
    op.execute("""
        CREATE INDEX idx_esig_record
        ON electronic_signatures (table_name, record_id);
    """)
    op.execute("""
        CREATE INDEX idx_esig_signer
        ON electronic_signatures (signer_id, signed_at DESC);
    """)
    op.execute("""
        CREATE INDEX idx_esig_tenancy
        ON electronic_signatures (site_id, sponsor_id);
    """)
    op.execute("""
        CREATE INDEX idx_esig_session_time
        ON electronic_signatures (session_id, signed_at DESC);
    """)

    # --- investigational_product_log ---
    op.execute("""
        CREATE INDEX idx_ip_log_session
        ON investigational_product_log (session_id);
    """)
    op.execute("""
        CREATE INDEX idx_ip_log_compound_lot
        ON investigational_product_log (compound, lot_number);
    """)
    op.execute("""
        CREATE INDEX idx_ip_log_tenancy
        ON investigational_product_log (site_id, sponsor_id);
    """)
    op.execute("""
        CREATE INDEX idx_ip_log_time
        ON investigational_product_log (session_id, event_timestamp DESC);
    """)

    # --- adverse_event_log ---
    op.execute("""
        CREATE INDEX idx_ae_session
        ON adverse_event_log (session_id);
    """)
    op.execute("""
        CREATE INDEX idx_ae_tenancy
        ON adverse_event_log (site_id, sponsor_id);
    """)
    op.execute("""
        CREATE INDEX idx_ae_time
        ON adverse_event_log (session_id, db_insert_time DESC);
    """)
    # All unresolved serious AEs requiring FDA reporting
    op.execute("""
        CREATE INDEX idx_ae_serious_unreported
        ON adverse_event_log (site_id, sponsor_id)
        WHERE is_serious = TRUE AND fda_reported_at IS NULL;
    """)

    # --- participant_consent_log ---
    op.execute("""
        CREATE INDEX idx_consent_participant_protocol
        ON participant_consent_log (participant_id, protocol_id);
    """)
    op.execute("""
        CREATE INDEX idx_consent_tenancy
        ON participant_consent_log (site_id, sponsor_id);
    """)
    op.execute("""
        CREATE INDEX idx_consent_active
        ON participant_consent_log (participant_id, protocol_id)
        WHERE revoked_at IS NULL;
    """)
    op.execute("""
        CREATE INDEX idx_consent_session
        ON participant_consent_log (session_id);
    """)

    # --- session_signal_metadata ---
    op.execute("""
        CREATE INDEX idx_session_signal_metadata_tenancy
        ON session_signal_metadata (sponsor_id, site_id);
    """)
    op.execute("""
        CREATE INDEX idx_session_signal_metadata_session
        ON session_signal_metadata (session_id);
    """)

    # --- data_correction_amendment_log ---
    op.execute("""
        CREATE INDEX idx_correction_session
        ON data_correction_amendment_log (session_id);
    """)
    op.execute("""
        CREATE INDEX idx_correction_tenancy
        ON data_correction_amendment_log (site_id, sponsor_id);
    """)
    # Find all corrections to a specific record in any table
    op.execute("""
        CREATE INDEX idx_correction_table_record
        ON data_correction_amendment_log (table_name, record_id);
    """)

    # --- session_environment_log ---
    op.execute("""
        CREATE INDEX idx_env_log_session
        ON session_environment_log (session_id);
    """)
    op.execute("""
        CREATE INDEX idx_env_log_tenancy
        ON session_environment_log (site_id, sponsor_id);
    """)
    # Time-ordered environment readings within a session
    op.execute("""
        CREATE INDEX idx_env_log_session_time
        ON session_environment_log (session_id, db_insert_time DESC);
    """)


def downgrade() -> None:
    # Drop all indexes created above.
    # Tables themselves are not affected — just the indexes.

    for table in BIOSIGNAL_TABLES:
        op.execute(f"DROP INDEX IF EXISTS idx_{table}_session_time;")
        op.execute(f"DROP INDEX IF EXISTS idx_{table}_tenancy;")

    op.execute("DROP INDEX IF EXISTS idx_eeg_session_channel_time;")

    op.execute("DROP INDEX IF EXISTS idx_sessions_sponsor;")
    op.execute("DROP INDEX IF EXISTS idx_sessions_site;")
    op.execute("DROP INDEX IF EXISTS idx_sessions_trial_arm;")
    op.execute("DROP INDEX IF EXISTS idx_sessions_sponsor_site;")
    op.execute("DROP INDEX IF EXISTS idx_sessions_tenancy;")
    op.execute("DROP INDEX IF EXISTS idx_sessions_status;")
    op.execute("DROP INDEX IF EXISTS idx_sessions_compound;")

    for table in EVENT_TABLES:
        op.execute(f"DROP INDEX IF EXISTS idx_{table}_session;")
        op.execute(f"DROP INDEX IF EXISTS idx_{table}_tenancy;")

    op.execute("DROP INDEX IF EXISTS idx_alert_events_severity;")
    op.execute("DROP INDEX IF EXISTS idx_alert_events_unacknowledged;")
    op.execute("DROP INDEX IF EXISTS idx_echo_events_session_time;")
    op.execute("DROP INDEX IF EXISTS idx_echo_events_actor;")
    op.execute("DROP INDEX IF EXISTS idx_echo_events_zone_label;")

    op.execute("DROP INDEX IF EXISTS idx_audit_events_session_time;")

    op.execute("DROP INDEX IF EXISTS idx_schema_version_session;")
    op.execute("DROP INDEX IF EXISTS idx_schema_version_alembic;")
    op.execute("DROP INDEX IF EXISTS idx_schema_version_recorded;")

    op.execute("DROP INDEX IF EXISTS idx_esig_session;")
    op.execute("DROP INDEX IF EXISTS idx_esig_record;")
    op.execute("DROP INDEX IF EXISTS idx_esig_signer;")
    op.execute("DROP INDEX IF EXISTS idx_esig_tenancy;")
    op.execute("DROP INDEX IF EXISTS idx_esig_session_time;")

    op.execute("DROP INDEX IF EXISTS idx_ip_log_session;")
    op.execute("DROP INDEX IF EXISTS idx_ip_log_compound_lot;")
    op.execute("DROP INDEX IF EXISTS idx_ip_log_tenancy;")
    op.execute("DROP INDEX IF EXISTS idx_ip_log_time;")

    op.execute("DROP INDEX IF EXISTS idx_ae_session;")
    op.execute("DROP INDEX IF EXISTS idx_ae_tenancy;")
    op.execute("DROP INDEX IF EXISTS idx_ae_time;")
    op.execute("DROP INDEX IF EXISTS idx_ae_serious_unreported;")

    op.execute("DROP INDEX IF EXISTS idx_consent_participant_protocol;")
    op.execute("DROP INDEX IF EXISTS idx_consent_tenancy;")
    op.execute("DROP INDEX IF EXISTS idx_consent_active;")
    op.execute("DROP INDEX IF EXISTS idx_consent_session;")

    op.execute("DROP INDEX IF EXISTS idx_session_signal_metadata_tenancy;")
    op.execute("DROP INDEX IF EXISTS idx_session_signal_metadata_session;")

    op.execute("DROP INDEX IF EXISTS idx_correction_session;")
    op.execute("DROP INDEX IF EXISTS idx_correction_tenancy;")
    op.execute("DROP INDEX IF EXISTS idx_correction_table_record;")

    op.execute("DROP INDEX IF EXISTS idx_env_log_session;")
    op.execute("DROP INDEX IF EXISTS idx_env_log_tenancy;")
    op.execute("DROP INDEX IF EXISTS idx_env_log_session_time;")
