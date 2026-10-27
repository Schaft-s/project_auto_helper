from __future__ import annotations

import json

from autonaparnik.adapters.nhtsa import LookupOutcome
from autonaparnik.adapters.openrouter import ChatResult
from autonaparnik.adapters.specialist import idle_run
from autonaparnik.application.orchestrator import (
    Orchestrator,
    _context_messages,
    clip_history,
    is_neutral_turn,
    user_history_only,
)
from autonaparnik.domain.models import (
    ChatRequest,
    Coverage,
    Discussions,
    HistoryMessage,
    KnownIssues,
    SpecialistBlock,
    SpecialistResult,
    SourcedClaim,
    ToolEvent,
    VehicleProfile,
)
from autonaparnik.retrieval.search import CorpusIndex
from autonaparnik.tools.discussions import DiscussionOutcome
from autonaparnik.tools.workshop import WorkshopOutcome
from autonaparnik.config import Settings


class ScriptedRouter:
    def __init__(self, script: list[ChatResult]):
        self.script = list(script)
        self.calls: list[list[dict]] = []
        self.tool_args: list = []

    async def chat(self, messages, tools=None, timeout=None, force_json=False, max_tokens=None):
        self.calls.append(messages)
        self.tool_args.append(tools)
        if not self.script:
            raise AssertionError("unexpected extra router call")
        return self.script.pop(0)


class FakeLookup:
    def __init__(self, outcome: LookupOutcome, event: ToolEvent):
        self.outcome = outcome
        self.event = event
        self.calls = []

    async def run(self, request, args, remaining):
        self.calls.append((request.vehicle.model_dump(), args.model_dump()))
        return self.outcome, self.event


class FakeWorkshop:
    def __init__(self, outcome: WorkshopOutcome):
        self.outcome = outcome
        self.calls = []

    async def run(self, request, args, remaining):
        self.calls.append(args.model_dump())
        return self.outcome


class FakeDiscussions:
    def __init__(self, outcome: DiscussionOutcome | None = None):
        self.outcome = outcome or _empty_discussions()
        self.calls = []

    async def run(self, request, args, remaining):
        self.calls.append(args.model_dump())
        return self.outcome


def _empty_lookup() -> LookupOutcome:
    known = KnownIssues(
        recalls=Coverage(status="empty", total_matching_count=0, returned_count=0, analyzed_count=0, pages_fetched=1, is_partial=False),
        complaints=Coverage(status="empty", total_matching_count=0, returned_count=0, analyzed_count=0, pages_fetched=1, is_partial=False),
        claims=[],
        limitations=["Пустая выборка не доказывает безопасность."],
    )
    return LookupOutcome(known_issues=known, evidence=[], status="ok", mode="live", elapsed_ms=1)


def _clip_chunk():
    hits = CorpusIndex.from_jsonl().search("фиксатор клипса", VehicleProfile(market="unknown"))
    assert hits
    return hits[0]


def _workshop_block(evidence_id: str) -> SpecialistBlock:
    return SpecialistBlock(
        result=SpecialistResult(
            task="post_repair_checks",
            status="general_only",
            summary="Проверить посадку клипсы; это общий ориентир.",
            checks=[
                {
                    "text": "Проверить, что фиксатор сел заподлицо.",
                    "relation": "required_check",
                    "evidence_ids": [evidence_id],
                }
            ],
            missing_information=[],
            limitations=["Демо-документ, не карта конкретной машины."],
        ),
        model_run={
            "executed": True,
            "stage": "base",
            "model_id": "deepseek/deepseek-v4.1-flash-1017",
            "base_revision": "specialist.v1",
            "artifact_sha256": "a" * 64,
            "latency_ms": 1,
            "raw_schema_valid": True,
            "repaired": False,
        },
        input_evidence_ids=[evidence_id],
    )


def test_user_history_strips_assistant() -> None:
    kept = user_history_only(
        [
            HistoryMessage(role="assistant", text="секретные шаги"),
            HistoryMessage(role="user", text="вопрос"),
        ]
    )
    assert [item.role for item in kept] == ["user"]


def test_context_messages_keep_history_and_plain_utterance() -> None:
    messages = _context_messages(
        ChatRequest(
            message="а у бмв семёрки 2020 года какие проблемы с этим?",
            vehicle=VehicleProfile(make="BMW", model="7 Series", model_year=2020, market="unknown"),
            history=[
                HistoryMessage(role="user", text="почему перегреваются машины"),
                HistoryMessage(role="assistant", text="Перегрев — когда охлаждение не успевает."),
            ],
        )
    )
    assert messages[0]["role"] == "system"
    assert "BMW 7 Series 2020" in messages[0]["content"]
    assert messages[1] == {"role": "user", "content": "почему перегреваются машины"}
    assert messages[-1]["content"] == "а у бмв семёрки 2020 года какие проблемы с этим?"
    assert "марка или null" not in json.dumps(messages, ensure_ascii=False)


