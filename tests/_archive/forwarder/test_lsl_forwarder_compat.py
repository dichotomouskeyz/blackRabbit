"""Compatibility tests for the capture.lsl_forwarder entry point."""

import capture.lsl_forwarder as lsl_forwarder
from capture.forwarder.cli import main


class TestLSLForwarderCompatibility:
    def test_lsl_forwarder_is_thin_entrypoint(self):
        assert lsl_forwarder.main is main
        assert not hasattr(lsl_forwarder, "_build_stream_threads")
