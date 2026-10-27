from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from autonaparnik.config import Settings
from autonaparnik.domain.models import Coverage, Evidence, KnownIssues, SourcedClaim, VehicleProfile, VehicleSafetyArgs

ALLOWED_MCP_TOOLS = {
    "nhtsa_lookup_vehicles",
    "nhtsa_search_recalls",
    "nhtsa_search_complaints",
}
RECALL_URL = "https://www.nhtsa.gov/recalls"
COMPLAINT_URL = "https://www.nhtsa.gov/nhtsa-datasets-and-apis"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"<[^>]+>", " ", str(value)).strip()


def _clip(value: str, limit: int = 480) -> str:
    value = " ".join(value.split())
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def _eid(prefix: str, source_id: str) -> str:
    digest = hashlib.sha256(source_id.encode("utf-8")).hexdigest()[:10]
    return f"E{prefix}_{digest}"


def parse_mcp_payload(result: Any) -> dict[str, Any]:
    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict) and structured:
        inner = structured.get("result", structured)
        if isinstance(inner, dict):
            return inner
        return structured
    for item in getattr(result, "content", None) or []:
        text = getattr(item, "text", None)
        if not text:
            continue
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    if getattr(result, "isError", False):
        raise RuntimeError("MCP tool returned an error")
    raise RuntimeError("MCP tool returned no structured payload")


def _rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("Results", "results", "data", "items"):
        value = payload.get(key)
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
    return []


def _total(payload: dict[str, Any], rows: list[dict[str, Any]]) -> int | None:
    for key in ("Count", "total", "count", "totalCount"):
        if key in payload and payload[key] is not None:
            try:
                return int(payload[key])
            except (TypeError, ValueError):
                continue
    return len(rows)


@dataclass
class CacheEntry:
    expires_at: float
    payload: dict[str, Any]
    retrieved_at: datetime


class MemoryCache:
    def __init__(self) -> None:
        self._data: dict[str, CacheEntry] = {}

    def get(self, key: str) -> CacheEntry | None:
        entry = self._data.get(key)
        if entry is None or entry.expires_at < time.time():
            return None
        return entry

    def set(self, key: str, payload: dict[str, Any], ttl: float, retrieved_at: datetime) -> None:
        self._data[key] = CacheEntry(expires_at=time.time() + ttl, payload=payload, retrieved_at=retrieved_at)


@dataclass
class LookupOutcome:
    known_issues: KnownIssues
    evidence: list[Evidence]
    status: str
    mode: str
    elapsed_ms: float
    questions: list[str] = field(default_factory=list)