def test_empty_vehicle_does_not_claim_missing_profile() -> None:
    messages = _context_messages(
        ChatRequest(
            message="стучит коробка",
            vehicle=VehicleProfile(market="unknown"),
        )
    )
    assert "профил" not in messages[0]["content"].lower()
    assert "/car" not in messages[0]["content"]


def test_clip_history_keeps_short_assistant() -> None:
    kept = clip_history(
        [
            HistoryMessage(role="user", text="перегрев"),
            HistoryMessage(role="assistant", text="A" * 800),
        ]
    )
    assert [item.role for item in kept] == ["user", "assistant"]
    assert len(kept[1].text) == 400


def test_neutral_turn_matches_thanks_not_followup() -> None:
    assert is_neutral_turn("спасибо")
    assert is_neutral_turn(" /help ")
    assert is_neutral_turn("Привет!")
    assert is_neutral_turn("как дела")
    assert not is_neutral_turn("спасибо, греется только в пробке")
    assert not is_neutral_turn("привет, вопрос по камри 3.5, почему расход огромный")


async def test_known_issues_without_vehicle_still_calls_router(settings: Settings) -> None:
    clarify = ChatResult(
        content=json.dumps(
            {
                "telegram_html": "Какая марка, модель и год? Напишите их в сообщении.",
                "questions": ["Какая марка, модель и год?"],
                "limitations": ["демо"],
                "route": "clarify",
            }
        ),
        tool_calls=[],
        raw_message={},
    )
    router = ScriptedRouter([clarify, clarify])
    orch = Orchestrator(
        settings,
        router,
        FakeLookup(_empty_lookup(), ToolEvent(tool="vehicle_safety_lookup", status="ok", mode="live", elapsed_ms=1)),
        FakeWorkshop(_unused_workshop()),
        FakeDiscussions(),
    )
    answer = await orch.handle(
        ChatRequest(
            message="Есть ли отзывы?",
            vehicle=VehicleProfile(market="unknown"),
            intent="known_issues",
        )
    )
    assert router.calls
    assert "марка" in answer.summary.lower()
    assert answer.tool_events == []


async def test_lookup_takes_vehicle_from_tool_args(settings: Settings) -> None:
    lookup = FakeLookup(
        _empty_lookup(),
        ToolEvent(tool="vehicle_safety_lookup", status="ok", mode="live", elapsed_ms=1),
    )
    router = ScriptedRouter(
        [
            ChatResult(
                content="",
                tool_calls=[
                    {
                        "id": "call_s",
                        "type": "function",
                        "function": {
                            "name": "vehicle_safety_lookup",
                            "arguments": json.dumps(
                                {
                                    "make": "Toyota",
                                    "model": "Camry",
                                    "model_year": 2015,
                                    "include_complaints": True,
                                }
                            ),
                        },
                    }
                ],
                raw_message={},
            ),
            ChatResult(
                content=json.dumps(
                    {
                        "telegram_html": "По Camry 2015 в NHTSA пустая выборка.",
                        "questions": [],
                        "limitations": ["демо"],
                        "route": "known_issues",
                    }
                ),
                tool_calls=[],
                raw_message={},
            ),
        ]
    )
    orch = Orchestrator(settings, router, lookup, FakeWorkshop(_unused_workshop()), FakeDiscussions())
    answer = await orch.handle(
        ChatRequest(
            message="Есть ли отзывы по Camry 2015?",
            vehicle=VehicleProfile(market="unknown"),
            intent="auto",
        )
    )
    assert lookup.calls[0][0]["make"] == "Toyota"
    assert lookup.calls[0][0]["model"] == "Camry"
    assert lookup.calls[0][0]["model_year"] == 2015
    assert answer.vehicle.make == "Toyota"
    assert answer.vehicle.model == "Camry"
    assert answer.vehicle.model_year == 2015


