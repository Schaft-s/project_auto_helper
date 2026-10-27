"""Record router traffic and check that tool payloads actually reach the model."""

from __future__ import annotations

import json
import re
from typing import Any

from autonaparnik.adapters.openrouter import ChatResult
from autonaparnik.domain.models import AnswerEnvelope, ChatRequest, HistoryMessage, VehicleProfile
from autonaparnik.factory import build_orchestrator

STOP = {
    "this",
    "that",
    "with",
    "from",
    "have",
    "been",
    "will",
    "your",
    "about",
    "there",
    "their",
    "which",
    "would",
    "could",
    "should",
    "after",
    "before",
    "owner",
    "nhtsa",
    "https",
    "кампания",
    "сообщение",
    "владельца",
    "отзывн",
}


class RecordingRouter:
    def __init__(self, inner):
        self.inner = inner
        self.calls: list[dict[str, Any]] = []

    async def chat(self, messages, **kwargs) -> ChatResult:
        result = await self.inner.chat(messages, **kwargs)
        self.calls.append(
            {
                "messages": messages,
                "tools": kwargs.get("tools"),
                "force_json": kwargs.get("force_json"),
                "content": result.content,
                "tool_calls": result.tool_calls,
            }
        )
        return result


def attach_recorder(orch) -> RecordingRouter:
    recorder = RecordingRouter(orch.router)
    orch.router = recorder
    orch.workshop.specialist.router = recorder
    return recorder


def dump_calls(recorder: RecordingRouter) -> str:
    return json.dumps(
        [
            {
                "force_json": call["force_json"],
                "tool_calls": [item["function"]["name"] for item in call["tool_calls"]],
                "messages": call["messages"],
                "content": (call["content"] or "")[:800],
            }
            for call in recorder.calls
        ],
        ensure_ascii=False,
    )


def _tool_blobs(recorder: RecordingRouter) -> list[str]:
    blobs = []
    for call in recorder.calls:
        for message in call["messages"]:
            if message.get("role") == "tool":
                blobs.append(str(message.get("content") or ""))
    return blobs


def _specialist_blobs(recorder: RecordingRouter) -> list[str]:
    blobs = []
    for call in recorder.calls:
        for message in call["messages"]:
            if message.get("role") != "user":
                continue
            text = str(message.get("content") or "")
            if '"evidence"' in text and '"task"' in text:
                blobs.append(text)
    return blobs


def _compose_outputs(recorder: RecordingRouter) -> str:
    parts = []
    for call in recorder.calls:
        if call.get("force_json") and not call.get("tool_calls"):
            parts.append(call.get("content") or "")
        elif call.get("force_json") and any(
            '"evidence"' in str(m.get("content") or "") for m in call["messages"] if m.get("role") == "user"
        ):
            parts.append(call.get("content") or "")
    return "\n".join(parts)


def _tokens(text: str) -> list[str]:
    found = []
    for raw in re.findall(r"\b\d{2}[A-Z]?\d{3,}\b|\b\d{7,}\b", text or ""):
        found.append(raw)
    for raw in re.findall(r"[A-Za-zА-Яа-яЁё]{5,}", text or ""):
        low = raw.lower()
        if low in STOP:
            continue
        found.append(raw)
    return found[:12]


def _used(needles: list[str], haystack: str) -> bool:
    blob = haystack.lower()
    hits = 0
    for needle in needles:
        if needle.lower() in blob:
            hits += 1
    return hits >= 1


