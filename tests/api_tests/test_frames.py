"""INV-010 [unit] — WS frames use lsl_timestamp as the time axis.

build_sample_frame(rows) maps lsl_timestamp (never db_insert_time or a server
clock) into the frame `t`.
"""

from api.frames import build_sample_frame


def test_build_sample_frame_uses_lsl_timestamp():
    # Tests INV-010 [unit]: t == [lsl_timestamp], never db_insert_time.
    rows = [
        {
            "lsl_timestamp": 100.0,
            "db_insert_time": 999999.0,  # distinct, must NOT appear
            "value": 1.5,
            "modality": "eeg",
            "channel": "ch_0",
        }
    ]
    frame = build_sample_frame(rows)
    assert frame["t"] == [100.0], f"t must be the lsl_timestamp axis, got {frame['t']!r}"
    assert 999999.0 not in frame["t"], "db_insert_time must never appear in the time axis"


def test_build_sample_frame_preserves_lsl_order_for_multiple_rows():
    # Tests INV-010 [unit]: multiple rows keep lsl_timestamp order, no db_insert_time.
    rows = [
        {"lsl_timestamp": 10.0, "db_insert_time": 500.0, "value": 1.0},
        {"lsl_timestamp": 11.0, "db_insert_time": 501.0, "value": 2.0},
        {"lsl_timestamp": 12.0, "db_insert_time": 502.0, "value": 3.0},
    ]
    frame = build_sample_frame(rows)
    assert frame["t"] == [10.0, 11.0, 12.0]
    db_times = {500.0, 501.0, 502.0}
    assert not (set(frame["t"]) & db_times), "no db_insert_time value may leak into t"