class NhtsaMcpAdapter:
    def __init__(self, settings: Settings, cache: MemoryCache | None = None):
        self.settings = settings
        self.cache = cache or MemoryCache()

    async def lookup(self, vehicle: VehicleProfile, args: VehicleSafetyArgs, remaining: float) -> LookupOutcome:
        started = time.perf_counter()
        if not vehicle.make or not vehicle.model or vehicle.model_year is None:
            known = KnownIssues(
                recalls=_needs_context_coverage(),
                complaints=_needs_context_coverage() if args.include_complaints else _not_requested(),
                claims=[],
                limitations=["Для поиска NHTSA нужны марка, модель и модельный год."],
            )
            return LookupOutcome(
                known_issues=known,
                evidence=[],
                status="needs_context",
                mode="not_run",
                elapsed_ms=(time.perf_counter() - started) * 1000,
                questions=_missing_vehicle_questions(vehicle),
            )

        budget = {"left": self.settings.mcp_calls_max}
        evidence: list[Evidence] = []
        limitations: list[str] = []
        modes: list[str] = []

        recalls_cov, recall_rows, recall_mode = await self._search(
            "nhtsa_search_recalls",
            {"make": vehicle.make, "model": vehicle.model, "modelYear": vehicle.model_year},
            remaining,
            budget,
            empty_is_ok=True,
        )
        modes.append(recall_mode)
        recall_evidence = _recall_evidence(recall_rows, recall_mode)
        evidence.extend(recall_evidence)

        if args.include_complaints:
            complaints_cov, complaint_rows, complaint_mode = await self._search_complaints(
                vehicle, remaining, budget
            )
            modes.append(complaint_mode)
            complaint_evidence = _complaint_evidence(complaint_rows, args.symptom, complaint_mode)
            evidence.extend(complaint_evidence)
        else:
            complaints_cov = _not_requested()
            complaint_evidence = []

        claims = _claims_from_evidence(recall_evidence, complaint_evidence)
        if vehicle.market != "US":
            limitations.append(
                "Кампании и жалобы NHTSA относятся к рынку США; указанный рынок автомобиля — "
                f"{vehicle.market}."
            )
        if complaints_cov.is_partial:
            limitations.append("Просмотрена не вся выборка жалоб; это не полный обзор базы.")
        if recalls_cov.status == "unavailable":
            limitations.append("Источник отзывных кампаний временно недоступен; это не «кампаний нет».")
        if complaints_cov.status == "unavailable":
            limitations.append("Источник жалоб временно недоступен; это не «жалоб нет».")
        if recalls_cov.status == "empty" and complaints_cov.status in {"empty", "not_requested"}:
            limitations.append("Пустая выборка не доказывает, что автомобиль безопасен.")

        status = _facade_status(recalls_cov, complaints_cov)
        mode = _combine_modes(modes)
        known = KnownIssues(
            recalls=recalls_cov,
            complaints=complaints_cov,
            claims=claims[:10],
            limitations=limitations[:6],
        )
        return LookupOutcome(
            known_issues=known,
            evidence=evidence[:20],
            status=status,
            mode=mode,
            elapsed_ms=(time.perf_counter() - started) * 1000,
        )

    async def _search_complaints(
        self, vehicle: VehicleProfile, remaining: float, budget: dict[str, int]
    ) -> tuple[Coverage, list[dict[str, Any]], str]:
        pages: list[dict[str, Any]] = []
        collected: list[dict[str, Any]] = []
        total: int | None = None
        modes: list[str] = []
        page_size = self.settings.complaints_page_size
        unavailable = False
        for page_index in range(self.settings.complaint_pages_max):
            if budget["left"] <= 0 or remaining <= 1:
                break
            offset = page_index * page_size
            coverage, rows, mode, payload = await self._search(
                "nhtsa_search_complaints",
                {
                    "make": vehicle.make,
                    "model": vehicle.model,
                    "modelYear": vehicle.model_year,
                    "limit": page_size,
                    "offset": offset,
                },
                remaining,
                budget,
                empty_is_ok=True,
                return_payload=True,
            )
            modes.append(mode)
            if coverage.status == "unavailable":
                unavailable = True
                break
            pages.append(payload)
            collected.extend(rows)
            total = _total(payload, rows) if total is None else total
            if payload.get("is_partial") is False or (total is not None and offset + len(rows) >= total):
                break
            if not rows:
                break
        unique: dict[str, dict[str, Any]] = {}
        for row in collected:
            key = str(row.get("odiNumber") or row.get("ODINumber") or json.dumps(row, sort_keys=True))
            unique[key] = row
        rows = list(unique.values())
        if unavailable and not rows:
            return (
                Coverage(
                    status="unavailable",
                    total_matching_count=None,
                    returned_count=0,
                    analyzed_count=0,
                    pages_fetched=len(pages),
                    is_partial=True,
                ),
                [],
                "live",
            )
        if not rows and not unavailable:
            return (
                Coverage(
                    status="empty",
                    total_matching_count=0,
                    returned_count=0,
                    analyzed_count=0,
                    pages_fetched=max(len(pages), 1),
                    is_partial=False,
                ),
                [],
                _combine_modes(modes) if modes else "live",
            )
        returned = len(rows)
        analyzed = min(returned, page_size)
        is_partial = total is not None and analyzed < total
        if total is None:
            is_partial = True
        status = "partial" if is_partial or unavailable else "ok"
        return (
            Coverage(
                status=status,
                total_matching_count=total,
                returned_count=returned,
                analyzed_count=analyzed,
                pages_fetched=max(len(pages), 1),
                is_partial=is_partial or unavailable,
            ),
            rows,
            _combine_modes(modes) if modes else "live",
        )

    async def _search(
        self,
        tool: str,
        arguments: dict[str, Any],
        remaining: float,
        budget: dict[str, int],
        *,
        empty_is_ok: bool,
        return_payload: bool = False,
    ):
        key = json.dumps({"tool": tool, "arguments": arguments}, sort_keys=True)
        cached = self.cache.get(key)
        if cached:
            payload = cached.payload
            rows = _rows(payload)
            coverage = _coverage_from_payload(payload, rows, empty_is_ok, pages=1)
            if return_payload:
                return coverage, rows, "cache", payload
            return coverage, rows, "cache"
        if budget["left"] <= 0:
            coverage = Coverage(
                status="unavailable",
                total_matching_count=None,
                returned_count=0,
                analyzed_count=0,
                pages_fetched=0,
                is_partial=True,
            )
            if return_payload:
                return coverage, [], "live", {}
            return coverage, [], "live"
        budget["left"] -= 1
        try:
            payload = await self._call_tool(tool, arguments, remaining)
        except Exception:
            coverage = Coverage(
                status="unavailable",
                total_matching_count=None,
                returned_count=0,
                analyzed_count=0,
                pages_fetched=0,
                is_partial=True,
            )
            if return_payload:
                return coverage, [], "live", {}
            return coverage, [], "live"
        rows = _rows(payload)
        ttl = self.settings.cache_ttl_seconds if rows else self.settings.negative_cache_ttl_seconds
        self.cache.set(key, payload, ttl, _now())
        coverage = _coverage_from_payload(payload, rows, empty_is_ok, pages=1)
        if return_payload:
            return coverage, rows, "live", payload
        return coverage, rows, "live"

    async def _call_tool(self, name: str, arguments: dict[str, Any], remaining: float) -> dict[str, Any]:
        if name not in ALLOWED_MCP_TOOLS:
            raise RuntimeError(f"tool {name} is not on the allowlist")
        timeout = min(self.settings.mcp_call_timeout_seconds, max(1.0, remaining))
        async with streamablehttp_client(self.settings.mcp_url, timeout=timeout) as streams:
            read, write = streams[0], streams[1]
            async with ClientSession(read, write) as session:
                await session.initialize()
                listed = await session.list_tools()
                names = {tool.name for tool in listed.tools}
                if name not in names:
                    raise RuntimeError("MCP schema drift: required tool missing")
                result = await session.call_tool(name, arguments)
                return parse_mcp_payload(result)


