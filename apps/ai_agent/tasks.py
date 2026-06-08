"""Tareas Celery para indexación RAG y procesamiento del chatbot."""

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
