from autonaparnik.config import ROOT
from autonaparnik.domain.models import VehicleProfile
from autonaparnik.retrieval.search import CorpusIndex


def _index() -> CorpusIndex:
    return CorpusIndex.from_jsonl(ROOT / "data" / "mechanics" / "qa.jsonl")


def test_oil_overfill_hits_mse_1125() -> None:
    hits = _index().search("too much oil Acura TSX siphon dipstick", VehicleProfile(market="unknown"))
    ids = {hit.document.document_id for hit in hits}
    assert "MSE-1125" in ids
    assert hits[0].evidence.source_type == "mechanics_qa"
    assert hits[0].evidence.url and hits[0].evidence.url.startswith("https://mechanics.stackexchange.com/")


def test_timing_belt_hits_mse_1() -> None:
    hits = _index().search("timing belt 2003 Honda Accord EX V6 mileage manual", VehicleProfile(make="Honda", model="Accord", model_year=2003))
    assert any(hit.document.document_id == "MSE-1" for hit in hits)


def test_jump_start_hits_mse_1410() -> None:
    hits = _index().search("jump start black clamp bare metal hydrogen battery", VehicleProfile(market="unknown"))
    assert any(hit.document.document_id == "MSE-1410" for hit in hits)


def test_battery_cca_hits_mse_312() -> None:
    hits = _index().search(
        "higher Ah car battery CCA 1998 Subaru Outback",
        VehicleProfile(make="Subaru", model="Outback", model_year=1998),
    )
    assert any(hit.document.document_id == "MSE-312" for hit in hits)
