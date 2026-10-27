from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from autonaparnik.config import ROOT
from autonaparnik.domain.models import Document, Evidence, VehicleProfile

TOKEN = re.compile(r"[a-zA-Zа-яА-ЯёЁ0-9]{3,}")


def tokenize(text: str) -> list[str]:
    return [tok.lower() for tok in TOKEN.findall(text)]


def _norm(value: str | None) -> str | None:
    if not value:
        return None
    return re.sub(r"\s+", " ", value).strip().lower()


def applicability(doc: Document, vehicle: VehicleProfile) -> str:
    constraints = doc.vehicle_constraints
    make_ok = _fields_ok(constraints.make, vehicle.make)
    model_ok = _fields_ok(constraints.model, vehicle.model)
    year_ok = constraints.model_year is None or vehicle.model_year is None or constraints.model_year == vehicle.model_year
    if make_ok is False or model_ok is False or year_ok is False:
        return "mismatch"
    filled_match = (
        constraints.make
        and vehicle.make
        and _norm(constraints.make) == _norm(vehicle.make)
        and constraints.model
        and vehicle.model
        and _norm(constraints.model) == _norm(vehicle.model)
        and constraints.model_year is not None
        and vehicle.model_year == constraints.model_year
    )
    if filled_match:
        return "matched"
    if doc.transfer_scope == "general_principle":
        return "general"
    return "unknown"


def _fields_ok(constraint: str | None, actual: str | None) -> bool | None:
    if not constraint or not actual:
        return None
    return _norm(constraint) == _norm(actual)


@dataclass
class RetrievedChunk:
    document: Document
    evidence: Evidence
    score: float


class CorpusIndex:
    def __init__(self, documents: list[Document]):
        self.documents = documents
        self._hay = {
            doc.document_id: set(tokenize(doc.title + " " + doc.content + " " + doc.operation_type))
            for doc in documents
        }

    @classmethod
    def from_jsonl(cls, path: Path | None = None) -> "CorpusIndex":
        path = path or (ROOT / "data" / "corpus" / "documents.jsonl")
        documents = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            raw = json.loads(line)
            content = raw["content"]
            raw["content_sha256"] = hashlib.sha256(content.encode("utf-8")).hexdigest()
            documents.append(Document.model_validate(raw))
        return cls(documents)

    def search(
        self,
        query: str,
        vehicle: VehicleProfile,
        top_k: int = 4,
        collection: str | None = None,
    ) -> list[RetrievedChunk]:
        query_tokens = tokenize(query)
        scored: list[tuple[float, Document, str]] = []
        for doc in self.documents:
            if doc.review_status != "approved":
                continue
            if not doc.rights.retrieval or not doc.rights.public_serve:
                continue
            if doc.transfer_scope == "unreviewed":
                continue
            appl = applicability(doc, vehicle)
            if appl == "mismatch":
                continue
            score = _score_against(query_tokens, self._hay[doc.document_id])
            if score <= 0 and query_tokens:
                continue
            scored.append((score, doc, appl))
        scored.sort(key=lambda item: item[0], reverse=True)
        now = datetime.now(timezone.utc)
        return [_to_chunk(doc, appl, score, now) for score, doc, appl in scored[:top_k]]


def _score_against(query_tokens: list[str], hay_set: set[str]) -> float:
    if not query_tokens:
        return 0.1
    overlap = sum(1 for tok in query_tokens if tok in hay_set)
    return overlap / len(set(query_tokens))


def _score(query_tokens: list[str], doc: Document) -> float:
    hay = set(tokenize(doc.title + " " + doc.content + " " + doc.operation_type))
    return _score_against(query_tokens, hay)


def _to_chunk(doc: Document, appl: str, score: float, now: datetime) -> RetrievedChunk:
    evidence_id = "E" + re.sub(r"[^A-Za-z0-9_-]", "", doc.document_id)[:20]
    if not evidence_id.startswith("E") or len(evidence_id) < 2:
        evidence_id = "E" + hashlib.sha256(doc.document_id.encode()).hexdigest()[:8]
    excerpt = doc.content if len(doc.content) <= 2000 else doc.content[:1999] + "…"
    if doc.source_type == "demo_fixture":
        source_type = "demo_note"
    elif doc.source_type == "qa":
        source_type = "mechanics_qa"
    else:
        source_type = "technical_doc"
    url = doc.locator if doc.locator.startswith("https://") else None
    evidence = Evidence(
        evidence_id=evidence_id,
        source_type=source_type,
        source_id=doc.document_id,
        title=doc.title,
        locator=doc.locator,
        url=url,
        excerpt=excerpt,
        retrieved_at=now,
        mode="fixture" if doc.source_type in {"demo_fixture", "qa"} else "live",
        applicability=appl if appl in {"matched", "general", "unknown"} else "unknown",
        source_market="general",
    )
    return RetrievedChunk(document=doc, evidence=evidence, score=score)
