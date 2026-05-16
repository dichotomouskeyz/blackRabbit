"""Session initializer package and compatibility exports."""

import psycopg2

from capture.session_init import workflow as _workflow
from capture.session_init.cli import _parse_args, _parse_uuid, main
from capture.session_init.constants import VALID_COMPOUNDS, VALID_DOSE_UNITS
from capture.session_init.metadata import _build_metadata_rows
from capture.session_init.sql import _METADATA_INSERT, SESSION_ACTIVATE, SESSION_INSERT
from config import settings


def _sync_compat_patches() -> None:
    _workflow.psycopg2 = psycopg2


def create_session(*args, **kwargs) -> str:
    _sync_compat_patches()
    return _workflow.create_session(*args, **kwargs)


__all__ = [
    "SESSION_ACTIVATE",
    "SESSION_INSERT",
    "VALID_COMPOUNDS",
    "VALID_DOSE_UNITS",
    "_METADATA_INSERT",
    "_build_metadata_rows",
    "_parse_args",
    "_parse_uuid",
    "create_session",
    "main",
    "psycopg2",
    "settings",
]
