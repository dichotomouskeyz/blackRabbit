"""Forwarder stream thread construction."""

import threading

from capture.echo_handler import ECHOThread
from capture.forwarder.models import SessionConfig
from capture.forwarder.rows import (
    _build_eda_rows,
    _build_eeg_rows,
    _build_hrv_rows,
    _build_respiration_rows,
)
from capture.forwarder.sql import _EDA_INSERT, _EEG_INSERT, _HRV_INSERT, _RESPIRATION_INSERT
from capture.forwarder.stream_thread.stream_thread import _StreamThread
from capture.xdf import XDFWriter
from config import settings


def _build_stream_threads(
    cfg: SessionConfig,
    stop: threading.Event,
    xdf: XDFWriter,
) -> list[threading.Thread]:
    threads: list[threading.Thread] = [
        _StreamThread(
            stream_name=settings.LSL_STREAM_EEG,
            stream_type="EEG",
            chunk_size=settings.LSL_CHUNK_EEG,
            row_builder=_build_eeg_rows,
            insert_sql=_EEG_INSERT,
            cfg=cfg,
            stop_event=stop,
            xdf_writer=xdf,
            table_name="eeg_samples",
            hash_fields=("sample_index", "channel_id", "voltage"),
            hash_sort_keys=("sample_index", "channel_id"),
        ),
        _StreamThread(
            stream_name=settings.LSL_STREAM_HRV,
            stream_type="HRV",
            chunk_size=settings.LSL_CHUNK_HRV,
            row_builder=_build_hrv_rows,
            insert_sql=_HRV_INSERT,
            cfg=cfg,
            stop_event=stop,
            xdf_writer=xdf,
            table_name="hrv_samples",
            hash_fields=("sample_index", "rr_interval_ms"),
            hash_sort_keys=("sample_index",),
        ),
        _StreamThread(
            stream_name=settings.LSL_STREAM_EDA,
            stream_type="EDA",
            chunk_size=settings.LSL_CHUNK_EDA,
            row_builder=_build_eda_rows,
            insert_sql=_EDA_INSERT,
            cfg=cfg,
            stop_event=stop,
            xdf_writer=xdf,
            table_name="eda_samples",
            hash_fields=("sample_index", "raw_conductance_us"),
            hash_sort_keys=("sample_index",),
        ),
        _StreamThread(
            stream_name=settings.LSL_STREAM_RESPIRATION,
            stream_type="Respiration",
            chunk_size=settings.LSL_CHUNK_RESPIRATION,
            row_builder=_build_respiration_rows,
            insert_sql=_RESPIRATION_INSERT,
            cfg=cfg,
            stop_event=stop,
            xdf_writer=xdf,
            table_name="respiration_samples",
            hash_fields=("sample_index", "raw_amplitude"),
            hash_sort_keys=("sample_index",),
        ),
    ]
    threads.append(ECHOThread(cfg=cfg, stop_event=stop, xdf_writer=xdf))
    return threads
