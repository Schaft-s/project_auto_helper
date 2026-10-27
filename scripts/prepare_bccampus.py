"""Chunk BCcampus / Camosun Trades Access Common Core text (CC BY 4.0, text only)."""
from __future__ import annotations

import hashlib
import html
import json
import re
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "bccampus" / "chunks.jsonl"
HTML_TAG = re.compile(r"<[^>]+>")

SOURCES = [
    {
        "document_prefix": "BCC-E4",
        "title": "Use Multimeters",
        "url": "https://openlibrary-repo.ecampusontario.ca/jspui/bitstream/123456789/423/4/E4.pdf",
        "kind": "pdf",
        "rights_ref": "Camosun College, Trades Access Common Core E-4, CC BY 4.0 (text only; ITA illustrations excluded).",
    },
    {
        "document_prefix": "BCC-C1",
        "title": "Describe Common Hand Tools and Their Uses",
        "url": "https://opentextbc.ca/constructiontradescommoncorec1/",
        "kind": "html",
        "rights_ref": "Camosun College / BCcampus, Trades Access Common Core C-1, CC BY 4.0 with documented exceptions.",
    },
]


def strip_html(text: str) -> str:
    text = HTML_TAG.sub(" ", text or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def chunk_text(text: str, size: int = 1000, overlap: int = 150) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    chunks = []
    start = 0
    while start < len(text):
        end = min(len(text), start + size)
        piece = text[start:end].strip()
        if len(piece) >= 200:
            chunks.append(piece)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks


def pdf_text(data: bytes) -> str:
    from pypdf import PdfReader
    from io import BytesIO

    reader = PdfReader(BytesIO(data))
    pages = []
    for page in reader.pages:
        pages.append(page.extract_text() or "")
    return re.sub(r"\s+", " ", " ".join(pages)).strip()


def fetch(source: dict) -> str:
    response = httpx.get(source["url"], timeout=45.0, follow_redirects=True)
    response.raise_for_status()
    if source["kind"] == "pdf":
        return pdf_text(response.content)
    return strip_html(response.text)


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    docs = []
    for source in SOURCES:
        try:
            text = fetch(source)
        except Exception as exc:
            print(f"skip {source['document_prefix']}: {exc}")
            continue
        for index, chunk in enumerate(chunk_text(text), start=1):
            doc_id = f"{source['document_prefix']}-{index:03d}"
            docs.append(
                {
                    "document_id": doc_id,
                    "source_group_id": source["document_prefix"],
                    "operation_type": "public_guidance",
                    "title": f"{source['title']} ({index})",
                    "language": "en",
                    "source_type": "public_guidance",
                    "workflow_context": "general",
                    "transfer_scope": "general_principle",
                    "vehicle_constraints": {
                        "make": None,
                        "model": None,
                        "model_year": None,
                        "market": "unknown",
                        "variant": None,
                    },
                    "revision": "bccampus-text",
                    "locator": source["url"],
                    "content_sha256": hashlib.sha256(chunk.encode("utf-8")).hexdigest(),
                    "requires_visual_context": False,
                    "review_status": "approved",
                    "reviewer": "bccampus-text-ingest",
                    "rights": {
                        "train": False,
                        "retrieval": True,
                        "send_cloud": True,
                        "public_serve": True,
                        "publish_source": True,
                        "publish_weights": False,
                        "rights_ref": source["rights_ref"][:500],
                    },
                    "content": chunk[:99000],
                }
            )
    if not docs:
        raise SystemExit("no BCcampus chunks fetched")
    with OUT.open("w", encoding="utf-8") as handle:
        for doc in docs:
            handle.write(json.dumps(doc, ensure_ascii=False) + "\n")
    print(f"wrote {len(docs)} chunks to {OUT}")


if __name__ == "__main__":
    main()
