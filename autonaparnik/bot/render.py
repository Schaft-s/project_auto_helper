from __future__ import annotations

import html
import re

from autonaparnik.domain.models import AnswerEnvelope, Evidence, SpecialistBlock
from autonaparnik.textutil import unique_questions

ALLOWED_TAG = re.compile(
    r"</?(?:b|i|code)(?:\s*)>|</a>|<a\s+href=\"https?://[^\"]+\"\s*>",
    re.IGNORECASE,
)
SESSION_LIMITATIONS = (
    "<b>Ограничения</b>\n"
    "• Консультация по открытым источникам, не диагноз и не подтверждение ремонта.\n"
    "• NHTSA — рынок США; жалобы владельцев не доказывают причину поломки.\n"
    "• Форумы — чужой опыт, не заводская карта. VIN не проверяется."
)
_ITOGO_LINE = re.compile(
    r"^(?:<b>)?итог(?:</b>)?(?:\s*\[[^\]]*\])?\s*:?\s*",
    re.IGNORECASE,
)
_SECTION = re.compile(
    r"(?:^|\n+)(?:<b>)?(?:ограничения|уточнения|трасса|источники)(?:</b>)?\s*:?[ \t]*\n.*",
    re.IGNORECASE | re.DOTALL,
)


def sanitize_telegram_html(text: str) -> str:
    placeholders: list[str] = []

    def keep(match: re.Match[str]) -> str:
        tag = match.group(0)
        if tag.lower().startswith("<a "):
            href = re.search(r'href="([^"]+)"', tag)
            if href:
                safe = html.escape(href.group(1), quote=True)
                placeholders.append(f'<a href="{safe}">')
            else:
                placeholders.append("&lt;a&gt;")
        elif tag.lower() == "</a>":
            placeholders.append("</a>")
        else:
            placeholders.append(tag.lower())
        return f"\x00{len(placeholders) - 1}\x00"

    held = ALLOWED_TAG.sub(keep, text)
    escaped = html.escape(held, quote=False)
    for index, tag in enumerate(placeholders):
        escaped = escaped.replace(f"\x00{index}\x00", tag)
    return escaped


def strip_protocol(text: str) -> str:
    cleaned = text.replace("\r\n", "\n").strip()
    first, _, rest = cleaned.partition("\n")
    first = _ITOGO_LINE.sub("", first).strip()
    cleaned = f"{first}\n{rest}".strip() if rest else first
    cleaned = _SECTION.sub("", cleaned).strip()
    return cleaned


def render_answer(answer: AnswerEnvelope) -> list[str]:
    summary = strip_protocol(answer.summary)
    parts = [sanitize_telegram_html(summary)]
    extra_questions = unique_questions(list(answer.questions), summary, limit=2)
    if extra_questions:
        parts.append("\n".join(f"• {sanitize_telegram_html(item)}" for item in extra_questions))
    assembly = _render_assembly(answer.specialist)
    if assembly:
        parts.append(assembly)
    links = _source_links(answer)
    if links:
        parts.append("\n".join(links))
    text = "\n\n".join(part for part in parts if part)
    if len(text) > 3500:
        text = text[:3499] + "…"
    return [text]


def _render_assembly(block: SpecialistBlock | None) -> str:
    if block is None or not block.result.checks:
        return ""
    lines = []
    for check in block.result.checks[:5]:
        lines.append(f"• {sanitize_telegram_html(check.text)}")
    return "\n".join(lines)


def _link_label(item: Evidence) -> str:
    source_id = (item.source_id or "").strip()
    if item.source_type == "nhtsa_recall":
        return f"NHTSA отзыв {source_id}"[:60] if source_id else "NHTSA отзыв"
    if item.source_type == "nhtsa_complaint":
        return f"NHTSA жалоба {source_id}"[:60] if source_id else "NHTSA жалоба"
    if item.source_type == "mechanics_qa":
        return f"Mechanics.SE {source_id}"[:60] if source_id else "Mechanics.SE"
    return (source_id or item.title or "источник")[:60]


def _source_links(answer: AnswerEnvelope) -> list[str]:
    preferred = [
        item
        for item in answer.evidence
        if item.source_type in {"nhtsa_recall", "nhtsa_complaint", "mechanics_qa"}
    ]
    pool = preferred or [
        item for item in answer.evidence if item.source_type != "technical_doc"
    ]
    links = []
    seen: set[str] = set()
    for item in pool:
        if not item.url or not item.url.startswith("https://"):
            continue
        if item.url in seen:
            continue
        seen.add(item.url)
        title = html.escape(_link_label(item), quote=False)
        href = html.escape(item.url, quote=True)
        links.append(f'• <a href="{href}">{title}</a>')
        if len(links) >= 3:
            break
    return links
