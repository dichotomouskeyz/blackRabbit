"""Domain seed fixtures for ARC integration tests.

These fixtures insert a minimal but schema-valid session with ECHO anchor
events and EEG samples placed within the alignment threshold of each anchor,
then commit so DB-backed ARC code can read them. The root `db_conn` fixture
rolls everything back on teardown.
"""

from types import SimpleNamespace

import pytest

from tests.capture_tests.arc.support import (
    DEVICE_ID,
    PARTICIPANT_ID,
    SESSION_ID,
    SITE_ID,
    SPONSOR_ID,
)

_ANCHOR_TS = (1000.0, 1100.0, 1200.0)
# Two of the three anchors share this (event_type, zone_label) pair.
_MATCHING_FILTER = ("manual_marker", "dose_administration")


@pytest.fixture
def arc_seeded_session(cursor, db_conn):
    cursor.execute(
        """
        INSERT INTO sessions
            (id, site_id, sponsor_id, participant_id, capture_source,
             compound, status, started_at)
        VALUES
            (%s::uuid, %s::uuid, %s::uuid, %s::uuid, 'simulated',
             'psilocybin', 'closed'::session_status, NOW())
        """,
        (SESSION_ID, SITE_ID, SPONSOR_ID, PARTICIPANT_ID),
    )

    echo_specs = [
        ("manual_marker", "dose_administration"),
        ("manual_marker", "dose_administration"),
        ("zone_enter", "in_room"),
    ]
    for ts, (event_type, zone_label) in zip(_ANCHOR_TS, echo_specs):
        cursor.execute(
            """
            INSERT INTO echo_events
                (session_id, participant_id, site_id, sponsor_id, event_type,
                 source, actor_role, zone_label, lsl_timestamp, db_insert_time)
            VALUES
                (%s::uuid, %s::uuid, %s::uuid, %s::uuid, %s,
                 'manual_logging', 'therapist', %s, %s, NOW())
            """,
            (SESSION_ID, PARTICIPANT_ID, SITE_ID, SPONSOR_ID, event_type, zone_label, ts),
        )

    # EEG samples within 0.1 s of each anchor → well under the 1.0 s gate.
    sample_index = 0
    for ts in _ANCHOR_TS:
        for offset in (-0.1, 0.0, 0.1):
            cursor.execute(
                """
                INSERT INTO eeg_samples
                    (id, session_id, participant_id, site_id, sponsor_id,
                     device_id, lsl_timestamp, db_insert_time, sample_index,
                     channel_id, voltage)
                VALUES
                    (gen_random_uuid(), %s::uuid, %s::uuid, %s::uuid, %s::uuid,
                     %s::uuid, %s, NOW(), %s, 'ch_0', 1.0)
                """,
                (
                    SESSION_ID,
                    PARTICIPANT_ID,
                    SITE_ID,
                    SPONSOR_ID,
                    DEVICE_ID,
                    ts + offset,
                    sample_index,
                ),
            )
            sample_index += 1

    db_conn.commit()

    yield {
        "echo_count": len(_ANCHOR_TS),
        "matching_filters": [_MATCHING_FILTER],
        "matching_count": 2,
        "aligned_stream": "eeg",
    }
    cursor.execute("DELETE FROM eeg_samples WHERE session_id = %s::uuid", (SESSION_ID,))
    cursor.execute("DELETE FROM echo_events WHERE session_id = %s::uuid", (SESSION_ID,))
    cursor.execute("DELETE FROM sessions WHERE id = %s::uuid", (SESSION_ID,))
    db_conn.commit()


@pytest.fixture
def arc_sparse_session(cursor, db_conn):
    """Session with ECHO anchors but only a couple of biosignal samples —
    below any reasonable `min_sample_count` baseline threshold (R-022)."""
    cursor.execute(
        """
        INSERT INTO sessions
            (id, site_id, sponsor_id, participant_id, capture_source,
             compound, status, started_at)
        VALUES
            (%s::uuid, %s::uuid, %s::uuid, %s::uuid, 'simulated',
             'psilocybin', 'closed'::session_status, NOW())
        """,
        (SESSION_ID, SITE_ID, SPONSOR_ID, PARTICIPANT_ID),
    )
    for idx, ts in enumerate((1000.0, 1000.1)):
        cursor.execute(
            """
            INSERT INTO eeg_samples
                (id, session_id, participant_id, site_id, sponsor_id,
                 device_id, lsl_timestamp, db_insert_time, sample_index,
                 channel_id, voltage)
            VALUES
                (gen_random_uuid(), %s::uuid, %s::uuid, %s::uuid, %s::uuid,
                 %s::uuid, %s, NOW(), %s, 'ch_0', 1.0)
            """,
            (SESSION_ID, PARTICIPANT_ID, SITE_ID, SPONSOR_ID, DEVICE_ID, ts, idx),
        )
    db_conn.commit()
    yield {"sample_count": 2}
    cursor.execute("DELETE FROM eeg_samples WHERE session_id = %s::uuid", (SESSION_ID,))
    cursor.execute("DELETE FROM sessions WHERE id = %s::uuid", (SESSION_ID,))
    db_conn.commit()


@pytest.fixture
def arc_config(tmp_path):
    """Best-effort ARC config for integration tests.

    Phase D wires this to the project's real config loader. The shape below
    mirrors the fields the processor spec references (baseline window duration,
    minimum sample count, per-modality signal components).
    """
    return SimpleNamespace(
        config_version="arc_watchdog_config.toml@test-001",
        baseline=SimpleNamespace(
            window_duration_s=10.0,
            min_sample_count=100,
        ),
        signal_components={
            "eeg": "eeg_alpha_power",
            "hrv": "hrv_rmssd",
            "eda": "eda_mean",
            "respiration": "respiration_rate",
        },
        debounce_gap_s=1.0,
    )
