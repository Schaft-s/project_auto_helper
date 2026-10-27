from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from autonaparnik.adapters.nhtsa import LookupOutcome
from autonaparnik.adapters.openrouter import ChatResult, OpenRouterClient
from autonaparnik.config import ORCHESTRATOR_PROMPT_VERSION, ROOT, TOOL_SCHEMAS, Settings
from autonaparnik.domain.models import (
    AnswerEnvelope,
    ChatRequest,
    DiscussionArgs,
    HistoryMessage,
    KnownIssues,
    SpecialistBlock,
    ToolEvent,
    VehicleSafetyArgs,
    WorkshopArgs,
)
from autonaparnik.jsonutil import extract_json_object
from autonaparnik.textutil import unique_questions
from autonaparnik.tools.discussions import DiscussionOutcome, SearchDiscussions
from autonaparnik.tools.vehicle_safety import VehicleSafetyLookup, merge_vehicle
from autonaparnik.tools.workshop import WorkshopConsult, WorkshopOutcome

DEFAULT_LIMITATIONS = [
    "Это консультация, не дистанционный диагноз и не подтверждение ремонта.",
]


def _orchestrator_prompt() -> str:
    return (ROOT / "prompts" / f"{ORCHESTRATOR_PROMPT_VERSION}.md").read_text(encoding="utf-8")


def user_history_only(history: list[HistoryMessage]) -> list[HistoryMessage]:
    return [item for item in history if item.role == "user"]


ASSISTANT_HISTORY_CHARS = 400
_NEUTRAL = {
    "привет",
    "здравствуйте",
    "здравствуй",
    "добрый день",
    "добрый вечер",
    "доброе утро",
    "хай",
    "ку",
    "hello",
    "hi",
    "спасибо",
    "спасибо большое",
    "благодарю",
    "спс",
    "thanks",
    "thx",
    "thank you",
    "ок",
    "окей",
    "okay",
    "ok",
    "хорошо",
    "ладно",
    "понял",
    "понятно",
    "ясно",
    "супер",
    "отлично",
    "принято",
    "все ясно",
    "всё ясно",
    "все понятно",
    "всё понятно",
    "help",
    "помощь",
    "что умеешь",
    "что ты умеешь",
    "как дела",
    "как ты",
    "как жизнь",
}


def clip_history(history: list[HistoryMessage]) -> list[HistoryMessage]:
    clipped: list[HistoryMessage] = []
    for item in history[-12:]:
        if item.role == "assistant":
            clipped.append(HistoryMessage(role="assistant", text=item.text[:ASSISTANT_HISTORY_CHARS]))
        else:
            clipped.append(item)
    return clipped


def is_neutral_turn(text: str) -> bool:
    cleaned = text.strip().lower()
    cleaned = re.sub(r"^[/.]+", "", cleaned)
    cleaned = re.sub(r"[.!?…,]+$", "", cleaned).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned in _NEUTRAL


def vehicle_complete(request: ChatRequest) -> bool:
    return bool(request.vehicle.make and request.vehicle.model and request.vehicle.model_year is not None)


@dataclass
class RunState:
    lookup: LookupOutcome | None = None
    workshop: WorkshopOutcome | None = None
    discussions: DiscussionOutcome | None = None
    events: list[ToolEvent] = field(default_factory=list)
    executed: set[str] = field(default_factory=set)
    router_calls: int = 0


