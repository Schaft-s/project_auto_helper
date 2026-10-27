from __future__ import annotations

from dataclasses import dataclass

CAUTION_MARKERS = (
    "srs",
    "airbag",
    "air bag",
    "подушк",
    "подушек",
    "пилот",
    "высоковольт",
    "high voltage",
    "hv battery",
    "hybrid battery",
    "orange cable",
    "оранжев",
    "преднатяжит",
    "pretensioner",
)


@dataclass(frozen=True)
class RiskDecision:
    out_of_scope: bool
    caution: bool
    reason: str | None


def classify_risk(*texts: str) -> RiskDecision:
    blob = " ".join(t.lower() for t in texts if t)
    for marker in CAUTION_MARKERS:
        if marker in blob:
            return RiskDecision(
                out_of_scope=False,
                caution=True,
                reason=(
                    "Это ответственный узел (SRS или высоковольтная система). "
                    "Опишу только общую логику, не сервисную карту."
                ),
            )
    return RiskDecision(out_of_scope=False, caution=False, reason=None)
