import pytest

from capture.xdf.writer import XDFWriter
from tests.capture_tests.xdf.support import PARTICIPANT_ID, SESSION_ID, SITE_ID, SPONSOR_ID


@pytest.fixture()
def writer(tmp_path, monkeypatch):
    """XDFWriter that writes to a temp directory."""
    import config.settings as s

    monkeypatch.setattr(s, "XDF_BACKUP_DIR", tmp_path)
    w = XDFWriter(SESSION_ID, PARTICIPANT_ID, SITE_ID, SPONSOR_ID)
    yield w
    if not w.is_closed:
        w.close()


@pytest.fixture()
def closed_writer(writer):
    writer.close()
    return writer
