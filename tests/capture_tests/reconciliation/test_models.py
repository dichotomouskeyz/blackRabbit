"""Spec-driven tests for reconciliation models (reconciliation.md R-001..R-003).

Phase 3b/5b — `StreamResult`, `ReconciliationReport`. Unit tests; no DB.
Assertions derive from the spec text only.

NOTE (black-box): dataclass field names are inferred from the spec. Phase D
resolves any mismatch in the `_result` / `_report` helpers only.
"""

from batch.reconciliation.models import ReconciliationReport, StreamResult
from tests.capture_tests.reconciliation.support import SESSION_ID

# NOTE (Phase D finding): in the implementation `gap` and `is_reconciled` are
# plain stored fields on the dataclasses; the xdf-minus-db / all-gaps-zero
# computation lives in `build_report` (covered by R-015). These unit tests
# therefore construct the fields directly and verify the documented arithmetic
# relationship and serialization shape.


def _result(xdf_count=10, db_count=10):
    return StreamResult(xdf_count=xdf_count, db_count=db_count, gap=xdf_count - db_count)


def _report(named_streams, is_reconciled, max_clock_drift_s=0.01):
    return ReconciliationReport(
        session_id=SESSION_ID,
        xdf_path="/tmp/session.xdf",
        streams=named_streams,
        is_reconciled=is_reconciled,
        ran_at="2026-06-09T00:00:00Z",
        max_clock_drift_s=max_clock_drift_s,
    )


class TestStreamResult:
    """reconciliation.md — `StreamResult`.

    ASSERTION SOURCE: spec-only
    Model used for assertions: Claude (Fable 5), implementation source withheld.
    """

    def test_r001_gap_is_xdf_minus_db(self):
        r1 = _result(xdf_count=10, db_count=7)
        assert r1.gap == r1.xdf_count - r1.db_count == 3
        r2 = _result(xdf_count=5, db_count=8)
        assert r2.gap == r2.xdf_count - r2.db_count == -3


class TestReconciliationReport:
    """reconciliation.md — `ReconciliationReport`.

    ASSERTION SOURCE: spec-only
    Model used for assertions: Claude (Fable 5), implementation source withheld.
    """

    def test_r002_is_reconciled_only_when_all_gaps_zero(self):
        all_zero = _report({"EEG": _result(10, 10), "HRV": _result(5, 5)}, is_reconciled=True)
        assert all_zero.is_reconciled is True
        assert all(s.gap == 0 for s in all_zero.streams.values())

        one_gap = _report({"EEG": _result(10, 10), "HRV": _result(6, 5)}, is_reconciled=False)
        assert one_gap.is_reconciled is False
        assert any(s.gap != 0 for s in one_gap.streams.values())

    def test_r003_as_dict_shape(self):
        report = _report({"EEG": _result(10, 10)}, is_reconciled=True)
        d = report.as_dict()
        for key in (
            "session_id",
            "xdf_path",
            "is_reconciled",
            "ran_at",
            "max_clock_drift_s",
            "streams",
        ):
            assert key in d
        eeg = d["streams"]["EEG"]
        for key in ("xdf_count", "db_count", "gap"):
            assert key in eeg
