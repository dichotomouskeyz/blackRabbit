"""Schema introspection helpers shared across schema test modules."""

_TS_SESSION = "ffff0000-0000-0000-0000-000000000001"
_TS_PARTICIPANT = "ffff0001-0000-0000-0000-000000000001"
_TS_SITE = "ffff0002-0000-0000-0000-000000000001"
_TS_SPONSOR = "ffff0003-0000-0000-0000-000000000001"
_TS_DEVICE = "ffff0004-0000-0000-0000-000000000001"
_TS_LSL = 12345.678901

_BIOSIGNAL_TABLES = ["eeg_samples", "hrv_samples", "eda_samples", "respiration_samples"]


def table_exists(cursor, table_name: str) -> bool:
    cursor.execute(
        """
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = %s
        )
        """,
        (table_name,),
    )
    return cursor.fetchone()[0]


def column_exists(cursor, table_name: str, column_name: str) -> bool:
    cursor.execute(
        """
        SELECT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = %s AND column_name = %s
        )
        """,
        (table_name, column_name),
    )
    return cursor.fetchone()[0]


def is_hypertable(cursor, table_name: str) -> bool:
    cursor.execute(
        """
        SELECT EXISTS (
            SELECT 1 FROM timescaledb_information.hypertables
            WHERE hypertable_name = %s
        )
        """,
        (table_name,),
    )
    return cursor.fetchone()[0]
