"""Public report and evidence types, independent of the agent SDK."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue


class InvestigationError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Evidence(ClosedModel):
    id: str
    session_id: str
    analysis_id: str
    artifact_sha256: str
    source: Literal["saved_arc", "raw_window", "recording_quality", "session_metadata"]
    metric: str
    value: JsonValue
    units: str | None = None
    event_id: int | None = None
    window: str | None = None
    modality: str | None = None


class Finding(ClosedModel):
    text: str = Field(min_length=1, max_length=4000)
    evidence_ids: list[str] = Field(min_length=1, max_length=30)


class InvestigationDraft(ClosedModel):
    summary: str = Field(min_length=1, max_length=4000)
    findings: list[Finding] = Field(default_factory=list, max_length=20)
    quality_limitations: list[str] = Field(default_factory=list, max_length=20)
    unresolved_questions: list[str] = Field(default_factory=list, max_length=20)


class InvestigationReport(InvestigationDraft):
    session_id: str
    analysis_id: str
    artifact_sha256: str
    evidence: list[Evidence]
    mode: Literal["configured_model", "scripted_demo"] = "configured_model"


def build_report(
    draft: InvestigationDraft,
    tools,
    *,
    mode: Literal["configured_model", "scripted_demo"] = "configured_model",
):
    """Hydrate cited evidence from the server registry, never from model values."""
    cited = list(dict.fromkeys(ref for finding in draft.findings for ref in finding.evidence_ids))
    unknown = [ref for ref in cited if ref not in tools.evidence]
    if unknown:
        raise ValueError("Unknown evidence references: " + ", ".join(unknown))
    return InvestigationReport(
        **draft.model_dump(),
        session_id=tools.session_id,
        analysis_id=tools.analysis_id,
        artifact_sha256=tools.artifact_sha256,
        evidence=[tools.evidence[ref] for ref in cited],
        mode=mode,
    )
