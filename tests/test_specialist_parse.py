from __future__ import annotations

import json

from autonaparnik.adapters.openrouter import ChatResult
from autonaparnik.adapters.specialist import SpecialistAdapter, _try_parse
from autonaparnik.config import Settings
from autonaparnik.domain.models import ChatRequest, HistoryMessage, VehicleProfile, WorkshopArgs


def test_try_parse_drops_extra_fields_and_caps_checks() -> None:
    payload = {
        "task": "post_repair_checks",
        "status": "general_only",
        "summary": "ok",
        "extra": "drop me",
        "checks": [
            {
                "text": "проверить клипсу",
                "relation": "required_check",
                "evidence_ids": ["ETRIM-01"],
                "comment": "noise",
            }
        ]
        + [
            {"text": f"ещё {i}", "relation": "required_check", "evidence_ids": ["ETRIM-01"]}
            for i in range(20)
        ],
        "missing_information": [],
        "limitations": ["демо"],
    }

    parsed, ok = _try_parse("post_repair_checks", json.dumps(payload, ensure_ascii=False))
    assert ok and parsed is not None
    assert len(parsed.checks) == 7


def _ok_specialist_json(summary: str = "ok") -> str:
    return json.dumps(
        {
            "task": "assembly_checklist",
            "status": "general_only",
            "summary": summary,
            "checks": [
                {
                    "text": "Проверить посадку клипс и разъёмов.",
                    "relation": "required_check",
                    "evidence_ids": ["EASSUME"],
                }
            ],
            "missing_information": [],
            "limitations": ["демо"],
        },
        ensure_ascii=False,
    )


async def test_specialist_payload_includes_history_without_filled_vehicle(settings: Settings) -> None:
    captured: list[list[dict]] = []

    class CaptureRouter:
        async def chat(self, messages, tools=None, timeout=None, force_json=False, max_tokens=None):
            captured.append(messages)
            return ChatResult(content=_ok_specialist_json("Снять фару BMW 7."), tool_calls=[], raw_message={})

    adapter = SpecialistAdapter(settings, CaptureRouter())
    request = ChatRequest(
        message="другу фару снять собрать надо, как это сделать",
        vehicle=VehicleProfile(market="unknown"),
        history=[
            HistoryMessage(role="user", text="bmw 7 серии дорест 2021-2022"),
            HistoryMessage(role="assistant", text="BMW 7 Series 2021–2022 — на что смотреть."),
        ],
    )
    block = await adapter.consult(
        request,
        WorkshopArgs(task="assembly_checklist", query="BMW 7 Series снять фару"),
        [],
        remaining=30.0,
    )
    assert block.result.status == "general_only"
    assert captured
    payload = json.loads(captured[0][1]["content"])
    assert payload["vehicle"]["make"] is None
    assert payload["history"][0]["text"] == "bmw 7 серии дорест 2021-2022"
    assert "BMW 7 Series" in payload["query"]
    assert "фару" in payload["question"]


async def test_specialist_payload_keeps_car_switch_history(settings: Settings) -> None:
    captured: list[list[dict]] = []

    class CaptureRouter:
        async def chat(self, messages, tools=None, timeout=None, force_json=False, max_tokens=None):
            captured.append(messages)
            return ChatResult(content=_ok_specialist_json("Панель Civic."), tool_calls=[], raw_message={})

    adapter = SpecialistAdapter(settings, CaptureRouter())
    request = ChatRequest(
        message="нет, лучше honda civic 2012 — после панели дребезг",
        vehicle=VehicleProfile(market="unknown"),
        history=[
            HistoryMessage(role="user", text="смотрю audi a4 2018"),
            HistoryMessage(role="assistant", text="Audi A4 2018 — типичные болячки."),
        ],
    )
    await adapter.consult(
        request,
        WorkshopArgs(task="post_repair_checks", query="Honda Civic 2012 дребезг панели"),
        [],
        remaining=30.0,
    )
    payload = json.loads(captured[0][1]["content"])
    history_blob = json.dumps(payload["history"], ensure_ascii=False)
    assert "audi a4 2018" in history_blob.lower()
    assert "Honda Civic" in payload["query"]
    assert "дребезг" in payload["question"]


async def test_specialist_payload_followup_same_car_from_history(settings: Settings) -> None:
    captured: list[list[dict]] = []

    class CaptureRouter:
        async def chat(self, messages, tools=None, timeout=None, force_json=False, max_tokens=None):
            captured.append(messages)
            return ChatResult(content=_ok_specialist_json("Подкрылок."), tool_calls=[], raw_message={})

    adapter = SpecialistAdapter(settings, CaptureRouter())
    request = ChatRequest(
        message="а клипсы подкрылка на этой же машине как проверить?",
        vehicle=VehicleProfile(market="unknown"),
        history=[
            HistoryMessage(role="user", text="honda accord 2014, накладка консоли криво"),
            HistoryMessage(role="assistant", text="Проверить клипсы консоли Accord."),
        ],
    )
    await adapter.consult(
        request,
        WorkshopArgs(task="post_repair_checks", query="Honda Accord 2014 клипсы подкрылка"),
        [],
        remaining=30.0,
    )
    payload = json.loads(captured[0][1]["content"])
    assert any("accord" in item["text"].lower() for item in payload["history"])
    assert "подкрылка" in payload["question"]
    assert payload["vehicle"]["make"] is None
