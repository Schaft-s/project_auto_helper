from __future__ import annotations

from autonaparnik.domain.models import VehicleProfile
from autonaparnik.retrieval.search import CorpusIndex, applicability


def test_corpus_loads_and_finds_clips() -> None:
    index = CorpusIndex.from_jsonl()
    assert len(index.documents) >= 15
    hits = index.search("дребезг декоративной панели клипса", VehicleProfile(market="unknown"))
    assert hits
    titles = " ".join(hit.document.title.lower() + hit.document.content.lower() for hit in hits)
    assert "панел" in titles or "клип" in titles or "фиксатор" in titles


def test_mismatch_vehicle_specific_excluded() -> None:
    index = CorpusIndex.from_jsonl()
    demo = next(doc for doc in index.documents if doc.document_id == "MISMATCH-01")
    assert applicability(demo, VehicleProfile(make="Chery", model="Tiggo", model_year=2020, market="RU")) == "mismatch"
    hits = index.search("клипса зеркала DemoMake", VehicleProfile(make="Chery", model="Tiggo", model_year=2020))
    assert all(hit.document.document_id != "MISMATCH-01" for hit in hits)
