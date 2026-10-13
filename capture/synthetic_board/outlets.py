"""Stream specification and LSL outlet construction."""

import argparse
from typing import Any

from capture.synthetic_board.models import StreamSpec
from capture.synthetic_board.samples import (
    eda_sample,
    eeg_sample,
    hrv_sample,
    respiration_sample,
)
from config import settings


def validate_rate(name: str, rate_hz: float) -> None:
    if rate_hz <= 0:
        raise ValueError(f"{name} must be positive, got {rate_hz!r}")


def make_outlet(pylsl, spec: StreamSpec):
    info = pylsl.StreamInfo(
        name=spec.name,
        type=spec.stream_type,
        channel_count=spec.channel_count,
        nominal_srate=spec.rate_hz,
        channel_format=pylsl.cf_float32,
        source_id=spec.source_id,
    )
    return pylsl.StreamOutlet(info)


def build_stream_specs(args: argparse.Namespace) -> list[StreamSpec]:
    return [
        StreamSpec(
            name=settings.LSL_STREAM_EEG,
            stream_type="EEG",
            channel_count=settings.EEG_CHANNEL_COUNT,
            rate_hz=args.eeg_rate,
            source_id="untitledplatform_1a_synthetic_eeg",
            sample_factory=eeg_sample,
            factory_args=(settings.EEG_CHANNEL_COUNT, args.eeg_rate),
        ),
        StreamSpec(
            name=settings.LSL_STREAM_HRV,
            stream_type="HRV",
            channel_count=1,
            rate_hz=args.hrv_rate,
            source_id="untitledplatform_1a_synthetic_hrv",
            sample_factory=hrv_sample,
            factory_args=(args.hrv_rate,),
        ),
        StreamSpec(
            name=settings.LSL_STREAM_EDA,
            stream_type="EDA",
            channel_count=1,
            rate_hz=args.eda_rate,
            source_id="untitledplatform_1a_synthetic_eda",
            sample_factory=eda_sample,
            factory_args=(args.eda_rate,),
        ),
        StreamSpec(
            name=settings.LSL_STREAM_RESPIRATION,
            stream_type="Respiration",
            channel_count=1,
            rate_hz=args.respiration_rate,
            source_id="untitledplatform_1a_synthetic_respiration",
            sample_factory=respiration_sample,
            factory_args=(args.respiration_rate,),
        ),
    ]


def validate_specs(specs: list[StreamSpec]) -> None:
    for spec in specs:
        validate_rate(spec.stream_type, spec.rate_hz)


def create_outlets(pylsl, specs: list[StreamSpec]) -> dict[str, Any]:
    return {spec.stream_type: make_outlet(pylsl, spec) for spec in specs}
