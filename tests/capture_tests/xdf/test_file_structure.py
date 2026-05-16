"""XDF file-level structure tests: magic, headers, footers."""

import struct

from capture.xdf import _STREAM_IDS, _TAG_FILE_HEADER, _TAG_STREAM_FOOTER, _TAG_STREAM_HEADER
from tests.capture_tests.xdf.support import SESSION_ID, SITE_ID, SPONSOR_ID, _iter_chunks


class TestFileStructure:
    def test_starts_with_magic(self, writer):
        from capture.xdf import _XDF_MAGIC

        writer.close()
        raw = writer.path.read_bytes()
        assert raw[:4] == _XDF_MAGIC

    def test_has_file_header_chunk(self, writer):
        writer.close()
        raw = writer.path.read_bytes()
        tags = [tag for tag, _ in _iter_chunks(raw)]
        assert _TAG_FILE_HEADER in tags

    def test_has_five_stream_headers(self, writer):
        writer.close()
        raw = writer.path.read_bytes()
        count = sum(1 for t, _ in _iter_chunks(raw) if t == _TAG_STREAM_HEADER)
        assert count == 5

    def test_stream_header_ids_are_correct(self, writer):
        writer.close()
        raw = writer.path.read_bytes()
        found_ids = set()
        for tag, payload in _iter_chunks(raw):
            if tag == _TAG_STREAM_HEADER:
                stream_id = struct.unpack_from("<I", payload, 0)[0]
                found_ids.add(stream_id)
        assert found_ids == set(_STREAM_IDS.values())

    def test_stream_header_xml_contains_session_id(self, writer):
        writer.close()
        raw = writer.path.read_bytes()
        for tag, payload in _iter_chunks(raw):
            if tag == _TAG_STREAM_HEADER:
                xml = payload[4:].decode("utf-8")
                assert SESSION_ID in xml

    def test_stream_header_xml_contains_site_and_sponsor(self, writer):
        writer.close()
        raw = writer.path.read_bytes()
        for tag, payload in _iter_chunks(raw):
            if tag == _TAG_STREAM_HEADER:
                xml = payload[4:].decode("utf-8")
                assert SITE_ID in xml
                assert SPONSOR_ID in xml

    def test_has_five_stream_footers_on_close(self, writer):
        writer.close()
        raw = writer.path.read_bytes()
        footer_count = sum(1 for t, _ in _iter_chunks(raw) if t == _TAG_STREAM_FOOTER)
        assert footer_count == 5

    def test_file_grows_after_write_samples(self, writer):
        size_before = writer.path.stat().st_size
        writer.write_samples("EEG", [[1.0] * 8, [2.0] * 8], [100.0, 100.004])
        size_after = writer.path.stat().st_size
        assert size_after > size_before