def _coverage_from_payload(payload: dict[str, Any], rows: list[dict[str, Any]], empty_is_ok: bool, pages: int) -> Coverage:
    total = _total(payload, rows)
    returned = len(rows)
    if returned == 0 and empty_is_ok and total in {0, None}:
        return Coverage(
            status="empty",
            total_matching_count=0,
            returned_count=0,
            analyzed_count=0,
            pages_fetched=max(pages, 1),
            is_partial=False,
        )
    analyzed = returned
    is_partial = bool(payload.get("is_partial")) or (total is not None and analyzed < total)
    status = "partial" if is_partial else "ok"
    return Coverage(
        status=status,
        total_matching_count=total,
        returned_count=returned,
        analyzed_count=analyzed,
        pages_fetched=pages,
        is_partial=is_partial,
    )


def _needs_context_coverage() -> Coverage:
    return Coverage(
        status="needs_context",
        total_matching_count=None,
        returned_count=0,
        analyzed_count=0,
        pages_fetched=0,
        is_partial=False,
    )


def _not_requested() -> Coverage:
    return Coverage(
        status="not_requested",
        total_matching_count=None,
        returned_count=0,
        analyzed_count=0,
        pages_fetched=0,
        is_partial=False,
    )


def _missing_vehicle_questions(vehicle: VehicleProfile) -> list[str]:
    questions = []
    if not vehicle.make:
        questions.append("Какая марка автомобиля?")
    if not vehicle.model:
        questions.append("Какая модель?")
    if vehicle.model_year is None:
        questions.append("Какой модельный год?")
    return questions[:3]


