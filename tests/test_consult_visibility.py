from __future__ import annotations

import json
from datetime import datetime, timezone

from autonaparnik.adapters.nhtsa import LookupOutcome
from autonaparnik.application.orchestrator import RunState, _compact_lookup, _tool_messages
from autonaparnik.domain.models import Coverage, Evidence, KnownIssues, SourcedClaim

from tests.consult_cases import CASES


def test_consult_cases_cover_routes_and_are_unique() -> None:
    assert len(CASES) >= 30
    ids = [case["id"] for case in CASES]
    assert len(ids) == len(set(ids))
    groups = {case["group"] for case in CASES}
    assert {"nhtsa", "discussions", "workshop", "combined"}.issubset(groups)
    allowed = {"vehicle_safety_lookup", "workshop_consult", "search_discussions"}
    for case in CASES:
        for name in (case["expect"].get("tools_include") or []) + (case["expect"].get("tools_exclude") or []):
            assert name in allowed, case["id"]
        assert case["request"]["message"]
        assert "vehicle" in case["request"]


def _lookup_with_campaign() -> LookupOutcome:
    evidence = Evidence(
        evidence_id="ER_abcd123456",
        source_type="nhtsa_recall",
        source_id="22V123000",
        title="Recall 22V123000: AIR BAGS",
        locator="NHTSA campaign 22V123000",
        url="https://www.nhtsa.gov/recalls",
        excerpt="Takata inflator may rupture",
        retrieved_at=datetime(2026, 10, 26, tzinfo=timezone.utc),
        mode="live",
        applicability="matched",
        source_market="US",
    )
    known = KnownIssues(
        recalls=Coverage(
            status="ok",
            total_matching_count=1,
            returned_count=1,
            analyzed_count=1,
            pages_fetched=1,
            is_partial=False,
        ),
        complaints=Coverage(
            status="empty",
            total_matching_count=0,
            returned_count=0,
            analyzed_count=0,
            pages_fetched=1,
            is_partial=False,
        ),
        claims=[
            SourcedClaim(
                text="Кампания 22V123000: Takata inflator may rupture",
                evidence_ids=["ER_abcd123456"],
            )
        ],
        limitations=[],
    )
    return LookupOutcome(known_issues=known, evidence=[evidence], status="ok", mode="live", elapsed_ms=1)


def test_compact_lookup_shows_campaign_and_url() -> None:
    payload = _compact_lookup(_lookup_with_campaign())
    assert payload["claims"][0]["text"].startswith("Кампания 22V123000")
    assert payload["links"][0]["url"] == "https://www.nhtsa.gov/recalls"
    assert payload["links"][0]["source_id"] == "22V123000"
    assert payload["recalls"]["count"] == 1


def test_tool_messages_put_lookup_in_front_of_the_model() -> None:
    state = RunState(lookup=_lookup_with_campaign())
    messages = _tool_messages(
        [
            {
                "id": "call_s",
                "function": {"name": "vehicle_safety_lookup", "arguments": "{}"},
            }
        ],
        state,
    )
    content = messages[0]["content"]
    assert messages[0]["role"] == "tool"
    assert "22V123000" in content
    assert "Takata inflator" in content
    assert "https://www.nhtsa.gov/recalls" in content
    parsed = json.loads(content)
    assert parsed["links"]
