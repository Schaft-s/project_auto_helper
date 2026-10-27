from __future__ import annotations

import os

import pytest

from tests.consult_cases import CASES
from tests.consult_harness import run_all

LIVE = os.environ.get("AUTONAPARNIK_LIVE") == "1"


@pytest.mark.live
@pytest.mark.skipif(not LIVE, reason="set AUTONAPARNIK_LIVE=1 to call OpenRouter/MCP")
async def test_live_consult_cases_model_sees_tool_data() -> None:
    report = await run_all(CASES)
    failed = [item for item in report["results"] if item["status"] == "fail"]
    assert report["total"] >= 30
    assert not failed, "\n".join(
        f"{item['id']}: {item['failures']} | got={item['got']}" for item in failed
    )