class Orchestrator:
    def __init__(
        self,
        settings: Settings,
        router: OpenRouterClient,
        lookup: VehicleSafetyLookup,
        workshop: WorkshopConsult,
        discussions: SearchDiscussions,
    ):
        self.settings = settings
        self.router = router
        self.lookup = lookup
        self.workshop = workshop
        self.discussions = discussions
        self.prompt = _orchestrator_prompt()

    async def handle(self, request: ChatRequest) -> AnswerEnvelope:
        started = time.monotonic()
        deadline = started + self.settings.deadline_seconds
        request = request.model_copy(update={"history": clip_history(request.history)})
        trace_id = uuid.uuid4().hex[:16]
        state = RunState()

        neutral = is_neutral_turn(request.message)
        try:
            first = await self._router_call(
                request,
                [],
                tools=None if neutral else TOOL_SCHEMAS,
                deadline=deadline,
                state=state,
                force_json=neutral,
            )
        except Exception:
            return _error_envelope(trace_id, request, "Сильная модель недоступна; вымышленную консультацию не составляю.")

        if not neutral:
            await self._execute_tools(request, first.tool_calls, state, deadline)
            draft = await self._compose(request, first, state, deadline)
        else:
            draft = self._compose_neutral(first)
        try:
            return self._build_envelope(trace_id, request, draft, state)
        except Exception:
            return _error_envelope(trace_id, request, "Не удалось собрать проверяемый ответ по источникам.")

    async def _router_call(
        self,
        request: ChatRequest,
        extra_messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None,
        deadline: float,
        state: RunState,
        force_json: bool = False,
    ) -> ChatResult:
        if state.router_calls >= self.settings.router_calls_max:
            raise RuntimeError("router budget exhausted")
        remaining = deadline - time.monotonic()
        if remaining <= 1:
            raise RuntimeError("deadline")
        messages = [{"role": "system", "content": self.prompt}, *_context_messages(request), *extra_messages]
        state.router_calls += 1
        timeout = min(self.settings.router_call_timeout_seconds, remaining)
        return await self.router.chat(messages, tools=tools, timeout=timeout, force_json=force_json)

    async def _execute_tools(
        self, request: ChatRequest, tool_calls: list[dict[str, Any]], state: RunState, deadline: float
    ) -> None:
        remaining = deadline - time.monotonic()
        for call in tool_calls:
            name = (call.get("function") or {}).get("name")
            if name in state.executed:
                continue
            if name not in {"vehicle_safety_lookup", "workshop_consult", "search_discussions"}:
                continue
            arguments = _args((call.get("function") or {}).get("arguments"))
            if name == "vehicle_safety_lookup":
                args = VehicleSafetyArgs.model_validate(arguments)
                request.vehicle = merge_vehicle(request.vehicle, args)
                outcome, event = await self.lookup.run(request, args, remaining)
                state.lookup = outcome
                state.events.append(event)
            elif name == "workshop_consult":
                if "query" not in arguments:
                    arguments["query"] = request.message[:2000]
                args = WorkshopArgs.model_validate(arguments)
                state.workshop = await self.workshop.run(request, args, remaining)
                state.events.append(state.workshop.event)
            elif name == "search_discussions":
                if "query" not in arguments:
                    arguments["query"] = request.message[:2000]
                args = DiscussionArgs.model_validate(arguments)
                state.discussions = await self.discussions.run(request, args, remaining)
                state.events.append(state.discussions.event)
            state.executed.add(name)

    async def _compose(
        self, request: ChatRequest, first: ChatResult, state: RunState, deadline: float
    ) -> dict[str, Any]:
        if state.workshop and not state.lookup and not state.discussions:
            result = state.workshop.block.result
            return {
                "summary": result.summary[:2800],
                "questions": result.missing_information[:2],
                "limitations": (result.limitations or DEFAULT_LIMITATIONS)[:1],
                "route": "workshop",
            }
        extra = []
        if first.tool_calls:
            extra.append({"role": "assistant", "content": first.content or None, "tool_calls": first.tool_calls})
            extra.extend(_tool_messages(first.tool_calls, state))
        extra.append(
            {
                "role": "user",
                "content": (
                    "Собери итоговый JSON: telegram_html, questions, limitations, route. "
                    "В telegram_html — готовый ответ без дублей уточнений, сырых цитат и сборочных шагов. "
                    "questions пустой, если уточнения уже в telegram_html."
                ),
            }
        )
        try:
            second = await self._router_call(
                request, extra, tools=None, deadline=deadline, state=state, force_json=True
            )
            draft = extract_json_object(second.content)
        except Exception:
            draft = {
                "summary": _fallback_summary(state, request),
                "questions": [],
                "limitations": DEFAULT_LIMITATIONS,
                "route": _route_from_state(state),
            }
        html = str(draft.get("telegram_html") or draft.get("summary") or _fallback_summary(state, request))
        draft["summary"] = html[:2800]
        draft.setdefault("questions", [])
        draft.setdefault("limitations", DEFAULT_LIMITATIONS)
        draft.setdefault("route", _route_from_state(state))
        return draft

    def _compose_neutral(self, first: ChatResult) -> dict[str, Any]:
        try:
            draft = extract_json_object(first.content)
        except Exception:
            draft = {}
        html = str(draft.get("telegram_html") or draft.get("summary") or "Чем помочь по машине?")
        return {
            "summary": html[:800],
            "questions": [],
            "limitations": DEFAULT_LIMITATIONS,
            "route": "general",
        }

    def _build_envelope(
        self, trace_id: str, request: ChatRequest, draft: dict[str, Any], state: RunState
    ) -> AnswerEnvelope:
        evidence = []
        if state.lookup:
            evidence.extend(state.lookup.evidence)
        if state.workshop:
            evidence.extend(chunk.evidence for chunk in state.workshop.chunks)
            if state.workshop.assumed_evidence is not None:
                evidence.append(state.workshop.assumed_evidence)
        if state.discussions:
            evidence.extend(chunk.evidence for chunk in state.discussions.chunks)
        specialist = state.workshop.block if state.workshop else None
        known = state.lookup.known_issues if state.lookup else None
        discussions = state.discussions.discussions if state.discussions else None
        allowed_routes = {"clarify", "known_issues", "workshop", "discussions", "combined", "general"}
        route = draft.get("route") if draft.get("route") in allowed_routes else _route_from_state(state)
        if _source_count(state) >= 2:
            route = "combined"
        elif specialist:
            route = "workshop"
        elif known:
            route = "known_issues"
        elif discussions:
            route = "discussions"
        summary = str(draft.get("summary") or _fallback_summary(state, request))[:2800]
        if not summary:
            summary = "Нужны дополнительные сведения."
        questions = [str(item)[:500] for item in (draft.get("questions") or []) if str(item).strip()][:2]
        if state.lookup and state.lookup.questions:
            questions = (state.lookup.questions + questions)[:2]
        if vehicle_complete(request):
            questions = [item for item in questions if not _asks_vehicle_identity(item)][:2]
        questions = unique_questions(questions, summary, limit=2)
        limitations = [str(item)[:500] for item in (draft.get("limitations") or []) if str(item).strip()]
        if not limitations:
            limitations = list(DEFAULT_LIMITATIONS)
        if request.vehicle.market != "US" and known is not None and all("рынк" not in item.lower() for item in limitations):
            limitations.append("Данные NHTSA относятся к рынку США.")
        status = _envelope_status(route, state, specialist, known)
        cited: set[str] = set()
        if known:
            for claim in known.claims:
                cited.update(claim.evidence_ids)
        if discussions:
            for claim in discussions.claims:
                cited.update(claim.evidence_ids)
        if specialist:
            cited.update(specialist.input_evidence_ids)
            for check in specialist.result.checks:
                cited.update(check.evidence_ids)
        evidence = _select_evidence(evidence, cited, limit=20)
        kept_ids = {item.evidence_id for item in evidence}
        if known:
            known = known.model_copy(
                update={"claims": [claim for claim in known.claims if set(claim.evidence_ids).issubset(kept_ids)]}
            )
        if discussions:
            discussions = discussions.model_copy(
                update={
                    "claims": [claim for claim in discussions.claims if set(claim.evidence_ids).issubset(kept_ids)]
                }
            )
        return AnswerEnvelope(
            schema_version="2.0",
            trace_id=trace_id,
            status=status,
            route=route,
            vehicle=request.vehicle,
            summary=summary,
            known_issues=known,
            specialist=specialist,
            questions=questions[:3],
            limitations=limitations[:8],
            discussions=discussions,
            evidence=evidence,
            tool_events=state.events[:3],
        )


