from __future__ import annotations

import time
from dataclasses import dataclass

from autonaparnik.config import Settings
from autonaparnik.domain.models import ChatRequest, DiscussionArgs, Discussions, SourcedClaim, ToolEvent
from autonaparnik.retrieval.search import CorpusIndex, RetrievedChunk

LIMITATIONS = [
    "Mechanics Stack Exchange и учебные тексты — не официальная сервисная карта.",
]


@dataclass
class DiscussionOutcome:
    discussions: Discussions
    chunks: list[RetrievedChunk]
    event: ToolEvent
    payload: dict


class SearchDiscussions:
    def __init__(self, settings: Settings, index: CorpusIndex):
        self.settings = settings
        self.index = index

    async def run(self, request: ChatRequest, args: DiscussionArgs, remaining: float) -> DiscussionOutcome:
        started = time.perf_counter()
        search = getattr(self.index, "search")
        chunks = search(
            args.query or request.message,
            request.vehicle,
            top_k=self.settings.rag_top_k,
            collection=args.collection,
        )
        elapsed = (time.perf_counter() - started) * 1000
        if not chunks:
            discussions = Discussions(status="empty", claims=[], limitations=LIMITATIONS[:1])
            event = ToolEvent(tool="search_discussions", status="ok", mode="fixture", elapsed_ms=elapsed)
            return DiscussionOutcome(
                discussions=discussions,
                chunks=[],
                event=event,
                payload={"status": "empty", "hits": []},
            )
        claims = []
        hits = []
        for chunk in chunks[:4]:
            excerpt = (chunk.evidence.excerpt or chunk.document.title)[:180]
            claims.append(SourcedClaim(text=excerpt[:500], evidence_ids=[chunk.evidence.evidence_id]))
            hits.append(
                {
                    "evidence_id": chunk.evidence.evidence_id,
                    "title": chunk.document.title[:200],
                    "url": chunk.evidence.url,
                    "excerpt": excerpt,
                    "collection": "manuals" if chunk.document.source_type == "public_guidance" else "mechanics",
                }
            )
        discussions = Discussions(status="ok", claims=claims[:4], limitations=LIMITATIONS[:1])
        event = ToolEvent(tool="search_discussions", status="ok", mode="fixture", elapsed_ms=elapsed)
        return DiscussionOutcome(
            discussions=discussions,
            chunks=chunks[:4],
            event=event,
            payload={"status": "ok", "hits": hits, "limitations": LIMITATIONS[:1]},
        )
