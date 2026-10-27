"""Upsert Mechanics SE and BCcampus chunks into Qdrant hybrid collections."""
from __future__ import annotations

import json
from pathlib import Path

from autonaparnik.config import ROOT, load_settings
from autonaparnik.domain.models import Document
from autonaparnik.retrieval.qdrant import (
    DENSE_DIM,
    MANUALS_COLLECTION,
    MECHANICS_COLLECTION,
    document_payload,
    embed_passages,
    point_id,
)

BATCH = 32


def load_docs(path: Path) -> list[Document]:
    if not path.exists():
        return []
    docs = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        raw = json.loads(line)
        docs.append(Document.model_validate(raw))
    return docs


def ensure_collection(client, name: str) -> None:
    from qdrant_client import models

    names = {item.name for item in client.get_collections().collections}
    if name in names:
        return
    client.create_collection(
        collection_name=name,
        vectors_config={"dense": models.VectorParams(size=DENSE_DIM, distance=models.Distance.COSINE)},
        sparse_vectors_config={"bm25": models.SparseVectorParams(modifier=models.Modifier.IDF)},
    )


def upsert(client, name: str, docs: list[Document], collection_tag: str) -> int:
    from qdrant_client import models

    total = 0
    for start in range(0, len(docs), BATCH):
        batch = docs[start : start + BATCH]
        texts = [f"{doc.title}\n{doc.content}" for doc in batch]
        dense, sparse = embed_passages(texts)
        points = []
        for doc, vec, spr in zip(batch, dense, sparse):
            points.append(
                models.PointStruct(
                    id=point_id(doc.document_id),
                    vector={
                        "dense": vec,
                        "bm25": models.SparseVector(indices=list(spr.indices), values=list(spr.values)),
                    },
                    payload=document_payload(doc, collection_tag),
                )
            )
        client.upsert(collection_name=name, points=points)
        total += len(points)
        print(f"{name}: {total}/{len(docs)}")
    return total


def main() -> None:
    from qdrant_client import QdrantClient

    settings = load_settings()
    client = QdrantClient(url=settings.qdrant_url, timeout=30, check_compatibility=False)
    ensure_collection(client, MECHANICS_COLLECTION)
    ensure_collection(client, MANUALS_COLLECTION)
    mechanics = load_docs(ROOT / "data" / "mechanics" / "qa.jsonl")
    manuals = load_docs(ROOT / "data" / "bccampus" / "chunks.jsonl")
    n_m = upsert(client, MECHANICS_COLLECTION, mechanics, "mechanics")
    n_b = upsert(client, MANUALS_COLLECTION, manuals, "manuals")
    print(json.dumps({"mechanics": n_m, "manuals": n_b, "url": settings.qdrant_url}))


if __name__ == "__main__":
    main()