def _select_evidence(items: list, cited: set[str], limit: int = 20) -> list:
    unique = []
    seen: set[str] = set()
    for item in items:
        if item.evidence_id in seen:
            continue
        seen.add(item.evidence_id)
        unique.append(item)
    cited_items = [item for item in unique if item.evidence_id in cited]
    rest = [item for item in unique if item.evidence_id not in cited]
    return (cited_items + rest)[:limit]


def _vehicle_line(vehicle) -> str:
    parts = [vehicle.make, vehicle.model, str(vehicle.model_year) if vehicle.model_year is not None else None]
    name = " ".join(part for part in parts if part)
    if not name:
        return ""
    return (
        f"Уже известные данные машины: {name}, рынок {vehicle.market}. "
        "Марку, модель и год из текста не переспрашивай."
    )


def _asks_vehicle_identity(text: str) -> bool:
    return bool(re.search(r"марка|модель|/car|модельн(?:ый|ого)\s+год", text, re.IGNORECASE))


def _context_messages(request: ChatRequest) -> list[dict[str, Any]]:
    header = f"Аудитория: {request.audience}."
    extra = _vehicle_line(request.vehicle)
    if extra:
        header = f"{header}\n{extra}"
    messages = [{"role": "system", "content": header}]
    for item in request.history[-12:]:
        role = "assistant" if item.role == "assistant" else "user"
        messages.append({"role": role, "content": item.text})
    messages.append({"role": "user", "content": request.message})
    return messages


