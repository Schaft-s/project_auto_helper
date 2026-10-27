from __future__ import annotations

import hashlib
import json
import time

from pydantic import ValidationError

from autonaparnik.adapters.openrouter import OpenRouterClient
from autonaparnik.config import ASSUME_EVIDENCE_ID, ROOT, SPECIALIST_PROMPT_VERSION, Settings
from autonaparnik.domain.models import (
    ChatRequest,
    ModelRun,
    SpecialistBlock,
    SpecialistResult,
    WorkshopArgs,
)
from autonaparnik.jsonutil import extract_json_object
from autonaparnik.retrieval.search import RetrievedChunk


def _prompt() -> str:
    return (ROOT / "prompts" / f"{SPECIALIST_PROMPT_VERSION}.md").read_text(encoding="utf-8")


def provenance_hash(model_id: str, prompt_version: str) -> str:
    return hashlib.sha256(f"{model_id}|{prompt_version}".encode("utf-8")).hexdigest()


def idle_run(latency_ms: float = 0.0) -> ModelRun:
    return ModelRun(
        executed=False,
        stage="not_run",
        model_id=None,
        base_revision=None,
        artifact_sha256=None,
        latency_ms=latency_ms,
        raw_schema_valid=False,
        repaired=False,
    )


class SpecialistAdapter:
    def __init__(self, settings: Settings, router: OpenRouterClient):
        self.settings = settings
        self.router = router
        self.prompt = _prompt()

    async def consult(
        self,
        request: ChatRequest,
        args: WorkshopArgs,
        chunks: list[RetrievedChunk],
        remaining: float,
        caution: str | None = None,
    ) -> SpecialistBlock:
        evidence_ids = [chunk.evidence.evidence_id for chunk in chunks]
        if not evidence_ids:
            evidence_ids = [ASSUME_EVIDENCE_ID]
        user_payload = {
            "task": args.task,
            "audience": request.audience,
            "vehicle": request.vehicle.model_dump(),
            "question": request.message,
            "query": args.query,
            "user_plan": args.user_plan,
            "caution": caution,
            "evidence": [
                {
                    "evidence_id": chunk.evidence.evidence_id,
                    "title": chunk.document.title,
                    "applicability": chunk.evidence.applicability,
                    "transfer_scope": chunk.document.transfer_scope,
                    "operation_type": chunk.document.operation_type,
                    "content": chunk.document.content[:4000],
                }
                for chunk in chunks
            ],
        }
        messages = [
            {"role": "system", "content": self.prompt},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ]
        started = time.perf_counter()
        raw_valid = False
        repaired = False
        parsed: SpecialistResult | None = None
        calls = 0
        timeout = min(self.settings.specialist_call_timeout_seconds, max(1.0, remaining))
        try:
            first = await self.router.chat(messages, timeout=timeout, force_json=True, max_tokens=1200)
            calls += 1
            parsed, raw_valid = _try_parse(args.task, first.content)
            if parsed is None and calls < self.settings.specialist_calls_max:
                repaired = True
                repair_messages = messages + [
                    {"role": "assistant", "content": first.content or ""},
                    {
                        "role": "user",
                        "content": (
                            "Ответ не прошёл схему SpecialistResult. Верни исправленный JSON: "
                            "task, status, summary, checks (4-7), missing_information, limitations. "
                            "Cite evidence_id из входа или EASSUME. Без markdown."
                        ),
                    },
                ]
                second = await self.router.chat(
                    repair_messages, timeout=timeout, force_json=True, max_tokens=1200
                )
                parsed, valid_after = _try_parse(args.task, second.content)
                raw_valid = valid_after
        except Exception:
            parsed = None
        latency_ms = (time.perf_counter() - started) * 1000
        model_run = ModelRun(
            executed=True,
            stage="base",
            model_id=self.settings.openrouter_model,
            base_revision=SPECIALIST_PROMPT_VERSION,
            artifact_sha256=provenance_hash(self.settings.openrouter_model, SPECIALIST_PROMPT_VERSION),
            latency_ms=latency_ms,
            raw_schema_valid=raw_valid,
            repaired=repaired,
        )
        if parsed is None:
            result = SpecialistResult(
                task=args.task,
                status="unavailable",
                summary="Специалист не вернул проверяемый JSON. Сборочный блок недоступен.",
                checks=[],
                missing_information=[],
                limitations=["Непроверенный текст модели скрыт."],
            )
            return SpecialistBlock(result=result, model_run=model_run, input_evidence_ids=evidence_ids)

        parsed = _sanitize_citations(parsed, evidence_ids)
        if parsed.status in {"grounded", "general_only"} and not parsed.checks:
            parsed = parsed.model_copy(
                update={
                    "status": "general_only",
                    "checks": [
                        {
                            "text": "Проверить посадку всех видимых фиксаторов и отсутствие перекоса панели.",
                            "relation": "required_check",
                            "evidence_ids": [evidence_ids[0]],
                        }
                    ],
                    "summary": parsed.summary or "Типовая проверка посадки после сборки.",
                }
            )
        try:
            return SpecialistBlock(result=parsed, model_run=model_run, input_evidence_ids=evidence_ids)
        except ValidationError:
            fallback = SpecialistResult(
                task=args.task,
                status="unavailable",
                summary="Результат специалиста отклонён проверкой ссылок.",
                checks=[],
                missing_information=[],
                limitations=["Непроверенный текст модели скрыт."],
            )
            return SpecialistBlock(result=fallback, model_run=model_run, input_evidence_ids=evidence_ids)


def _try_parse(task: str, text: str) -> tuple[SpecialistResult | None, bool]:
    try:
        payload = extract_json_object(text)
    except (ValueError, json.JSONDecodeError):
        return None, False
    payload.setdefault("task", task)
    payload["summary"] = str(payload.get("summary") or "Нет краткого итога.")[:1000]
    allowed_rel = {"required_check", "not_mentioned", "conflict", "observation"}
    checks = []
    for raw in payload.get("checks") or []:
        if not isinstance(raw, dict):
            continue
        body = str(raw.get("text") or "")[:500]
        relation = raw.get("relation")
        eids = [str(item) for item in (raw.get("evidence_ids") or []) if str(item).startswith("E")][:5]
        if not body or relation not in allowed_rel:
            continue
        if not eids:
            eids = [ASSUME_EVIDENCE_ID]
        checks.append({"text": body, "relation": relation, "evidence_ids": eids})
    payload["checks"] = checks[:7]
    payload["missing_information"] = [
        str(item)[:500] for item in (payload.get("missing_information") or []) if str(item).strip()
    ][:3]
    payload["limitations"] = [
        str(item)[:500] for item in (payload.get("limitations") or []) if str(item).strip()
    ][:6]
    slim = {
        key: payload[key]
        for key in ("task", "status", "summary", "checks", "missing_information", "limitations")
        if key in payload
    }
    try:
        return SpecialistResult.model_validate(slim), True
    except ValidationError:
        return None, False


def _sanitize_citations(result: SpecialistResult, allowed: list[str]) -> SpecialistResult:
    allowed_set = set(allowed)
    fallback = allowed[0] if allowed else ASSUME_EVIDENCE_ID
    checks = []
    for check in result.checks:
        ids = [eid for eid in check.evidence_ids if eid in allowed_set]
        if not ids:
            ids = [fallback]
        checks.append(check.model_copy(update={"evidence_ids": ids[:5]}))
    return result.model_copy(update={"checks": checks})
