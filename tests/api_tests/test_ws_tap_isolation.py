"""INV-008a [integration] — WS tap exists, refuses upgrade, holds no StreamThread.

M0 portion only (INV-008b is deferred to the tap milestone):
- the WS /sessions/{id}/stream route refuses the upgrade with a capability reason
  (covered also in test_capability_gating); here we add the import check.
- the WS tap module does not import or accept a StreamThread (or its inlet/conn).
"""

import pathlib
import re

_API_DIR = pathlib.Path(__file__).resolve().parents[2] / "api"

# Where GREEN places the WS tap; any of these module files counts as "the tap".
_TAP_CANDIDATES = ("ws.py", "stream.py", "tap.py", "websocket.py")


def _tap_source() -> str | None:
    for name in _TAP_CANDIDATES:
        p = _API_DIR / name
        if p.exists():
            return p.read_text(encoding="utf-8")
    return None


def test_ws_tap_module_exists():
    # Tests INV-008a [integration]: the WS tap module is present in M0 (scaffolded).
    assert _tap_source() is not None, (
        "expected a WS tap module in api/ (one of: " + ", ".join(_TAP_CANDIDATES) + ")"
    )


def test_ws_tap_does_not_import_stream_thread():
    # Tests INV-008a [integration]: tap holds no StreamThread / forwarder inlet/conn.
    src = _tap_source()
    assert src is not None, "WS tap module must exist before this check is meaningful"
    assert "StreamThread" not in src, (
        "INV-008a: the WS tap must not import or hold a StreamThread (PAT-009)"
    )
    assert not re.search(r"from\s+capture\.forwarder", src), (
        "INV-008a: the WS tap must not import forwarder internals (own its own inlets)"
    )
