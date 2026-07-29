
from __future__ import annotations

from celery import shared_task

from apps.ai_agent.models import ChatMessage, KnowledgeDocument

from apps.ai_agent.services.chat import process_user_message
from apps.ai_agent.services.rag import index_document


@shared_task(bind=True, max_retries=2, default_retry_delay=5)
def index_knowledge_document(self, documento_id: int) -> dict:
    try:
        documento = KnowledgeDocument.objects.get(pk=documento_id)
        count = index_document(documento)
        return {'documento_id': documento_id, 'chunks': count}
    except KnowledgeDocument.DoesNotExist:
        return {'error': 'documento no encontrado'}
    except Exception as exc:
        raise self.retry(exc=exc)


def _run_ticket_analysis(ticket_id: int) -> dict:
    from apps.accounts.models import CustomUser
    from apps.tickets.models import Ticket, TicketStatus
    from apps.tickets.services.assignment import (
        get_technicians_with_workload,
        suggest_best_technician,
    )
    from apps.tickets.services.transitions import InvalidTransitionError, transition_ticket

    from apps.ai_agent.services.gemini import analyze_ticket_description

    try:
        ticket = Ticket.objects.select_related('inquilino').get(pk=ticket_id)
    except Ticket.DoesNotExist:
        return {'error': 'ticket no encontrado'}

    if ticket.estado != TicketStatus.CREADO_PENDIENTE_IA:
        return {'skipped': 'estado ya avanzado, sin acción'}

    tecnicos_workload = get_technicians_with_workload()
    tecnicos_data = [
        {
            'id': t['id'],
            'nombre': t['nombre'],
            'especialidad': t.get('especialidad', ''),
            'carga_actual': t['carga_actual'],
            'max_carga': t['max_carga'],
            'disponible': t['carga_disponible'] > 0,
        }
        for t in tecnicos_workload
    ]

    resultado = analyze_ticket_description(
        titulo=ticket.titulo,
        descripcion=ticket.descripcion,
        tecnicos=tecnicos_data,
    )

    from apps.tickets.models import TicketCategory, TicketPriority
    _categorias_validas = set(TicketCategory.values)
    _prioridades_validas = set(TicketPriority.values)

    cat_raw = resultado.get('categoria_sugerida', '')
    pri_raw = resultado.get('prioridad_sugerida', '')

    ticket.ia_categoria_sugerida = cat_raw if cat_raw in _categorias_validas else TicketCategory.OTRO
    ticket.ia_prioridad_sugerida = pri_raw if pri_raw in _prioridades_validas else TicketPriority.MEDIA
    ticket.ia_descripcion_tecnica = resultado.get('descripcion_tecnica', '')
    ticket.ia_razon_asignacion = resultado.get('razon_asignacion', '')
    ticket.ia_confianza = resultado.get('confianza')

    update_fields = [
        'ia_categoria_sugerida', 'ia_prioridad_sugerida',
        'ia_descripcion_tecnica', 'ia_razon_asignacion', 'ia_confianza',
    ]

    ticket.categoria = ticket.ia_categoria_sugerida
    ticket.prioridad = ticket.ia_prioridad_sugerida
    update_fields.extend(['categoria', 'prioridad'])

    tecnico_id = resultado.get('tecnico_sugerido_id') or 0
    tecnico_sugerido = None
    if tecnico_id:
        try:
            tecnico_sugerido = CustomUser.objects.get(
                pk=tecnico_id, role=CustomUser.Roles.TECNICO, is_active=True,
            )
            ticket.ia_tecnico_sugerido = tecnico_sugerido
            update_fields.append('ia_tecnico_sugerido')
        except CustomUser.DoesNotExist:
            pass

    if tecnico_sugerido is None:
        mejor = suggest_best_technician(ticket.categoria, ticket.prioridad)
        if mejor is not None:
            ticket.ia_tecnico_sugerido = mejor
            tecnico_sugerido = mejor
            update_fields.append('ia_tecnico_sugerido')

    ticket.save(update_fields=update_fields)

    try:
        transition_ticket(ticket, nuevo_estado=TicketStatus.ANALIZADO_POR_IA, actor_role='SYSTEM')
    except InvalidTransitionError:
        pass

    try:
        nota_validacion = 'Pre-asignación IA pendiente de validación por el administrador.'
        if tecnico_sugerido:
            nota_validacion = (
                f'Pre-asignación IA: {tecnico_sugerido.get_full_name()} '
                f'(confianza: {resultado.get("confianza", 0):.2f}). '
                f'Pendiente de validación por el administrador.'
            )
        transition_ticket(
            ticket,
            nuevo_estado=TicketStatus.PENDIENTE_VALIDACION,
            actor_role='SYSTEM',
            nota=nota_validacion,
        )
    except InvalidTransitionError:
        pass

    return {
        'ticket_id': ticket_id,
        'categoria': ticket.ia_categoria_sugerida,
        'prioridad': ticket.ia_prioridad_sugerida,
        'confianza': str(ticket.ia_confianza),
        'tecnico_sugerido': tecnico_sugerido.get_full_name() if tecnico_sugerido else None,
        'auto_asignado': False,
    }


@shared_task(bind=True, max_retries=2, default_retry_delay=10)
def analyze_ticket(self, ticket_id: int) -> dict:
    try:
        return _run_ticket_analysis(ticket_id)
    except Exception as exc:
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
def process_chat_message(self, mensaje_id: int, user_mensaje_id: int | None = None) -> dict:
    try:
        asistente_msg = ChatMessage.objects.select_related('sesion').get(pk=mensaje_id)
        user_msg = None
        if user_mensaje_id is not None:
            user_msg = ChatMessage.objects.filter(pk=user_mensaje_id).first()
        process_user_message(asistente_msg, user_msg)
        return {
            'mensaje_uuid': str(asistente_msg.uuid),
            'estado': asistente_msg.estado_proceso,
        }
    except ChatMessage.DoesNotExist:
        return {'error': 'mensaje no encontrado'}
    except Exception as exc:
        raise self.retry(exc=exc)
