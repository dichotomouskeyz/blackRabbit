"""Spec-driven tests for batch/arc/windows.py (arc-windows.md).

Phase 5b — ARC temporal window helpers. Pure, in-memory; no DB, no I/O.
One test per R-xxx rule. Assertions derive from the spec text only.
"""

import math

import pytest

from batch.arc.windows import (
    ARCWindowBounds,
    centered_arc_window,
    centered_arc_windows,
    centered_w1,
    centered_w2,
    centered_w3,
)

_ECHO_TS = 1000.0


def _valid_bounds(start=100.0, center=105.0, end=110.0):
    return ARCWindowBounds(
        name="w1",
        label="immediate",
        center_lsl_timestamp=center,
        start_lsl_timestamp=start,
        end_lsl_timestamp=end,
    )


def _bounds(center, start, end):
    return ARCWindowBounds(
        name="w1",
        label="immediate",
        center_lsl_timestamp=center,
        start_lsl_timestamp=start,
        end_lsl_timestamp=end,
    )


class TestARCWindowBoundsValidation:
    """arc-windows.md — `ARCWindowBounds` validation.

    ASSERTION SOURCE: spec-only
    Model used for assertions: Claude (Fable 5), implementation source withheld.
    """

    @pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
    def test_r001_non_finite_center_raises(self, bad):
        with pytest.raises(ValueError):
            _bounds(center=bad, start=100.0, end=110.0)

    @pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
    def test_r001_non_finite_start_raises(self, bad):
        with pytest.raises(ValueError):
            _bounds(center=105.0, start=bad, end=110.0)

    @pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
    def test_r001_non_finite_end_raises(self, bad):
        with pytest.raises(ValueError):
            _bounds(center=105.0, start=100.0, end=bad)

    def test_r002_end_not_after_start_raises(self):
        with pytest.raises(ValueError):
            _bounds(center=100.0, start=100.0, end=100.0)
        with pytest.raises(ValueError):
            _bounds(center=100.0, start=110.0, end=100.0)

    def test_r003_center_outside_bounds_raises(self):
        with pytest.raises(ValueError):
            _bounds(center=99.0, start=100.0, end=110.0)
        with pytest.raises(ValueError):
            _bounds(center=111.0, start=100.0, end=110.0)

    def test_r004_width_s_is_end_minus_start(self):
        bounds = _valid_bounds(start=100.0, center=105.0, end=110.0)
        assert bounds.width_s == pytest.approx(10.0)


class TestContains:
    """arc-windows.md — `contains` / `as_sql_params`.

    ASSERTION SOURCE: spec-only
    Model used for assertions: Claude (Fable 5), implementation source withheld.
    """

    def test_r005_contains_default_excludes_end(self):
        bounds = _valid_bounds(start=100.0, center=105.0, end=110.0)
        assert bounds.contains(100.0) is True
        assert bounds.contains(105.0) is True
        assert bounds.contains(109.999) is True
        assert bounds.contains(110.0) is False

    def test_r006_contains_include_end_true(self):
        bounds = _valid_bounds(start=100.0, center=105.0, end=110.0)
        assert bounds.contains(110.0, include_end=True) is True

    def test_r007_as_sql_params_returns_start_end(self):
        bounds = _valid_bounds(start=100.0, center=105.0, end=110.0)
        assert bounds.as_sql_params() == (100.0, 110.0)


class TestCenteredArcWindow:
    """arc-windows.md — `centered_arc_window`.

    ASSERTION SOURCE: spec-only
    Model used for assertions: Claude (Fable 5), implementation source withheld.
    """

    @pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
    def test_r008_non_finite_echo_raises(self, bad):
        with pytest.raises(ValueError):
            centered_arc_window(bad, "w1", 30.0)

    @pytest.mark.parametrize("bad", [0.0, -1.0, math.nan, math.inf])
    def test_r009_invalid_width_raises(self, bad):
        with pytest.raises(ValueError):
            centered_arc_window(_ECHO_TS, "w1", bad)

    def test_r010_window_centered_on_echo(self):
        window = centered_arc_window(_ECHO_TS, "w1", 30.0)
        assert window.center_lsl_timestamp == pytest.approx(_ECHO_TS)
        assert window.start_lsl_timestamp == pytest.approx(_ECHO_TS - 15.0)
        assert window.end_lsl_timestamp == pytest.approx(_ECHO_TS + 15.0)


class TestCenteredArcWindows:
    """arc-windows.md — `centered_arc_windows`.

    ASSERTION SOURCE: spec-only
    Model used for assertions: Claude (Fable 5), implementation source withheld.
    """

    @pytest.mark.parametrize(
        "widths",
        [
            # A non-empty dict missing a window key. (An empty dict falls back to
            # the canonical widths by design, so it is not included here.)
            {"w2": 120.0, "w3": 300.0},
            {"w1": 30.0, "w3": 300.0},
            {"w1": 30.0, "w2": 120.0},
        ],
    )
    def test_r011_missing_window_key_raises(self, widths):
        with pytest.raises(ValueError):
            centered_arc_windows(_ECHO_TS, widths)

    def test_r012_returns_three_in_order(self):
        widths = {"w1": 30.0, "w2": 120.0, "w3": 300.0}
        result = centered_arc_windows(_ECHO_TS, widths)
        assert isinstance(result, tuple)
        assert len(result) == 3
        assert result[0].width_s == pytest.approx(30.0)
        assert result[1].width_s == pytest.approx(120.0)
        assert result[2].width_s == pytest.approx(300.0)


class TestCanonicalWindowWidths:
    """arc-windows.md — canonical window widths.

    ASSERTION SOURCE: spec-only
    Model used for assertions: Claude (Fable 5), implementation source withheld.
    """

    def test_r013_w1_width_is_30(self):
        assert centered_w1(_ECHO_TS).width_s == pytest.approx(30.0)

    def test_r014_w2_width_is_120(self):
        assert centered_w2(_ECHO_TS).width_s == pytest.approx(120.0)

    def test_r015_w3_width_is_300(self):
        assert centered_w3(_ECHO_TS).width_s == pytest.approx(300.0)