def evaluate_visibility(case: dict, answer: AnswerEnvelope, recorder: RecordingRouter) -> list[str]:
    expect = case["expect"]
    failures: list[str] = []
    tools = [event.tool for event in answer.tool_events]
    for name in expect.get("tools_include") or []:
        if name not in tools:
            failures.append(f"missing tool {name}; got {tools}")
    for name in expect.get("tools_exclude") or []:
        if name in tools:
            failures.append(f"unexpected tool {name}; got {tools}")

    tool_text = "\n".join(_tool_blobs(recorder))
    specialist_text = "\n".join(_specialist_blobs(recorder))
    model_out = " ".join([answer.summary, *answer.questions, _compose_outputs(recorder)])
    if answer.specialist:
        model_out += " " + answer.specialist.result.summary
        model_out += " " + " ".join(check.text for check in answer.specialist.result.checks)

    if expect.get("see_lookup"):
        if "vehicle_safety_lookup" not in tools:
            failures.append("see_lookup: lookup was not executed")
        elif not tool_text:
            failures.append("see_lookup: no tool-role payload reached the model")
        elif answer.known_issues and answer.known_issues.claims:
            snippet = answer.known_issues.claims[0].text[:48]
            if snippet not in tool_text:
                failures.append(f"see_lookup: claim missing from tool payload: {snippet!r}")
            if '"links"' not in tool_text and "nhtsa.gov" not in tool_text.lower():
                if answer.known_issues.recalls.returned_count or answer.known_issues.complaints.returned_count:
                    failures.append("see_lookup: links/nhtsa.gov not in tool payload")
        elif answer.known_issues:
            status = answer.known_issues.recalls.status
            if str(status) not in tool_text and '"status"' not in tool_text:
                failures.append("see_lookup: empty/status payload not visible")

    if expect.get("use_lookup") and answer.known_issues:
        claims = answer.known_issues.claims
        needles = []
        for claim in claims[:4]:
            needles.extend(_tokens(claim.text)[:3])
            if ":" in claim.text:
                needles.append(claim.text.split(":", 1)[0].replace("Кампания", "").replace("Сообщение владельца", "").strip())
        empty = not claims
        if empty:
            blob = answer.summary.lower()
            if not any(word in blob for word in ("нет", "не найден", "пуст", "не числ", "отсутств", "не найдены", "nhtsa")):
                failures.append("use_lookup: empty NHTSA result not reflected in summary")
        elif needles and not _used(needles, model_out):
            if not any(word in answer.summary.lower() for word in ("кампан", "жалоб", "отзыв", "nhtsa", "odi")):
                failures.append(f"use_lookup: summary ignores lookup facts {needles[:6]}")

    if expect.get("see_discussions"):
        if "search_discussions" not in tools:
            failures.append("see_discussions: search_discussions was not executed")
        elif not tool_text:
            failures.append("see_discussions: no tool-role payload reached the model")
        elif answer.discussions and answer.discussions.claims:
            snippet = answer.discussions.claims[0].text[:40]
            if snippet not in tool_text:
                failures.append(f"see_discussions: excerpt missing from tool payload: {snippet!r}")
            if "mechanics.stackexchange.com" not in tool_text and "openlibrary-repo" not in tool_text and '"hits"' not in tool_text:
                failures.append("see_discussions: hits/urls missing from tool payload")

    if expect.get("use_discussions") and answer.discussions and answer.discussions.claims:
        needles = []
        for claim in answer.discussions.claims[:3]:
            needles.extend(_tokens(claim.text)[:3])
        if needles and not _used(needles, model_out):
            if "форум" not in answer.summary.lower() and "обсужд" not in answer.summary.lower() and "stack" not in answer.summary.lower():
                failures.append(f"use_discussions: summary ignores discussion excerpts {needles[:6]}")

    if expect.get("see_workshop"):
        if "workshop_consult" not in tools:
            failures.append("see_workshop: workshop_consult was not executed")
        elif not specialist_text:
            failures.append("see_workshop: specialist did not receive an evidence payload")
        elif '"content"' not in specialist_text and '"title"' not in specialist_text:
            failures.append("see_workshop: RAG chunks missing from specialist input")

    if expect.get("use_workshop"):
        if answer.specialist is None:
            failures.append("use_workshop: no specialist block")
        elif answer.specialist.result.status in {"grounded", "general_only"} and not answer.specialist.result.checks:
            failures.append("use_workshop: specialist returned no checks")
        elif answer.specialist and specialist_text:
            cited = {eid for check in answer.specialist.result.checks for eid in check.evidence_ids}
            if cited and not any(eid in specialist_text for eid in cited):
                failures.append(f"use_workshop: cited ids {cited} were not in specialist input")

    blob = " ".join([answer.summary, *answer.questions, *answer.limitations]).lower()
    if answer.specialist:
        blob += " " + answer.specialist.result.summary.lower()
        blob += " " + " ".join(check.text.lower() for check in answer.specialist.result.checks)
    wanted = expect.get("summary_must_any") or []
    if wanted and not any(needle.lower() in answer.summary.lower() for needle in wanted):
        failures.append(f"summary misses all of {wanted}")
    for needle in expect.get("must_not") or []:
        if needle.lower() in blob:
            failures.append(f"forbidden text: {needle}")
    return failures


