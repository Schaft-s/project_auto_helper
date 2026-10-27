from __future__ import annotations

import os

import pytest

from tests.consult_dialogs import DIALOGS
from tests.consult_harness import run_dialogs

LIVE = os.environ.get("AUTONAPARNIK_LIVE") == "1"


def test_dialog_catalog_has_multi_step_coverage() -> None:
    assert len(DIALOGS) >= 5
    ids = [item["id"] for item in DIALOGS]
    assert len(ids) == len(set(ids))
    assert all(len(item["steps"]) >= 2 for item in DIALOGS)
    assert any(step["message"].lower().startswith("спасибо") for item in DIALOGS for step in item["steps"])
    assert any(step["message"].lower() == "привет" for item in DIALOGS for step in item["steps"])


@pytest.mark.live
@pytest.mark.skipif(not LIVE, reason="set AUTONAPARNIK_LIVE=1 to call OpenRouter/MCP")
async def test_live_multi_turn_dialogs() -> None:
    report = await run_dialogs(DIALOGS)
    failed = [item for item in report["results"] if item["status"] == "fail"]
    assert not failed, "\n".join(f"{item['id']}: {item['failures']}" for item in failed)
