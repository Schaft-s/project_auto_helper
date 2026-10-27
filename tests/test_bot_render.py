from __future__ import annotations

from autonaparnik.bot.render import render_answer, sanitize_telegram_html, strip_protocol
from autonaparnik.domain.models import AnswerEnvelope
from autonaparnik.textutil import question_covered_by_summary, unique_questions


def test_render_escapes_html() -> None:
    answer = AnswerEnvelope.model_validate(
        {
            "schema_version": "2.0",
            "trace_id": "trace-html",
            "status": "ok",
            "route": "general",
            "vehicle": {"market": "unknown"},
            "summary": "Символ <script>alert(1)</script> не должен исполняться.",
            "known_issues": None,
            "specialist": None,
            "questions": [],
            "limitations": ["граница"],
            "evidence": [],
            "tool_events": [],
        }
    )
    html = "\n".join(render_answer(answer))
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "Ограничения" not in html
    assert "граница" not in html


def test_render_strips_protocol_and_skips_limitations() -> None:
    answer = AnswerEnvelope.model_validate(
        {
            "schema_version": "2.0",
            "trace_id": "trace-compact",
            "status": "needs_clarification",
            "route": "clarify",
            "vehicle": {"market": "unknown"},
            "summary": (
                "Итог [needs_clarification / clarify]\n"
                "Понял: у вас BMW 320.\n\n"
                "Ограничения\n"
                "• Это консультация, не диагноз."
            ),
            "known_issues": None,
            "discussions": None,
            "specialist": None,
            "questions": ["Какой год?"],
            "limitations": ["короткая оговорка", "ещё одна"],
            "evidence": [
                {
                    "evidence_id": "EMSE1125",
                    "source_type": "mechanics_qa",
                    "source_id": "MSE-1125",
                    "title": "Oil overfill",
                    "locator": "https://mechanics.stackexchange.com/questions/1125",
                    "url": "https://mechanics.stackexchange.com/questions/1125",
                    "excerpt": "A" * 400,
                    "retrieved_at": "2026-10-26T00:00:00Z",
                    "mode": "fixture",
                    "applicability": "general",
                    "source_market": "general",
                }
            ],
            "tool_events": [],
        }
    )
    chunks = render_answer(answer)
    assert len(chunks) == 1
    html = chunks[0]
    assert "Итог" not in html
    assert "needs_clarification" not in html
    assert "Ограничения" not in html
    assert "короткая оговорка" not in html
    assert "BMW 320" in html
    assert "Какой год?" in html
    assert "Уточнения" not in html
    assert "mechanics.stackexchange.com" in html


def test_strip_protocol_drops_itogo_line() -> None:
    text = strip_protocol("<b>Итог</b> [ok / general]\nКороткий ответ.")
    assert "Итог" not in text
    assert "Короткий ответ." in text


def test_sanitize_keeps_bold() -> None:
    assert sanitize_telegram_html("<b>ок</b>") == "<b>ок</b>"


def test_render_prefers_forum_links_over_manuals() -> None:
    answer = AnswerEnvelope.model_validate(
        {
            "schema_version": "2.0",
            "trace_id": "trace-links",
            "status": "ok",
            "route": "discussions",
            "vehicle": {"market": "unknown"},
            "summary": "Перегрев, сначала уровень антифриза.",
            "known_issues": None,
            "discussions": {"status": "ok", "claims": [], "limitations": ["форум"]},
            "specialist": None,
            "questions": [],
            "limitations": ["x"],
            "evidence": [
                {
                    "evidence_id": "EBCCE4001",
                    "source_type": "technical_doc",
                    "source_id": "BCC-E4-001",
                    "title": "Use Multimeters (35)",
                    "locator": "https://example.com/e4",
                    "url": "https://example.com/e4",
                    "excerpt": "DMM",
                    "retrieved_at": "2026-10-26T00:00:00Z",
                    "mode": "live",
                    "applicability": "general",
                    "source_market": "general",
                },
                {
                    "evidence_id": "EMSE318",
                    "source_type": "mechanics_qa",
                    "source_id": "MSE-318",
                    "title": "I bought a BMW 318i and the engine overheated",
                    "locator": "https://mechanics.stackexchange.com/questions/318",
                    "url": "https://mechanics.stackexchange.com/questions/318",
                    "excerpt": "coolant",
                    "retrieved_at": "2026-10-26T00:00:00Z",
                    "mode": "fixture",
                    "applicability": "general",
                    "source_market": "general",
                },
            ],
            "tool_events": [],
        }
    )
    html = "\n".join(render_answer(answer))
    assert "Use Multimeters" not in html
    assert "mechanics.stackexchange.com" in html
    assert "Mechanics.SE MSE-318" in html
    assert "I bought a BMW" not in html


def test_render_skips_paraphrased_duplicate_questions() -> None:
    summary = (
        "BMW 3 Series 2021, «маленький угол зажигания».\n\n"
        "Что стоит уточнить:\n"
        "• угол маленький всегда или только под нагрузкой / на холостых;\n"
        "• какое топливо залито и есть ли ошибки по детонации."
    )
    answer = AnswerEnvelope.model_validate(
        {
            "schema_version": "2.0",
            "trace_id": "trace-dup-q",
            "status": "ok",
            "route": "general",
            "vehicle": {"make": "BMW", "model": "3 Series", "model_year": 2021, "market": "unknown"},
            "summary": summary,
            "known_issues": None,
            "specialist": None,
            "questions": [
                "Угол маленький постоянно или только под нагрузкой/на холостых?",
                "Какое топливо заливаете и есть ли сейчас ошибки по детонации?",
            ],
            "limitations": ["x"],
            "evidence": [
                {
                    "evidence_id": "ENHTSA1",
                    "source_type": "nhtsa_complaint",
                    "source_id": "11761564",
                    "title": "Complaint 11761564: ENGINE",
                    "locator": "https://www.nhtsa.gov/vehicle/2021/BMW/3%20SERIES",
                    "url": "https://www.nhtsa.gov/vehicle/2021/BMW/3%20SERIES",
                    "excerpt": "starter",
                    "retrieved_at": "2026-10-26T00:00:00Z",
                    "mode": "live",
                    "applicability": "matched",
                    "source_market": "US",
                }
            ],
            "tool_events": [],
        }
    )
    html = "\n".join(render_answer(answer))
    assert html.count("нагрузк") == 1
    assert html.count("топлив") == 1
    assert "Complaint 11761564: ENGINE" not in html
    assert "NHTSA жалоба 11761564" in html


def test_prompts_stay_short_without_few_shots() -> None:
    from pathlib import Path

    from autonaparnik.config import ROOT

    orch = (ROOT / "prompts" / "orchestrator.v2.md").read_text(encoding="utf-8")
    spec = (ROOT / "prompts" / "specialist.v2.md").read_text(encoding="utf-8")
    assert len(orch) < 2500
    assert len(spec) < 1200
    assert "U: привет" not in orch
    assert "few-shot" not in orch.lower()
    assert "vehicle_safety_lookup" in orch
    assert "search_discussions" in orch
    assert "workshop_consult" in orch
    assert "SpecialistResult" in spec


def test_question_overlap_helpers() -> None:
    summary = "Угол маленький всегда или только под нагрузкой на холостых? Какое топливо?"
    assert question_covered_by_summary(
        "Угол маленький постоянно или только под нагрузкой/на холостых?",
        summary,
    )
    assert unique_questions(
        [
            "Угол маленький постоянно или только под нагрузкой/на холостых?",
            "Какой пробег у машины?",
        ],
        summary,
    ) == ["Какой пробег у машины?"]
