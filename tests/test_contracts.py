from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from autonaparnik.domain.models import AnswerEnvelope, ChatRequest, Document, SpecialistResult

SPEC = Path(__file__).resolve().parents[1] / "autonaparnik_agent_plan_v2" / "examples"


def test_positive_chat_request() -> None:
    payload = json.loads((SPEC / "chat-request.json").read_text())
    ChatRequest.model_validate(payload)


def test_positive_answer() -> None:
    payload = json.loads((SPEC / "answer.json").read_text())
    AnswerEnvelope.model_validate(payload)


def test_positive_specialist() -> None:
    payload = json.loads((SPEC / "specialist-result.json").read_text())
    SpecialistResult.model_validate(payload)


def test_positive_document() -> None:
    payload = json.loads((SPEC / "document.json").read_text())
    Document.model_validate(payload)


def test_invalid_history_system_role() -> None:
    payload = json.loads((SPEC / "invalid-history.json").read_text())
    with pytest.raises(ValidationError):
        ChatRequest.model_validate(payload)


def test_invalid_citation() -> None:
    payload = json.loads((SPEC / "invalid-citation.json").read_text())
    with pytest.raises(ValidationError):
        AnswerEnvelope.model_validate(payload)


def test_invalid_specialist_empty_evidence() -> None:
    payload = json.loads((SPEC / "invalid-specialist.json").read_text())
    with pytest.raises(ValidationError):
        SpecialistResult.model_validate(payload)


def test_invalid_model_provenance() -> None:
    payload = json.loads((SPEC / "invalid-model-provenance.json").read_text())
    with pytest.raises(ValidationError):
        AnswerEnvelope.model_validate(payload)


def test_assistant_history_is_allowed_in_contract_but_stripped_later() -> None:
    req = ChatRequest.model_validate(
        {
            "message": "Привет",
            "vehicle": {"market": "unknown"},
            "history": [{"role": "assistant", "text": "не должно уйти в облако"}],
        }
    )
    assert req.history[0].role == "assistant"
