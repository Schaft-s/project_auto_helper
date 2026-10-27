"""Run golden cases. Offline cases need no network; live cases need MCP + OpenRouter."""
from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass

from autonaparnik.config import ROOT, Settings, load_settings
from autonaparnik.domain.models import ChatRequest, VehicleProfile
from autonaparnik.factory import build_orchestrator
from autonaparnik.policy.risk import classify_risk
from autonaparnik.retrieval.search import CorpusIndex
from autonaparnik.smoke import smoke_mcp, smoke_router


def load_cases() -> list[dict]:
    path = ROOT / "evaluation" / "golden.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


@dataclass
class GoldenRuntime:
    settings: Settings
    mechanics: CorpusIndex
    workshop: CorpusIndex
    orch: object | None = None

    def orchestrator(self):
        if self.orch is None:
            self.orch = build_orchestrator(self.settings)
        return self.orch


def build_runtime(settings: Settings | None = None) -> GoldenRuntime:
    settings = settings or load_settings()
    return GoldenRuntime(
        settings=settings,
        mechanics=CorpusIndex.from_jsonl(ROOT / "data" / "mechanics" / "qa.jsonl"),
        workshop=CorpusIndex.from_jsonl(),
    )


def evaluate_answer(case: dict, answer) -> list[str]:
    expect = case["expect"]
    failures = []
    if answer.status not in expect.get("status_in", [answer.status]):
        failures.append(f"status {answer.status} not in {expect['status_in']}")
    if expect.get("route_in") and answer.route not in expect["route_in"]:
        failures.append(f"route {answer.route} not in {expect['route_in']}")
    tools = [event.tool for event in answer.tool_events]
    for name in expect.get("tools_include") or []:
        if name not in tools:
            failures.append(f"missing tool {name}; got {tools}")
    for name in expect.get("tools_exclude") or []:
        if name in tools:
            failures.append(f"unexpected tool {name}")
    if expect.get("min_questions") and len(answer.questions) < expect["min_questions"]:
        failures.append("too few clarification questions")
    if expect.get("min_evidence") and len(answer.evidence) < expect["min_evidence"]:
        failures.append(f"evidence {len(answer.evidence)} < {expect['min_evidence']}")
    types = {item.source_type for item in answer.evidence}
    wanted_types = set(expect.get("evidence_source_types_any") or [])
    if wanted_types and not wanted_types.intersection(types):
        failures.append(f"source types {types} miss {wanted_types}")
    ids = {item.source_id for item in answer.evidence} | {item.evidence_id for item in answer.evidence}
    wanted_ids = set(expect.get("evidence_source_ids_any") or [])
    if wanted_ids and not wanted_ids.intersection(ids):
        failures.append(f"source ids {sorted(ids)[:12]} miss {wanted_ids}")
    if expect.get("specialist_status_in"):
        status = answer.specialist.result.status if answer.specialist else None
        if status not in expect["specialist_status_in"]:
            failures.append(f"specialist status {status} not in {expect['specialist_status_in']}")
    if expect.get("specialist_checks_max") is not None:
        n_checks = len(answer.specialist.result.checks) if answer.specialist else 0
        if n_checks > expect["specialist_checks_max"]:
            failures.append(f"specialist checks {n_checks} > {expect['specialist_checks_max']}")
    parts = [answer.summary, *answer.questions, *answer.limitations]
    if answer.specialist:
        parts.append(answer.specialist.result.summary)
        parts.extend(check.text for check in answer.specialist.result.checks)
    blob = " ".join(parts).lower()
    for needle in expect.get("must_not") or []:
        if needle.lower() in blob:
            failures.append(f"forbidden text: {needle}")
    return failures


