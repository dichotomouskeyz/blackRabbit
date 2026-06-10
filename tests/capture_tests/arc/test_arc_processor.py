"""Spec-driven tests for batch/arc/processor.py (arc-processor.md).

Phase 5b — ARC post-session computation. Unit tests cover debounce
clustering, cluster value objects, anchor-filter helpers, and the baseline
row builder; integration tests cover DB loading, idempotent upsert, and the
`run_arc_post_session` orchestrator. One test per R-xxx rule.
Assertions derive from the spec text only.

NOTE (black-box): some private-helper signatures below are inferred from the
spec's prose. Phase D resolves any signature mismatch in the call site /
helper only — assertion values are never adjusted.
"""

import math
from types import SimpleNamespace

import pytest

from batch.arc.processor import (
    AnchorEventFilter,
    ARCPostSessionError,
    EchoAnchorCluster,
    _anchor_filter_pairs,
    _build_baseline_row,
    cluster_echo_anchor_rows,
    compute_session_baseline_rows,
    load_echo_anchor_rows,
    run_arc_post_session,
    upsert_session_baselines,
)
from tests.capture_tests.arc.support import (
    PARTICIPANT_ID,
    SESSION_ID,
    SITE_ID,
    SPONSOR_ID,
)


def _row(row_id, ts, event_type="manual_marker", zone_label="dose_administration"):
    return SimpleNamespace(
        id=row_id,
        lsl_timestamp=ts,
        event_type=event_type,
        zone_label=zone_label,
    )


class TestClusterValidation:
    """arc-processor.md — cluster validation.

    ASSERTION SOURCE: spec-only
    Model used for assertions: Claude (Fable 5), implementation source withheld.
    """

    def test_r001_negative_debounce_gap_raises(self):
        with pytest.raises(ValueError):
            cluster_echo_anchor_rows([_row(1, 1000.0)], debounce_gap_s=-1.0)

    @pytest.mark.parametrize("bad", [math.inf, -math.inf, math.nan])
    def test_r002_non_finite_debounce_gap_raises(self, bad):
        with pytest.raises(ValueError):
            cluster_echo_anchor_rows([_row(1, 1000.0)], debounce_gap_s=bad)

    def test_r003_empty_input_returns_empty_tuple(self):
        assert cluster_echo_anchor_rows([], debounce_gap_s=1.0) == ()


class TestDebounceClustering:
    """arc-processor.md — debounce clustering logic.

    ASSERTION SOURCE: spec-only
    Model used for assertions: Claude (Fable 5), implementation source withheld.
    """

    def test_r004_gap_below_threshold_same_cluster(self):
        rows = [_row(1, 1000.0), _row(2, 1000.5)]
        clusters = cluster_echo_anchor_rows(rows, debounce_gap_s=1.0)
        assert len(clusters) == 1
        assert clusters[0].size == 2

    def test_r005_gap_equal_threshold_same_cluster(self):
        rows = [_row(1, 1000.0), _row(2, 1001.0)]
        clusters = cluster_echo_anchor_rows(rows, debounce_gap_s=1.0)
        assert len(clusters) == 1
        assert clusters[0].size == 2

    def test_r006_gap_above_threshold_different_clusters(self):
        rows = [_row(1, 1000.0), _row(2, 1001.5)]
        clusters = cluster_echo_anchor_rows(rows, debounce_gap_s=1.0)
        assert len(clusters) == 2

    def test_r007_unsorted_input_same_result_as_sorted(self):
        unsorted_rows = [_row(2, 1001.5), _row(1, 1000.0), _row(3, 1000.5)]
        sorted_rows = [_row(1, 1000.0), _row(3, 1000.5), _row(2, 1001.5)]
        a = cluster_echo_anchor_rows(unsorted_rows, debounce_gap_s=1.0)
        b = cluster_echo_anchor_rows(sorted_rows, debounce_gap_s=1.0)
        assert tuple(c.size for c in a) == tuple(c.size for c in b)

    def test_r008_sequential_index_from_zero(self):
        rows = [_row(1, 1000.0), _row(2, 1005.0), _row(3, 1010.0)]
        clusters = cluster_echo_anchor_rows(rows, debounce_gap_s=1.0)
        assert [c.index for c in clusters] == [0, 1, 2]


class TestEchoAnchorCluster:
    """arc-processor.md — `EchoAnchorCluster` properties.

    ASSERTION SOURCE: spec-only
    Model used for assertions: Claude (Fable 5), implementation source withheld.
    """

    def test_r009_empty_members_raises(self):
        with pytest.raises(ValueError):
            EchoAnchorCluster(index=0, members=())

    def test_r010_canonical_anchor_is_first_member(self):
        first = _row(1, 1000.0)
        cluster = EchoAnchorCluster(index=0, members=(first, _row(2, 1000.5)))
        assert cluster.canonical_anchor is first

    def test_r011_size_is_member_count(self):
        cluster = EchoAnchorCluster(
            index=0, members=(_row(1, 1000.0), _row(2, 1000.5), _row(3, 1000.9))
        )
        assert cluster.size == 3

    def test_r012_start_and_end_timestamps(self):
        members = (_row(1, 1000.0), _row(2, 1000.5), _row(3, 1000.9))
        cluster = EchoAnchorCluster(index=0, members=members)
        assert cluster.start_lsl_timestamp == 1000.0
        assert cluster.end_lsl_timestamp == 1000.9


