"""HW-008: source times are converted, never repaired."""

import numpy as np
import pytest

from capture.hardware.clock import EpochClock
from capture.hardware.errors import HardwareError


def test_fixed_offset_and_independent_source_histories():
    clock = EpochClock.measure(lambda: 100.0, 0.05, lambda: 1000.0)
    np.testing.assert_allclose(clock.convert("a", np.array([1000, 1000.004])), [100, 100.004])
    np.testing.assert_allclose(clock.convert("b", np.array([999])), [99])
    assert clock.offset == -900
    assert clock.uncertainty == 0
    clock.check()


@pytest.mark.parametrize("times", [[0], [-1], [np.nan], [np.inf], [3, 2], [3, 3]])
def test_invalid_timestamp_vectors(times):
    clock = EpochClock.measure(lambda: 100.0, 0.05, lambda: 1000.0)
    with pytest.raises(HardwareError, match="finite and increasing"):
        clock.convert("a", np.array(times))


def test_backward_across_chunks_is_rejected():
    clock = EpochClock.measure(lambda: 100.0, 0.05, lambda: 1000.0)
    clock.convert("a", np.array([1000, 1001]))
    with pytest.raises(HardwareError):
        clock.convert("a", np.array([1001]))


def test_host_clock_discontinuity_stops_conversion():
    wall = [1000.0]
    clock = EpochClock.measure(lambda: 100.0, 0.05, lambda: wall[0])
    wall[0] += 1
    with pytest.raises(HardwareError) as error:
        clock.check()
    assert error.value.code == "clock_discontinuity"


def test_lsl_zero_timestamp_sentinel_is_rejected():
    clock = EpochClock.measure(lambda: 100.0, 0.05, lambda: 1000.0)
    with pytest.raises(HardwareError, match="not publishable"):
        clock.convert("a", np.array([900.0]))
