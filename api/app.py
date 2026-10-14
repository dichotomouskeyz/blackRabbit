"""FastAPI application factory for the operator UI surface (M0).

The API WRAPS the existing backend contracts (PAT-010): it never reimplements
them, its direct reads run on a read-only DB role (INV-002), and tenancy is
server-injected (INV-001). Blocked/scaffolded capabilities fail closed with the
structured 409 capability-status body FIRST (INV-013), before any validation,
DB connection, or backend call.

Documented endpoint set (spec Endpoint contract):
  GET  /health
  GET  /capabilities
  GET  /vocab
  GET  /sessions
  GET  /sessions/{session_id}/status
  POST /sessions
  WS   /sessions/{session_id}/stream            (scaffolded: upgrade refused)
  GET  /sessions/{session_id}/arc               (persisted report; watermark gated)
  POST /sessions/{session_id}/markers           (blocked: 409)
  POST /sessions/{session_id}/capture:start     (blocked: 409)
  POST /sessions/{session_id}/capture:stop      (blocked: 409)
  POST /sessions/{session_id}/close             (blocked: 409)
  POST /sessions/{session_id}/arc:run           (blocked: 409)
  POST /agent/chat                             (optional investigation agent)
"""

import json

import psycopg2
from fastapi import Depends, FastAPI, Request, WebSocket
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

# Module-attribute access (INV-013 / QA-005): import the MODULE, not the names,
# so test patches on `api.deps` (e.g. monkeypatching get_readonly_connection /
# get_tenant_context) bind at call time. `from api.deps import X` would bind the
# name at import and leave the patch dead.
from api import arc, capabilities, deps, investigation, session_filters, sessions, vocab
from api.deps import TenantContext

CONTRACT_VERSION = "0"

# WebSocket close code for a refused upgrade carrying a capability-status reason.
# 4409 is an app-defined (4000-4999) code mirroring HTTP 409; NOT the default
# 1000 normal-closure the stub emits (INV-013 / INV-008a).
_WS_CAPABILITY_CLOSE_CODE = 4409


# --- Response models (INV-005: closed allowlist, extra='forbid') -------------
class SessionRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    status: str
    compound: str
    started_at: str | None = None
    closed_at: str | None = None
    created_at: str | None = None


