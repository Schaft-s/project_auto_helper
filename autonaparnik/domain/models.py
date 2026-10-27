"""Canonical contracts, copied from autonaparnik_agent_plan_v2/contracts/models.py."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ShortText = Annotated[str, Field(min_length=1, max_length=500)]
EvidenceId = Annotated[str, Field(pattern=r"^E[A-Za-z0-9_-]{1,63}$")]
Sha256 = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Task = Literal["assembly_checklist", "review_plan", "post_repair_checks"]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_default=True)


class VehicleProfile(Contract):
    make: Annotated[str, Field(min_length=1, max_length=100)] | None = None
    model: Annotated[str, Field(min_length=1, max_length=100)] | None = None
    model_year: Annotated[int, Field(strict=True, ge=1886, le=2100)] | None = None
    market: Literal["US", "KZ", "RU", "EU", "other", "unknown"] = "unknown"
    variant: ShortText | None = None


class HistoryMessage(Contract):
    role: Literal["user", "assistant"]
    text: Annotated[str, Field(min_length=1, max_length=6000)]


class ChatRequest(Contract):
    message: Annotated[str, Field(min_length=1, max_length=6000)]
    vehicle: VehicleProfile
    audience: Literal["owner", "mechanic"] = "owner"
    intent: Literal["auto", "known_issues", "workshop", "discussions"] = "auto"
    history: Annotated[list[HistoryMessage], Field(max_length=12)] = []

    @model_validator(mode="after")
    def bounded_history(self):
        if len(self.message) + sum(len(m.text) for m in self.history) > 30000:
            raise ValueError("total history and message exceed 30000 characters")
        return self


class Check(Contract):
    text: ShortText
    relation: Literal["required_check", "not_mentioned", "conflict", "observation"]
    evidence_ids: Annotated[list[EvidenceId], Field(min_length=1, max_length=5)]


class SpecialistResult(Contract):
    task: Task
    status: Literal["grounded", "general_only", "needs_context", "out_of_scope", "unavailable"]
    summary: Annotated[str, Field(min_length=1, max_length=1000)]
    checks: Annotated[list[Check], Field(max_length=12)]
    missing_information: Annotated[list[ShortText], Field(max_length=3)]
    limitations: Annotated[list[ShortText], Field(max_length=6)]

    @model_validator(mode="after")
    def grounded_checks(self):
        if self.status in {"needs_context", "out_of_scope", "unavailable"} and self.checks:
            raise ValueError("non-answer status must not contain procedural checks")
        if self.status in {"grounded", "general_only"} and not self.checks:
            raise ValueError("grounded/general response needs at least one sourced check")
        return self


class ModelRun(Contract):
    executed: bool
    stage: Literal["base", "sft", "not_run"]
    model_id: str | None
    base_revision: str | None
    artifact_sha256: Sha256 | None
    latency_ms: Annotated[float, Field(ge=0)]
    raw_schema_valid: bool
    repaired: bool

    @model_validator(mode="after")
    def real_provenance(self):
        if self.executed:
            if self.stage == "not_run" or not all((self.model_id, self.base_revision, self.artifact_sha256)):
                raise ValueError("executed model requires real artifact provenance")
        elif self.stage != "not_run" or self.artifact_sha256 is not None:
            raise ValueError("not-executed model must not claim checkpoint execution")
        return self


class SpecialistBlock(Contract):
    result: SpecialistResult
    model_run: ModelRun
    input_evidence_ids: Annotated[list[EvidenceId], Field(max_length=10)]

    @model_validator(mode="after")
    def seen_sources_only(self):
        allowed = set(self.input_evidence_ids)
        for check in self.result.checks:
            if not set(check.evidence_ids).issubset(allowed):
                raise ValueError("specialist cited evidence it was not given")
        return self


class Evidence(Contract):
    evidence_id: EvidenceId
    source_type: Literal["nhtsa_recall", "nhtsa_complaint", "technical_doc", "demo_note", "mechanics_qa"]
    source_id: ShortText
    title: ShortText
    locator: ShortText
    url: str | None
    excerpt: Annotated[str, Field(max_length=2000)] | None
    retrieved_at: datetime
    mode: Literal["live", "cache", "fixture"]
    applicability: Literal["matched", "general", "unknown"]
    source_market: Literal["US", "KZ", "RU", "EU", "other", "unknown", "general"]

    @model_validator(mode="after")
    def allow_link_shape(self):
        if self.url is not None and not (self.url.startswith("https://") or self.url.startswith("/api/v1/corpus/")):
            raise ValueError("evidence URLs must be https or application corpus paths")
        return self


class Coverage(Contract):
    status: Literal["ok", "empty", "partial", "unavailable", "not_requested", "needs_context"]
    total_matching_count: Annotated[int, Field(ge=0)] | None
    returned_count: Annotated[int, Field(ge=0)]
    analyzed_count: Annotated[int, Field(ge=0)]
    pages_fetched: Annotated[int, Field(ge=0, le=2)]
    is_partial: bool

    @model_validator(mode="after")
    def honest_coverage(self):
        if self.analyzed_count > self.returned_count:
            raise ValueError("cannot analyze more records than returned")
        if self.total_matching_count is not None:
            if self.returned_count > self.total_matching_count:
                raise ValueError("returned count exceeds matching count")
            if self.analyzed_count < self.total_matching_count and not self.is_partial:
                raise ValueError("incomplete analysis must be marked partial")
        if self.status == "empty" and (self.returned_count != 0 or self.total_matching_count != 0):
            raise ValueError("empty requires a confirmed zero-count result")
        if self.status == "unavailable" and self.total_matching_count is not None:
            raise ValueError("unavailability must not invent a total count")
        return self


class SourcedClaim(Contract):
    text: ShortText
    evidence_ids: Annotated[list[EvidenceId], Field(min_length=1, max_length=5)]


class KnownIssues(Contract):
    recalls: Coverage
    complaints: Coverage
    claims: Annotated[list[SourcedClaim], Field(max_length=10)]
    limitations: Annotated[list[ShortText], Field(max_length=6)]


class Discussions(Contract):
    status: Literal["ok", "empty", "unavailable"]
    claims: Annotated[list[SourcedClaim], Field(max_length=8)]
    limitations: Annotated[list[ShortText], Field(max_length=6)]


class ToolEvent(Contract):
    tool: Literal["vehicle_safety_lookup", "workshop_consult", "search_discussions"]
    status: Literal["ok", "partial", "unavailable", "needs_context", "out_of_scope"]
    mode: Literal["live", "cache", "fixture", "not_run"]
    elapsed_ms: Annotated[float, Field(ge=0)]


class AnswerEnvelope(Contract):
    schema_version: Literal["2.0"]
    trace_id: Annotated[str, Field(min_length=8, max_length=100)]
    status: Literal["ok", "partial", "needs_clarification", "out_of_scope", "error"]
    route: Literal["clarify", "known_issues", "workshop", "discussions", "combined", "general"]
    vehicle: VehicleProfile
    summary: Annotated[str, Field(min_length=1, max_length=2800)]
    known_issues: KnownIssues | None = None
    specialist: SpecialistBlock | None = None
    discussions: Discussions | None = None
    questions: Annotated[list[ShortText], Field(max_length=3)]
    limitations: Annotated[list[ShortText], Field(max_length=8)]
    evidence: Annotated[list[Evidence], Field(max_length=20)]
    tool_events: Annotated[list[ToolEvent], Field(max_length=3)]

    @model_validator(mode="after")
    def current_evidence_and_specialist(self):
        ids = {e.evidence_id for e in self.evidence}
        if len(ids) != len(self.evidence):
            raise ValueError("duplicate evidence identifiers")
        claims = self.known_issues.claims if self.known_issues else []
        discussion_claims = self.discussions.claims if self.discussions else []
        checks = self.specialist.result.checks if self.specialist else []
        for item in [*claims, *discussion_claims, *checks]:
            if not set(item.evidence_ids).issubset(ids):
                raise ValueError("citation does not exist in the current response")
        if self.route == "workshop" and self.specialist is None:
            raise ValueError("workshop route needs explicit specialist result or unavailability")
        if self.route == "discussions" and self.discussions is None:
            raise ValueError("discussions route needs a discussions block")
        if self.route == "combined":
            sources = int(self.known_issues is not None) + int(self.specialist is not None) + int(self.discussions is not None)
            if sources < 2:
                raise ValueError("combined route needs at least two source blocks")
        if self.specialist and self.specialist.result.status in {"grounded", "general_only"}:
            if not self.specialist.model_run.executed:
                raise ValueError("a sourced specialist answer requires actual model execution")
        if self.specialist and not set(self.specialist.input_evidence_ids).issubset(ids):
            raise ValueError("specialist input references absent evidence")
        return self


class Rights(Contract):
    train: bool = False
    retrieval: bool = False
    send_cloud: bool = False
    public_serve: bool = False
    publish_source: bool = False
    publish_weights: bool = False
    rights_ref: ShortText


class Document(Contract):
    document_id: Annotated[str, Field(min_length=1, max_length=100)]
    source_group_id: Annotated[str, Field(min_length=1, max_length=100)]
    operation_type: ShortText
    title: ShortText
    language: Literal["ru", "en", "other"]
    source_type: Literal["kso", "service_manual", "public_guidance", "own_general", "qa", "demo_fixture"]
    workflow_context: Literal["manufacturing", "service", "general"]
    transfer_scope: Literal["vehicle_specific", "general_principle", "unreviewed"]
    vehicle_constraints: VehicleProfile
    revision: ShortText
    locator: ShortText
    content_sha256: Sha256
    requires_visual_context: bool
    review_status: Literal["approved", "pending", "rejected"]
    reviewer: ShortText | None
    rights: Rights
    content: Annotated[str, Field(min_length=1, max_length=100000)]

    @model_validator(mode="after")
    def reviewed_before_use(self):
        if self.review_status == "approved" and not self.reviewer:
            raise ValueError("approved document requires reviewer")
        return self


class VehicleSafetyArgs(Contract):
    symptom: Annotated[str, Field(max_length=1000)] = ""
    include_complaints: bool = True
    make: Annotated[str, Field(min_length=1, max_length=100)] | None = None
    model: Annotated[str, Field(min_length=1, max_length=100)] | None = None
    model_year: Annotated[int, Field(strict=True, ge=1886, le=2100)] | None = None
    market: Literal["US", "KZ", "RU", "EU", "other", "unknown"] | None = None


class WorkshopArgs(Contract):
    task: Task
    query: Annotated[str, Field(min_length=1, max_length=2000)]
    user_plan: Annotated[str, Field(max_length=4000)] | None = None


class DiscussionArgs(Contract):
    query: Annotated[str, Field(min_length=1, max_length=2000)]
    collection: Literal["mechanics", "manuals", "both"] = "both"
