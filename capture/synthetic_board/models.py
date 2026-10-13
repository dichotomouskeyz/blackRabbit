"""Synthetic stream models."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

SampleFactory = Callable[..., list[float]]


@dataclass(frozen=True)
class StreamSpec:
    name: str
    stream_type: str
    channel_count: int
    rate_hz: float
    source_id: str
    sample_factory: SampleFactory
    factory_args: tuple[Any, ...] = ()
