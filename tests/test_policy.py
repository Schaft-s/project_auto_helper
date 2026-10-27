from __future__ import annotations

from autonaparnik.policy.risk import classify_risk


def test_airbag_is_caution() -> None:
    decision = classify_risk("Как снять модуль подушки безопасности?")
    assert decision.caution is True
    assert decision.out_of_scope is False


def test_brake_is_in_scope() -> None:
    decision = classify_risk("Замена тормозных колодок по шагам")
    assert decision.out_of_scope is False
    assert decision.caution is False


def test_clip_is_in_scope() -> None:
    decision = classify_risk("После установки декоративной панели дребезг, проверить клипсы")
    assert decision.out_of_scope is False
    assert decision.caution is False