async def run_case(case: dict, orch, recorder: RecordingRouter) -> dict:
    recorder.calls.clear()
    raw = dict(case["request"])
    raw.setdefault("audience", "owner")
    raw.setdefault("intent", "auto")
    raw.setdefault("history", [])
    request = ChatRequest.model_validate(raw)
    try:
        answer = await orch.handle(request)
    except Exception as exc:
        return {
            "id": case["id"],
            "group": case.get("group"),
            "note": case.get("note"),
            "status": "fail",
            "failures": [f"exception: {type(exc).__name__}: {exc}"],
            "got": {
                "status": "error",
                "route": None,
                "tools": [],
                "first_tool_calls": [],
                "router_calls": len(recorder.calls),
                "lookup_claims": [],
                "discussion_excerpts": [],
                "specialist": None,
                "summary": "",
                "tool_payload_chars": 0,
                "specialist_payload_chars": 0,
            },
        }
    failures = evaluate_visibility(case, answer, recorder)
    first_tools = []
    if recorder.calls:
        first_tools = [item["function"]["name"] for item in recorder.calls[0]["tool_calls"]]
    return {
        "id": case["id"],
        "group": case.get("group"),
        "note": case.get("note"),
        "status": "fail" if failures else "pass",
        "failures": failures,
        "got": {
            "status": answer.status,
            "route": answer.route,
            "tools": [event.tool for event in answer.tool_events],
            "first_tool_calls": first_tools,
            "router_calls": len(recorder.calls),
            "lookup_claims": [claim.text for claim in (answer.known_issues.claims if answer.known_issues else [])][:3],
            "discussion_excerpts": [claim.text for claim in (answer.discussions.claims if answer.discussions else [])][:2],
            "specialist": answer.specialist.result.status if answer.specialist else None,
            "summary": answer.summary[:400],
            "tool_payload_chars": sum(len(blob) for blob in _tool_blobs(recorder)),
            "specialist_payload_chars": sum(len(blob) for blob in _specialist_blobs(recorder)),
        },
    }


async def run_all(cases: list[dict]) -> dict:
    orch = build_orchestrator()
    recorder = attach_recorder(orch)
    results = []
    for case in cases:
        results.append(await run_case(case, orch, recorder))
    failed = [item for item in results if item["status"] == "fail"]
    return {"results": results, "passed": len(results) - len(failed), "failed": len(failed), "total": len(results)}


def evaluate_dialog_step(step: dict, answer: AnswerEnvelope, recorder: RecordingRouter) -> list[str]:
    expect = step["expect"]
    failures: list[str] = []
    tools = [event.tool for event in answer.tool_events]
    for name in expect.get("tools_include") or []:
        if name not in tools:
            failures.append(f"missing tool {name}; got {tools}")
    for name in expect.get("tools_exclude") or []:
        if name in tools:
            failures.append(f"unexpected tool {name}; got {tools}")
    if expect.get("route_in") and answer.route not in expect["route_in"]:
        failures.append(f"route {answer.route} not in {expect['route_in']}")
    if expect.get("max_chars") and len(answer.summary) > expect["max_chars"]:
        failures.append(f"summary {len(answer.summary)} > {expect['max_chars']}")
    blob = answer.summary.lower()
    wanted = expect.get("must_any") or []
    if wanted and not any(needle.lower() in blob for needle in wanted):
        failures.append(f"summary misses all of {wanted}")
    for needle in expect.get("must_not") or []:
        if needle.lower() in blob:
            failures.append(f"forbidden text: {needle}")
    return failures


async def run_dialog(dialog: dict, orch, recorder: RecordingRouter) -> dict:
    history: list[HistoryMessage] = []
    vehicle = VehicleProfile()
    step_results = []
    for index, step in enumerate(dialog["steps"], 1):
        recorder.calls.clear()
        request = ChatRequest(
            message=step["message"],
            vehicle=vehicle,
            intent="auto",
            history=list(history),
        )
        try:
            answer = await orch.handle(request)
        except Exception as exc:
            step_results.append(
                {
                    "step": index,
                    "message": step["message"],
                    "status": "fail",
                    "failures": [f"exception: {type(exc).__name__}: {exc}"],
                    "got": {"summary": "", "tools": [], "route": None},
                }
            )
            break
        failures = evaluate_dialog_step(step, answer, recorder)
        history.append(HistoryMessage(role="user", text=step["message"]))
        history.append(HistoryMessage(role="assistant", text=answer.summary[:400]))
        step_results.append(
            {
                "step": index,
                "message": step["message"],
                "status": "fail" if failures else "pass",
                "failures": failures,
                "got": {
                    "route": answer.route,
                    "tools": [event.tool for event in answer.tool_events],
                    "summary": answer.summary[:400],
                    "questions": answer.questions,
                },
            }
        )
    failed = [item for item in step_results if item["status"] == "fail"]
    return {
        "id": dialog["id"],
        "note": dialog.get("note"),
        "status": "fail" if failed else "pass",
        "failures": [f"step {item['step']}: {item['failures']}" for item in failed],
        "steps": step_results,
    }


async def run_dialogs(dialogs: list[dict]) -> dict:
    orch = build_orchestrator()
    recorder = attach_recorder(orch)
    results = []
    for dialog in dialogs:
        results.append(await run_dialog(dialog, orch, recorder))
    failed = [item for item in results if item["status"] == "fail"]
    return {"results": results, "passed": len(results) - len(failed), "failed": len(failed), "total": len(results)}
