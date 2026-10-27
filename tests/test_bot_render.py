from __future__ import annotations

from autonaparnik.bot.render import render_answer, sanitize_telegram_html, strip_protocol
from autonaparnik.domain.models import AnswerEnvelope


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
