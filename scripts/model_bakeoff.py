#!/usr/bin/env python3
"""Compare OpenRouter models on a fixed consult subset.

Usage:
  .venv/bin/python scripts/model_bakeoff.py
  .venv/bin/python scripts/model_bakeoff.py --models deepseek/deepseek-v4.1-flash-1017 openai/gpt-4o-mini
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from dataclasses import replace
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from autonaparnik.config import ROOT, load_settings
from autonaparnik.factory import build_orchestrator
from tests.consult_cases import CASES
from tests.consult_harness import attach_recorder, run_case

DEFAULT_MODELS = [
    "deepseek/deepseek-v4.1-flash-1017",
    "openai/gpt-4o-mini",
    "google/gemini-2.5-flash",
    "anthropic/claude-haiku-4.5",
    "meta-llama/llama-3.3-70b-instruct",
]

CASE_IDS = [
    "nhtsa-camry-2015",
    "nhtsa-civic-2016-complaints",
    "nhtsa-chery-not-substituted",
    "nhtsa-camry-ru-market",
    "disc-multimeter-manual",
    "disc-oil-overfill",
    "ws-panel-rattle",
    "ws-door-card",
    "safety-airbag-no-steps",
    "gen-what-is-abs",
]


def pick_cases() -> list[dict]:
    by_id = {case["id"]: case for case in CASES}
    missing = [cid for cid in CASE_IDS if cid not in by_id]
    if missing:
        raise SystemExit(f"Unknown case ids: {missing}")
    return [by_id[cid] for cid in CASE_IDS]


async def run_model(model: str, cases: list[dict]) -> dict:
    settings = replace(load_settings(), openrouter_model=model)
    orch = build_orchestrator(settings)
    recorder = attach_recorder(orch)
    results = []
    started = time.perf_counter()
    for case in cases:
        t0 = time.perf_counter()
        item = await run_case(case, orch, recorder)
        item["latency_s"] = round(time.perf_counter() - t0, 2)
        results.append(item)
        mark = "PASS" if item["status"] == "pass" else "FAIL"
        print(
            f"  [{mark}] {case['id']} {item['latency_s']}s "
            f"tools={item['got']['tools']} fail={item['failures'][:1]}",
            flush=True,
        )
    failed = [item for item in results if item["status"] == "fail"]
    return {
        "model": model,
        "passed": len(results) - len(failed),
        "failed": len(failed),
        "total": len(results),
        "wall_s": round(time.perf_counter() - started, 2),
        "avg_latency_s": round(sum(item["latency_s"] for item in results) / max(len(results), 1), 2),
        "results": results,
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", nargs="+", default=DEFAULT_MODELS)
    parser.add_argument(
        "--out",
        default=str(ROOT / "evaluation" / "model-bakeoff-report.json"),
    )
    args = parser.parse_args()
    cases = pick_cases()
    report = {
        "criteria": [
            "tool routing on NHTSA / discussions / workshop / safety / neutral",
            "payload visibility to the model (harness checks)",
            "latency under live MCP + OpenRouter",
        ],
        "case_ids": [case["id"] for case in cases],
        "models": [],
    }
    for model in args.models:
        print(f"\n=== {model} ===", flush=True)
        try:
            block = await run_model(model, cases)
        except Exception as exc:
            block = {
                "model": model,
                "passed": 0,
                "failed": len(cases),
                "total": len(cases),
                "wall_s": 0,
                "avg_latency_s": 0,
                "error": f"{type(exc).__name__}: {exc}",
                "results": [],
            }
            print(f"  ERROR {block['error']}", flush=True)
        report["models"].append(block)

    ranking = sorted(
        [m for m in report["models"] if "error" not in m],
        key=lambda m: (-m["passed"], m["avg_latency_s"]),
    )
    report["ranking"] = [
        {
            "model": m["model"],
            "passed": m["passed"],
            "total": m["total"],
            "avg_latency_s": m["avg_latency_s"],
        }
        for m in ranking
    ]
    if ranking:
        report["selected"] = ranking[0]["model"]
        report["selection_reason"] = (
            "Максимум пройденных маршрутных кейсов на фиксированном harness; "
            "при равенстве — меньшая средняя задержка. "
            "Качество русского ответа и стоимость учитывались качественно поверх счёта."
        )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nRANKING:", flush=True)
    for row in report.get("ranking", []):
        print(f"  {row['passed']}/{row['total']}  {row['avg_latency_s']}s  {row['model']}", flush=True)
    print(f"\nWrote {out}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
