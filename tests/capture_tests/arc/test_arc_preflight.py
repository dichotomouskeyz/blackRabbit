"""Integration tests for ARC ECHO/APEX temporal alignment preflight."""

from uuid import uuid4

import pytest

from batch.arc.preflight import (
    assert_arc_temporal_alignment,
    validate_arc_temporal_alignment,
)

_PARTICIPANT_ID = "aaaa0000-0000-0000-0000-000000000001"
_SITE_ID = "bbbb0000-0000-0000-0000-000000000001"
_SPONSOR_ID = "cccc0000-0000-0000-0000-000000000001"
_DEVICE_ID = "dddd0000-0000-0000-0000-000000000001"


def _insert_echo(cursor, session_id: str, lsl_timestamp: float) -> None:
    cursor.execute(
        """
        INSERT INTO echo_events (
            session_id, participant_id, site_id, sponsor_id,
            event_type, source, actor_id, actor_role, zone_label, lsl_timestamp
        ) VALUES (
            %s, %s, %s, %s,
            'zone_enter', 'manual_logging', 'therapist_01', 'therapist',
            'arms_reach', %s
        )
        """,
        (session_id, _PARTICIPANT_ID, _SITE_ID, _SPONSOR_ID, lsl_timestamp),
    )


def _insert_eeg(cursor, session_id: str, lsl_timestamp: float, sample_index: int) -> None:
    cursor.execute(
        """
        INSERT INTO eeg_samples (
            session_id, participant_id, site_id, sponsor_id, device_id,
            channel_id, voltage, lsl_timestamp, sample_index
        ) VALUES (%s, %s, %s, %s, %s, 'Cz', 12.5, %s, %s)
        """,
        (
            session_id,
            _PARTICIPANT_ID,
            _SITE_ID,
            _SPONSOR_ID,
            _DEVICE_ID,
            lsl_timestamp,
            sample_index,
        ),
    )


def _insert_hrv(cursor, session_id: str, lsl_timestamp: float, sample_index: int) -> None:
    cursor.execute(
        """
        INSERT INTO hrv_samples (
            session_id, participant_id, site_id, sponsor_id, device_id,
            rr_interval_ms, heart_rate_bpm, lsl_timestamp, sample_index
        ) VALUES (%s, %s, %s, %s, %s, 800.0, 75.0, %s, %s)
        """,
        (
            session_id,
            _PARTICIPANT_ID,
            _SITE_ID,
            _SPONSOR_ID,
            _DEVICE_ID,
            lsl_timestamp,
            sample_index,
        ),
    )


def _insert_eda(cursor, session_id: str, lsl_timestamp: float, sample_index: int) -> None:
    cursor.execute(
        """
        INSERT INTO eda_samples (
            session_id, participant_id, site_id, sponsor_id, device_id,
            raw_conductance_us, conductance_us, lsl_timestamp, sample_index
        ) VALUES (%s, %s, %s, %s, %s, 0.25, 0.25, %s, %s)
        """,
        (
            session_id,
            _PARTICIPANT_ID,
            _SITE_ID,
            _SPONSOR_ID,
            _DEVICE_ID,
            lsl_timestamp,
            sample_index,
        ),
    )


def _insert_respiration(cursor, session_id: str, lsl_timestamp: float, sample_index: int) -> None:
    cursor.execute(
        """
        INSERT INTO respiration_samples (
            session_id, participant_id, site_id, sponsor_id, device_id,
            raw_amplitude, processed_amplitude, lsl_timestamp, sample_index
        ) VALUES (%s, %s, %s, %s, %s, 1.0, 1.0, %s, %s)
        """,
        (
            session_id,
            _PARTICIPANT_ID,
            _SITE_ID,
            _SPONSOR_ID,
            _DEVICE_ID,
            lsl_timestamp,
            sample_index,
        ),
    )


def _insert_apex_sample_set(cursor, session_id: str, lsl_timestamp: float, sample_index: int):
    _insert_eeg(cursor, session_id, lsl_timestamp, sample_index)
    _insert_hrv(cursor, session_id, lsl_timestamp, sample_index)
    _insert_eda(cursor, session_id, lsl_timestamp, sample_index)
    _insert_respiration(cursor, session_id, lsl_timestamp, sample_index)


