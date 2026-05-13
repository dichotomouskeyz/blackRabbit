"""XDF readers used by session reconciliation and backfill."""

import struct
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from pathlib import Path

from batch.reconciliation.models import (
    _ECHO_STREAM_NAME,
    _TAG_SAMPLES,
    _TAG_STREAM_FOOTER,
    _TAG_STREAM_HEADER,
    _XDF_MAGIC,
    XDFReadError,
    XDFTruncatedError,
)


def _read_chunk_length(f) -> int | None:
    """Read XDF variable-length integer from open file. Returns None at EOF."""
    nb = f.read(1)
    if not nb:
        return None
    num_bytes = nb[0]
    if num_bytes not in (1, 2, 4, 8):
        raise XDFReadError(
            f"invalid NumLengthBytes={num_bytes} at offset {f.tell() - 1}"
        )
    raw = f.read(num_bytes)
    if len(raw) < num_bytes:
        return None
    fmt = {1: "<B", 2: "<H", 4: "<I", 8: "<Q"}[num_bytes]
    return struct.unpack(fmt, raw)[0]


def read_xdf_counts(xdf_path: Path) -> dict[str, int]:
    """Return {stream_name: sample_count} by parsing StreamFooter chunks."""
    if not xdf_path.exists():
        raise XDFReadError(f"XDF file not found: {xdf_path}")

    id_to_name: dict[int, str] = {}
    counts: dict[str, int] = {}
    has_footers = False

    try:
        with open(xdf_path, "rb") as f:
            magic = f.read(4)
            if magic != _XDF_MAGIC:
                raise XDFReadError(
                    f"not an XDF file - magic={magic!r}, path={xdf_path}"
                )

            while True:
                length = _read_chunk_length(f)
                if length is None:
                    break

                tag_raw = f.read(2)
                if len(tag_raw) < 2:
                    break
                tag = struct.unpack("<H", tag_raw)[0]
                payload_length = length - 2

                if tag == _TAG_STREAM_HEADER and payload_length >= 4:
                    payload = f.read(payload_length)
                    sid = struct.unpack_from("<I", payload, 0)[0]
                    xml_str = payload[4:].decode("utf-8", errors="replace")
                    try:
                        root = ET.fromstring(xml_str)
                        name_el = root.find("name")
                        if name_el is not None and name_el.text:
                            id_to_name[sid] = name_el.text
                    except ET.ParseError:
                        pass

                elif tag == _TAG_STREAM_FOOTER and payload_length >= 4:
                    has_footers = True
                    payload = f.read(payload_length)
                    sid = struct.unpack_from("<I", payload, 0)[0]
                    xml_str = payload[4:].decode("utf-8", errors="replace")
                    try:
                        root = ET.fromstring(xml_str)
                        count_el = root.find("sample_count")
                        if count_el is not None and count_el.text:
                            stream_name = id_to_name.get(sid, f"stream_{sid}")
                            counts[stream_name] = int(count_el.text)
                    except (ET.ParseError, ValueError):
                        pass

                else:
                    f.seek(payload_length, 1)

    except OSError as exc:
        raise XDFReadError(f"cannot read XDF file: {exc}") from exc

    if not has_footers:
        raise XDFTruncatedError(
            f"XDF file has no stream footers - forwarder was stopped before close(): {xdf_path}"
        )

    return counts


def _skip_echo_marker_samples(f, num_samples: int) -> bool:
    for _ in range(num_samples):
        if len(f.read(8)) < 8:
            return False
        marker_len = _read_chunk_length(f)
        if marker_len is None:
            return False
        f.seek(marker_len, 1)
    return True