def _recall_evidence(rows: list[dict[str, Any]], mode: str) -> list[Evidence]:
    items = []
    seen: set[str] = set()
    retrieved = _now()
    for row in rows:
        campaign = _text(row.get("campaignNumber") or row.get("NHTSACampaignNumber") or row.get("campaign_id"))
        if not campaign or campaign in seen:
            continue
        seen.add(campaign)
        component = _text(row.get("component") or row.get("Component")) or "кампания"
        summary = _clip(_text(row.get("summary") or row.get("Summary")), 200)
        items.append(
            Evidence(
                evidence_id=_eid("R", campaign),
                source_type="nhtsa_recall",
                source_id=campaign,
                title=_clip(f"Recall {campaign}: {component}", 500),
                locator=f"NHTSA campaign {campaign}",
                url=RECALL_URL,
                excerpt=summary or None,
                retrieved_at=retrieved,
                mode=mode if mode in {"live", "cache", "fixture"} else "live",
                applicability="matched",
                source_market="US",
            )
        )
    return items


def _complaint_evidence(rows: list[dict[str, Any]], symptom: str, mode: str) -> list[Evidence]:
    ranked = list(rows)
    if symptom.strip():
        tokens = {tok for tok in re.split(r"\W+", symptom.lower()) if len(tok) > 2}

        def score(row: dict[str, Any]) -> int:
            blob = " ".join(
                _text(row.get(key) or "").lower() for key in ("summary", "Summary", "component", "Component")
            )
            return sum(1 for tok in tokens if tok in blob)

        ranked.sort(key=score, reverse=True)
    items = []
    seen: set[str] = set()
    retrieved = _now()
    for row in ranked[:20]:
        odi = _text(row.get("odiNumber") or row.get("ODINumber"))
        if not odi or odi in seen:
            continue
        seen.add(odi)
        component = _text(row.get("component") or row.get("Component")) or "жалоба"
        summary = _clip(_text(row.get("summary") or row.get("Summary")), 200)
        items.append(
            Evidence(
                evidence_id=_eid("C", odi),
                source_type="nhtsa_complaint",
                source_id=odi,
                title=_clip(f"Complaint {odi}: {component}", 500),
                locator=f"NHTSA ODI {odi}",
                url=COMPLAINT_URL,
                excerpt=summary or None,
                retrieved_at=retrieved,
                mode=mode if mode in {"live", "cache", "fixture"} else "live",
                applicability="unknown",
                source_market="US",
            )
        )
    return items


def _claims_from_evidence(recalls: list[Evidence], complaints: list[Evidence]) -> list[SourcedClaim]:
    claims: list[SourcedClaim] = []
    for item in recalls[:3]:
        text = item.excerpt or item.title
        claims.append(SourcedClaim(text=_clip(f"Кампания {item.source_id}: {text}", 200), evidence_ids=[item.evidence_id]))
    for item in complaints[:3]:
        text = item.excerpt or item.title
        claims.append(
            SourcedClaim(
                text=_clip(f"Сообщение владельца {item.source_id}: {text}", 200),
                evidence_ids=[item.evidence_id],
            )
        )
    return claims


def _facade_status(recalls: Coverage, complaints: Coverage) -> str:
    statuses = {recalls.status, complaints.status}
    if "needs_context" in statuses:
        return "needs_context"
    useful = {recalls.status, complaints.status} - {"not_requested"}
    if useful <= {"unavailable"}:
        return "unavailable"
    if "unavailable" in useful or "partial" in useful:
        return "partial"
    if useful <= {"empty"}:
        return "ok"
    return "ok"


def _combine_modes(modes: list[str]) -> str:
    useful = [mode for mode in modes if mode != "not_run"]
    if not useful:
        return "live"
    if all(mode == "cache" for mode in useful):
        return "cache"
    if all(mode == "fixture" for mode in useful):
        return "fixture"
    if "live" in useful:
        return "live"
    return useful[0]
