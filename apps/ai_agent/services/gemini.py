"""Cliente Gemini para embeddings y generación de texto."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from django.conf import settings
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = getattr(settings, 'GEMINI_EMBEDDING_MODEL', 'gemini-embedding-001')
CHAT_MODEL = getattr(settings, 'GEMINI_CHAT_MODEL', 'gemini-2.0-flash')


def _client() -> genai.Client:
    api_key = settings.GEMINI_API_KEY
    if not api_key:
        raise RuntimeError('GEMINI_API_KEY no configurada en el entorno.')
    return genai.Client(api_key=api_key)


def embed_text(text: str) -> list[float]:
    """Genera embedding vectorial para un fragmento de texto."""
    client = _client()
    response = client.models.embed_content(
        model=EMBEDDING_MODEL,
        contents=text,
        config=types.EmbedContentConfig(task_type='RETRIEVAL_DOCUMENT'),
    )
    return list(response.embeddings[0].values)


def embed_query(text: str) -> list[float]:
    """Embedding optimizado para consultas de búsqueda."""
    client = _client()
    response = client.models.embed_content(
        model=EMBEDDING_MODEL,
        contents=text,
        config=types.EmbedContentConfig(task_type='RETRIEVAL_QUERY'),
    )
    return list(response.embeddings[0].values)


def generate_chat_response(
    system_prompt: str,
    user_prompt: str,
    history: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Genera respuesta del asistente y metadatos estructurados."""
    client = _client()
    contents: list[types.Content] = []

    for turn in history or []:
        role = 'user' if turn['role'] == 'user' else 'model'
        contents.append(
            types.Content(
                role=role,
                parts=[types.Part.from_text(text=turn['content'])],
            )
        )

    contents.append(
        types.Content(
            role='user',
            parts=[types.Part.from_text(text=user_prompt)],
        )
    )

    response = client.models.generate_content(
        model=CHAT_MODEL,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=0.3,
            response_mime_type='application/json',
            response_schema={
                'type': 'OBJECT',
                'properties': {
                    'respuesta': {
                        'type': 'STRING',
                        'description': 'Guía completa en español con pasos numerados. Resolver sin ticket si es posible.',
                    },
                    'requiere_tecnico': {
                        'type': 'BOOLEAN',
                        'description': 'False por defecto. True solo emergencia, daño grave o falla tras intentar pasos.',
                    },
                    'titulo_ticket_sugerido': {
                        'type': 'STRING',
                        'description': 'Título breve si requiere_tecnico es true, vacío si no.',
                    },
                    'descripcion_ticket_sugerida': {
                        'type': 'STRING',
                        'description': 'Descripción estructurada del incidente si escala.',
                    },
                    'categoria_sugerida': {
                        'type': 'STRING',
                        'description': 'PLOMERIA|ELECTRICIDAD|INFRAESTRUCTURA|LIMPIEZA|SEGURIDAD|OTRO',
                    },
                    'prioridad_sugerida': {
                        'type': 'STRING',
                        'description': 'BAJA|MEDIA|ALTA|CRITICA',
                    },
                    'confianza': {
                        'type': 'NUMBER',
                        'description': 'Confianza 0.0-1.0 en la respuesta.',
                    },
                },
                'required': [
                    'respuesta',
                    'requiere_tecnico',
                    'confianza',
                ],
            },
        ),
    )

    raw = response.text or '{}'
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning('Respuesta Gemini no JSON, usando texto plano.')
        data = {
            'respuesta': raw.strip(),
            'requiere_tecnico': False,
            'confianza': 0.5,
        }

    return data


def analyze_ticket_description(
    titulo: str,
    descripcion: str,
    tecnicos: list[dict] | None = None,
) -> dict[str, Any]:
    """Analiza la descripción de un ticket y devuelve sugerencias estructuradas.

    Args:
        titulo: título del ticket ingresado por el inquilino.
        descripcion: descripción detallada del problema.
        tecnicos: lista de dicts con 'id' y 'nombre' de técnicos disponibles.

    Returns:
        Dict con categoria_sugerida, prioridad_sugerida, descripcion_tecnica,
        razon_asignacion, tecnico_sugerido_id y confianza.
    """
    client = _client()

    tecnicos_bloque = ''
    if tecnicos:
        lineas = [f'  - ID {t["id"]}: {t["nombre"]}' for t in tecnicos]
        tecnicos_bloque = 'Técnicos disponibles:\n' + '\n'.join(lineas) + '\n\n'

    prompt = (
        f'Analiza este ticket de mantenimiento inmobiliario:\n\n'
        f'TÍTULO: {titulo}\n'
        f'DESCRIPCIÓN: {descripcion}\n\n'
        f'{tecnicos_bloque}'
        f'Clasifica con precisión según el problema descrito y devuelve JSON.'
    )

    system = (
        'Eres un experto en mantenimiento inmobiliario. '
        'Analiza tickets de soporte y clasifícalos con precisión.\n'
        'Prioridades: BAJA (cosmético/estético), MEDIA (afecta confort), '
        'ALTA (funcionalidad esencial comprometida), CRITICA (riesgo de seguridad o daño grave inmediato).\n'
        'Categorías: PLOMERIA, ELECTRICIDAD, INFRAESTRUCTURA, LIMPIEZA, SEGURIDAD, OTRO.\n'
        'Responde exclusivamente en JSON según el esquema solicitado. Sin texto adicional.'
    )

    response = client.models.generate_content(
        model=CHAT_MODEL,
        contents=[types.Content(role='user', parts=[types.Part.from_text(text=prompt)])],
        config=types.GenerateContentConfig(
            system_instruction=system,
            temperature=0.1,
            response_mime_type='application/json',
            response_schema={
                'type': 'OBJECT',
                'properties': {
                    'categoria_sugerida': {
                        'type': 'STRING',
                        'description': 'PLOMERIA|ELECTRICIDAD|INFRAESTRUCTURA|LIMPIEZA|SEGURIDAD|OTRO',
                    },
                    'prioridad_sugerida': {
                        'type': 'STRING',
                        'description': 'BAJA|MEDIA|ALTA|CRITICA',
                    },
                    'descripcion_tecnica': {
                        'type': 'STRING',
                        'description': 'Resumen técnico del problema en ≤ 300 caracteres para el técnico.',
                    },
                    'razon_asignacion': {
                        'type': 'STRING',
                        'description': 'Por qué se asigna esa prioridad y categoría en ≤ 200 caracteres.',
                    },
                    'tecnico_sugerido_id': {
                        'type': 'INTEGER',
                        'description': 'ID del técnico más adecuado según la lista. 0 si no aplica.',
                    },
                    'confianza': {
                        'type': 'NUMBER',
                        'description': 'Confianza en el análisis entre 0.0 y 1.0.',
                    },
                },
                'required': [
                    'categoria_sugerida',
                    'prioridad_sugerida',
                    'descripcion_tecnica',
                    'confianza',
                ],
            },
        ),
    )

    raw = response.text or '{}'
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.warning('Respuesta Gemini no JSON en analyze_ticket: %s', raw[:200])
        return {
            'categoria_sugerida': 'OTRO',
            'prioridad_sugerida': 'MEDIA',
            'descripcion_tecnica': descripcion[:300],
            'razon_asignacion': '',
            'tecnico_sugerido_id': 0,
            'confianza': 0.5,
        }


def chunk_text(text: str, chunk_size: int = 600, overlap: int = 80) -> list[str]:
    """Divide texto en fragmentos con solapamiento para indexación RAG."""
    text = re.sub(r'\s+', ' ', text.strip())
    if not text:
        return []

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = end - overlap
    return chunks