async def test_workshop_block_not_rewritten_and_opaque_tool_result(settings: Settings) -> None:
    chunk = _clip_chunk()
    block = _workshop_block(chunk.evidence.evidence_id)
    workshop = FakeWorkshop(
        WorkshopOutcome(
            block=block,
            chunks=[chunk],
            event=ToolEvent(tool="workshop_consult", status="ok", mode="fixture", elapsed_ms=1),
            opaque={"status": "general_only", "block_id": "B_secret", "has_checks": True},
        )
    )
    router = ScriptedRouter(
        [
            ChatResult(
                content="",
                tool_calls=[
                    {
                        "id": "call_w",
                        "type": "function",
                        "function": {
                            "name": "workshop_consult",
                            "arguments": json.dumps({"task": "post_repair_checks", "query": "дребезг панели"}),
                        },
                    }
                ],
                raw_message={},
            )
        ]
    )
    orch = Orchestrator(
        settings,
        router,
        FakeLookup(_empty_lookup(), ToolEvent(tool="vehicle_safety_lookup", status="ok", mode="live", elapsed_ms=1)),
        workshop,
        FakeDiscussions(),
    )
    answer = await orch.handle(
        ChatRequest(
            message="После установки декоративной панели появился дребезг. Что проверить?",
            vehicle=VehicleProfile(make="Acura", model="RDX", model_year=2012, market="US"),
            intent="workshop",
        )
    )
    assert answer.route == "workshop"
    assert answer.specialist is not None
    assert answer.specialist.result.checks[0].text == "Проверить, что фиксатор сел заподлицо."
    assert answer.summary == block.result.summary
    assert len(router.calls) == 1


async def test_lookup_tool_payload_to_router_has_no_workshop_steps(settings: Settings) -> None:
    chunk = _clip_chunk()
    block = _workshop_block(chunk.evidence.evidence_id)
    workshop = FakeWorkshop(
        WorkshopOutcome(
            block=block,
            chunks=[chunk],
            event=ToolEvent(tool="workshop_consult", status="ok", mode="fixture", elapsed_ms=1),
            opaque={"status": "general_only", "block_id": "B_secret", "has_checks": True},
        )
    )
    lookup_event = ToolEvent(tool="vehicle_safety_lookup", status="ok", mode="live", elapsed_ms=1)
    router = ScriptedRouter(
        [
            ChatResult(
                content="",
                tool_calls=[
                    {
                        "id": "call_s",
                        "type": "function",
                        "function": {"name": "vehicle_safety_lookup", "arguments": "{\"include_complaints\": true}"},
                    },
                    {
                        "id": "call_w",
                        "type": "function",
                        "function": {
                            "name": "workshop_consult",
                            "arguments": json.dumps({"task": "review_plan", "query": "план"}),
                        },
                    },
                ],
                raw_message={},
            ),
            ChatResult(
                content=json.dumps(
                    {
                        "summary": "Кратко по источникам, без диагноза.",
                        "questions": [],
                        "limitations": ["демо"],
                        "route": "combined",
                    }
                ),
                tool_calls=[],
                raw_message={},
            ),
        ]
    )
    orch = Orchestrator(settings, router, FakeLookup(_empty_lookup(), lookup_event), workshop, FakeDiscussions())
    answer = await orch.handle(
        ChatRequest(
            message="И отзывы, и план фиксатора",
            vehicle=VehicleProfile(make="Acura", model="RDX", model_year=2012, market="US"),
            intent="auto",
        )
    )
    assert answer.route == "combined"
    second = router.calls[1]
    dumped = json.dumps(second, ensure_ascii=False)
    assert "Проверить, что фиксатор сел заподлицо" not in dumped
    assert "B_secret" in dumped
    assert answer.specialist.result.checks[0].text.startswith("Проверить")


def _empty_discussions() -> DiscussionOutcome:
    return DiscussionOutcome(
        discussions=Discussions(status="empty", claims=[], limitations=["нет совпадений"]),
        chunks=[],
        event=ToolEvent(tool="search_discussions", status="ok", mode="fixture", elapsed_ms=1),
        payload={"status": "empty", "hits": []},
    )


def _unused_workshop() -> WorkshopOutcome:
    return WorkshopOutcome(
        block=SpecialistBlock(
            result=SpecialistResult(
                task="assembly_checklist",
                status="unavailable",
                summary="не должен вызываться",
                checks=[],
                missing_information=[],
                limitations=["x"],
            ),
            model_run=idle_run(),
            input_evidence_ids=[],
        ),
        chunks=[],
        event=ToolEvent(tool="workshop_consult", status="unavailable", mode="not_run", elapsed_ms=0),
        opaque={"status": "unavailable", "block_id": "B_x", "has_checks": False},
    )