def evaluate_retrieval(case: dict, hits) -> list[str]:
    expect = case["expect"]
    failures = []
    ids = {hit.document.document_id for hit in hits}
    if expect.get("min_evidence") and len(hits) < expect["min_evidence"]:
        failures.append(f"hits {len(hits)} < {expect['min_evidence']}")
    wanted = set(expect.get("evidence_source_ids_any") or [])
    if wanted and not wanted.intersection(ids):
        failures.append(f"source ids {sorted(ids)[:12]} miss {wanted}")
    forbidden = set(expect.get("evidence_source_ids_none") or [])
    bad = forbidden.intersection(ids)
    if bad:
        failures.append(f"unexpected ids {sorted(bad)}")
    types = {hit.evidence.source_type for hit in hits}
    wanted_types = set(expect.get("evidence_source_types_any") or [])
    if wanted_types and hits and not wanted_types.intersection(types):
        failures.append(f"source types {types} miss {wanted_types}")
    return failures


def evaluate_policy(case: dict, decision) -> list[str]:
    failures = []
    want = case["expect"].get("out_of_scope")
    if want is True and not decision.out_of_scope:
        failures.append("expected out_of_scope")
    if want is False and decision.out_of_scope:
        failures.append("unexpected out_of_scope")
    if "caution" in case["expect"] and bool(decision.caution) != bool(case["expect"]["caution"]):
        failures.append(f"caution {decision.caution} != {case['expect']['caution']}")
    return failures


async def run_one(case: dict, runtime: GoldenRuntime) -> dict:
    kind = case.get("kind") or "orchestrator"
    vehicle = VehicleProfile.model_validate((case.get("request") or {}).get("vehicle") or {})
    if kind == "retrieval":
        index = runtime.mechanics if case.get("corpus") == "mechanics" else runtime.workshop
        hits = index.search(case["request"]["message"], vehicle, top_k=runtime.settings.rag_top_k)
        failures = evaluate_retrieval(case, hits)
        got = {"hits": [hit.document.document_id for hit in hits]}
    elif kind == "policy":
        decision = classify_risk(case["request"]["message"])
        failures = evaluate_policy(case, decision)
        got = {"out_of_scope": decision.out_of_scope, "caution": decision.caution}
    else:
        request = ChatRequest.model_validate(case["request"])
        answer = await runtime.orchestrator().handle(request)
        failures = evaluate_answer(case, answer)
        got = {
            "status": answer.status,
            "route": answer.route,
            "tools": [event.model_dump() for event in answer.tool_events],
            "evidence_ids": [item.source_id for item in answer.evidence],
            "specialist": answer.specialist.result.status if answer.specialist else None,
            "summary": answer.summary[:300],
        }
    return {
        "id": case["id"],
        "group": case.get("group"),
        "kind": kind,
        "architecture_note": case.get("architecture_note"),
        "status": "fail" if failures else "pass",
        "failures": failures,
        "got": got,
    }


async def run_connections() -> dict:
    return {"mcp": await smoke_mcp(), "router": await smoke_router()}


async def run_cases(live: bool, runtime: GoldenRuntime | None = None) -> dict:
    runtime = runtime or build_runtime()
    results = []
    for case in load_cases():
        if case.get("live") and not live:
            results.append({"id": case["id"], "status": "skipped", "reason": "live", "kind": case.get("kind")})
            continue
        results.append(await run_one(case, runtime))
    return {"results": results}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="run MCP/OpenRouter golden cases")
    parser.add_argument("--connections", action="store_true", help="only MCP and OpenRouter smoke")
    args = parser.parse_args()

    async def _run():
        report: dict = {"live": args.live}
        if args.connections or args.live:
            report["connections"] = await run_connections()
        report.update(await run_cases(live=args.live))
        out = ROOT / "evaluation" / "last-report.json"
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        failed = [item for item in report.get("results", []) if item.get("status") == "fail"]
        if args.live and report.get("connections"):
            mcp = report["connections"].get("mcp", {})
            if mcp.get("status") not in {"ok", "partial"}:
                raise SystemExit("MCP connection check failed")
            if not report["connections"].get("router", {}).get("ok"):
                raise SystemExit("OpenRouter connection check failed")
        if failed:
            raise SystemExit(f"{len(failed)} golden cases failed")

    asyncio.run(_run())


if __name__ == "__main__":
    main()
