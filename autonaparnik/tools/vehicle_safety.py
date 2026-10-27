from __future__ import annotations

from autonaparnik.adapters.nhtsa import LookupOutcome, NhtsaMcpAdapter
from autonaparnik.domain.models import ChatRequest, ToolEvent, VehicleProfile, VehicleSafetyArgs


def merge_vehicle(base: VehicleProfile, args: VehicleSafetyArgs) -> VehicleProfile:
    market = base.market
    if args.market and args.market != "unknown":
        market = args.market
    return VehicleProfile(
        make=args.make or base.make,
        model=args.model or base.model,
        model_year=args.model_year if args.model_year is not None else base.model_year,
        market=market,
        variant=base.variant,
    )


class VehicleSafetyLookup:
    def __init__(self, adapter: NhtsaMcpAdapter):
        self.adapter = adapter

    async def run(self, request: ChatRequest, args: VehicleSafetyArgs, remaining: float) -> tuple[LookupOutcome, ToolEvent]:
        outcome = await self.adapter.lookup(merge_vehicle(request.vehicle, args), args, remaining)
        event = ToolEvent(
            tool="vehicle_safety_lookup",
            status=outcome.status if outcome.status in {"ok", "partial", "unavailable", "needs_context", "out_of_scope"} else "ok",
            mode=outcome.mode if outcome.mode in {"live", "cache", "fixture", "not_run"} else "live",
            elapsed_ms=outcome.elapsed_ms,
        )
        return outcome, event
