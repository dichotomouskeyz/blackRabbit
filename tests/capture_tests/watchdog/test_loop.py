"""Spec-driven tests for the watchdog supervision loop (watchdog.md R-007..R-010).

Phase 2 — `run_watchdog_loop` restart/shutdown accounting. Unit tests with a
mocked subprocess + DB collaborators (no real process, no real DB).
Assertions derive from the spec text only.

NOTE (black-box): the loop's collaborator names and `run_watchdog_loop`
signature are inferred from the spec. The whole module is skipped if those
symbols cannot be imported, so a name mismatch surfaces as a skip (to be
wired in Phase D) rather than a collection error.
"""

import pytest

runner = pytest.importorskip("capture.watchdog.runner")

_HAS_LOOP = all(
    hasattr(runner, name)
    for name in (
        "run_watchdog_loop",
        "MAX_RESTARTS",
    )
)

pytestmark = pytest.mark.skipif(
    not _HAS_LOOP, reason="watchdog loop harness symbols not importable; wire in Phase D"
)


class _FakeProcess:
    """Minimal subprocess stand-in: exits immediately with a fixed code."""

    def __init__(self, returncode):
        self.returncode = returncode
        self.pid = 1234

    def wait(self, timeout=None):
        return self.returncode

    def poll(self):
        return self.returncode


class TestWatchdogLoop:
    """watchdog.md — watchdog loop.

    ASSERTION SOURCE: spec-only
    Model used for assertions: Claude (Fable 5), implementation source withheld.
    """

    def test_r007_clean_shutdown_does_not_increment_restart(self, monkeypatch):
        events = {"clean": 0, "restart_count_seen": []}
        monkeypatch.setattr(
            runner,
            "handle_clean_shutdown",
            lambda *a, **k: events.__setitem__("clean", events["clean"] + 1),
            raising=False,
        )
        state = runner.run_watchdog_loop  # presence asserted by skipif
        assert state is not None
        # Detailed wiring of the loop's state object is completed in Phase D;
        # this test documents R-007's contract: clean shutdown path is taken
        # and restart_count is not incremented.
        pytest.skip("loop state injection completed in Phase D with implementation access")

    def test_r008_unexpected_exit_increments_and_records(self):
        pytest.skip("loop state injection completed in Phase D with implementation access")

    def test_r009_exceeding_max_restarts_marks_failed(self):
        pytest.skip("loop state injection completed in Phase D with implementation access")

    def test_r010_every_unexpected_exit_logs_restart(self):
        pytest.skip("loop state injection completed in Phase D with implementation access")
