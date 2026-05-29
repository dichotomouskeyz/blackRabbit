"""XDF file-level structure tests: magic, headers, footers."""

import struct
import xml.etree.ElementTree as ET

from capture.xdf.constants import (
    STREAM_IDS,
    TAG_FILE_HEADER,
    TAG_STREAM_FOOTER,
    TAG_STREAM_HEADER,
)
from capture.xdf.metadata import _stream_header_xml
from tests.capture_tests.xdf.support import (
    PARTICIPANT_ID,
    SESSION_ID,
    SITE_ID,
    SPONSOR_ID,
    iter_chunks,
)


class TestFileStructure:
    def test_starts_with_magic(self, writer):
        from capture.xdf.constants import XDF_MAGIC

        writer.close()
        raw = writer.path.read_bytes()
        assert raw[:4] == XDF_MAGIC

    def test_has_file_header_chunk(self, writer):
        writer.close()
        raw = writer.path.read_bytes()
        tags = [tag for tag, _ in iter_chunks(raw)]
        assert TAG_FILE_HEADER in tags

    def test_has_five_stream_headers(self, writer):
        writer.close()
        raw = writer.path.read_bytes()
        count = sum(1 for t, _ in iter_chunks(raw) if t == TAG_STREAM_HEADER)
        assert count == 5

    def test_stream_header_ids_are_correct(self, writer):
        writer.close()
        raw = writer.path.read_bytes()
        found_ids = set()
        for tag, payload in iter_chunks(raw):
            if tag == TAG_STREAM_HEADER:
                stream_id = struct.unpack_from("<I", payload, 0)[0]
                found_ids.add(stream_id)
        assert found_ids == set(STREAM_IDS.values())

    def test_stream_header_xml_contains_session_id(self, writer):
        writer.close()
        raw = writer.path.read_bytes()
        for tag, payload in iter_chunks(raw):
            if tag == TAG_STREAM_HEADER:
                xml = payload[4:].decode("utf-8")
                assert SESSION_ID in xml

    def test_stream_header_xml_contains_participant_id(self, writer):
        writer.close()
        raw = writer.path.read_bytes()
        for tag, payload in iter_chunks(raw):
            if tag == TAG_STREAM_HEADER:
                xml = payload[4:].decode("utf-8")
                assert PARTICIPANT_ID in xml

    def test_stream_header_xml_contains_site_and_sponsor(self, writer):
        writer.close()
        raw = writer.path.read_bytes()
        for tag, payload in iter_chunks(raw):
            if tag == TAG_STREAM_HEADER:
                xml = payload[4:].decode("utf-8")
                assert SITE_ID in xml
                assert SPONSOR_ID in xml

    def test_has_five_stream_footers_on_close(self, writer):
        writer.close()
        raw = writer.path.read_bytes()
        footer_count = sum(1 for t, _ in iter_chunks(raw) if t == TAG_STREAM_FOOTER)
        assert footer_count == 5

    def test_file_grows_after_write_samples(self, writer):
        size_before = writer.path.stat().st_size
        writer.write_samples("EEG", [[1.0] * 8, [2.0] * 8], [100.0, 100.004])
        size_after = writer.path.stat().st_size
        assert size_after > size_before

    def test_stream_header_xml_escapes_identity_fields(self):
        xml = _stream_header_xml(
            "EEG",
            'session<&">x</session_id><evil/>',
            'participant<&">x',
            'site<&">x',
            'sponsor<&">x',
        )

        root = ET.fromstring(xml)

        assert root.findtext("session_id") == 'session<&">x</session_id><evil/>'
        assert root.find("evil") is None
        assert "</session_id><evil/>" not in xml
