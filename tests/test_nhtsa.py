from __future__ import annotations

from autonaparnik.adapters.nhtsa import NhtsaMcpAdapter, _coverage_from_payload
from autonaparnik.config import Settings
from autonaparnik.domain.models import VehicleProfile, VehicleSafetyArgs


async def test_empty_payload_is_empty_not_unavailable() -> None:
    coverage = _coverage_from_payload({"Count": 0, "Results": []}, [], True, 1)
    assert coverage.status == "empty"
    assert coverage.total_matching_count == 0
    assert coverage.returned_count == 0
    assert coverage.is_partial is False


async def test_nonzero_is_ok() -> None:
    rows = [{"campaignNumber": "X"}]
    coverage = _coverage_from_payload({"Count": 1, "Results": rows}, rows, True, 1)
    assert coverage.status == "ok"
    assert coverage.returned_count == 1


async def test_partial_when_analyzed_less_than_total() -> None:
    rows = [{"odiNumber": "1"}]
    coverage = _coverage_from_payload({"Count": 15, "Results": rows, "is_partial": True}, rows, True, 1)
    assert coverage.status == "partial"
    assert coverage.is_partial is True


async def test_chery_is_not_replaced(settings: Settings) -> None:
    adapter = NhtsaMcpAdapter(settings)
    seen: list[tuple[str, dict]] = []

    async def fake_call(name: str, arguments: dict, remaining: float) -> dict:
        seen.append((name, arguments))
        return {"Count": 0, "Results": []}

    adapter._call_tool = fake_call  # type: ignore[method-assign]
    vehicle = VehicleProfile(make="Chery", model="Tiggo", model_year=2020, market="RU")
    outcome = await adapter.lookup(vehicle, VehicleSafetyArgs(include_complaints=True), 30)
    assert seen
    for name, arguments in seen:
        assert arguments["make"] == "Chery"
        assert arguments["model"] == "Tiggo"
        assert arguments["modelYear"] == 2020
        assert "Honda" not in str(arguments)
    assert outcome.known_issues.recalls.status == "empty"
    assert any("США" in item or "US" in item for item in outcome.known_issues.limitations)


async def test_incomplete_vehicle_does_not_call_mcp(settings: Settings) -> None:
    adapter = NhtsaMcpAdapter(settings)

    async def boom(*_a, **_k):
        raise AssertionError("MCP must not be called")

    adapter._call_tool = boom  # type: ignore[method-assign]
    outcome = await adapter.lookup(VehicleProfile(market="unknown"), VehicleSafetyArgs(), 30)
    assert outcome.status == "needs_context"
    assert outcome.mode == "not_run"
    assert outcome.known_issues.recalls.status == "needs_context"
