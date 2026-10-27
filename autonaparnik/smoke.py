"""Optional live smokes. Does not print secrets or raw prompts."""
from __future__ import annotations

import argparse
import asyncio
import json

from autonaparnik.adapters.nhtsa import NhtsaMcpAdapter
from autonaparnik.adapters.openrouter import OpenRouterClient
from autonaparnik.config import load_settings
from autonaparnik.domain.models import VehicleProfile, VehicleSafetyArgs


async def smoke_mcp() -> dict:
    settings = load_settings()
    adapter = NhtsaMcpAdapter(settings)
    vehicle = VehicleProfile(make="Acura", model="RDX", model_year=2012, market="US")
    outcome = await adapter.lookup(vehicle, VehicleSafetyArgs(symptom="air bag", include_complaints=True), 60)
    return {
        "status": outcome.status,
        "mode": outcome.mode,
        "recalls": outcome.known_issues.recalls.status,
        "complaints": outcome.known_issues.complaints.status,
        "recall_count": outcome.known_issues.recalls.returned_count,
        "complaint_count": outcome.known_issues.complaints.returned_count,
        "evidence": len(outcome.evidence),
    }


async def smoke_router() -> dict:
    settings = load_settings()
    client = OpenRouterClient(settings)
    result = await client.chat(
        [
            {"role": "system", "content": "Reply with JSON {\"ok\": true} only."},
            {"role": "user", "content": "ping"},
        ],
        force_json=True,
        timeout=30,
    )
    await client.aclose()
    return {"ok": "ok" in result.content.lower() or "{" in result.content, "chars": len(result.content)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("target", choices=["mcp", "router", "all"])
    args = parser.parse_args()
    async def run():
        out = {}
        if args.target in {"mcp", "all"}:
            out["mcp"] = await smoke_mcp()
        if args.target in {"router", "all"}:
            out["router"] = await smoke_router()
        print(json.dumps(out, ensure_ascii=False, indent=2))
    asyncio.run(run())


if __name__ == "__main__":
    main()
