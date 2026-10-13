"""ECHO sample and row conversion helpers."""

from typing import Any


def raw_marker_from_sample(sample: Any) -> str | None:
    if sample is None:
        return None
    raw = sample[0] if isinstance(sample, list) else sample
    return raw if isinstance(raw, str) else None


def build_echo_row(cfg: Any, parsed: dict[str, str], lsl_ts: float) -> dict[str, Any]:
    return {
        "session_id": cfg.session_id,
        "participant_id": cfg.participant_id,
        "site_id": cfg.site_id,
        "sponsor_id": cfg.sponsor_id,
        "lsl_timestamp": lsl_ts,
        **parsed,
    }
