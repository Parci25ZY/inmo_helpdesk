"""Tareas Celery para indexación RAG, chatbot y análisis de tickets."""

from __future__ import annotations

from celery import shared_task

from apps.ai_agent.models import ChatMessage, KnowledgeDocument

from apps.ai_agent.services.chat import process_user_message
from apps.ai_agent.services.rag import index_document


@shared_task(bind=True, max_retries=2, default_retry_delay=5)
def index_knowledge_document(self, documento_id: int) -> dict:
    """Indexa un documento de conocimiento (chunks + embeddings)."""
    try:
        documento = KnowledgeDocument.objects.get(pk=documento_id)
        count = index_document(documento)
        return {'documento_id': documento_id, 'chunks': count}
    except KnowledgeDocument.DoesNotExist:
        return {'error': 'documento no encontrado'}
    except Exception as exc:
        raise self.retry(exc=exc)


def _run_ticket_analysis(ticket_id: int) -> dict:
    """Lógica de análisis IA de un ticket — usable como tarea o fallback síncrono."""
    from apps.accounts.models import CustomUser
    from apps.tickets.models import Ticket, TicketStatus
    from apps.tickets.services.transitions import InvalidTransitionError, transition_ticket

    from apps.ai_agent.services.gemini import analyze_ticket_description

    try:
        ticket = Ticket.objects.select_related('inquilino').get(pk=ticket_id)
    except Ticket.DoesNotExist:
        return {'error': 'ticket no encontrado'}

    if ticket.estado != TicketStatus.CREADO_PENDIENTE_IA:
        return {'skipped': 'estado ya avanzado, sin acción'}

    tecnicos = list(
        CustomUser.objects.filter(role=CustomUser.Roles.TECNICO, is_active=True)
        .values('id', 'first_name', 'last_name', 'especialidad')
    )
    tecnicos_data = [
        {
            'id': t['id'],
            'nombre': f"{t['first_name']} {t['last_name']}".strip(),
            'especialidad': t.get('especialidad', ''),
        }
        for t in tecnicos
    ]

    resultado = analyze_ticket_description(
        titulo=ticket.titulo,
        descripcion=ticket.descripcion,
        tecnicos=tecnicos_data,
    )

    # Validar valores contra enums antes de persistir
    from apps.tickets.models import TicketCategory, TicketPriority
    _categorias_validas = set(TicketCategory.values)
    _prioridades_validas = set(TicketPriority.values)

    cat_raw = resultado.get('categoria_sugerida', '')
    pri_raw = resultado.get('prioridad_sugerida', '')

    # Persistir sugerencias IA
    ticket.ia_categoria_sugerida = cat_raw if cat_raw in _categorias_validas else TicketCategory.OTRO
    ticket.ia_prioridad_sugerida = pri_raw if pri_raw in _prioridades_validas else TicketPriority.MEDIA
    ticket.ia_descripcion_tecnica = resultado.get('descripcion_tecnica', '')
    ticket.ia_razon_asignacion = resultado.get('razon_asignacion', '')
    ticket.ia_confianza = resultado.get('confianza')

    update_fields = [
        'ia_categoria_sugerida', 'ia_prioridad_sugerida',
        'ia_descripcion_tecnica', 'ia_razon_asignacion', 'ia_confianza',
    ]

    # Asignar categoría y prioridad al ticket basándose en la IA
    ticket.categoria = ticket.ia_categoria_sugerida
    ticket.prioridad = ticket.ia_prioridad_sugerida
    update_fields.extend(['categoria', 'prioridad'])

    tecnico_id = resultado.get('tecnico_sugerido_id') or 0
    tecnico_asignado = None
    if tecnico_id:
        try:
            tecnico_asignado = CustomUser.objects.get(pk=tecnico_id, role=CustomUser.Roles.TECNICO, is_active=True)
            ticket.ia_tecnico_sugerido = tecnico_asignado
            update_fields.append('ia_tecnico_sugerido')
        except CustomUser.DoesNotExist:
            pass

    ticket.save(update_fields=update_fields)

    # Transicionar a ANALIZADO_POR_IA
    try:
        transition_ticket(ticket, nuevo_estado=TicketStatus.ANALIZADO_POR_IA, actor_role='SYSTEM')
    except InvalidTransitionError:
        pass

    # Auto-asignación: si confianza >= 0.8 y hay técnico sugerido válido
    confianza = resultado.get('confianza', 0) or 0
    if confianza >= 0.8 and tecnico_asignado is not None:
        ticket.tecnico = tecnico_asignado
        ticket.save(update_fields=['tecnico'])
        try:
            transition_ticket(
                ticket,
                nuevo_estado=TicketStatus.ASIGNADO,
                actor_role='SYSTEM',
                nota=f'Auto-asignado por IA a {tecnico_asignado.get_full_name()} (confianza: {confianza:.2f}).',
            )
        except InvalidTransitionError:
            pass
    else:
        # Confianza baja o sin técnico → pasa a validación del admin
        try:
            transition_ticket(
                ticket,
                nuevo_estado=TicketStatus.PENDIENTE_VALIDACION,
                actor_role='SYSTEM',
                nota='Pendiente de validación manual por el administrador.',
            )
        except InvalidTransitionError:
            pass

    return {
        'ticket_id': ticket_id,
        'categoria': ticket.ia_categoria_sugerida,
        'prioridad': ticket.ia_prioridad_sugerida,
        'confianza': str(ticket.ia_confianza),
        'auto_asignado': confianza >= 0.8 and tecnico_asignado is not None,
    }


@shared_task(bind=True, max_retries=2, default_retry_delay=10)
def analyze_ticket(self, ticket_id: int) -> dict:
    """Analiza un ticket recién creado con Gemini y registra las sugerencias IA."""
    try:
        return _run_ticket_analysis(ticket_id)
    except Exception as exc:
        # Si Gemini falla, avanzar manualmente a PENDIENTE_VALIDACION como fallback
        try:
            from apps.tickets.models import Ticket, TicketStatus
            from apps.tickets.services.transitions import transition_ticket
            ticket = Ticket.objects.get(pk=ticket_id)
            if ticket.estado == TicketStatus.CREADO_PENDIENTE_IA:
                transition_ticket(
                    ticket,
                    nuevo_estado=TicketStatus.PENDIENTE_VALIDACION,
                    actor_role='SYSTEM',
                    nota='Análisis IA falló — pendiente de revisión manual.',
                )
        except Exception:
            pass
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=2, default_retry_delay=3)
def process_chat_message(self, mensaje_id: int) -> dict:
    """Procesa respuesta del asistente para un mensaje de usuario."""
    try:
        asistente_msg = ChatMessage.objects.select_related('sesion').get(pk=mensaje_id)
        process_user_message(asistente_msg)
        return {
            'mensaje_uuid': str(asistente_msg.uuid),
            'estado': asistente_msg.estado_proceso,
        }
    except ChatMessage.DoesNotExist:
        return {'error': 'mensaje no encontrado'}
    except Exception as exc:
        raise self.retry(exc=exc)
