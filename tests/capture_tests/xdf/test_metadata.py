"""Spec-driven tests for XDF stream metadata XML (xdf-writer.md R-010..R-013).

Phase 2 — stream header/footer XML. All unit tests; no DB.
Assertions derive from the spec text only.

NOTE (black-box): `_stream_header_xml` / `_stream_footer_xml` signatures are
inferred from the spec (channel_format and nominal_srate are *derived* from
the stream name per R-011/R-012, so they are not passed in). Phase D resolves
any signature mismatch in the call sites only.
"""

from capture.xdf.metadata import _stream_footer_xml, _stream_header_xml
from tests.capture_tests.xdf.support import (
    PARTICIPANT_ID,
    SESSION_ID,
    SPONSOR_ID,
)


def _as_str(result):
    return result.decode("utf-8") if isinstance(result, (bytes, bytearray)) else result


class TestStreamHeaderXml:
    """xdf-writer.md — `_stream_header_xml`.

    ASSERTION SOURCE: spec-only
    Model used for assertions: Claude (Fable 5), implementation source withheld.
    """

    def test_r010_user_strings_html_escaped(self):
        xml = _as_str(_stream_header_xml("EEG", SESSION_ID, PARTICIPANT_ID, "<x>&", SPONSOR_ID))
        assert "<x>&" not in xml
        assert "&lt;x&gt;" in xml
        assert "&amp;" in xml

    def test_r011_channel_format_per_stream(self):
        echo_xml = _as_str(
            _stream_header_xml("ECHO", SESSION_ID, PARTICIPANT_ID, "site", SPONSOR_ID)
        )
        eeg_xml = _as_str(_stream_header_xml("EEG", SESSION_ID, PARTICIPANT_ID, "site", SPONSOR_ID))
        assert "string" in echo_xml
        assert "float32" in eeg_xml

    def test_r012_echo_nominal_srate_zero(self):
        echo_xml = _as_str(
            _stream_header_xml("ECHO", SESSION_ID, PARTICIPANT_ID, "site", SPONSOR_ID)
        )
        assert "0.0" in echo_xml


class TestStreamFooterXml:
    """xdf-writer.md — `_stream_footer_xml`.

    ASSERTION SOURCE: spec-only
    Model used for assertions: Claude (Fable 5), implementation source withheld.
    """

    def test_r013_footer_encodes_timestamps_and_count(self):
        footer = _stream_footer_xml(10.0, 20.0, 5)
        assert isinstance(footer, (bytes, bytearray))
        text = footer.decode("utf-8")
        assert "10" in text
        assert "20" in text
        assert "5" in text
