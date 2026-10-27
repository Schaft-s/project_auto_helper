"""Convert H4 mechanics.stackexchange parquet into a retrieval JSONL.

Source revision:
https://huggingface.co/datasets/HuggingFaceH4/stack-exchange-preferences/resolve/c7bda74048748f55749cd663c3d8d1025a841fd9/data/mechanics.stackexchange.com/train-00000-of-00001.parquet
"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path

import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "mechanics" / "raw.parquet"
OUT = ROOT / "data" / "mechanics" / "qa.jsonl"
CATALOG = ROOT / "data" / "mechanics" / "catalog.json"
PHOTO = re.compile(r"\b(photo|picture|image|pic|screenshot|as shown)\b", re.I)
HTML_TAG = re.compile(r"<[^>]+>")


def strip_html(text: str) -> str:
    text = HTML_TAG.sub(" ", text or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def pick_answer(answers: list[dict]) -> dict | None:
    if not answers:
        return None
    selected = [a for a in answers if a.get("selected")]
    pool = selected or answers
    picked = max(pool, key=lambda a: int(a.get("pm_score") or 0))
    if not strip_html(picked.get("text") or ""):
        return None
    return picked


def title_from(question: str) -> str:
    first = re.split(r"(?<=[.?!])\s", question, maxsplit=1)[0]
    return first[:500] if first else question[:500]


def main() -> None:
    table = pq.read_table(RAW)
    rows = table.to_pylist()
    chosen = []
    for row in rows:
        question = strip_html(row.get("question") or "")
        if not question:
            continue
        answer = pick_answer(row.get("answers") or [])
        if not answer:
            continue
        body = strip_html(answer.get("text") or "")
        if not body:
            continue
        qid = int(row["qid"])
        meta = row.get("metadata") or []
        url = next((item for item in meta if isinstance(item, str) and "/questions/" in item), None)
        url = url or f"https://mechanics.stackexchange.com/questions/{qid}"
        score = int(answer.get("pm_score") or 0)
        content = (
            f"Question (Mechanics Stack Exchange, CC BY-SA):\n{question}\n\n"
            f"Answer by {answer.get('author') or 'unknown'} "
            f"(score {score}, selected={bool(answer.get('selected'))}):\n{body}\n\n"
            f"Source: {url}"
        )
        title = title_from(question)
        chosen.append(
            {
                "document_id": f"MSE-{qid}",
                "source_group_id": f"mechanics-se-{qid}",
                "operation_type": "public_qa",
                "title": title,
                "language": "en",
                "source_type": "qa",
                "workflow_context": "general",
                "transfer_scope": "general_principle",
                "vehicle_constraints": {
                    "make": None,
                    "model": None,
                    "model_year": None,
                    "market": "unknown",
                    "variant": None,
                },
                "revision": "h4-c7bda740",
                "locator": url,
                "content_sha256": "0" * 64,
                "requires_visual_context": bool(PHOTO.search(question)),
                "review_status": "approved",
                "reviewer": "h4-mechanics-full",
                "rights": {
                    "train": False,
                    "retrieval": True,
                    "send_cloud": True,
                    "public_serve": True,
                    "publish_source": True,
                    "publish_weights": False,
                    "rights_ref": "Mechanics Stack Exchange via HuggingFaceH4/stack-exchange-preferences, CC BY-SA.",
                },
                "content": content[:99000],
                "_catalog": {
                    "qid": qid,
                    "title": title,
                    "url": url,
                    "score": score,
                    "selected": bool(answer.get("selected")),
                },
            }
        )
    chosen.sort(key=lambda item: int(item["_catalog"]["score"]), reverse=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as handle:
        for item in chosen:
            catalog = item.pop("_catalog")
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
            item["_catalog"] = catalog
    CATALOG.write_text(
        json.dumps([item["_catalog"] for item in chosen[:40]], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"wrote {len(chosen)} documents to {OUT}")


if __name__ == "__main__":
    main()