async def test_discussions_excerpts_reach_router(settings: Settings) -> None:
    from autonaparnik.config import ROOT

    hits = CorpusIndex.from_jsonl(ROOT / "data" / "mechanics" / "qa.jsonl").search(
        "too much oil Acura TSX siphon", VehicleProfile(market="unknown")
    )
    chunk = next(hit for hit in hits if hit.document.document_id == "MSE-1125")
    outcome = DiscussionOutcome(
        discussions=Discussions(
            status="ok",
            claims=[SourcedClaim(text="Можно сифонить через щуп.", evidence_ids=[chunk.evidence.evidence_id])],
            limitations=["форум"],
        ),
        chunks=[chunk],
        event=ToolEvent(tool="search_discussions", status="ok", mode="fixture", elapsed_ms=1),
        payload={"status": "ok", "hits": [{"evidence_id": chunk.evidence.evidence_id, "excerpt": "siphon via dipstick"}]},
    )
    router = ScriptedRouter(
        [
            ChatResult(
                content="",
                tool_calls=[
                    {
                        "id": "call_d",
                        "type": "function",
                        "function": {"name": "search_discussions", "arguments": json.dumps({"query": "oil overfill"})},
                    }
                ],
                raw_message={},
            ),
            ChatResult(
                content=json.dumps(
                    {
                        "summary": "В обсуждении предлагают сифон через щуп, это не мануал.",
                        "questions": [],
                        "limitations": ["CC BY-SA"],
                        "route": "discussions",
                    }
                ),
                tool_calls=[],
                raw_message={},
            ),
        ]
    )
    orch = Orchestrator(
        settings,
        router,
        FakeLookup(_empty_lookup(), ToolEvent(tool="vehicle_safety_lookup", status="ok", mode="live", elapsed_ms=1)),
        FakeWorkshop(_unused_workshop()),
        FakeDiscussions(outcome),
    )
    answer = await orch.handle(
        ChatRequest(
            message="I poured too much oil into the Acura TSX, can I siphon it?",
            vehicle=VehicleProfile(make="Acura", model="TSX", model_year=2006, market="US"),
            intent="discussions",
        )
    )
    assert answer.route == "discussions"
    assert any(item.source_id == "MSE-1125" for item in answer.evidence)
    dumped = json.dumps(router.calls[1], ensure_ascii=False)
    assert "siphon via dipstick" in dumped


def test_select_evidence_keeps_cited_ids_when_over_limit() -> None:
    from datetime import datetime, timezone

    from autonaparnik.application.orchestrator import _select_evidence
    from autonaparnik.domain.models import Evidence

    def item(suffix: str) -> Evidence:
        return Evidence(
            evidence_id=f"ER_{suffix}",
            source_type="nhtsa_recall",
            source_id=suffix,
            title=f"Recall {suffix}",
            locator=suffix,
            url="https://www.nhtsa.gov/recalls",
            excerpt="x",
            retrieved_at=datetime(2026, 10, 26, tzinfo=timezone.utc),
            mode="live",
            applicability="matched",
            source_market="US",
        )

    many = [item(f"{i:03d}") for i in range(25)]
    cited = {"ER_021", "ER_022"}
    kept = _select_evidence(many, cited, limit=20)
    ids = [row.evidence_id for row in kept]
    assert "ER_021" in ids
    assert "ER_022" in ids
    assert len(kept) == 20


async def test_thanks_skips_tools_and_keeps_assistant_history(settings: Settings) -> None:
    router = ScriptedRouter(
        [
            ChatResult(
                content=json.dumps(
                    {
                        "telegram_html": "Пожалуйста.",
                        "questions": [],
                        "limitations": ["демо"],
                        "route": "general",
                    }
                ),
                tool_calls=[],
                raw_message={},
            )
        ]
    )
    orch = Orchestrator(
        settings,
        router,
        FakeLookup(_empty_lookup(), ToolEvent(tool="vehicle_safety_lookup", status="ok", mode="live", elapsed_ms=1)),
        FakeWorkshop(_unused_workshop()),
        FakeDiscussions(),
    )
    answer = await orch.handle(
        ChatRequest(
            message="спасибо",
            vehicle=VehicleProfile(market="unknown"),
            intent="auto",
            history=[
                HistoryMessage(role="user", text="бмв 320 li перегрев"),
                HistoryMessage(role="assistant", text="Проверить антифриз и вентилятор."),
            ],
        )
    )
    assert answer.route == "general"
    assert answer.tool_events == []
    assert router.tool_args == [None]
    assert len(router.calls) == 1
    dumped = json.dumps(router.calls[0], ensure_ascii=False)
    assert "Проверить антифриз" in dumped
    assert "Пожалуйста" in answer.summary
