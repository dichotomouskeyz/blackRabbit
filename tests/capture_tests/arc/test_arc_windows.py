"""Tests for ARC temporal window helpers."""

import pytest

from batch.arc.windows import (
    CANONICAL_CENTERED_WINDOW_WIDTHS_S,
    centered_arc_window,
    centered_arc_windows,
    centered_w1,
    centered_w2,
    centered_w3,
)


class TestARCWindows:
    def test_centered_w1_is_narrow_window_around_echo_timestamp(self):
        window = centered_w1(1_000.0)

        assert window.name == "w1"
        assert window.label == "narrow"
        assert window.start_lsl_timestamp == pytest.approx(985.0)
        assert window.end_lsl_timestamp == pytest.approx(1_015.0)
        assert window.width_s == pytest.approx(30.0)

    def test_centered_w2_is_medium_window_around_echo_timestamp(self):
        window = centered_w2(1_000.0)

        assert window.name == "w2"
        assert window.label == "medium"
        assert window.start_lsl_timestamp == pytest.approx(940.0)
        assert window.end_lsl_timestamp == pytest.approx(1_060.0)
        assert window.width_s == pytest.approx(120.0)

    def test_centered_w3_is_wide_window_around_echo_timestamp(self):
        window = centered_w3(1_000.0)

        assert window.name == "w3"
        assert window.label == "wide"
        assert window.start_lsl_timestamp == pytest.approx(850.0)
        assert window.end_lsl_timestamp == pytest.approx(1_150.0)
        assert window.width_s == pytest.approx(300.0)

    def test_centered_arc_windows_returns_ordered_w1_w2_w3(self):
        windows = centered_arc_windows(500.0)

        assert tuple(window.name for window in windows) == ("w1", "w2", "w3")
        assert [window.width_s for window in windows] == [
            CANONICAL_CENTERED_WINDOW_WIDTHS_S["w1"],
            CANONICAL_CENTERED_WINDOW_WIDTHS_S["w2"],
            CANONICAL_CENTERED_WINDOW_WIDTHS_S["w3"],
        ]

    def test_custom_widths_are_supported(self):
        windows = centered_arc_windows(
            100.0,
            widths_s={"w1": 10.0, "w2": 20.0, "w3": 40.0},
        )

        assert [(w.start_lsl_timestamp, w.end_lsl_timestamp) for w in windows] == [
            (95.0, 105.0),
            (90.0, 110.0),
            (80.0, 120.0),
        ]

    def test_contains_defaults_to_half_open_range(self):
        window = centered_arc_window(100.0, "w1", 10.0)

        assert window.contains(95.0) is True
        assert window.contains(100.0) is True
        assert window.contains(105.0) is False
        assert window.contains(105.0, include_end=True) is True
        assert window.as_sql_params() == (95.0, 105.0)

    def test_rejects_non_positive_width(self):
        with pytest.raises(ValueError, match="width_s"):
            centered_arc_window(100.0, "w1", 0.0)

    def test_rejects_missing_custom_window_width(self):
        with pytest.raises(ValueError, match="missing ARC window widths"):
            centered_arc_windows(100.0, widths_s={"w1": 10.0, "w2": 20.0})
