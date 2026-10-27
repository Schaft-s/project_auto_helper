from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any

from autonaparnik.config import Settings
from autonaparnik.domain.models import Document, VehicleProfile
from autonaparnik.retrieval.search import CorpusIndex, RetrievedChunk, applicability, _to_chunk

MECHANICS_COLLECTION = "mechanics_se"
MANUALS_COLLECTION = "tech_manuals"
DENSE_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
SPARSE_MODEL = "Qdrant/bm25"
DENSE_DIM = 384

_dense = None
_sparse = None


def _models():
    global _dense, _sparse
    from fastembed import SparseTextEmbedding, TextEmbedding

    if _dense is None:
        _dense = TextEmbedding(DENSE_MODEL)
    if _sparse is None:
        _sparse = SparseTextEmbedding(SPARSE_MODEL)
    return _dense, _sparse


def embed_passages(texts: list[str]) -> tuple[list[list[float]], list[Any]]:
    dense_model, sparse_model = _models()
    dense = [list(vec) for vec in dense_model.embed(texts)]
    sparse = list(sparse_model.embed(texts))
    return dense, sparse


def embed_query(query: str) -> tuple[list[float], Any]:
    dense_model, sparse_model = _models()
    dense = list(next(dense_model.embed([query])))
    sparse = next(sparse_model.embed([query]))
    return dense, sparse


def point_id(document_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, document_id))


def document_payload(doc: Document, collection: str) -> dict[str, Any]:
    return {
        "collection": collection,
        "document": doc.model_dump(mode="json"),
    }


class QdrantDiscussionsIndex:
    def __init__(self, settings: Settings, fallback: CorpusIndex):
        self.settings = settings
        self.fallback = fallback
        self._client = None

    def _connect(self):
        if self._client is not None:
            return self._client
        from qdrant_client import QdrantClient

        self._client = QdrantClient(url=self.settings.qdrant_url, timeout=5, check_compatibility=False)
        return self._client

    def available(self) -> bool:
        try:
            names = {item.name for item in self._connect().get_collections().collections}
        except Exception:
            return False
        return MECHANICS_COLLECTION in names or MANUALS_COLLECTION in names

    def search(
        self,
        query: str,
        vehicle: VehicleProfile,
        top_k: int = 4,
        collection: str | None = "both",
    ) -> list[RetrievedChunk]:
        if not self.available():
            return self.fallback.search(query, vehicle, top_k=top_k, collection=collection)
        names = _target_collections(collection)
        existing = {item.name for item in self._connect().get_collections().collections}
        names = [name for name in names if name in existing]
        if not names:
            return self.fallback.search(query, vehicle, top_k=top_k, collection=collection)
        try:
            dense, sparse = embed_query(query)
        except Exception:
            return self.fallback.search(query, vehicle, top_k=top_k, collection=collection)
        ranked: dict[str, tuple[float, Document]] = {}
        for name in names:
            for rank, doc in enumerate(_query_collection(self._connect(), name, dense, sparse, top_k * 3), start=1):
                score = ranked.get(doc.document_id, (0.0, doc))[0] + 1.0 / (60 + rank)
                ranked[doc.document_id] = (score, doc)
        now = datetime.now(timezone.utc)
        scored = []
        for score, doc in ranked.values():
            if doc.review_status != "approved":
                continue
            if not doc.rights.retrieval or not doc.rights.public_serve:
                continue
            appl = applicability(doc, vehicle)
            if appl == "mismatch":
                continue
            scored.append((score, doc, appl))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [_to_chunk(doc, appl, score, now) for score, doc, appl in scored[:top_k]]


def _target_collections(collection: str | None) -> list[str]:
    if collection == "mechanics":
        return [MECHANICS_COLLECTION]
    if collection == "manuals":
        return [MANUALS_COLLECTION]
    return [MECHANICS_COLLECTION, MANUALS_COLLECTION]


def _query_collection(client, name: str, dense: list[float], sparse, limit: int) -> list[Document]:
    from qdrant_client import models

    result = client.query_points(
        collection_name=name,
        prefetch=[
            models.Prefetch(query=dense, using="dense", limit=limit),
            models.Prefetch(
                query=models.SparseVector(indices=list(sparse.indices), values=list(sparse.values)),
                using="bm25",
                limit=limit,
            ),
        ],
        query=models.FusionQuery(fusion=models.Fusion.RRF),
        limit=limit,
        with_payload=True,
    )
    docs = []
    for point in result.points:
        raw = (point.payload or {}).get("document")
        if not isinstance(raw, dict):
            continue
        raw = dict(raw)
        content = raw.get("content") or ""
        raw["content_sha256"] = hashlib.sha256(content.encode("utf-8")).hexdigest()
        docs.append(Document.model_validate(raw))
    return docs
