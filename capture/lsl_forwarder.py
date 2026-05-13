"""LSL stream forwarder CLI and compatibility exports.

Implementation lives under capture/forwarder/:
  - models.py: SessionConfig and shared constants
  - rows.py: per-modality row builders
  - sql.py: INSERT statements
  - stream_thread.py: per-modality LSL thread
  - preflight.py: session readiness checks

Keep imports from capture.lsl_forwarder stable for tests and existing scripts.
"""

import argparse
import signal
import threading
import time
import uuid

from capture.control import clear_stop_request, stop_requested
from capture.echo_handler import ECHOThread
from capture.forwarder.models import (
    BUFFER_MAX_CHUNKS,
    DRIFT_WARN_THRESHOLD_S,
    PAYLOAD_SCHEMA_VERSION,
    SessionConfig,
)
from capture.forwarder.preflight import _verify_session_ready
from capture.forwarder.rows import (
    _build_eda_rows,
    _build_eeg_rows,
    _build_hrv_rows,
    _build_respiration_rows,
)
from capture.forwarder.sql import (
    _CLOCK_DRIFT_INSERT,
    _EDA_INSERT,
    _EEG_INSERT,
    _HRV_INSERT,
    _RESPIRATION_INSERT,
)
from capture.forwarder.stream_thread import _StreamThread
from capture.logger import get_logger, set_session_id
from capture.xdf_writer import XDFWriter
from config import settings

settings.validate()

log = get_logger("lsl_forwarder")

__all__ = [
    "BUFFER_MAX_CHUNKS",
    "DRIFT_WARN_THRESHOLD_S",
    "PAYLOAD_SCHEMA_VERSION",
    "SessionConfig",
    "_CLOCK_DRIFT_INSERT",
    "_EDA_INSERT",
    "_EEG_INSERT",
    "_HRV_INSERT",
    "_RESPIRATION_INSERT",
    "_StreamThread",
    "_build_eda_rows",
    "_build_eeg_rows",
    "_build_hrv_rows",
    "_build_respiration_rows",
    "_verify_session_ready",
]


def _parse_uuid(value: str) -> str:
    try:
        return str(uuid.UUID(value))
    except ValueError:
        raise argparse.ArgumentTypeError(f"'{value}' is not a valid UUID")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="untitledplatform_1a LSL forwarder")
    parser.add_argument(
        "--session-id", required=True, type=_parse_uuid, help="Session UUID"
    )
    parser.add_argument(
        "--participant-id",
        required=True,
        type=_parse_uuid,
        help="Pseudonymous participant UUID",
    )
    parser.add_argument("--site-id", required=True, type=_parse_uuid, help="Site UUID")
    parser.add_argument(
        "--sponsor-id", required=True, type=_parse_uuid, help="Sponsor UUID"
    )
    return parser.parse_args()


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


def main() -> None:
    args = _parse_args()
    cfg = SessionConfig(
        session_id=args.session_id,
        participant_id=args.participant_id,
        site_id=args.site_id,
        sponsor_id=args.sponsor_id,
    )

    set_session_id(cfg.session_id)
    clear_stop_request(cfg.session_id)
    _verify_session_ready(cfg)

    log.info(
        "forwarder starting",
        extra={
            "schema_version": PAYLOAD_SCHEMA_VERSION,
            "session_id": cfg.session_id,
            "participant_id": cfg.participant_id,
            "site_id": cfg.site_id,
            "sponsor_id": cfg.sponsor_id,
            "device_id": settings.DEVICE_ID,
            "simulation_mode": settings.SIMULATION_MODE,
        },
    )

    xdf = XDFWriter(
        session_id=cfg.session_id,
        site_id=cfg.site_id,
        sponsor_id=cfg.sponsor_id,
    )

    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda sig, frame: stop.set())
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, lambda sig, frame: stop.set())

    threads = _build_stream_threads(cfg, stop, xdf)
    for thread in threads:
        thread.start()

    log.info("all forwarder threads started - press Ctrl+C to stop")

    try:
        while not stop.is_set():
            if stop_requested(cfg.session_id):
                log.info("stop request file detected - flushing buffers")
                stop.set()
                break
            time.sleep(1)
    except KeyboardInterrupt:
        log.info("shutdown requested - flushing buffers")
        stop.set()

    for thread in threads:
        thread.join(timeout=10.0)

    xdf.close()
    log.info("forwarder stopped")


if __name__ == "__main__":
    main()