class SessionsList(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sessions: list[SessionRow]


class SessionStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    status: str
    started_at: str | None = None
    closed_at: str | None = None
    watermark_state: str


class CapabilityRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    capability: str
    endpoint: str
    status: str
    blocked_reason: str | None = None
    gate: str | None = None


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str
    version: str
    contract_version: str


class VocabResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    compounds: list[str]
    dose_units: list[str]


class CreateSessionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str


class ARCProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")
    algorithm_version: str
    config_sha256: str
    input_sha256: str
    artifact_sha256: str


class ARCReviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str
    analysis_id: str
    created_at: str
    provenance: ARCProvenance
    artifact: dict


# --- Create request body: closed allow-list (RS-004 / INV-004) ---------------
# extra='forbid' makes unknown keys (incl. site_id/sponsor_id) a 422 at FastAPI
# validation before the route body runs — no DB call. The named electrode kwargs
# mirror create_session's signature (sourced from session_signal_metadata).
class CreateSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    compound: str
    capture_source: str
    participant_id: str
    compound_dose: float | None = None
    compound_dose_unit: str | None = None
    protocol_arm: str | None = None
    room_id: str | None = None
    eeg_sensor_form: str | None = None
    eeg_electrode_system: str | None = None
    eeg_electrode_type: str | None = None
    hrv_electrode_placement: str | None = None
    hrv_electrode_type: str | None = None
    eda_electrode_placement: str | None = None
    eda_electrode_type: str | None = None
    eda_skin_prep: str | None = None


def _capability_409(endpoint_label: str) -> JSONResponse:
    """Build the 409 capability-status JSONResponse for a gated endpoint."""
    body = capabilities.capability_unavailable_body(endpoint_label)
    return JSONResponse(status_code=409, content=body)


def _structured_422(field: str, message: str, valid_choices=None) -> JSONResponse:
    content: dict[str, str | list[str]] = {"field": field, "message": message}
    if valid_choices is not None:
        content["valid_choices"] = list(valid_choices)
    return JSONResponse(status_code=422, content=content)


def create_app() -> FastAPI:
    """Build the operator API app (M0)."""
    app = FastAPI(title="blackRabbit operator API")
    investigation.install(app)

    # --- app-level fail-closed handlers (INV-014 / QA-001 / QA-004) ----------
    # Every DB-touching route inherits these: a backend-down condition or a
    # missing-tenancy config maps to a structured 503, never a raw 500/stack.

    @app.exception_handler(psycopg2.OperationalError)
    async def _backend_unavailable(request: Request, exc: psycopg2.OperationalError):
        # INV-014 / BND-004: DB unreachable or connection-exhausted -> 503 with a
        # defined operator-facing body, not a 500. Covers GET /sessions,
        # GET /sessions/{id}/status, POST /sessions, and any DB-touching read.
        return JSONResponse(
            status_code=503,
            content={
                "error": "backend_unavailable",
                "message": "backend database is unavailable; retry shortly",
            },
        )

    @app.exception_handler(deps.ConfigurationError)
    async def _tenancy_not_configured(request: Request, exc: deps.ConfigurationError):
        # INV-001 fail-closed: tenancy unset -> 503 with an actionable message,
        # never a 500 or a wrapped call with sponsor_id=None.
        return JSONResponse(
            status_code=503,
            content={
                "error": "tenancy_not_configured",
                "message": str(exc),
            },
        )

    # --- implemented reads ---------------------------------------------------
    @app.get("/health", response_model=HealthResponse)
    def _health() -> dict:
        from config import settings

        return {
            "status": "ok",
            "version": settings.APP_VERSION,
            "contract_version": CONTRACT_VERSION,
        }

    @app.get("/capabilities", response_model=list[CapabilityRow])
    def _capabilities():
        return capabilities.CAPABILITY_MATRIX

    @app.get("/vocab", response_model=VocabResponse)
    def _vocab() -> dict:
        return vocab.get_vocab()

    @app.get("/sessions", response_model=SessionsList)
    def _list_sessions(
        tenant: TenantContext = Depends(deps.get_tenant_context),
        session_id: str | None = None,
        participant_id: str | None = None,
        status: str | None = None,
        compound: str | None = None,
        created_from: str | None = None,
        created_before: str | None = None,
        limit: str | None = None,
    ):
        # SQ-002: validate every filter before tenancy or DB work.
        try:
            filters = session_filters.parse_session_filters(
                session_id=session_id,
                participant_id=participant_id,
                status=status,
                compound=compound,
                created_from=created_from,
                created_before=created_before,
                limit=limit,
            )
        except session_filters.FilterError as exc:
            return _structured_422(exc.field, exc.message, exc.valid_choices)
        # INV-001 fail-closed: enforce non-null tenancy before opening any DB
        # connection.
        validated_tenant = deps.require_tenant(tenant)
        conn = deps.get_readonly_connection()
        try:
            return sessions.list_sessions(
                conn, validated_tenant.sponsor_id, validated_tenant.site_id, filters
            )
        finally:
            conn.rollback()
            conn.close()

    @app.get("/sessions/{session_id}/status", response_model=SessionStatus)
    def _session_status(session_id: str, tenant: TenantContext = Depends(deps.get_tenant_context)):
        # INV-004: validate the path UUID before any tenancy/DB work.
        if not sessions.is_uuid(session_id):
            return _structured_422("session_id", "session_id must be a valid UUID")
        # INV-001 fail-closed: enforce non-null tenancy before any DB call.
        validated_tenant = deps.require_tenant(tenant)
        conn = deps.get_readonly_connection()
        try:
            payload = sessions.session_status(
                conn, session_id, validated_tenant.sponsor_id, validated_tenant.site_id
            )
        finally:
            conn.rollback()
            conn.close()
        if payload is None:
            return JSONResponse(
                status_code=404,
                content={"error": "not_found", "message": "session not found"},
            )
        return payload

    @app.post("/sessions", response_model=CreateSessionResponse)
    def _create_session(
        body: CreateSessionRequest,
        tenant: TenantContext = Depends(deps.get_tenant_context),
    ):
        # INV-005: participant_id validated as a UUID at the API layer, before DB.
        if not sessions.is_uuid(body.participant_id):
            return _structured_422("participant_id", "participant_id must be a valid UUID")
        # INV-001 fail-closed: enforce non-null tenancy before the wrapped call.
        validated_tenant = deps.require_tenant(tenant)
        try:
            session_id = sessions.create_session(
                compound=body.compound,
                capture_source=body.capture_source,
                participant_id=body.participant_id,
                sponsor_id=validated_tenant.sponsor_id,
                site_id=validated_tenant.site_id,
                compound_dose=body.compound_dose,
                compound_dose_unit=body.compound_dose_unit,
                protocol_arm=body.protocol_arm,
                room_id=body.room_id,
                eeg_sensor_form=body.eeg_sensor_form,
                eeg_electrode_system=body.eeg_electrode_system,
                eeg_electrode_type=body.eeg_electrode_type,
                hrv_electrode_placement=body.hrv_electrode_placement,
                hrv_electrode_type=body.hrv_electrode_type,
                eda_electrode_placement=body.eda_electrode_placement,
                eda_electrode_type=body.eda_electrode_type,
                eda_skin_prep=body.eda_skin_prep,
            )
        except ValueError as exc:
            return _map_create_value_error(exc)
        return {"session_id": session_id}

    @app.get("/sessions/{session_id}/arc", response_model=ARCReviewResponse)
    def _arc_read(session_id: str, tenant: TenantContext = Depends(deps.get_tenant_context)):
        if not sessions.is_uuid(session_id):
            return _structured_422("session_id", "session_id must be a valid UUID")
        validated_tenant = deps.require_tenant(tenant)
        conn = deps.get_readonly_connection()
        try:
            payload = arc.latest_artifact(
                conn, session_id, validated_tenant.sponsor_id, validated_tenant.site_id
            )
        except arc.SessionNotFound:
            return JSONResponse(
                status_code=404,
                content={"error": "not_found", "message": "session not found"},
            )
        except arc.WatermarkNotVerified as exc:
            return JSONResponse(
                status_code=409,
                content={
                    "error": "watermark_not_verified",
                    "message": str(exc),
                    "watermark_state": exc.watermark_state,
                },
            )
        finally:
            conn.rollback()
            conn.close()
        if payload is None:
            return JSONResponse(
                status_code=404,
                content={
                    "error": "analysis_not_found",
                    "message": "no persisted ARC analysis is available for this session",
                },
            )
        return payload

    # --- blocked capabilities (409 capability-status, first) -----------------
    @app.post("/sessions/{session_id}/markers")
    def _markers(session_id: str):
        return _capability_409("POST /sessions/{id}/markers")

    @app.post("/sessions/{session_id}/capture:start")
    def _capture_start(session_id: str):
        return _capability_409("POST /sessions/{id}/capture:start")

    @app.post("/sessions/{session_id}/capture:stop")
    def _capture_stop(session_id: str):
        return _capability_409("POST /sessions/{id}/capture:stop")

    @app.post("/sessions/{session_id}/close")
    def _close(session_id: str):
        return _capability_409("POST /sessions/{id}/close")

    @app.post("/sessions/{session_id}/arc:run")
    def _arc_run(session_id: str):
        return _capability_409("POST /sessions/{id}/arc:run")

    # --- scaffolded WS: refuse upgrade with capability close reason ----------
    @app.websocket("/sessions/{session_id}/stream")
    async def _stream(websocket: WebSocket, session_id: str):
        # INV-013 / INV-008a: refuse the upgrade with a non-default close code
        # carrying the structured capability-status reason (the same four fields
        # the HTTP 409 body carries). Close-frame reasons are length-limited, so
        # we send a compact JSON reason that mirrors is_capability_unavailable_body.
        body = capabilities.capability_unavailable_body("WS /sessions/{id}/stream")
        reason = json.dumps(body)
        await websocket.close(code=_WS_CAPABILITY_CLOSE_CODE, reason=reason)

    return app


def _map_create_value_error(exc: ValueError) -> JSONResponse:
    """Map create_session's pre-DB ValueError to a structured 422 (INV-007).

    For enum fields, valid_choices equals the canonical VALID_* set (sourced from
    session_init, never duplicated in api/).
    """
    from capture.session_init.constants import VALID_COMPOUNDS, VALID_DOSE_UNITS

    message = str(exc)
    if "compound_dose_unit" in message:
        return _structured_422("compound_dose_unit", message, VALID_DOSE_UNITS)
    if "compound" in message:
        return _structured_422("compound", message, VALID_COMPOUNDS)
    if "participant_id" in message:
        return _structured_422("participant_id", message)
    return _structured_422("request", message)


app = create_app()
