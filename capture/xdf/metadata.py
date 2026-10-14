import json
from datetime import datetime, timezone
from html import escape

from .constants import _CHANNEL_COUNTS, _SAMPLE_RATES


def _stream_header_xml(
    stream_name: str,
    session_id: str,
    participant_id: str,
    site_id: str,
    sponsor_id: str,
    *,
    eeg_channel_names: tuple[str, ...] | None = None,
    device_id: str | None = None,
) -> str:
    n_ch = _CHANNEL_COUNTS[stream_name]
    rate = _SAMPLE_RATES[stream_name]
    fmt = "string" if stream_name == "ECHO" else "float32"
    stream_type = "Markers" if stream_name == "ECHO" else stream_name
    source_id = f"untitledplatform_1a-{stream_name.lower()}"
    created_at = datetime.now(timezone.utc).isoformat()
    channel_metadata = (
        f"<eeg_channel_names>{escape(json.dumps(list(eeg_channel_names)))}</eeg_channel_names>"
        if stream_name == "EEG" and eeg_channel_names is not None
        else ""
    )
    device_metadata = f"<device_id>{escape(device_id)}</device_id>" if device_id else ""
    return (
        '<?xml version="1.0"?><info>'
        f"<name>{escape(stream_name)}</name>"
        f"<type>{escape(stream_type)}</type>"
        f"<channel_count>{n_ch}</channel_count>"
        f"<nominal_srate>{rate}</nominal_srate>"
        f"<channel_format>{fmt}</channel_format>"
        f"<source_id>{escape(source_id)}</source_id>"
        f"<session_id>{escape(session_id)}</session_id>"
        f"<participant_id>{escape(participant_id)}</participant_id>"
        f"<site_id>{escape(site_id)}</site_id>"
        f"<sponsor_id>{escape(sponsor_id)}</sponsor_id>"
        f"<created_at>{escape(created_at)}</created_at>"
        "<blackrabbit_xdf_format>1.0</blackrabbit_xdf_format>"
        f"{channel_metadata}{device_metadata}"
        "</info>"
    )


def _stream_footer_xml(first_ts: float, last_ts: float, sample_count: int) -> bytes:
    return (
        '<?xml version="1.0"?><info>'
        f"<first_timestamp>{first_ts}</first_timestamp>"
        f"<last_timestamp>{last_ts}</last_timestamp>"
        f"<sample_count>{sample_count}</sample_count>"
        "</info>"
    ).encode("utf-8")
