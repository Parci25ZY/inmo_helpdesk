"""Orquestación conversacional del chatbot con RAG."""

from __future__ import annotations

from django.utils import timezone

from apps.ai_agent.models import ChatMessage, ChatSession

from .gemini import embed_query, generate_chat_response
from .rag import retrieve_relevant_chunks

SYSTEM_PROMPT = """Eres el asistente virtual de InmoHelpdesk, especializado en mantenimiento
inmobiliario para inquilinos de edificios y condominios en Ecuador.

OBJETIVO PRINCIPAL: Resolver la consulta SIN técnico siempre que sea posible. Eres el primer
nivel de soporte: guías paso a paso, prevención y orientación. El ticket es el ÚLTIMO recurso.

REGLAS:
1. Responde SIEMPRE en español, tono profesional, claro y empático.
2. Usa el CONTEXTO RAG como fuente principal; si hay contexto relevante, da pasos concretos.
3. Si el contexto no cubre algo, ofrece medidas seguras generales y sugiere contactar al
   administrador — NO inventes procedimientos técnicos específicos.
4. requiere_tecnico=false por defecto. Usa true SOLO si se cumple AL MENOS UNA:
   - Daño estructural, riesgo eléctrico/gas/incendio activo, inundación grave incontrolable.
   - Equipo averiado que el inquilino no puede operar (tablero general, tubería empotrada rota).
   - El usuario ya intentó los pasos del contexto y el problema persiste o empeora.
5. requiere_tecnico=false cuando:
   - Pregunta "cómo", "dónde", "qué hago si", horarios, procedimientos, prevención.
   - Fuga leve, grifo goteando, disyuntor, llave de paso, dudas de reporte.
   - Puedes dar una guía completa con el contexto disponible.
6. En la respuesta incluye pasos numerados cuando ayude. Menciona crear ticket solo si
   requiere_tecnico=true, sin presionar si se resolvió la duda.
7. Emergencias: indica 911 y medidas inmediatas; requiere_tecnico=true.

Responde en JSON según el esquema solicitado."""


def _build_context(chunks) -> str:
    if not chunks:
        return '(Sin contexto RAG disponible — responde con precaución.)'
    parts = []
    for i, chunk in enumerate(chunks, 1):
        parts.append(
            f'[{i}] {chunk.documento.titulo} ({chunk.documento.get_categoria_display()}):\n'
            f'{chunk.contenido}'
        )
    return '\n\n'.join(parts)


_EMERGENCY = frozenset({
    'incendio', 'fuego', 'gas', 'explosión', 'explosion', '911', 'inundación grave',
    'electrocut', 'chispa', 'corto circuito con humo',
})
_DAMAGE_REQUIRES_TECH = frozenset({
    'tubo roto', 'tubería rota', 'sin luz en todo', 'tablero general', 'cielo raso cayendo',
    'derrumbe', 'estructural', 'cortocircuito persistente', 'no para de gotear',
    'empeora', 'no funcionó', 'sigue igual',
})
_INFORMATIONAL = frozenset({
    'cómo', 'como', 'dónde', 'donde', 'qué hago', 'que hago', 'cuál es', 'cual es',
    'horario', 'procedimiento', 'pasos', 'puedo', 'debo', 'recomiendas',
})


def _normalize_escalation(result: dict, user_text: str, chunks: list) -> dict:
    """Evita escalar a técnico cuando la consulta es resoluble con RAG."""
    text = user_text.lower()
    out = dict(result)

    if any(k in text for k in _EMERGENCY):
        out['requiere_tecnico'] = True
        return out

    if any(k in text for k in _INFORMATIONAL) and chunks:
        out['requiere_tecnico'] = False
        if out.get('titulo_ticket_sugerido'):
            out['titulo_ticket_sugerido'] = ''
            out['descripcion_ticket_sugerida'] = ''
        return out

    if out.get('requiere_tecnico') and not any(k in text for k in _DAMAGE_REQUIRES_TECH):
        if len(chunks) >= 2:
            out['requiere_tecnico'] = False
            out['titulo_ticket_sugerido'] = ''
            out['descripcion_ticket_sugerida'] = ''

    return out


