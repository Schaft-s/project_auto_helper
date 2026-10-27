from __future__ import annotations

from datetime import datetime, timezone
from dataclasses import dataclass

import time

from autonaparnik.adapters.specialist import SpecialistAdapter
from autonaparnik.config import ASSUME_EVIDENCE_ID, Settings
from autonaparnik.domain.models import ChatRequest, Evidence, SpecialistBlock, ToolEvent, WorkshopArgs
from autonaparnik.policy.risk import classify_risk
from autonaparnik.retrieval.search import CorpusIndex, RetrievedChunk


@dataclass
class WorkshopOutcome:
    block: SpecialistBlock
    chunks: list[RetrievedChunk]
    event: ToolEvent
    opaque: dict
    assumed_evidence: Evidence | None = None


class WorkshopConsult:
    def __init__(self, settings: Settings, index: CorpusIndex, specialist: SpecialistAdapter):
        self.settings = settings
        self.index = index
        self.specialist = specialist

    async def run(self, request: ChatRequest, args: WorkshopArgs, remaining: float) -> WorkshopOutcome:
        started = time.perf_counter()
        risk = classify_risk(request.message, args.query, args.user_plan or "")
        chunks = self.index.search(
            " ".join(part for part in [args.query, request.message, args.user_plan or ""] if part),
            request.vehicle,
            top_k=self.settings.rag_top_k,
        )
        assumed = None if chunks else _assumed_evidence()
        block = await self.specialist.consult(
            request, args, chunks, remaining, caution=risk.reason if risk.caution else None
        )
        elapsed = (time.perf_counter() - started) * 1000
        status = _event_status(block)
        mode = "fixture" if chunks and all(c.evidence.mode == "fixture" for c in chunks) else (
            "live" if block.model_run.executed else "not_run"
        )
        return WorkshopOutcome(
            block=block,
            chunks=chunks,
            event=ToolEvent(tool="workshop_consult", status=status, mode=mode, elapsed_ms=elapsed),
            opaque=_opaque(block),
            assumed_evidence=assumed,
        )


def _assumed_evidence() -> Evidence:
    return Evidence(
        evidence_id=ASSUME_EVIDENCE_ID,
        source_type="demo_note",
        source_id="ASSUME",
        title="Типовая сборка (черновик)",
        locator="specialist-placeholder",
        url=None,
        excerpt=None,
        retrieved_at=datetime.now(timezone.utc),
        mode="fixture",
        applicability="general",
        source_market="general",
    )


def _event_status(block: SpecialistBlock) -> str:
    mapping = {
        "needs_context": "needs_context",
        "out_of_scope": "out_of_scope",
        "unavailable": "unavailable",
        "grounded": "ok",
        "general_only": "ok",
    }
    return mapping.get(block.result.status, "ok")


def _opaque(block: SpecialistBlock) -> dict:
    return {
        "status": block.result.status,
        "block_id": f"B_{block.result.task}_{block.model_run.stage}",
        "has_checks": bool(block.result.checks),
        "summary": block.result.summary[:400],
    }
