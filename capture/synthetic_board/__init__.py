"""Synthetic board package and compatibility exports."""

from capture.synthetic_board.cli import main
from capture.synthetic_board.cli import parse_args as _parse_args
from capture.synthetic_board.models import SampleFactory, StreamSpec
from capture.synthetic_board.outlets import (
    build_stream_specs as _build_stream_specs,
)
from capture.synthetic_board.outlets import (
    create_outlets as _create_outlets,
)
from capture.synthetic_board.outlets import (
    make_outlet as _make_outlet,
)
from capture.synthetic_board.outlets import (
    validate_rate as _validate_rate,
)
from capture.synthetic_board.outlets import (
    validate_specs as _validate_specs,
)
from capture.synthetic_board.runtime import (
    build_threads as _build_threads,
)
from capture.synthetic_board.runtime import (
    handle_stop as _handle_stop,
)
from capture.synthetic_board.runtime import (
    run_until_stopped as _run_until_stopped,
)
from capture.synthetic_board.runtime import (
    stop_event as _stop,
)
from capture.synthetic_board.runtime import (
    stream_loop as _stream_loop,
)
from capture.synthetic_board.samples import (
    eda_sample as _eda_sample,
)
from capture.synthetic_board.samples import (
    eeg_sample as _eeg_sample,
)
from capture.synthetic_board.samples import (
    hrv_sample as _hrv_sample,
)
from capture.synthetic_board.samples import (
    respiration_sample as _respiration_sample,
)

__all__ = [
    "SampleFactory",
    "StreamSpec",
    "_build_stream_specs",
    "_build_threads",
    "_create_outlets",
    "_eda_sample",
    "_eeg_sample",
    "_handle_stop",
    "_hrv_sample",
    "_make_outlet",
    "_parse_args",
    "_respiration_sample",
    "_run_until_stopped",
    "_stop",
    "_stream_loop",
    "_validate_rate",
    "_validate_specs",
    "main",
]