def _session_history(sesion: ChatSession, limit: int = 8) -> list[dict[str, str]]:
    mensajes = (
        sesion.mensajes
        .filter(estado_proceso=ChatMessage.EstadoProceso.COMPLETADO)
        .exclude(rol=ChatMessage.Rol.SISTEMA)
        .order_by('-creado_en')[:limit]
    )
    history = []
    for msg in reversed(list(mensajes)):
        role = 'user' if msg.rol == ChatMessage.Rol.USUARIO else 'model'
        history.append({'role': role, 'content': msg.contenido})
    return history


def process_user_message(asistente_msg: ChatMessage) -> ChatMessage:
    """Procesa el mensaje del usuario vinculado y actualiza la respuesta del asistente."""
    sesion = asistente_msg.sesion
    user_msg = (
        sesion.mensajes
        .filter(rol=ChatMessage.Rol.USUARIO, creado_en__lt=asistente_msg.creado_en)
        .order_by('-creado_en')
        .first()
    )
    if not user_msg:
        asistente_msg.contenido = 'No encontré tu mensaje. Intenta de nuevo.'
        asistente_msg.estado_proceso = ChatMessage.EstadoProceso.ERROR
        asistente_msg.save(update_fields=['contenido', 'estado_proceso'])
        return asistente_msg

    try:
        query_embedding = embed_query(user_msg.contenido)
        chunks = retrieve_relevant_chunks(query_embedding)
        context = _build_context(chunks)
        history = _session_history(sesion)

        user_prompt = f"""CONTEXTO RAG:
{context}

PREGUNTA DEL INQUILINO:
{user_msg.contenido}

Responde según las reglas del sistema."""

        try:
            from apps.ai_agent.services.langchain_rag import generate_with_langchain
            result = generate_with_langchain(user_msg.contenido, history)
        except Exception:
            result = generate_chat_response(
                system_prompt=SYSTEM_PROMPT,
                user_prompt=user_prompt,
                history=history[:-1] if history else None,
            )

        result = _normalize_escalation(result, user_msg.contenido, chunks)

        asistente_msg.contenido = result.get('respuesta', 'No pude generar una respuesta.')
        asistente_msg.metadata = {
            'requiere_tecnico': result.get('requiere_tecnico', False),
            'titulo_ticket_sugerido': result.get('titulo_ticket_sugerido', ''),
            'descripcion_ticket_sugerida': result.get('descripcion_ticket_sugerida', ''),
            'categoria_sugerida': result.get('categoria_sugerida', 'OTRO'),
            'prioridad_sugerida': result.get('prioridad_sugerida', 'MEDIA'),
            'confianza': result.get('confianza', 0.0),
            'chunks_count': len(chunks),
        }
        asistente_msg.estado_proceso = ChatMessage.EstadoProceso.COMPLETADO
        asistente_msg.save(update_fields=['contenido', 'metadata', 'estado_proceso'])

        if chunks:
            asistente_msg.chunks_usados.set(chunks)

        if not sesion.titulo and user_msg.contenido:
            sesion.titulo = user_msg.contenido[:120]
            sesion.save(update_fields=['titulo', 'actualizado_en'])
        else:
            sesion.actualizado_en = timezone.now()
            sesion.save(update_fields=['actualizado_en'])

    except Exception as exc:
        asistente_msg.contenido = (
            'Hubo un error al procesar tu consulta. '
            'Por favor intenta de nuevo o reporta la incidencia directamente.'
        )
        asistente_msg.estado_proceso = ChatMessage.EstadoProceso.ERROR
        asistente_msg.metadata = {'error': str(exc)}
        asistente_msg.save(update_fields=['contenido', 'estado_proceso', 'metadata'])

    return asistente_msg
