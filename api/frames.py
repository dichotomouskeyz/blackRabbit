"""Pure WS frame builders (INV-010).

`build_sample_frame` maps `lsl_timestamp` (never `db_insert_time` or a server
clock) into the frame time axis `t` (TB-005 / PAT-004). Pure and side-effect
free so it is testable now, before the live tap exists.
"""


def build_sample_frame(rows: list[dict]) -> dict:
    """Build a samples WS frame from biosignal rows.

    The time axis `t` is always the per-row `lsl_timestamp` (INV-010). Values
    come from each row's `value`. Modality/channel are carried from the first
    row when present (a frame is per-modality/channel by contract).
    """
    first = rows[0] if rows else {}
    return {
        "type": "samples",
        "modality": first.get("modality"),
        "channel": first.get("channel"),
        "t": [row.get("lsl_timestamp") for row in rows],
        "v": [row.get("value") for row in rows],
    }