@pytest.mark.integration
class TestARCTemporalAlignment:
    def test_passes_when_every_echo_anchor_has_subsecond_apex_neighbors(self, cursor, db_conn):
        session_id = str(uuid4())
        _insert_echo(cursor, session_id, 100.20)
        _insert_echo(cursor, session_id, 101.80)
        _insert_apex_sample_set(cursor, session_id, 100.00, 1)
        _insert_apex_sample_set(cursor, session_id, 102.00, 2)

        report = assert_arc_temporal_alignment(db_conn, session_id)

        assert report.is_aligned is True
        assert report.echo_event_count == 2
        assert report.failed_streams == ()
        assert report.streams["EEG"].max_nearest_echo_delta_s == pytest.approx(0.20)
        assert report.as_dict()["is_aligned"] is True

    def test_fails_when_one_apex_stream_is_not_subsecond_aligned(self, cursor, db_conn):
        session_id = str(uuid4())
        _insert_echo(cursor, session_id, 100.20)
        _insert_eeg(cursor, session_id, 100.00, 1)
        _insert_eda(cursor, session_id, 100.00, 1)
        _insert_respiration(cursor, session_id, 100.00, 1)
        _insert_hrv(cursor, session_id, 90.00, 1)

        report = validate_arc_temporal_alignment(db_conn, session_id)

        assert report.is_aligned is False
        assert report.failed_streams == ("HRV",)
        assert report.streams["HRV"].max_nearest_echo_delta_s == pytest.approx(10.20)
        with pytest.raises(RuntimeError, match="failed streams: HRV"):
            report.raise_for_unaligned()

    def test_fails_without_echo_anchor_events(self, cursor, db_conn):
        session_id = str(uuid4())
        _insert_apex_sample_set(cursor, session_id, 100.00, 1)

        report = validate_arc_temporal_alignment(db_conn, session_id)

        assert report.is_aligned is False
        assert report.echo_event_count == 0
        with pytest.raises(RuntimeError, match="no ECHO anchor events"):
            report.raise_for_unaligned()

    def test_rejects_thresholds_that_are_not_subsecond(self, db_conn):
        with pytest.raises(ValueError, match="sub-second"):
            validate_arc_temporal_alignment(db_conn, str(uuid4()), threshold_s=1.5)

    def test_anchor_filter_excludes_non_anchor_events(self, cursor, db_conn):
        session_id = str(uuid4())
        # Insert zone_exit and in_room events — neither qualifies as anchor
        for label in ("arms_reach", "in_room"):
            cursor.execute(
                """
                INSERT INTO echo_events (
                    session_id, participant_id, site_id, sponsor_id,
                    event_type, source, actor_id, actor_role, zone_label, lsl_timestamp
                ) VALUES (%s, %s, %s, %s, 'zone_exit', 'manual_logging',
                          'therapist_01', 'therapist', %s, 100.0)
                """,
                (session_id, _PARTICIPANT_ID, _SITE_ID, _SPONSOR_ID, label),
            )
        _insert_apex_sample_set(cursor, session_id, 100.00, 1)

        anchor_filters = (("zone_enter", "arms_reach"),)
        report = validate_arc_temporal_alignment(db_conn, session_id, anchor_filters=anchor_filters)

        assert report.echo_event_count == 0
        assert report.is_aligned is False

    def test_anchor_filter_counts_only_matching_events(self, cursor, db_conn):
        session_id = str(uuid4())
        # One anchor event (zone_enter/arms_reach) and one non-anchor (zone_exit/arms_reach)
        _insert_echo(cursor, session_id, 100.0)  # zone_enter/arms_reach — anchor
        cursor.execute(
            """
            INSERT INTO echo_events (
                session_id, participant_id, site_id, sponsor_id,
                event_type, source, actor_id, actor_role, zone_label, lsl_timestamp
            ) VALUES (%s, %s, %s, %s, 'zone_exit', 'manual_logging',
                      'therapist_01', 'therapist', 'arms_reach', 200.0)
            """,
            (session_id, _PARTICIPANT_ID, _SITE_ID, _SPONSOR_ID),
        )
        _insert_apex_sample_set(cursor, session_id, 100.00, 1)
        _insert_apex_sample_set(cursor, session_id, 200.00, 2)

        anchor_filters = (("zone_enter", "arms_reach"),)
        report = validate_arc_temporal_alignment(db_conn, session_id, anchor_filters=anchor_filters)

        assert report.echo_event_count == 1

    def test_no_anchor_filter_counts_all_events(self, cursor, db_conn):
        session_id = str(uuid4())
        _insert_echo(cursor, session_id, 100.0)
        cursor.execute(
            """
            INSERT INTO echo_events (
                session_id, participant_id, site_id, sponsor_id,
                event_type, source, actor_id, actor_role, zone_label, lsl_timestamp
            ) VALUES (%s, %s, %s, %s, 'zone_exit', 'manual_logging',
                      'therapist_01', 'therapist', 'arms_reach', 200.0)
            """,
            (session_id, _PARTICIPANT_ID, _SITE_ID, _SPONSOR_ID),
        )
        _insert_apex_sample_set(cursor, session_id, 100.00, 1)

        report = validate_arc_temporal_alignment(db_conn, session_id)

        assert report.echo_event_count == 2
