"""WS tap module (INV-008 / TB-005).

M0 (INV-008a): the `WS /sessions/{id}/stream` route refuses the upgrade with a
capability-status close reason (implemented in `api.app`). This module holds the
tap's M0 scaffolding and the close-reason builder. It deliberately imports no
forwarder internals (PAT-009): when the tap milestone (INV-008b) lands it will
own its OWN LSL inlets, never share the forwarder's.

The deferred frame schema is built by `api.frames.build_sample_frame`
(INV-010 — `t` is always `lsl_timestamp`).
"""

import json

from api import capabilities

# App-defined WS close code mirroring HTTP 409 for a refused upgrade (INV-013).
WS_CAPABILITY_CLOSE_CODE = 4409

_WS_ENDPOINT_LABEL = "WS /sessions/{id}/stream"


def capability_close_reason() -> str:
    """Return the JSON capability-status close reason for the scaffolded WS.

    Mirrors the HTTP 409 capability body (capability/status/blocked_reason/gate)
    so the client maps the close to the same operator message (INV-014).
    """
    return json.dumps(capabilities.capability_unavailable_body(_WS_ENDPOINT_LABEL))
