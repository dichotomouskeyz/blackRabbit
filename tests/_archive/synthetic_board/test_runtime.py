"""Tests for synthetic board runtime stop-state hygiene."""

from capture.synthetic_board.runtime import clear_stop_event, stop_event


def test_clear_stop_event_resets_module_flag():
    stop_event.set()

    clear_stop_event()

    assert not stop_event.is_set()
