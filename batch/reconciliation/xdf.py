"""Strict XDF 1.0 readers, with explicitly selected legacy recovery."""

import io
import math
import struct
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from batch.reconciliation.models import XDFReadError, XDFTruncatedError

_IDENTITY_FIELDS = ("session_id", "participant_id", "site_id", "sponsor_id")
_STREAM_NAMES = {"EEG", "HRV", "EDA", "Respiration", "ECHO"}
_NUMERIC_FORMATS = {
    "float32": "f",
    "double64": "d",
    "int8": "b",
    "int16": "h",
    "int32": "i",
    "int64": "q",
}
_MAX_CHUNK_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True)
class XDFRecording:
    counts: dict[str, int]
    identity: dict[str, str]
    stream_metadata: dict[str, dict[str, str]]
    format: str


@dataclass
class _ScanState:
    headers: dict[int, dict[str, str]] = field(default_factory=dict)
    counts: dict[int, int] = field(default_factory=dict)
    footers: set[int] = field(default_factory=set)
    previous_ts: dict[int, float] = field(default_factory=dict)
    identity: dict[str, str] = field(default_factory=dict)


def _read_exact(f, count: int) -> bytes:
    if count < 0 or count > _MAX_CHUNK_BYTES:
        raise XDFReadError("invalid or oversized XDF field length")
    data = f.read(count)
    if len(data) != count:
        raise XDFTruncatedError("incomplete XDF chunk or sample")
    return data


def _read_chunk_length(f, *, legacy: bool = False) -> int | None:
    prefix = f.read(1)
    if not prefix:
        return None
    width = prefix[0]
    allowed = (1, 2, 4, 8) if legacy else (1, 4, 8)
    if width not in allowed:
        detail = "; historical custom files require explicit legacy=True" if width == 2 else ""
        raise XDFReadError(f"invalid XDF integer width {width}{detail}")
    return int.from_bytes(_read_exact(f, width), "little")


def _required_length(f, *, legacy: bool) -> int:
    value = _read_chunk_length(f, legacy=legacy)
    if value is None:
        raise XDFTruncatedError("missing XDF variable-length integer")
    return value


def _xml_fields(payload: bytes) -> dict[str, str]:
    try:
        root = ET.fromstring(payload.decode("utf-8"))
    except (ET.ParseError, UnicodeError) as exc:
        raise XDFReadError("invalid XDF metadata XML") from exc
    if root.tag != "info":
        raise XDFReadError("XDF metadata root must be info")
    fields = {}
    for child in root:
        if child.tag in fields:
            raise XDFReadError(f"duplicate XDF metadata field: {child.tag}")
        fields[child.tag] = child.text or ""
    return fields


def _read_header(state: _ScanState, sid: int, payload: bytes, *, legacy: bool) -> None:
    metadata = _xml_fields(payload)
    name = metadata.get("name", "")
    if not name or sid in state.headers or name in {v["name"] for v in state.headers.values()}:
        raise XDFReadError("missing or duplicate XDF stream identity")
    try:
        channels = int(metadata["channel_count"])
        rate = float(metadata["nominal_srate"])
    except (KeyError, ValueError) as exc:
        raise XDFReadError("invalid XDF stream channel count or sample rate") from exc
    if channels <= 0 or not math.isfinite(rate) or rate < 0:
        raise XDFReadError("invalid XDF stream channel count or sample rate")
    if metadata.get("channel_format") not in {*_NUMERIC_FORMATS, "string"}:
        raise XDFReadError("unsupported XDF channel format")
    if legacy and metadata.get("blackrabbit_xdf_format") == "1.0":
        raise XDFReadError("standard XDF recording cannot be decoded as legacy")
    identity = {key: metadata.get(key, "") for key in _IDENTITY_FIELDS}
    if state.headers and identity != state.identity:
        raise XDFReadError("XDF streams disagree on session or tenant identity")
    state.identity = identity
    state.headers[sid] = metadata
    state.counts[sid] = 0


def _samples(state: _ScanState, sid: int, payload: bytes, *, legacy: bool):
    metadata = state.headers[sid]
    stream = io.BytesIO(payload)
    if legacy:
        _read_exact(stream, 8)  # historical custom chunk wall clock
    count = _required_length(stream, legacy=legacy)
    width = int(metadata["channel_count"])
    kind = metadata["channel_format"]
    numeric = _NUMERIC_FORMATS.get(kind)
    for _ in range(count):
        timestamp_width = 8 if legacy else _read_exact(stream, 1)[0]
        if timestamp_width == 8:
            ts = struct.unpack("<d", _read_exact(stream, 8))[0]
        elif timestamp_width == 0:
            rate = float(metadata["nominal_srate"])
            if sid not in state.previous_ts or rate <= 0:
                raise XDFReadError("XDF omitted timestamp cannot be reconstructed")
            ts = state.previous_ts[sid] + 1.0 / rate
        else:
            raise XDFReadError(f"invalid XDF timestamp width {timestamp_width}")
        if not math.isfinite(ts):
            raise XDFReadError("non-finite XDF timestamp")
        if numeric is not None:
            fmt = f"<{width}{numeric}"
            values = list(struct.unpack(fmt, _read_exact(stream, struct.calcsize(fmt))))
            if not all(math.isfinite(value) for value in values):
                raise XDFReadError("non-finite XDF signal value")
        else:
            values = []
            for _channel in range(width):
                length = _required_length(stream, legacy=legacy)
                try:
                    values.append(_read_exact(stream, length).decode("utf-8"))
                except UnicodeError as exc:
                    raise XDFReadError("invalid UTF-8 XDF marker") from exc
        index = state.counts[sid]
        state.counts[sid] += 1
        state.previous_ts[sid] = ts
        yield metadata["name"], index, ts, values
    if stream.read(1):
        raise XDFReadError("trailing bytes in XDF samples chunk")


