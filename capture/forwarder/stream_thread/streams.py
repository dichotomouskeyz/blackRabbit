"""Forwarder stream thread construction."""

import threading

from capture.echo_handler import ECHOThread
from capture.forwarder.models import SessionConfig
from capture.forwarder.rows import (
    build_eda_rows,
    build_eeg_rows,
    build_hrv_rows,
    build_respiration_rows,
)
from capture.forwarder.sql import EDA_INSERT, EEG_INSERT, HRV_INSERT, RESPIRATION_INSERT
from capture.forwarder.stream_thread.stream_thread import StreamThread
from capture.xdf.writer import XDFWriter
from config import settings


def build_stream_threads(
    cfg: SessionConfig,
    stop: threading.Event,
    xdf: XDFWriter,
) -> list[threading.Thread]:
    threads: list[threading.Thread] = [
        StreamThread(
            stream_name=settings.LSL_STREAM_EEG,
            stream_type="EEG",
            chunk_size=settings.LSL_CHUNK_EEG,
            row_builder=build_eeg_rows,
            insert_sql=EEG_INSERT,
            cfg=cfg,
            stop_event=stop,
            xdf_writer=xdf,
            table_name="eeg_samples",
            hash_fields=("sample_index", "channel_id", "voltage"),
            hash_sort_keys=("sample_index", "channel_id"),
        ),
        StreamThread(
            stream_name=settings.LSL_STREAM_HRV,
            stream_type="HRV",
            chunk_size=settings.LSL_CHUNK_HRV,
            row_builder=build_hrv_rows,
            insert_sql=HRV_INSERT,
            cfg=cfg,
            stop_event=stop,
            xdf_writer=xdf,
            table_name="hrv_samples",
            hash_fields=("sample_index", "rr_interval_ms"),
            hash_sort_keys=("sample_index",),
        ),
        StreamThread(
            stream_name=settings.LSL_STREAM_EDA,
            stream_type="EDA",
            chunk_size=settings.LSL_CHUNK_EDA,
            row_builder=build_eda_rows,
            insert_sql=EDA_INSERT,
            cfg=cfg,
            stop_event=stop,
            xdf_writer=xdf,
            table_name="eda_samples",
            hash_fields=("sample_index", "raw_conductance_us"),
            hash_sort_keys=("sample_index",),
        ),
        StreamThread(
            stream_name=settings.LSL_STREAM_RESPIRATION,
            stream_type="Respiration",
            chunk_size=settings.LSL_CHUNK_RESPIRATION,
            row_builder=build_respiration_rows,
            insert_sql=RESPIRATION_INSERT,
            cfg=cfg,
            stop_event=stop,
            xdf_writer=xdf,
            table_name="respiration_samples",
            hash_fields=("sample_index", "raw_amplitude"),
            hash_sort_keys=("sample_index",),
        ),
    ]
    threads.append(_build_echo_thread(cfg, stop, xdf))
    return threads


_build_stream_threads = build_stream_threads


def _build_echo_thread(
    cfg: SessionConfig,
    stop: threading.Event,
    xdf: XDFWriter,
) -> ECHOThread:
    """Build the ECHO marker stream thread for lsl_forwarder."""
    return ECHOThread(cfg=cfg, stop_event=stop, xdf_writer=xdf)
