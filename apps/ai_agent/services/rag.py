"""Pipeline RAG: indexación y recuperación semántica."""

from __future__ import annotations

import math

from django.db import transaction

from apps.ai_agent.models import KnowledgeChunk, KnowledgeDocument

from .gemini import chunk_text, embed_text


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def index_document(documento: KnowledgeDocument) -> int:
    """Genera chunks y embeddings para un documento. Retorna cantidad indexada."""
    fragmentos = chunk_text(documento.contenido)
    if not fragmentos:
        return 0

    with transaction.atomic():
        documento.chunks.all().delete()
        for idx, fragmento in enumerate(fragmentos):
            embedding = embed_text(fragmento)
            KnowledgeChunk.objects.create(
                documento=documento,
                indice=idx,
                contenido=fragmento,
                embedding=embedding,
                token_count=len(fragmento.split()),
            )
        documento.indexado = True
        documento.save(update_fields=['indexado', 'actualizado_en'])

    return len(fragmentos)


def retrieve_relevant_chunks(
    query_embedding: list[float],
    top_k: int = 5,
    min_score: float = 0.28,
) -> list[KnowledgeChunk]:
    """Recupera los fragmentos más relevantes por similitud coseno."""
    chunks = (
        KnowledgeChunk.objects
        .filter(documento__activo=True, documento__indexado=True)
        .select_related('documento')
    )

    scored: list[tuple[float, KnowledgeChunk]] = []
    for chunk in chunks:
        score = _cosine_similarity(query_embedding, chunk.embedding)
        if score >= min_score:
            scored.append((score, chunk))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [chunk for _, chunk in scored[:top_k]]
