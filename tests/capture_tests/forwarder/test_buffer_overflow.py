"""Spec-driven test for forwarder buffer overflow (forwarder.md R-017).

Phase 2 — bounded chunk buffer. Unit test; no DB.
Assertions derive from the spec text only.

NOTE (black-box): `buffer_chunk` location/signature is inferred from the
spec. Phase D resolves any import/signature mismatch only.
"""

from collections import deque
from types import SimpleNamespace

from capture.forwarder.models import BUFFER_MAX_CHUNKS
from capture.forwarder.stream_thread.stream_chunks import buffer_chunk


class TestBufferOverflow:
    """forwarder.md — buffer overflow.

    ASSERTION SOURCE: spec-only
    Model used for assertions: Claude (Fable 5), implementation source withheld.
    """

    def test_r017_oldest_chunk_dropped_at_capacity(self):
        thread = SimpleNamespace(
            _buffer=deque(maxlen=BUFFER_MAX_CHUNKS),
            _stream_type="EEG",
            _chunk_count=1,
        )
        # Fill to capacity with identifiable chunks.
        for i in range(BUFFER_MAX_CHUNKS):
            thread._buffer.append([("chunk", i)])
        oldest = thread._buffer[0]

        buffer_chunk(thread, [("chunk", "new")])

        assert len(thread._buffer) == BUFFER_MAX_CHUNKS
        assert thread._buffer[0] is not oldest
        assert thread._buffer[-1] == [("chunk", "new")]