class TestAnchorFilterPairs:
    """arc-processor.md — anchor filter helper.

    ASSERTION SOURCE: spec-only
    Model used for assertions: Claude (Fable 5), implementation source withheld.
    """

    def test_r013_none_and_empty_return_none(self):
        assert _anchor_filter_pairs(None) is None
        assert _anchor_filter_pairs([]) is None

    def test_r014_returns_pair_per_filter(self):
        filters = [
            AnchorEventFilter(event_type="manual_marker", zone_label="dose"),
            AnchorEventFilter(event_type="zone_enter", zone_label="chair"),
        ]
        pairs = _anchor_filter_pairs(filters)
        assert tuple(pairs) == (
            ("manual_marker", "dose"),
            ("zone_enter", "chair"),
        )


class TestBaselineRowBuilder:
    """arc-processor.md — baseline row builder.

    ASSERTION SOURCE: spec-only
    Model used for assertions: Claude (Fable 5), implementation source withheld.
    """

    @pytest.mark.parametrize("bad_count", [0, -1])
    def test_r015_zero_or_negative_sample_count_returns_none(self, bad_count):
        # stats tuple = (mean, std, sample_count).
        row = _build_baseline_row(
            SESSION_ID,
            PARTICIPANT_ID,
            SITE_ID,
            SPONSOR_ID,
            "hrv",
            "hrv_rmssd",
            (1.0, 0.5, bad_count),
            1000.0,
            1010.0,
        )
        assert row is None


@pytest.mark.integration
class TestEchoAnchorLoading:
    """arc-processor.md — ECHO anchor loading.

    ASSERTION SOURCE: spec-only
    Model used for assertions: Claude (Fable 5), implementation source withheld.
    """

    def test_r016_rows_ordered_by_timestamp_then_id(self, db_conn, arc_seeded_session):
        rows = load_echo_anchor_rows(db_conn, SESSION_ID, SPONSOR_ID)
        timestamps = [r.lsl_timestamp for r in rows]
        assert timestamps == sorted(timestamps)

    def test_r017_anchor_filters_restrict_rows(self, db_conn, arc_seeded_session):
        rows = load_echo_anchor_rows(
            db_conn,
            SESSION_ID,
            SPONSOR_ID,
            anchor_filters=arc_seeded_session["matching_filters"],
        )
        assert len(rows) == arc_seeded_session["matching_count"]

    def test_r018_no_filters_returns_all_rows(self, db_conn, arc_seeded_session):
        rows = load_echo_anchor_rows(db_conn, SESSION_ID, SPONSOR_ID, anchor_filters=None)
        assert len(rows) == arc_seeded_session["echo_count"]


@pytest.mark.integration
class TestBaselinePersistence:
    """arc-processor.md — baseline persistence + orchestrator.

    ASSERTION SOURCE: spec-only
    Model used for assertions: Claude (Fable 5), implementation source withheld.
    """

    def test_r019_upsert_is_idempotent(self, db_conn, arc_seeded_session, arc_config):
        rows = compute_session_baseline_rows(db_conn, SESSION_ID, SPONSOR_ID, arc_config)
        upsert_session_baselines(db_conn, rows)
        upsert_session_baselines(db_conn, rows)
        db_conn.commit()
        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM session_baselines WHERE session_id = %s::uuid",
                (SESSION_ID,),
            )
            count = cur.fetchone()[0]
        with db_conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(DISTINCT (modality, signal_component))
                FROM session_baselines WHERE session_id = %s::uuid
                """,
                (SESSION_ID,),
            )
            distinct = cur.fetchone()[0]
        assert count == distinct

    def test_r020_upsert_empty_is_noop(self, db_conn):
        # No SQL executed for an empty sequence — must not raise.
        assert upsert_session_baselines(db_conn, []) is None

    def test_r021_no_biosignal_data_returns_empty(self, db_conn, arc_config):
        rows = compute_session_baseline_rows(db_conn, SESSION_ID, SPONSOR_ID, arc_config)
        assert tuple(rows) == ()

    def test_r022_too_few_samples_raises(self, db_conn, arc_sparse_session, arc_config):
        with pytest.raises(RuntimeError):
            compute_session_baseline_rows(db_conn, SESSION_ID, SPONSOR_ID, arc_config)

    def test_r023_run_writes_baselines_and_counts(self, db_conn, arc_seeded_session, arc_config):
        result = run_arc_post_session(db_conn, SESSION_ID, SPONSOR_ID, arc_config)
        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM session_baselines WHERE session_id = %s::uuid",
                (SESSION_ID,),
            )
            written = cur.fetchone()[0]
        assert result.baseline_row_count == written

    def test_r024_errors_wrapped_as_arc_post_session_error(self, db_conn, arc_config):
        # Unknown session → an unhandled error inside the pipeline must surface
        # as ARCPostSessionError, not the original exception type.
        with pytest.raises(ARCPostSessionError):
            run_arc_post_session(
                db_conn,
                "00000000-0000-4000-8000-0000000000ff",
                SPONSOR_ID,
                arc_config,
            )
