from __future__ import annotations

import re

_STOP = {
    "и",
    "или",
    "ли",
    "есть",
    "а",
    "в",
    "во",
    "на",
    "по",
    "к",
    "ко",
    "с",
    "со",
    "у",
    "о",
    "об",
    "от",
    "до",
    "за",
    "из",
    "для",
    "что",
    "это",
    "как",
    "какой",
    "какая",
    "какие",
    "какое",
    "каков",
    "сейчас",
    "уже",
    "только",
    "то",
    "же",
    "бы",
    "если",
    "ваш",
    "ваша",
    "ваше",
    "ваши",
    "машина",
    "автомобиль",
}


def normalize_question_text(text: str) -> str:
    cleaned = re.sub(r"<[^>]+>", " ", text.lower())
    cleaned = re.sub(r"[^\wа-яё]+", " ", cleaned, flags=re.IGNORECASE)
    return " ".join(cleaned.split())


def question_covered_by_summary(question: str, summary: str) -> bool:
    q = normalize_question_text(question)
    s = normalize_question_text(summary)
    if not q:
        return True
    if q in s:
        return True
    tokens = {tok for tok in q.split() if tok not in _STOP and len(tok) > 1}
    if not tokens:
        return q in s
    overlap = sum(1 for tok in tokens if tok in s.split() or tok in s)
    return overlap / len(tokens) >= 0.6


def unique_questions(questions: list[str], summary: str, *, limit: int = 2) -> list[str]:
    kept: list[str] = []
    for item in questions:
        text = item.strip()
        if not text or question_covered_by_summary(text, summary):
            continue
        if any(question_covered_by_summary(text, prev) for prev in kept):
            continue
        kept.append(text)
        if len(kept) >= limit:
            break
    return kept