def _scan(xdf_path: str | Path, state: _ScanState, *, legacy: bool):
    try:
        with Path(xdf_path).open("rb") as f:
            if _read_exact(f, 4) != b"XDF:":
                raise XDFReadError("not an XDF file")
            has_file_header = False
            while (length := _read_chunk_length(f, legacy=legacy)) is not None:
                if length < 2 or length > _MAX_CHUNK_BYTES:
                    raise XDFReadError("invalid or oversized XDF chunk length (maximum 64 MiB)")
                tag = struct.unpack("<H", _read_exact(f, 2))[0]
                payload = _read_exact(f, length - 2)
                if not has_file_header and tag != 1:
                    raise XDFReadError("XDF FileHeader must be first")
                if tag == 1:
                    if has_file_header:
                        raise XDFReadError("duplicate XDF FileHeader")
                    version = _xml_fields(payload).get("version", "")
                    try:
                        valid_version = 1 <= float(version) < 2
                    except ValueError:
                        valid_version = False
                    if not valid_version:
                        raise XDFReadError("unsupported XDF version")
                    has_file_header = True
                elif tag in (2, 3, 6):
                    if len(payload) < 4:
                        raise XDFTruncatedError("missing XDF stream ID")
                    sid = struct.unpack_from("<I", payload)[0]
                    if tag == 2:
                        _read_header(state, sid, payload[4:], legacy=legacy)
                    elif sid not in state.headers:
                        raise XDFReadError("XDF chunk references undeclared stream")
                    elif sid in state.footers:
                        raise XDFReadError("XDF stream has content after its footer")
                    elif tag == 3:
                        yield from _samples(state, sid, payload[4:], legacy=legacy)
                    else:
                        footer = _xml_fields(payload[4:])
                        try:
                            footer_count = int(footer["sample_count"])
                        except (KeyError, ValueError) as exc:
                            raise XDFReadError("invalid XDF footer count") from exc
                        if footer_count != state.counts[sid]:
                            raise XDFReadError("XDF footer count differs from decoded samples")
                        state.footers.add(sid)
            if not has_file_header or not state.headers:
                raise XDFReadError("XDF file has no stream headers")
            if state.footers != state.headers.keys():
                raise XDFTruncatedError("XDF file is missing one or more stream footers")
    except OSError as exc:
        raise XDFReadError(f"cannot read XDF file: {exc}") from exc


def inspect_xdf(xdf_path: str | Path, *, legacy: bool = False) -> XDFRecording:
    """Decode and validate the entire recording without retaining sample arrays."""
    state = _ScanState()
    for _ in _scan(xdf_path, state, legacy=legacy):
        pass
    return XDFRecording(
        counts={header["name"]: state.counts[sid] for sid, header in state.headers.items()},
        identity=dict(state.identity),
        stream_metadata={header["name"]: dict(header) for header in state.headers.values()},
        format="blackrabbit-legacy" if legacy else "xdf-1.0",
    )


def validate_xdf_identity(
    xdf_path: str | Path,
    session_id: str,
    sponsor_id: str,
    participant_id: str | None = None,
    site_id: str | None = None,
    *,
    legacy: bool = False,
) -> dict[str, int]:
    """Validate a complete blackRabbit capture and its expected canonical identity."""
    recording = inspect_xdf(xdf_path, legacy=legacy)
    if set(recording.counts) != _STREAM_NAMES:
        raise XDFReadError("blackRabbit XDF must declare all five capture streams")
    for name, metadata in recording.stream_metadata.items():
        expected_format = "string" if name == "ECHO" else "float32"
        if metadata["channel_format"] != expected_format:
            raise XDFReadError(f"invalid channel format for blackRabbit {name} stream")
        if name != "EEG" and int(metadata["channel_count"]) != 1:
            raise XDFReadError(f"blackRabbit {name} stream must have one channel")
    if not all(recording.identity.values()):
        raise XDFReadError("XDF is missing session or tenant identity")
    expected = dict(
        session_id=session_id, sponsor_id=sponsor_id, participant_id=participant_id, site_id=site_id
    )
    for key, value in expected.items():
        if value is not None and recording.identity[key] != str(value):
            raise XDFReadError(f"XDF {key} does not match the requested session")
    return recording.counts


def read_xdf_counts(xdf_path: str | Path, *, legacy: bool = False) -> dict[str, int]:
    return inspect_xdf(xdf_path, legacy=legacy).counts


def stream_xdf_samples(
    xdf_path: str | Path,
    target_stream_name: str,
    *,
    legacy: bool = False,
) -> Iterator[tuple[int, float, list[float]]]:
    for name, index, timestamp, values in _scan(xdf_path, _ScanState(), legacy=legacy):
        if name == target_stream_name and name != "ECHO":
            yield index, timestamp, values


def stream_xdf_markers(
    xdf_path: str | Path,
    *,
    legacy: bool = False,
) -> Iterator[tuple[int, float, str]]:
    for name, index, timestamp, values in _scan(xdf_path, _ScanState(), legacy=legacy):
        if name == "ECHO":
            if len(values) != 1 or not isinstance(values[0], str):
                raise XDFReadError("ECHO must be one string channel")
            yield index, timestamp, values[0]
