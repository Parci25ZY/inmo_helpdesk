"""Pipeline RAG: indexación y recuperación semántica."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
from django.db import transaction

from apps.ai_agent.models import KnowledgeChunk, KnowledgeDocument

from .gemini import chunk_text, embed_text

logger = logging.getLogger(__name__)


def _cosine_similarity_batch(
    query: np.ndarray,
    matrix: np.ndarray,
) -> np.ndarray:
    """Calcula similitud coseno entre un vector query y una matriz de embeddings.

    Args:
        query: vector 1-D de shape (d,).
        matrix: matriz 2-D de shape (n, d).

    Returns:
        Array 1-D de shape (n,) con las similitudes.
    """
    if matrix.size == 0:
        return np.array([])
    # Normalizar
    query_norm = query / (np.linalg.norm(query) + 1e-10)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-10
    matrix_norm = matrix / norms
    return matrix_norm @ query_norm


def index_document(documento: KnowledgeDocument) -> int:
    """Genera chunks y embeddings para un documento. Retorna cantidad indexada.

    Usa ThreadPoolExecutor para paralelizar las llamadas a la API de
    embeddings, reduciendo la latencia total de O(n × latencia) a
    ~O(latencia) con suficientes workers.
    """
    fragmentos = chunk_text(documento.contenido)
    if not fragmentos:
        return 0

    # Generar embeddings en paralelo (máx 4 workers para no saturar la API)
    embeddings: dict[int, list[float]] = {}

    def _embed(idx: int, texto: str) -> tuple[int, list[float]]:
        return idx, embed_text(texto)

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {
            pool.submit(_embed, idx, frag): idx
            for idx, frag in enumerate(fragmentos)
        }
        for future in as_completed(futures):
            try:
                idx, emb = future.result()
                embeddings[idx] = emb
            except Exception as exc:
                idx = futures[future]
                logger.warning(
                    'Error generando embedding para chunk %d del doc %s: %s',
                    idx, documento.titulo, exc,
                )
                embeddings[idx] = []

    with transaction.atomic():
        documento.chunks.all().delete()
        for idx, fragmento in enumerate(fragmentos):
            KnowledgeChunk.objects.create(
                documento=documento,
                indice=idx,
                contenido=fragmento,
                embedding=embeddings.get(idx, []),
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
    """Recupera los fragmentos más relevantes por similitud coseno.

    Usa NumPy para cálculo vectorizado batch en lugar de iterar uno
    por uno en Python puro. ~100x más rápido para colecciones grandes.
    """
    chunks = list(
        KnowledgeChunk.objects
        .filter(documento__activo=True, documento__indexado=True)
        .select_related('documento')
    )

    if not chunks:
        return []

    # Filtrar chunks sin embedding válido
    valid_chunks = [c for c in chunks if c.embedding]
    if not valid_chunks:
        return []

    query_vec = np.asarray(query_embedding, dtype=np.float32)
    embedding_matrix = np.asarray(
        [c.embedding for c in valid_chunks], dtype=np.float32,
    )

    scores = _cosine_similarity_batch(query_vec, embedding_matrix)

    # Filtrar por score mínimo y ordenar
    mask = scores >= min_score
    if not mask.any():
        return []

    indices = np.where(mask)[0]
    filtered_scores = scores[indices]
    top_indices = indices[np.argsort(filtered_scores)[::-1][:top_k]]

    return [valid_chunks[i] for i in top_indices]
