from __future__ import annotations

import os

import pytest

from tests.consult_dialogs import DIALOGS
from tests.consult_harness import run_dialogs

LIVE = os.environ.get("AUTONAPARNIK_LIVE") == "1"


def test_dialog_catalog_has_multi_step_coverage() -> None:
    assert len(DIALOGS) >= 10
    ids = [item["id"] for item in DIALOGS]
    assert len(ids) == len(set(ids))
    workshop_context_ids = {
        "bmw7-then-headlight-workshop",
        "camry-then-door-card-workshop",
        "switch-car-then-panel-workshop",
        "workshop-followup-same-car",
        "pronoun-this-car-workshop",
        "symptom-then-assembly-switch",
    }
    assert workshop_context_ids.issubset(ids)
    assert all(len(item["steps"]) >= 2 for item in DIALOGS)
    assert any(step["message"].lower().startswith("спасибо") for item in DIALOGS for step in item["steps"])
    assert any(step["message"].lower() == "привет" for item in DIALOGS for step in item["steps"])
    for dialog_id in workshop_context_ids:
        dialog = next(item for item in DIALOGS if item["id"] == dialog_id)
        workshop_steps = [step for step in dialog["steps"] if "workshop_consult" in (step["expect"].get("tools_include") or [])]
        assert workshop_steps, f"{dialog_id} has no workshop step"
        assert any("specialist_must_any" in step["expect"] for step in workshop_steps), dialog_id


@pytest.mark.live
@pytest.mark.skipif(not LIVE, reason="set AUTONAPARNIK_LIVE=1 to call OpenRouter/MCP")
async def test_live_multi_turn_dialogs() -> None:
    report = await run_dialogs(DIALOGS)
    failed = [item for item in report["results"] if item["status"] == "fail"]
    assert not failed, "\n".join(f"{item['id']}: {item['failures']}" for item in failed)
