from __future__ import annotations

from autonaparnik.adapters.nhtsa import NhtsaMcpAdapter
from autonaparnik.adapters.openrouter import OpenRouterClient
from autonaparnik.adapters.specialist import SpecialistAdapter
from autonaparnik.application.orchestrator import Orchestrator
from autonaparnik.config import ROOT, Settings, load_settings
from autonaparnik.retrieval.search import CorpusIndex
from autonaparnik.tools.discussions import SearchDiscussions
from autonaparnik.tools.vehicle_safety import VehicleSafetyLookup
from autonaparnik.tools.workshop import WorkshopConsult


def build_discussions_index(settings: Settings) -> CorpusIndex:
    lexical = CorpusIndex.from_jsonl(ROOT / "data" / "mechanics" / "qa.jsonl")
    try:
        from autonaparnik.retrieval.qdrant import QdrantDiscussionsIndex

        hybrid = QdrantDiscussionsIndex(settings, fallback=lexical)
        if hybrid.available():
            return hybrid  # type: ignore[return-value]
    except Exception:
        pass
    return lexical


def build_orchestrator(settings: Settings | None = None) -> Orchestrator:
    settings = settings or load_settings()
    router = OpenRouterClient(settings)
    workshop_index = CorpusIndex.from_jsonl()
    discussions_index = build_discussions_index(settings)
    specialist = SpecialistAdapter(settings, router)
    return Orchestrator(
        settings=settings,
        router=router,
        lookup=VehicleSafetyLookup(NhtsaMcpAdapter(settings)),
        workshop=WorkshopConsult(settings, workshop_index, specialist),
        discussions=SearchDiscussions(settings, discussions_index),
    )
