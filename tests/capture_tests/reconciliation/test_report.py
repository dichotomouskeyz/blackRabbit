"""Unit and fixture-backed tests for build_report."""

from pathlib import Path

from batch.reconcile import build_report, read_xdf_counts
from tests.capture_tests.reconciliation.support import SESSION_ID


class TestBuildReport:
    def _make_report(self, xdf_counts, db_counts, path=None):
        return build_report(
            session_id=SESSION_ID,
            xdf_path=path or Path("/fake/session.xdf"),
            xdf_counts=xdf_counts,
            db_counts=db_counts,
        )

    def test_reconciled_when_counts_match(self):
        counts = {"EEG": 100, "HRV": 10, "EDA": 20, "Respiration": 15}
        report = self._make_report(counts, counts)
        assert report.is_reconciled is True

    def test_not_reconciled_when_eeg_gap(self):
        xdf = {"EEG": 100, "HRV": 10, "EDA": 20, "Respiration": 15}
        db = {"EEG": 90, "HRV": 10, "EDA": 20, "Respiration": 15}
        report = self._make_report(xdf, db)
        assert report.is_reconciled is False

    def test_gap_is_xdf_minus_db(self):
        xdf = {"EEG": 100}
        db = {"EEG": 90}
        report = self._make_report(xdf, db)
        assert report.streams["EEG"].gap == 10

    def test_negative_gap_when_db_exceeds_xdf(self):
        xdf = {"HRV": 5}
        db = {"HRV": 8}
        report = self._make_report(xdf, db)
        assert report.streams["HRV"].gap == -3

    def test_zero_gap_when_both_zero(self):
        report = self._make_report(
            {"EEG": 0, "HRV": 0, "EDA": 0, "Respiration": 0},
            {"EEG": 0, "HRV": 0, "EDA": 0, "Respiration": 0},
        )
        assert report.is_reconciled is True

    def test_stream_present_in_xdf_not_db_flagged(self):
        xdf = {"EEG": 50}
        db = {}
        report = self._make_report(xdf, db)
        assert report.streams["EEG"].gap == 50
        assert report.is_reconciled is False

    def test_stream_present_in_db_not_xdf_flagged(self):
        xdf = {}
        db = {"HRV": 10}
        report = self._make_report(xdf, db)
        assert report.streams["HRV"].gap == -10
        assert report.is_reconciled is False

    def test_all_stream_tables_always_present_in_report(self):
        report = self._make_report({}, {})
        for name in ("EEG", "HRV", "EDA", "Respiration"):
            assert name in report.streams

    def test_as_dict_contains_required_keys(self):
        report = self._make_report({"EEG": 10}, {"EEG": 10})
        d = report.as_dict()
        assert "session_id" in d
        assert "is_reconciled" in d
        assert "streams" in d
        assert "ran_at" in d

    def test_as_dict_streams_contain_gap(self):
        report = self._make_report({"EEG": 10}, {"EEG": 7})
        d = report.as_dict()
        assert d["streams"]["EEG"]["gap"] == 3


class TestEndToEnd:
    def test_xdf_counts_flow_into_report_correctly(self, xdf_file):
        path, expected = xdf_file
        xdf_counts = read_xdf_counts(path)
        report = build_report(SESSION_ID, path, xdf_counts, xdf_counts)
        assert report.is_reconciled is True
        for name, count in expected.items():
            assert report.streams[name].xdf_count == count
            assert report.streams[name].gap == 0

    def test_simulated_db_loss_detected(self, xdf_file):
        path, _ = xdf_file
        xdf_counts = read_xdf_counts(path)
        db_counts = {**xdf_counts, "EEG": xdf_counts["EEG"] - 5}
        report = build_report(SESSION_ID, path, xdf_counts, db_counts)
        assert report.is_reconciled is False
        assert report.streams["EEG"].gap == 5