def _args(raw: Any) -> dict[str, Any]:
    if raw in (None, ""):
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _tool_messages(tool_calls: list[dict[str, Any]], state: RunState) -> list[dict[str, Any]]:
    messages = []
    for call in tool_calls:
        name = (call.get("function") or {}).get("name")
        call_id = call.get("id") or name
        if name == "vehicle_safety_lookup" and state.lookup:
            payload = _compact_lookup(state.lookup)
        elif name == "workshop_consult" and state.workshop:
            payload = state.workshop.opaque
        elif name == "search_discussions" and state.discussions:
            payload = _compact_discussions(state.discussions)
        else:
            payload = {"status": "unavailable"}
        messages.append({"role": "tool", "tool_call_id": call_id, "content": json.dumps(payload, ensure_ascii=False)})
    return messages


def _compact_lookup(outcome: LookupOutcome) -> dict[str, Any]:
    issues = outcome.known_issues
    claims = [{"text": claim.text[:120], "evidence_ids": claim.evidence_ids} for claim in issues.claims[:4]]
    links = []
    seen: set[str] = set()
    for item in outcome.evidence:
        if not item.url or not item.url.startswith("https://") or item.url in seen:
            continue
        seen.add(item.url)
        kind = "recall" if item.source_type == "nhtsa_recall" else "complaint"
        links.append({"kind": kind, "source_id": item.source_id, "url": item.url})
        if len(links) >= 3:
            break
    return {
        "status": outcome.status,
        "recalls": {"status": issues.recalls.status, "count": issues.recalls.returned_count},
        "complaints": {"status": issues.complaints.status, "count": issues.complaints.returned_count},
        "claims": claims,
        "links": links,
        "questions": outcome.questions[:2],
        "hint": "1–3 факта своими словами. Не копируй claims дословно.",
    }


def _compact_discussions(outcome: DiscussionOutcome) -> dict[str, Any]:
    hits = []
    for raw in (outcome.payload.get("hits") or [])[:4]:
        if not isinstance(raw, dict):
            continue
        hits.append(
            {
                "evidence_id": raw.get("evidence_id"),
                "url": raw.get("url"),
                "fact": str(raw.get("excerpt") or raw.get("title") or "")[:120],
                "collection": raw.get("collection"),
            }
        )
    return {
        "status": outcome.payload.get("status") or outcome.discussions.status,
        "hits": hits,
        "limitations": (outcome.payload.get("limitations") or outcome.discussions.limitations)[:1],
        "hint": "1–3 факта своими словами. Не копируй hits дословно.",
    }


def _source_count(state: RunState) -> int:
    return int(state.lookup is not None) + int(state.workshop is not None) + int(state.discussions is not None)


def _route_from_state(state: RunState) -> str:
    if _source_count(state) >= 2:
        return "combined"
    if state.workshop:
        return "workshop"
    if state.lookup:
        return "known_issues"
    if state.discussions:
        return "discussions"
    return "general"


def _fallback_summary(state: RunState, request: ChatRequest) -> str:
    if state.workshop:
        return state.workshop.block.result.summary
    if state.lookup and state.lookup.status == "needs_context":
        return "Для поиска по NHTSA не хватает марки, модели и года. Напишите их в сообщении."
    if state.lookup and state.lookup.known_issues.claims:
        return "Нашёл сведения NHTSA по машине. Это не диагноз конкретного автомобиля."
    if state.discussions and state.discussions.discussions.claims:
        return "Нашёл похожие обсуждения. Это не официальная инструкция."
    return "Могу поискать отзывы NHTSA, обсуждения на форуме или подсказать по сборке."


def _envelope_status(route: str, state: RunState, specialist: SpecialistBlock | None, known: KnownIssues | None) -> str:
    if route == "clarify" or (state.lookup and state.lookup.status == "needs_context" and specialist is None):
        return "needs_clarification"
    if specialist and specialist.result.status == "out_of_scope" and known is None:
        return "out_of_scope"
    if specialist and specialist.result.status == "unavailable":
        return "partial"
    if known and known.recalls.status == "unavailable" and known.complaints.status == "unavailable":
        return "partial"
    if known and (known.recalls.status == "unavailable" or known.complaints.status == "unavailable"):
        return "partial"
    return "ok"


def _error_envelope(trace_id: str, request: ChatRequest, summary: str) -> AnswerEnvelope:
    return AnswerEnvelope(
        schema_version="2.0",
        trace_id=trace_id,
        status="error",
        route="general",
        vehicle=request.vehicle,
        summary=summary,
        known_issues=None,
        specialist=None,
        questions=[],
        limitations=DEFAULT_LIMITATIONS,
        evidence=[],
        tool_events=[],
    )
