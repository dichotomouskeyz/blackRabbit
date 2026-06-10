"""Smoke tests for the two unspecced entry-point files (capture-control.md note).

`capture/lsl_forwarder.py` is a 4-line entry shim fully covered by the
forwarder spec; `capture/metadata.py` is an empty stub. Neither has its own
spec, so these tests only confirm the import contract.

ASSERTION SOURCE: spec-only (capture-control.md line 14)
Model used for assertions: Claude (Fable 5), implementation source withheld.
"""

import importlib


def test_lsl_forwarder_reexports_cli_main():
    shim = importlib.import_module("capture.lsl_forwarder")
    cli = importlib.import_module("capture.forwarder.cli")
    assert shim.main is cli.main


def test_metadata_stub_imports_cleanly():
    module = importlib.import_module("capture.metadata")
    assert module is not None