def stream_xdf_samples(
    xdf_path: Path,
    target_stream_name: str,
) -> Iterator[tuple[int, float, list[float]]]:
    """Yield (sample_index, lsl_timestamp, channel_values) for one stream."""
    id_to_name: dict[int, str] = {}
    id_to_channels: dict[int, int] = {}
    stream_positions: dict[int, int] = {}

    with open(xdf_path, "rb") as f:
        magic = f.read(4)
        if magic != _XDF_MAGIC:
            raise XDFReadError(f"not an XDF file: {xdf_path}")

        while True:
            length = _read_chunk_length(f)
            if length is None:
                break

            tag_raw = f.read(2)
            if len(tag_raw) < 2:
                break
            tag = struct.unpack("<H", tag_raw)[0]
            payload_remaining = length - 2

            if tag == _TAG_STREAM_HEADER and payload_remaining >= 4:
                sid = struct.unpack("<I", f.read(4))[0]
                xml_bytes = f.read(payload_remaining - 4)
                try:
                    root = ET.fromstring(xml_bytes.decode("utf-8", errors="replace"))
                    name_el = root.find("name")
                    ch_el = root.find("channel_count")
                    if name_el is not None and name_el.text:
                        id_to_name[sid] = name_el.text
                    if ch_el is not None and ch_el.text:
                        id_to_channels[sid] = int(ch_el.text)
                except (ET.ParseError, ValueError):
                    pass

            elif tag == _TAG_SAMPLES and payload_remaining >= 13:
                sid = struct.unpack("<I", f.read(4))[0]
                f.read(8)
                num_samples = _read_chunk_length(f)
                if num_samples is None:
                    break

                stream_name = id_to_name.get(sid, f"stream_{sid}")
                n_channels = id_to_channels.get(sid, 0)
                start_idx = stream_positions.get(sid, 0)

                if stream_name == _ECHO_STREAM_NAME:
                    if not _skip_echo_marker_samples(f, num_samples):
                        return
                elif stream_name == target_stream_name and n_channels > 0:
                    for i in range(num_samples):
                        ts_raw = f.read(8)
                        if len(ts_raw) < 8:
                            return
                        ts = struct.unpack("<d", ts_raw)[0]
                        vraw = f.read(n_channels * 4)
                        if len(vraw) < n_channels * 4:
                            return
                        vals = list(struct.unpack(f"<{n_channels}f", vraw))
                        yield (start_idx + i, ts, vals)
                elif n_channels > 0:
                    f.seek(num_samples * (8 + n_channels * 4), 1)
                else:
                    break

                stream_positions[sid] = start_idx + num_samples

            else:
                f.seek(payload_remaining, 1)


def stream_xdf_markers(xdf_path: Path) -> Iterator[tuple[int, float, str]]:
    """Yield (marker_index, lsl_timestamp, marker_text) for ECHO markers."""
    id_to_name: dict[int, str] = {}
    stream_positions: dict[int, int] = {}

    with open(xdf_path, "rb") as f:
        magic = f.read(4)
        if magic != _XDF_MAGIC:
            raise XDFReadError(f"not an XDF file: {xdf_path}")

        while True:
            length = _read_chunk_length(f)
            if length is None:
                break

            tag_raw = f.read(2)
            if len(tag_raw) < 2:
                break
            tag = struct.unpack("<H", tag_raw)[0]
            payload_remaining = length - 2

            if tag == _TAG_STREAM_HEADER and payload_remaining >= 4:
                sid = struct.unpack("<I", f.read(4))[0]
                xml_bytes = f.read(payload_remaining - 4)
                try:
                    root = ET.fromstring(xml_bytes.decode("utf-8", errors="replace"))
                    name_el = root.find("name")
                    if name_el is not None and name_el.text:
                        id_to_name[sid] = name_el.text
                except ET.ParseError:
                    pass

            elif tag == _TAG_SAMPLES and payload_remaining >= 13:
                payload_end = f.tell() + payload_remaining
                sid = struct.unpack("<I", f.read(4))[0]
                f.read(8)
                num_samples = _read_chunk_length(f)
                if num_samples is None:
                    break

                stream_name = id_to_name.get(sid, f"stream_{sid}")
                start_idx = stream_positions.get(sid, 0)

                if stream_name == _ECHO_STREAM_NAME:
                    for i in range(num_samples):
                        ts_raw = f.read(8)
                        if len(ts_raw) < 8:
                            return
                        ts = struct.unpack("<d", ts_raw)[0]
                        marker_len = _read_chunk_length(f)
                        if marker_len is None:
                            return
                        marker_raw = f.read(marker_len)
                        if len(marker_raw) < marker_len:
                            return
                        yield (
                            start_idx + i,
                            ts,
                            marker_raw.decode("utf-8", errors="replace"),
                        )
                else:
                    f.seek(payload_end)

                stream_positions[sid] = start_idx + num_samples

            else:
                f.seek(payload_remaining, 1)
